"""Codex's local stdio app-server, using an existing ChatGPT subscription."""
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import threading
import time
import uuid

from .host import Fatal, save_json
from .environment import clean_env
from .nested import CommandEnvironment, NestedUsage
from .native_usage import NativeUsage
from .codex_children import NativeChildren
from .pi_sandbox import PiSandbox
from .sandbox import EXECUTION_POLICY
from .context import AUTO_COMPACT_TOKENS, CONTEXT_POLICY, OUTPUT_SETTLE_SECONDS, OutputGuard, compaction_threshold
from .loops import work_limit_error, WorkLimitReached


class RecoverableTurn(Fatal):
    """A settled turn may continue after compaction if its usage is covered."""


MESSAGE_SECONDS = OUTPUT_SETTLE_SECONDS
RECOVERY_PROMPT = (
    "The previous turn was stopped because of a context or output limit. "
    "Continue the pending task from the current repository and recorded tool results. "
    "Tools may already have completed: inspect current state before taking further action; "
    "do not replay completed commands or accepted edits. "
    "Keep all existing task requirements, permissions and review findings in force. "
    "Continue from the next unfinished step."
)


class Usage:
    """Sum each thread's increasing provider counters once, not notification totals.

    These are observed counters, not inferred prices for missing responses.
    Cached input is already in input; reasoning is already in output.
    """
    def __init__(self):
        self.totals = {}
        self.transport_totals = {}
        self.native_totals = {}
        self.uncertain = []

    def observe_tokens(self, thread, input_tokens, output_tokens, cached_input_tokens=0):
        if not thread or any(type(v) is not int or v < 0 for v in (input_tokens, output_tokens, cached_input_tokens)):
            self.uncertain.append("invalid usage notification")
            return False
        now = (input_tokens, output_tokens, cached_input_tokens)
        before = self.transport_totals.get(thread, self.totals.get(thread, (0, 0, 0))
                                           if thread not in self.native_totals else (0, 0, 0))
        if any(a < b for a, b in zip(now, before)):
            self.uncertain.append(f"provider counters decreased for {thread}; no negative charge inferred")
            return False
        self.transport_totals[thread] = now
        self._merge(thread)
        return now[:2] != before[:2]

    def observe_native(self, thread, input_tokens, output_tokens, cached_input_tokens=0):
        now = (input_tokens, output_tokens, cached_input_tokens)
        if not thread or any(type(v) is not int or v < 0 for v in now):
            self.uncertain.append("invalid native usage counters")
            return False
        before = self.native_totals.get(thread, (0, 0, 0))
        if any(a < b for a, b in zip(now, before)):
            self.uncertain.append(f"native counters decreased for {thread}; no negative charge inferred")
            return False
        # Both sources include ordinary responses. Native totals additionally
        # include compactions; adding the two sources would double-charge work.
        self.native_totals[thread] = now
        self._merge(thread)
        return now[:2] != before[:2]

    def _merge(self, thread):
        self.totals[thread] = tuple(max(a, b) for a, b in zip(
            self.transport_totals.get(thread, (0, 0, 0)),
            self.native_totals.get(thread, (0, 0, 0))))

    def observe(self, params):
        thread = params.get("threadId")
        value = params.get("tokenUsage", {}).get("total", {})
        if not thread or not isinstance(value, dict):
            self.uncertain.append("invalid usage notification")
            return False
        return self.observe_tokens(thread, value.get("inputTokens", 0), value.get("outputTokens", 0), value.get("cachedInputTokens", 0))

    @property
    def raw(self):
        return sum(v[0] + v[1] for v in self.totals.values())

    @property
    def cached(self):
        return sum(v[2] for v in self.totals.values())

    def report(self):
        return {"observed_raw_tokens": self.raw, "cached_input_tokens": self.cached,
                "uncertainties": list(dict.fromkeys(self.uncertain)),
                "thread_totals": self.totals,
                "app_server_thread_totals": self.transport_totals,
                "native_thread_totals": self.native_totals,
                "definition": "sum of observed per-thread input+output counters; cache/reasoning not added again"}


class ReviewSettlement:
    """Retain a review time stop while its current response supplies usage."""
    def __init__(self):
        self.error = None
        self.started = None
        self.outcome = None

    @staticmethod
    def eligible(error):
        return (isinstance(error, WorkLimitReached) and error.signal["metric"] == "seconds"
                and error.settle_seconds > 0)

    def wait(self, error, covered, now):
        if not self.eligible(error):
            if self.error is not None:
                self.outcome = "hard_limit"
            return False
        if self.error is None:
            self.error, self.started = error, now
        if covered:
            self.outcome = "priced_boundary"
        elif now - self.started >= self.error.settle_seconds:
            self.outcome = "timeout"
        else:
            return True
        return False

    def resolve(self, error):
        # A later global or token stop takes precedence over the saved time stop.
        return self.error if self.error is not None and self.eligible(error) else error

    def record(self, row, now):
        if self.error is not None:
            row["work_limit_settlement"] = {
                "trigger": self.error.signal, "settle_seconds": self.error.settle_seconds,
                "outcome": self.outcome or "turn_completed", "elapsed_seconds": now - self.started}


class ChildAccounting:
    """Shared controls for native command-launched verification agents."""
    def register_host_tools(self, thread, tools, handler):
        if not tools:
            if handler is not None:
                raise ValueError("a host tool handler requires tool definitions")
            return
        if not callable(handler):
            raise ValueError("host tools require a callable handler")
        names = [tool["name"] for tool in tools]
        if len(set(names)) != len(names):
            raise ValueError("duplicate host tool name")
        if not hasattr(self, "host_tools"):
            self.host_tools = {}
        self.host_tools[thread] = {"names": set(names), "handler": handler, "calls": {}}
        save_json(self.artifacts / (thread + "-host-tools.json"), tools)

    def dispatch_host_tool(self, thread, turn, name, arguments, call_id):
        """Execute an owned call once; reconnect/repeated deliveries reuse its result."""
        registered = getattr(self, "host_tools", {}).get(thread)
        if not registered or name not in registered["names"]:
            return {"success": False, "text": "Unknown host tool."}
        if not isinstance(arguments, dict) or not isinstance(call_id, str) or not call_id:
            return {"success": False, "text": "Host tool requires object arguments and a call ID."}
        identity = f"{thread}:{turn}:{call_id}"
        request = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)
        previous = registered["calls"].get(identity)
        if previous is not None:
            if previous["request"] != request or "result" not in previous:
                raise Fatal("conflicting or unfinished host tool call; refusing replay")
            return previous["result"]
        self.settle_host_children()
        error = self.budget_error()
        if error:
            raise error
        receipt = registered["calls"][identity] = {"request": request}
        result = registered["handler"](name, arguments, identity)
        if (not isinstance(result, dict) or type(result.get("success")) is not bool
                or not isinstance(result.get("text"), str)):
            raise Fatal("invalid host tool result; operation retained without replay")
        receipt["result"] = result
        return result

    def command_argv(self, argv):
        return self.commands.sandbox.command(True, argv)

    def budget_error(self):
        raw = self.observed_raw()
        now = time.monotonic()
        if now >= self.deadline or raw >= self.max_raw:
            return Fatal("workflow wall-time/observed-token limit reached")
        return work_limit_error(getattr(self, "work_limits", ()), raw, now)

    def child_report(self, force=False):
        if not hasattr(self, "nested"):
            return {"observed_raw_tokens": 0, "cached_input_tokens": 0,
                    "measurement_complete": True, "errors": [], "incomplete": []}
        self.refresh_children(force=force)
        parents = self.accounted_threads()
        report = self.nested.report(parents)
        if hasattr(self, "commands"):
            processes = self.commands.children.report()
            report["processes"] = processes
            report["measurement_complete"] &= processes["measurement_complete"]
            report["errors"].extend(processes["errors"])
        return report

    def refresh_children(self, force=False):
        self.nested.refresh(self.accounted_threads(), force=force)

    def accounted_threads(self):
        return self.parent_threads | set(self.usage.totals)

    def settle_host_children(self):
        self.settle_children()

    def settle_children(self):
        if not hasattr(self, "commands"):
            return
        def check_budget():
            error = self.budget_error()
            if error:
                raise error
        try:
            processes = self.commands.children.settle(check_budget)
        except BaseException:
            self.commands.close()
            raise
        child = self.child_report(force=True)
        if not processes["measurement_complete"] or not child["measurement_complete"]:
            detail = processes["pending"] + processes["errors"] + child["errors"] + child["incomplete"]
            raise Fatal("incomplete nested token measurement; no further generation: "+"; ".join(detail))

    def observed_raw(self):
        child = self.child_report()
        if child["errors"]:
            raise Fatal("nested agent isolation/accounting failure: "+"; ".join(child["errors"]))
        return self.usage.raw+child["observed_raw_tokens"]


class Codex(ChildAccounting):
    def __init__(self, repo, artifacts, model, effort, deadline, max_raw, max_turns, executable="codex", *, require_git_write=False):
        self.repo, self.artifacts = Path(repo), Path(artifacts)
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.deadline, self.max_raw, self.max_turns = deadline, max_raw, max_turns
        self.model, self.effort = model, effort
        self.usage, self.turns, self.missing_turns = Usage(), [], []
        self.native_usage = {}
        self.native_children = NativeChildren()
        self.context_usage = {}
        self.auto_compact_limit = AUTO_COMPACT_TOKENS
        self.counter, self.events, self.pending = 0, queue.Queue(), deque()
        self.active = None
        self.log = (self.artifacts / "transport.jsonl").open("x")
        self.stderr = (self.artifacts / "stderr.txt").open("x")
        self.process = None
        if os.environ.get("AGENT_LAB_CHILD") == "1":
            raise Fatal("recursive benchmark generation is forbidden")
        self.commands = CommandEnvironment(self.repo, self.artifacts / "commands", model, effort, executable,
                                           deadline=deadline)
        self.command_env = self.commands.env
        self.sandbox = self.commands.sandbox
        self.nested = NestedUsage(self.repo, model, effort)
        self.parent_threads = set()
        argv = [self.commands.executable, "--disable", "apps", "-c", 'forced_login_method="chatgpt"',
                "-c", 'model_provider="openai"', "-c", 'model='+json.dumps(model),
                "-c", 'model_reasoning_effort='+json.dumps(effort),
                *self.commands.config_arguments(),
                "app-server", "--listen", "stdio://"]
        env = self.command_env
        try:
            self.process = subprocess.Popen(argv, cwd=self.repo, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1, start_new_session=True)
            self.reader = threading.Thread(target=self._reader, daemon=True)
            self.reader.start()
            self.rpc("initialize", {"clientInfo": {"name": "agent_behavior_lab", "version": "0.1.0"},
                                    "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized", "params": {}})
            account = self.rpc("account/read", {"refreshToken": False})
            if (account.get("account") or {}).get("type") != "chatgpt":
                raise Fatal("existing ChatGPT subscription login required; no API fallback")
            config = self.rpc("config/read", {"includeLayers": False}).get("config", {})
            configured_limit = config.get("model_auto_compact_token_limit")
            if type(configured_limit) is int and configured_limit > 0:
                self.auto_compact_limit = min(configured_limit, AUTO_COMPACT_TOKENS)
            if config.get("model_provider", "openai") != "openai" or config.get("forced_login_method") != "chatgpt":
                raise Fatal("effective provider/login configuration does not match subscription-only policy")
            provider = config.get("model_providers", {}).get("openai", {})
            if provider.get("base_url") or provider.get("env_key") or provider.get("http_headers") or provider.get("env_http_headers"):
                raise Fatal("custom OpenAI provider endpoint/auth configuration is not admitted")
            normalized_config = json.dumps(config, sort_keys=True).replace(str(self.artifacts.resolve()), "<RUN_PROVIDER>")
            self.identity = {"codex_version": subprocess.check_output([self.commands.executable, "--version"], text=True, env=clean_env()).strip(),
                "auth": "chatgpt", "model": model, "effort": effort,
                "effective_config_sha256": hashlib.sha256(normalized_config.encode()).hexdigest(),
                "execution_policy": EXECUTION_POLICY,
                "host_tool_transport": "native-tools-v1",
                "context_policy": {**CONTEXT_POLICY, "auto_compact_tokens": self.auto_compact_limit,
                                   "message_seconds": MESSAGE_SECONDS, "recovery_attempts": 1},
                "nested_policy": "codex-owned-native-children-v3"}
            save_json(self.artifacts / "provider.json", self.identity)
            if require_git_write:
                self.verify_git_write()
        except BaseException:
            self.close()
            raise

    def _reader(self):
        try:
            for line in self.process.stdout:
                try:
                    self.events.put(json.loads(line))
                except json.JSONDecodeError:
                    self.events.put({"_transport_error": "non-JSON server output"})
        finally:
            self.events.put({"_transport_error": "app-server stdout closed"})

    def record(self, direction, event):
        # Account/config responses may contain identity or local secrets. The
        # client records only the non-secret readback identity above.
        self.log.write(json.dumps({"time": time.time(), "direction": direction, "event": event})+"\n")
        self.log.flush()

    def send(self, message):
        self.record("send", message)
        self.process.stdin.write(json.dumps(message)+"\n")
        self.process.stdin.flush()

    def incoming(self, timeout, private_id=None):
        try:
            message = self.events.get(timeout=max(0.001, timeout))
        except queue.Empty:
            return None
        if "_transport_error" in message:
            raise Fatal(message["_transport_error"])
        if message.get("id") != private_id or private_id is None:
            self.record("receive", message)
        if "id" in message and "method" in message and message["method"] != "item/tool/call":
            # Never approve extra permissions, external auth or interactive work.
            self.send({"id": message["id"], "error": {"code": -32601, "message": "interactive server requests are unsupported; approval policy is never"}})
        self.observe_notification(message)
        return message

    def observe_notification(self, message):
        self.native_children.observe(message, self.parent_threads)
        if message.get("method") == "thread/tokenUsage/updated":
            params = message.get("params", {})
            fresh = self.usage.observe(params)
            message["_fresh_usage"] = fresh
            self.remember_context(params)

    def accounted_threads(self):
        children = getattr(self, "native_children", None)
        return super().accounted_threads() | (set(children.threads) if children else set())

    def discover_native_children(self):
        children = getattr(self, "native_children", None)
        if children is None or not hasattr(self, "nested"):
            return
        # A fork's file can precede its transport notification. Admit its
        # ancestry as pending before the generic scanner sees inherited rows.
        # Iterate so discovery order cannot hide a grandchild's owned parent.
        remaining = [entry for entry in self.nested.files.values() if entry]
        while remaining:
            owned = self.parent_threads | set(children.threads)
            discovered = [entry for entry in remaining
                if entry.get("parent_thread_id") in owned and entry["thread"] not in owned]
            if not discovered:
                break
            for entry in discovered:
                children.discover(entry["thread"], entry["parent_thread_id"])
            remaining = [entry for entry in remaining if entry not in discovered]

    def refresh_children(self, force=False):
        self.nested.scan(force=force)
        self.discover_native_children()
        self.nested.consume(self.accounted_threads())

    def settle_host_children(self):
        # A native child can run concurrently with its parent's host command.
        # CLI-launched processes retain their existing settlement contract.
        super().settle_children()

    def native_child_report(self):
        children = getattr(self, "native_children", None)
        return (children.report(getattr(self, "native_usage", {}), self.model, self.effort)
                if children else {"threads": {}, "errors": [], "pending": [],
                                  "active": False, "measurement_complete": True})

    def settle_children(self):
        super().settle_children()
        if not getattr(self, "native_children", None) or not self.native_children.threads:
            return
        missing_since = None
        while True:
            self.refresh_native_usage(force=True)
            report = self.native_child_report()
            if report["errors"]:
                raise Fatal("native child accounting failure: " + "; ".join(report["errors"]))
            error = self.budget_error()
            if error:
                raise error
            if report["measurement_complete"]:
                return
            if report["active"]:
                missing_since = None
            elif missing_since is None:
                missing_since = time.monotonic()
            elif time.monotonic() - missing_since >= 5:
                raise Fatal("incomplete native child token measurement: " + "; ".join(report["pending"]))
            message = self.pending.popleft() if self.pending else self.incoming(0.1)
            if message and message.get("method") == "item/tool/call" and "id" in message:
                self.send({"id": message["id"], "result": {"success": False,
                    "contentItems": [{"type": "inputText", "text":
                        "Host tool call is not owned by an active author turn."}]}})

    def remember_context(self, params):
        value = params.get("tokenUsage", {})
        last = value.get("last", {})
        count = last.get("totalTokens")
        if count is None:
            counts = [last.get("inputTokens"), last.get("outputTokens")]
            count = sum(counts) if all(type(n) is int and n >= 0 for n in counts) else None
        # A zeroed error notification is not a successful reduction of context.
        if params.get("threadId") and type(count) is int and count > 0:
            if not hasattr(self, "context_usage"):
                self.context_usage = {}
            self.context_usage[params["threadId"]] = {
                "tokens": count, "window": value.get("modelContextWindow")}

    def rpc(self, method, params, timeout=30):
        self.counter += 1
        identity = self.counter
        self.send({"id": identity, "method": method, "params": params})
        end = min(self.deadline, time.monotonic()+timeout)
        private = identity if method in ("account/read", "config/read") else None
        while time.monotonic() < end:
            message = self.incoming(min(0.2, end-time.monotonic()), private)
            if message is None:
                continue
            if message.get("id") == identity and "method" not in message:
                if "error" in message:
                    raise Fatal(f"{method} failed: {message['error']}")
                return message.get("result", {})
            self.pending.append(message)
        raise Fatal(f"{method} timed out")

    def writable_policy(self):
        return self.sandbox.policy(True)

    def verify_git_write(self):
        # Called only for a newly cloned workflow, never by readback/doctor.
        # Refreshing its clean index changes no source or commit history.
        params = {"command": ["git", "update-index", "--refresh"],
                  "cwd": str(self.repo), "sandboxPolicy": self.writable_policy(),
                  "timeoutMs": 10000}
        receipt = self.rpc("command/exec", params)
        save_json(self.artifacts / "git-write-preflight.json", {"request": params, "response": receipt})
        if receipt.get("exitCode") != 0:
            raise Fatal("Git-write preflight failed before model generation: "+receipt.get("stderr", "unknown error"))

    def start_thread(self, writable=False, tools=None, tool_handler=None):
        options = self.sandbox.thread_options(writable)
        options['config']['model_reasoning_effort'] = self.effort
        options['config']['model_auto_compact_token_limit'] = getattr(self, "auto_compact_limit", AUTO_COMPACT_TOKENS)
        params = {"cwd": str(self.repo), "model": self.model,
            "modelProvider": "openai", "approvalPolicy": "never",
            **options,
            "experimentalRawEvents": False}
        if tools:
            params["dynamicTools"] = [{"type": "function", **tool} for tool in tools]
        result = self.rpc("thread/start", params)
        self.parent_threads.add(result["thread"]["id"])
        self.register_native_thread(result["thread"])
        self.register_host_tools(result["thread"]["id"], tools, tool_handler)
        return result["thread"]["id"]

    def register_native_thread(self, thread, cwd=None):
        path = thread.get("path")
        if not isinstance(path, str) or not path:
            raise Fatal("Codex did not return an owned rollout path; native token accounting is unavailable")
        self.native_usage[thread["id"]] = NativeUsage(path, thread["id"], cwd or self.repo)

    def refresh_native_usage(self, force=False):
        if hasattr(self, "nested"):
            self.nested.scan(force=force)
            self.discover_native_children()
        readers = getattr(self, "native_usage", {})
        children = getattr(self, "native_children", None)
        if children and children.threads and hasattr(self, "nested"):
            for path, entry in self.nested.files.items():
                if entry and entry["thread"] in children.threads and entry["thread"] not in readers:
                    child = entry["thread"]
                    readers[child] = NativeUsage(path, child, self.repo,
                        parent_thread_id=children.threads[child]["parent_thread_id"])
        now = time.monotonic()
        if not readers or (not force and now - getattr(self, "_native_refresh_at", -1) < 0.25):
            return
        self._native_refresh_at = now
        changed = False
        for thread, reader in readers.items():
            before = reader.offset, len(reader.errors)
            reader.refresh()
            changed |= before != (reader.offset, len(reader.errors))
            if reader.totals and not reader.errors:
                self.usage.observe_native(thread, *reader.totals)
        if changed or force:
            path = self.artifacts / "native-usage.json"
            temporary = path.with_suffix(".json.tmp")
            save_json(temporary, {thread: reader.report() for thread, reader in readers.items()})
            temporary.replace(path)

    def observed_raw(self):
        self.refresh_native_usage()
        errors = [error for reader in getattr(self, "native_usage", {}).values() for error in reader.errors]
        if errors:
            raise Fatal("native token accounting failure: " + "; ".join(errors))
        child_errors = self.native_child_report()["errors"]
        if child_errors:
            raise Fatal("native child accounting failure: " + "; ".join(child_errors))
        return super().observed_raw()

    def check_limits(self):
        if len(self.turns) >= self.max_turns:
            raise Fatal("workflow turn limit reached")
        error = self.budget_error()
        if error:
            raise error

    def compact(self, thread, label):
        self._turn_once(thread, "Compact the existing conversation history.", label + "-compact",
                        compacting=True)
        getattr(self, "context_usage", {}).pop(thread, None)

    def turn(self, thread, prompt, label, writable=False):
        self.settle_children()
        self.check_limits()
        context = getattr(self, "context_usage", {}).get(thread)
        if context:
            threshold = compaction_threshold(context["window"],
                getattr(self, "auto_compact_limit", AUTO_COMPACT_TOKENS))
            # UTF-8 bytes are a conservative upper bound for incoming text tokens.
            if context["tokens"] + len(prompt.encode("utf-8")) >= threshold:
                self.compact(thread, label)
        for attempt in range(2):
            try:
                return self._turn_once(thread, prompt, label, writable)
            except RecoverableTurn as exc:
                if attempt:
                    raise Fatal("context/output recovery exhausted after one retry: " + str(exc)) from exc
                # Never turn a missing usage tail into invented zero-cost work.
                if not self.report()["measurement_complete"]:
                    raise Fatal("context/output recovery stopped: incomplete token measurement; "
                                "failed output retained, no further generation") from exc
                self.compact(thread, label)
                prompt = RECOVERY_PROMPT

    def _turn_once(self, thread, prompt, label, writable=False,
                   *, compacting=False):
        self.settle_children()
        self.refresh_native_usage(force=True)
        self.check_limits()
        transport_before = self.usage.transport_totals.get(thread, (0, 0, 0))
        folder = self.artifacts / f"turn-{len(self.turns)+1:04d}"
        folder.mkdir()
        actual_tools = thread in getattr(self, "host_tools", {})
        (folder / "prompt.txt").write_text(prompt)
        row = {"label": label, "thread_id": thread, "status": "started", "prompt_file": str(folder / "prompt.txt")}
        if compacting:
            row["kind"] = "compaction"
        self.turns.append(row)
        turn_id = None
        guard = OutputGuard()
        replies, interrupted = [], None
        priced, last_output, last_usage = False, 0.0, 0.0
        last_compaction = 0.0
        stop_reason, stop_at, failure = None, None, None
        failure_error = None
        output_guard_at = None
        output_rejected = False
        stream_log = None
        stop_budget = None
        tool_stop = None
        settlement = ReviewSettlement()
        last_response_activity = 0.0
        recoverable, compacted = False, False
        compaction_items = set()
        compaction_active = False
        streaming = {}
        operation_end = min(self.deadline, time.monotonic() + 300) if compacting else self.deadline

        def compaction_covered():
            reader = getattr(self, "native_usage", {}).get(thread)
            if not compaction_items or reader is None:
                return True
            return (not reader.errors and not reader.missing_compactions and
                    len(reader.completed_compactions(turn_id)) >= len(compaction_items))

        def output_covered():
            if compaction_active:
                return False
            reader = getattr(self, "native_usage", {}).get(thread)
            if reader is not None:
                # The rollout may be flushed later than the app-server event.
                # Wait for all observed ordinary response costs as well as the
                # compaction receipt before accepting a directive or continuing.
                ordinary = [receipt for response_id, receipt in reader.responses.items()
                            if receipt["turn_id"] == turn_id and response_id not in reader.compactions]
                observed = self.usage.transport_totals.get(thread, (0, 0, 0))
                needed = tuple(a - b for a, b in zip(observed, transport_before))
                covered = tuple(sum(receipt["usage"][i] for receipt in ordinary) for i in range(3))
                if reader.errors or any(a < b for a, b in zip(covered, needed)):
                    return False
            if (reader is not None and compaction_items and not replies and not streaming
                    and last_response_activity <= last_compaction):
                return compaction_covered()
            # Owned compaction receipts cover compaction completion independently
            # of ordinary message freshness. Automatic compaction can complete
            # after the last transport counter, which omits its cost entirely.
            # Without native evidence retain the transport freshness requirement.
            required_output = max(last_output, last_response_activity,
                                  0.0 if reader is not None else last_compaction)
            return priced and last_usage >= required_output and compaction_covered()

        def record_output(method, params, now):
            nonlocal last_output, stop_reason, recoverable, output_guard_at, stream_log, output_rejected
            last_output = now
            if method == "item/agentMessage/delta":
                item_id = params.get("itemId", "agent-message")
                if stream_log is None:
                    stream_path = folder / "agent-message-deltas.jsonl"
                    stream_log = stream_path.open("x")
                    row["stream_file"] = str(stream_path)
                stream_log.write(json.dumps({"item_id": item_id, "delta": params.get("delta", "")}) + "\n")
                stream_log.flush()
                streaming.setdefault(item_id, now)
                violation = guard.observe(item_id, params.get("delta", ""))
            else:
                item = params["item"]
                text = item["text"]
                replies.append(text)
                item_id = item.get("id", "agent-message")
                streaming.pop(item_id, None)
                violation = guard.finish(item_id, text)
            if violation:
                output_rejected = True
            if violation and (stop_reason is None or (
                    violation == "agent_message_bytes" and output_guard_at is not None)):
                stop_reason = violation
                if failure is None and interrupted != "budget":
                    recoverable = True
                if output_guard_at is None:
                    output_guard_at = now
                    row["output_guard"] = {"reason": violation, "settle_seconds": OUTPUT_SETTLE_SECONDS}
                if violation == "agent_message_bytes":
                    row["output_guard"]["hard_limit"] = violation

        def record_failure(error, status):
            nonlocal failure, failure_error, recoverable
            # Terminal provider errors take precedence over output recovery,
            # including an error notification followed by an interrupted turn.
            if failure is None or (error and isinstance(failure_error, dict) and
                                   failure_error.get("codexErrorInfo") == "contextWindowExceeded"):
                failure_error = error
                failure = f"agent turn ended unexpectedly: {status}; {error}"
            recoverable = (not compacting and interrupted != "budget"
                           and isinstance(failure_error, dict)
                           and failure_error.get("codexErrorInfo") == "contextWindowExceeded")

        try:
            if compacting:
                self.rpc("thread/compact/start", {"threadId": thread})
            else:
                params = {"threadId": thread, "input": [{"type": "text", "text": prompt}],
                    "model": self.model, "effort": self.effort, "approvalPolicy": "never",
                    "sandboxPolicy": self.sandbox.policy(writable)}
                result = self.rpc("turn/start", params)
                turn_id = result["turn"]["id"]
                self.active = thread, turn_id
                row["turn_id"] = turn_id
            while True:
                now = time.monotonic()
                if stop_at is not None and now-stop_at > 15:
                    raise Fatal("interrupted turn did not close within 15 seconds; retained with unknown tail")
                if interrupted is None:
                    stop_budget = self.budget_error() or tool_stop
                    if stop_budget:
                        stop_reason = str(stop_budget)
                        recoverable = False
                        covered = output_covered()
                        if settlement.eligible(stop_budget) and covered and not self.pending:
                            # Process queued activity before using an earlier
                            # response's receipt as a cancellation boundary.
                            buffered = self.incoming(0)
                            if buffered is not None:
                                self.pending.append(buffered)
                        waiting = settlement.wait(stop_budget, covered and not self.pending, now)
                        reason = None if waiting else "budget"
                        if waiting and failure:
                            settlement.outcome, reason = "provider_error", "provider_error"
                        elif waiting and (row.get("output_guard", {}).get("hard_limit") or
                                          (streaming and now - min(streaming.values()) >= MESSAGE_SECONDS)):
                            settlement.outcome, reason = "hard_limit", "runaway_output"
                            output_rejected = True
                        elif waiting and compacting and now >= operation_end:
                            settlement.outcome, reason = "hard_limit", "compaction_timeout"
                    elif compacting and now >= operation_end:
                        stop_reason, reason = "context compaction timed out", "compaction_timeout"
                    elif failure:
                        reason = "provider_error"
                    elif not compacting and streaming and now - min(streaming.values()) >= MESSAGE_SECONDS:
                        stop_reason, reason = "agent message exceeded streaming time limit", "runaway_output"
                        output_rejected = True
                        recoverable = True
                    elif stop_reason:
                        # Soft output guards reject the response immediately,
                        # but cancelling its stream can destroy its usage tail.
                        # Give it a bounded chance to finish at a priced boundary.
                        covered = output_covered()
                        settling = (output_guard_at is not None and
                                    stop_reason != "agent_message_bytes" and
                                    now - output_guard_at < OUTPUT_SETTLE_SECONDS and not covered)
                        reason = None if settling else "runaway_output"
                        if reason and output_guard_at is not None:
                            row["output_guard"]["settlement"] = (
                                "hard_limit" if stop_reason == "agent_message_bytes" else
                                "priced_boundary" if covered else "timeout")
                    else:
                        reason = None
                    if reason:
                        if turn_id is None:
                            raise Fatal(stop_reason or "cannot interrupt an unidentified turn")
                        self.counter += 1
                        self.send({"id": self.counter, "method": "turn/interrupt", "params": {"threadId": thread, "turnId": turn_id}})
                        interrupted, stop_at = reason, now
                message = self.pending.popleft() if self.pending else self.incoming(0.1)
                if message is None:
                    continue
                params = message.get("params", {})
                if message.get("method") == "item/tool/call" and "id" in message:
                    owned = (params.get("threadId") == thread and params.get("turnId") == turn_id
                             and turn_id is not None and actual_tools and not compacting)
                    if owned and interrupted is None and not stop_reason:
                        if params.get("namespace") is not None:
                            result = {"success": False, "text": "Unknown host tool namespace."}
                        else:
                            try:
                                result = self.dispatch_host_tool(thread, turn_id, params.get("tool"),
                                    params.get("arguments"), params.get("callId"))
                            except WorkLimitReached as exc:
                                tool_stop, stop_reason = exc, str(exc)
                                result = getattr(exc, "completed_tool_result", {
                                    "success": False, "text": "Host operation stopped."})
                                self.counter += 1
                                self.send({"id": self.counter, "method": "turn/interrupt",
                                    "params": {"threadId": thread, "turnId": turn_id}})
                                interrupted, stop_at = "budget", time.monotonic()
                        row.setdefault("host_tool_calls", []).append(params.get("callId"))
                    else:
                        result = {"success": False, "text": "Host tool call is not owned by an active author turn."}
                    self.send({"id": message["id"], "result": {"success": result["success"],
                        "contentItems": [{"type": "inputText", "text": result["text"]}]}})
                    continue
                if params.get("threadId") != thread:
                    continue
                method = message.get("method")
                event_turn = params.get("turnId") or params.get("turn", {}).get("id")
                item = params.get("item", {})
                if compacting and turn_id is None and event_turn and (
                    method == "turn/started" or item.get("type") == "contextCompaction"
                ):
                    turn_id = event_turn
                    row["turn_id"] = turn_id
                    self.active = thread, turn_id
                if event_turn != turn_id or turn_id is None:
                    continue
                now = time.monotonic()
                if method == "thread/tokenUsage/updated":
                    self.remember_context(params)
                    if message.get("_fresh_usage"):
                        priced, last_usage = True, now
                elif method == "item/started" and item.get("type") in ("reasoning", "agentMessage"):
                    last_response_activity = now
                elif method == "item/agentMessage/delta":
                    record_output(method, params, now)
                elif method == "item/completed" and item.get("type") == "agentMessage":
                    record_output(method, params, now)
                elif method == "item/completed" and item.get("type") == "contextCompaction":
                    compacted = True
                    compaction_items.add(item.get("id", "context-compaction"))
                    compaction_active = False
                    last_compaction = now
                elif method == "item/started" and item.get("type") == "contextCompaction":
                    compaction_active = True
                elif method == "turn/completed":
                    status = params["turn"].get("status")
                    row.update(status=status, interrupt_reason=interrupted)
                    error = params["turn"].get("error")
                    if error or status not in ("completed", "interrupted") or (status == "interrupted" and not interrupted):
                        record_failure(error or {}, status)
                    break
                elif method == "error" and params.get("willRetry") is not True:
                    record_failure(params.get("error") or {}, "failed")
            # Terminal failures also drain and retain their usage before recovery.
            minimum_end = time.monotonic()+1.0
            end = minimum_end+4.0
            buffered, self.pending = self.pending, deque()
            while time.monotonic() < end:
                self.refresh_native_usage()
                if output_covered() and time.monotonic() >= minimum_end and not buffered:
                    break
                message = buffered.popleft() if buffered else self.incoming(min(0.1, end-time.monotonic()))
                if message:
                    p = message.get("params", {})
                    owned = p.get("threadId") == thread and p.get("turnId") == turn_id
                    if owned and message.get("method") == "thread/tokenUsage/updated":
                        self.remember_context(p)
                        if message.get("_fresh_usage"):
                            priced, last_usage = True, time.monotonic()
                    elif owned and message.get("method") == "item/agentMessage/delta":
                        record_output(message["method"], p, time.monotonic())
                    elif (owned and message.get("method") == "item/started"
                          and p.get("item", {}).get("type") in ("reasoning", "agentMessage")):
                        last_response_activity = time.monotonic()
                    elif (owned and message.get("method") == "item/completed"
                          and p.get("item", {}).get("type") == "agentMessage"):
                        record_output(message["method"], p, time.monotonic())
                    elif owned and message.get("method") == "error" and p.get("willRetry") is not True:
                        record_failure(p.get("error") or {}, "failed")
                    else:
                        self.pending.append(message)
            self.pending.extend(buffered)
            self.refresh_native_usage(force=True)
            if failure and not (not compacting and isinstance(failure_error, dict)
                                and failure_error.get("codexErrorInfo") == "contextWindowExceeded"):
                recoverable = False
            if output_guard_at is not None:
                row["output_guard"].setdefault("settlement", interrupted or "turn_completed")
                row["output_guard"]["elapsed_seconds"] = time.monotonic() - output_guard_at
            row["usage_observed_after_last_message"] = output_covered()
            if compaction_items:
                reader = getattr(self, "native_usage", {}).get(thread)
                row["compaction_usage"] = {
                    "completed_items": sorted(compaction_items),
                    "response_ids": [receipt["response_id"] for receipt in reader.completed_compactions(turn_id)]
                                    if reader else [],
                    "covered": compaction_covered(),
                }
            if failure and not recoverable:
                # An unknown generation failure is not a certified response
                # boundary, even if an earlier counter happened to arrive.
                row["usage_observed_after_last_message"] = False
            final = next((text for text in reversed(replies) if text.strip()), "")
            (folder / "reply.txt").write_text(final)
            save_json(folder / "messages.json", replies)
            stop_budget = self.budget_error() or tool_stop
            if settlement.error is not None:
                if failure:
                    settlement.outcome = "provider_error"
                elif stop_budget and not settlement.eligible(stop_budget):
                    settlement.outcome = "hard_limit"
                stop_budget = settlement.resolve(stop_budget)
                settlement.record(row, time.monotonic())
            if stop_budget:
                stop_reason, recoverable = str(stop_budget), False
            if stop_reason or failure:
                row["recovery_eligible"] = recoverable and not compacting
                if isinstance(stop_budget, WorkLimitReached) and not failure:
                    row["work_limit"] = stop_budget.signal
                    raise stop_budget
                error_class = RecoverableTurn if row["recovery_eligible"] else Fatal
                raise error_class(failure or stop_reason)
            if compacting and not compacted:
                raise Fatal("compaction completed without a contextCompaction item")
            if not row["usage_observed_after_last_message"]:
                self.missing_turns.append({"thread_id": thread, "turn_id": turn_id,
                    "reason": "no fresh usage covering the last delivered message"})
            if row["usage_observed_after_last_message"]:
                self.settle_children()
            if (compacting or compaction_items) and not self.report()["measurement_complete"]:
                raise Fatal("incomplete token measurement after compaction; no further generation")
            if not row["usage_observed_after_last_message"]:
                raise Fatal("incomplete native token measurement; no further generation")
            return final
        except BaseException as exc:
            if settlement.error is not None and "work_limit_settlement" not in row:
                settlement.outcome = settlement.outcome or "provider_error"
                settlement.record(row, time.monotonic())
            if turn_id is not None and interrupted is None and row.get("status") == "started":
                try:
                    self.counter += 1
                    self.send({"id": self.counter, "method": "turn/interrupt", "params": {"threadId": thread, "turnId": turn_id}})
                    drain_end = time.monotonic()+2
                    while time.monotonic() < drain_end:
                        self.incoming(min(0.1, drain_end-time.monotonic()))
                except (OSError, Fatal):
                    self.usage.uncertain.append("transport unavailable during cancellation drain")
            if row["status"] == "started":
                row["status"] = "failed"
            row.update(error=str(exc))
            if not row.get("usage_observed_after_last_message") and not any(
                missing.get("turn_id") == turn_id and missing.get("thread_id") == thread
                for missing in self.missing_turns
            ):
                self.missing_turns.append({"thread_id": thread, "turn_id": turn_id,
                    "reason": "failed/incomplete turn; inspect retained transport"})
            raise
        finally:
            if stream_log is not None:
                stream_log.close()
            save_json(folder / "result.json", row)
            with (self.artifacts / "coverage.jsonl").open("a") as journal:
                journal.write(json.dumps({"turn_id": turn_id, "label": label,
                    "status": row["status"], "error": row.get("error"),
                    "usage_observed_after_last_message": row.get("usage_observed_after_last_message", False)})+"\n")
            self.active = None

    def report(self):
        self.refresh_native_usage(force=True)
        native = {thread: reader.report() for thread, reader in getattr(self, "native_usage", {}).items()}
        native_complete = all(not value["errors"] and not value["missing_compactions"] for value in native.values())
        child = self.child_report(force=True)
        native_children = self.native_child_report()
        return {**self.usage.report(), "turns": self.turns, "unpriced_or_incomplete_turns": self.missing_turns,
                "native_usage": native,
                "native_children": native_children,
                "parent_observed_raw_tokens": self.usage.raw, "nested": child,
                "observed_raw_tokens": self.usage.raw+child["observed_raw_tokens"],
                "cached_input_tokens": self.usage.cached+child["cached_input_tokens"],
                "measurement_complete": (not self.missing_turns and not self.usage.uncertain and bool(self.turns)
                                         and native_complete and child["measurement_complete"]
                                         and native_children["measurement_complete"]),
                "qualification": "parent response coverage with owned native compaction receipts, plus owned native child lifecycle/model/counters; not a proof that every internal response was priced"}

    def close(self):
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                    self.process.wait(timeout=2)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    self.process.wait(timeout=2)
        if self.process is not None:
            self.process.stdout.close()
        if hasattr(self, "commands"):
            self.commands.close()
        self.log.close()
        self.stderr.close()


class PiThread:
    def __init__(self, thread_id, argv, cwd, env, stderr, log_fn, *, host_tools=None):
        self.thread_id = thread_id
        self.log_fn = log_fn
        self.events = queue.Queue()
        self.host_requests = self.host_responses = None
        inherited = ()
        if host_tools:
            request_read, request_write = os.pipe()
            response_read, response_write = os.pipe()
            self.host_requests = os.fdopen(request_read, "r")
            self.host_responses = os.fdopen(response_write, "w", buffering=1)
            inherited = (request_write, response_read)
            env = {**env, "AGENT_LAB_PI_HOST_REQUEST_FD": str(request_write),
                   "AGENT_LAB_PI_HOST_RESPONSE_FD": str(response_read),
                   "AGENT_LAB_PI_HOST_THREAD_ID": thread_id}
        try:
            self.process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            bufsize=1,
            start_new_session=True,
            pass_fds=inherited,
            )
        except BaseException:
            if self.host_requests:
                self.host_requests.close()
                self.host_responses.close()
            raise
        finally:
            for fd in inherited:
                os.close(fd)
        self.reader = threading.Thread(target=self._reader, daemon=True)
        self.reader.start()
        if self.host_requests:
            self.host_reader = threading.Thread(target=self._host_reader, daemon=True)
            self.host_reader.start()

    def _host_reader(self):
        try:
            for line in self.host_requests:
                message = json.loads(line)
                self.log_fn("host_receive", message)
                self.events.put(message)
        except (OSError, ValueError):
            self.events.put({"_transport_error": "invalid Pi host tool bridge message"})

    def host_result(self, call_id, result):
        message = {"callId": call_id, **result}
        self.log_fn("host_send", message)
        self.host_responses.write(json.dumps(message) + "\n")
        self.host_responses.flush()

    def _reader(self):
        try:
            for line in self.process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    self.log_fn("receive", msg)
                    self.events.put(msg)
                except json.JSONDecodeError:
                    self.events.put({"_transport_error": "non-JSON server output"})
        except Exception:
            pass
        finally:
            self.events.put({"_transport_error": "pi stdout closed"})

    def send(self, message):
        self.log_fn("send", message)
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def incoming(self, timeout):
        try:
            return self.events.get(timeout=max(0.001, timeout))
        except queue.Empty:
            return None

    def rpc(self, message, timeout=30):
        req_id = message.get("id") or str(uuid.uuid4())
        message["id"] = req_id
        self.send(message)
        end = time.monotonic() + timeout
        deferred = []
        try:
            while time.monotonic() < end:
                event = self.incoming(min(0.2, end - time.monotonic()))
                if event is None:
                    continue
                if "_transport_error" in event:
                    raise Fatal(event["_transport_error"])
                if event.get("type") == "response" and event.get("id") == req_id:
                    return event
                deferred.append(event)
            raise Fatal(f"{message.get('type')} timed out")
        finally:
            for e in deferred:
                self.events.put(e)

    def close(self):
        if self.process is not None:
            if self.process.stdin is not None:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass
            if self.process.poll() is None:
                try:
                    self.process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                        self.process.wait(timeout=2)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        try:
                            os.killpg(self.process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        self.process.wait(timeout=2)
            if self.process.stdout is not None:
                try:
                    self.process.stdout.close()
                except Exception:
                    pass
        if self.host_responses is not None:
            self.host_responses.close()
        if self.host_requests is not None:
            self.host_requests.close()


def pi_usage_tokens(value):
    """Pi separates uncached input, cache reads and cache writes."""
    if not isinstance(value, dict):
        raise Fatal("Pi session/response usage is missing")
    counts = (value.get("input"), value.get("output"), value.get("cacheRead", 0), value.get("cacheWrite", 0))
    if any(type(n) is not int or n < 0 for n in counts):
        raise Fatal("Pi session/response usage has invalid token counts")
    for key in ("total", "totalTokens"):
        if key in value and (type(value[key]) is not int or value[key] != sum(counts)):
            raise Fatal("Pi session/response usage has inconsistent totals")
    inputs, outputs, reads, writes = counts
    return inputs + reads + writes, outputs, reads


class PiCancellationReceipts:
    """Owned proof that an SDK error did not dispatch a model request."""
    prefix = "Lab request not dispatched: "

    def __init__(self, path, thread, turn):
        self.path, self.thread, self.turn = path, thread, turn
        self.accepted = {}

    def covers(self, event, interrupted):
        kind = event.get("type")
        message = event.get("message", {})
        if (kind not in ("message_start", "message_end", "turn_end")
                or not isinstance(message, dict)
                or not isinstance(message.get("errorMessage"), str)
                or not message["errorMessage"].startswith(self.prefix)):
            return False
        receipt_id = message["errorMessage"][len(self.prefix):]
        try:
            uuid.UUID(receipt_id)
            receipts = [json.loads(line) for line in self.path.read_text().splitlines()]
            matching = [r for r in receipts if r.get("receipt_id") == receipt_id]
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise Fatal("Pi cancellation receipt is unavailable or invalid") from exc
        if len(matching) != 1:
            raise Fatal("Pi cancellation receipt is missing or duplicated")
        receipt = matching[0]
        expected = {"type": "request_not_dispatched", "thread_id": self.thread,
                    "turn_id": self.turn, "provider": message.get("provider"),
                    "model": message.get("model"), "api": message.get("api"),
                    "reason": "already_aborted_before_prepare"}
        if (not interrupted or any(receipt.get(k) != v for k, v in expected.items())
                or message.get("role") != "assistant" or message.get("content") != []
                or message.get("stopReason") not in ("error", "aborted")
                or message.get("responseId") or pi_usage_tokens(message.get("usage")) != (0, 0, 0)):
            raise Fatal("Pi cancellation receipt does not match the stopped request")
        fingerprint = hashlib.sha256(json.dumps(message, sort_keys=True).encode()).hexdigest()
        accepted = self.accepted.setdefault(receipt_id, {"fingerprint": fingerprint, "events": [],
                                                       "receipt": receipt})
        sequence = ["message_start", "message_end", "turn_end"]
        if (accepted["fingerprint"] != fingerprint or len(accepted["events"]) >= len(sequence)
                or kind != sequence[len(accepted["events"])]):
            raise Fatal("Pi cancellation receipt was reused or has an invalid lifecycle")
        accepted["events"].append(kind)
        return True

    def complete(self):
        return all(row["events"] == ["message_start", "message_end", "turn_end"]
                   for row in self.accepted.values())


class Pi(ChildAccounting):
    transport = "pi-rpc-stdio"

    def __init__(self, repo, artifacts, model, effort, deadline, max_raw, max_turns, executable="pi", *, require_git_write=False, codex_executable="codex"):
        self.repo, self.artifacts = Path(repo).resolve(), Path(artifacts).resolve()
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.deadline, self.max_raw, self.max_turns = deadline, max_raw, max_turns
        self.model, self.effort = model or "gpt-5.5", effort
        self.usage, self.turns, self.missing_turns = Usage(), [], []
        self.threads = {}
        self.thread_counter = 0
        self.log = (self.artifacts / "transport.jsonl").open("x")
        self.stderr = (self.artifacts / "stderr.txt").open("x")
        self.sessions_dir = self.artifacts / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        if os.environ.get("AGENT_LAB_CHILD") == "1":
            raise Fatal("recursive benchmark generation is forbidden")
        resolved = shutil.which(executable)
        if not resolved:
            raise ValueError(f"Pi executable not found: {executable}")
        self.executable = str(Path(resolved).absolute())
        try:
            self.commands = CommandEnvironment(self.repo, self.artifacts / "commands", self.model, effort,
                                               codex_executable, deadline=deadline)
            self.command_env = self.commands.env
            self.nested = NestedUsage(self.repo, self.model, effort)
            self.parent_threads = set()
            self.sandbox = PiSandbox(self.repo, self.commands.executable, self.executable,
                                     execution=self.commands.sandbox)
            self._probe()
            if require_git_write:
                self.verify_git_write()
        except BaseException:
            self.close()
            raise

    def _probe(self):
        version = subprocess.check_output([self.executable, "--version"], text=True, env=self.command_env, timeout=10).strip()
        probe = self.new_thread("probe", writable=False, no_session=True)
        try:
            self.prepare_turn(probe, False)
        finally:
            probe.close()
        controls = {"pi_version": version, "model": self.model, "effort": self.effort,
                    "auth": "openai-codex", "sandbox": "codex-native-tools-v1",
                    "host_tool_transport": "native-tools-v1", "request_guard": "pre-dispatch-v1",
                    "execution_policy": EXECUTION_POLICY,
                    "nested_policy": "same-model-subscription-supervised-native-history-v2"}
        self.identity = {
            **controls,
            "harness": "pi",
            "codex_version": subprocess.check_output([self.commands.executable, "--version"], text=True, env=clean_env(), timeout=10).strip(),
            "usage_accounting": "pi-session-totals-with-cache-and-cancellation-receipts-v3",
            "effective_config_sha256": hashlib.sha256(json.dumps(controls, sort_keys=True).encode()).hexdigest(),
        }
        save_json(self.artifacts / "provider.json", self.identity)

    def verify_git_write(self):
        argv = self.sandbox.command(True, ["git", "update-index", "--refresh"])
        receipt = subprocess.run(argv, cwd=self.repo, env=self.command_env, text=True, capture_output=True,
                                 timeout=max(0.001, min(10, self.deadline-time.monotonic())))
        save_json(self.artifacts / "git-write-preflight.json", {"request": argv,
                  "response": {"exitCode": receipt.returncode, "stdout": receipt.stdout, "stderr": receipt.stderr}})
        if receipt.returncode != 0:
            raise Fatal("Git-write preflight failed before model generation: " + receipt.stderr)

    def launch_arguments(self):
        return [self.executable, "--mode", "rpc", "--approve", "--provider", "openai-codex",
                "--model", self.model, "--thinking", self.effort, "--no-extensions",
                "--extension", str(PiSandbox.extension), "--tools", "read,bash,edit,write"]

    def validate_state(self, response):
        data = response.get("data") or {}
        model = data.get("model") or {}
        if (not response.get("success") or model.get("provider") != "openai-codex"
                or model.get("id") != self.model or data.get("thinkingLevel") != self.effort):
            raise Fatal("Pi effective provider/model/effort differs from the benchmark; no generation")

    def new_thread(self, thread_id, writable=False, no_session=False, tools=None):
        policy = self.artifacts / (thread_id + "-sandbox.json")
        self.sandbox.configure(policy, writable, self.deadline)
        argv = self.launch_arguments()
        if tools:
            tool_index = argv.index("--tools") + 1
            argv[tool_index] += "," + ",".join(tool["name"] for tool in tools)
        if no_session:
            argv += ["--no-session"]
        else:
            session_dir = self.sessions_dir / thread_id
            session_dir.mkdir()
            argv += ["--session-dir", str(session_dir)]
        env = {**self.command_env, "AGENT_LAB_PI_MODULE": self.sandbox.module,
               "AGENT_LAB_PI_POLICY": str(policy), "AGENT_LAB_PI_THREAD_ID": thread_id,
               "AGENT_LAB_PI_REQUEST_JOURNAL": str(self.artifacts / (thread_id + "-requests.jsonl"))}
        if tools:
            definitions = self.artifacts / (thread_id + "-host-tools.json")
            env["AGENT_LAB_PI_HOST_TOOLS"] = str(definitions)
        th = PiThread(thread_id, argv, self.repo, env, self.stderr, self.record, host_tools=tools)
        th.policy = policy
        return th

    def prepare_turn(self, thread, writable):
        state = thread.rpc({"type": "get_state"}, timeout=max(0.001, min(30, self.deadline-time.monotonic())))
        self.validate_state(state)
        ready = thread.policy.with_suffix(".json.ready")
        receipt = json.loads(ready.read_text()) if ready.is_file() else {}
        if receipt.get("pid") != thread.process.pid or receipt.get("request_guard") != "pre-dispatch-v1":
            raise Fatal("Pi sandbox extension did not load; refusing unsandboxed generation")
        self.sandbox.configure(thread.policy, writable, self.deadline)

    def record(self, direction, event):
        self.log.write(json.dumps({"time": time.time(), "direction": direction, "event": event}) + "\n")
        self.log.flush()

    def start_thread(self, writable=False, tools=None, tool_handler=None):
        self.thread_counter += 1
        thread_id = f"pi-thread-{self.thread_counter}"
        self.register_host_tools(thread_id, tools, tool_handler)
        th = self.new_thread(thread_id, writable, tools=tools)
        self.threads[thread_id] = th
        self.prepare_turn(th, writable)
        return thread_id

    def turn(self, thread, prompt, label, writable=False):
        self.settle_children()
        if len(self.turns) >= self.max_turns:
            raise Fatal("workflow turn limit reached")
        error = self.budget_error()
        if error:
            raise error
        self.prepare_turn(self.threads[thread], writable)
        actual_tools = thread in getattr(self, "host_tools", {})
        folder = self.artifacts / f"turn-{len(self.turns)+1:04d}"
        folder.mkdir()
        (folder / "prompt.txt").write_text(prompt)
        turn_id = f"turn-{len(self.turns)+1:04d}"
        row = {"label": label, "thread_id": thread, "turn_id": turn_id, "status": "started", "prompt_file": str(folder / "prompt.txt")}
        self.turns.append(row)
        th = self.threads[thread]
        policy = json.loads(th.policy.read_text())
        policy["turn_id"] = turn_id
        staged = th.policy.with_name(th.policy.name + ".next")
        staged.write_text(json.dumps(policy))
        staged.replace(th.policy)
        cancellations = PiCancellationReceipts(self.artifacts / (thread + "-requests.jsonl"), thread, turn_id)
        before_raw = sum(self.usage.totals.get(thread, (0, 0, 0))[:2])
        counted_messages = set()
        replies, interrupted = [], None
        priced, last_output, last_usage = False, 0.0, 0.0
        stop_reason, stop_at = None, None
        stop_budget = None
        tool_stop = None
        settlement = ReviewSettlement()
        last_response_activity = 0.0
        buffered = None
        try:
            th.send({"id": turn_id, "type": "prompt", "message": prompt})
            while True:
                now = time.monotonic()
                if stop_at is not None and now - stop_at > 15:
                    raise Fatal("interrupted turn did not close within 15 seconds; retained with unknown tail")
                if interrupted is None:
                    stop_budget = self.budget_error() or tool_stop
                    reason = "budget" if stop_budget else None
                    if stop_budget:
                        covered = priced and last_usage >= max(last_output, last_response_activity)
                        if settlement.eligible(stop_budget) and covered and buffered is None:
                            buffered = th.incoming(0)
                        if settlement.wait(stop_budget, covered and buffered is None, now):
                            reason = None
                    if reason:
                        th.send({"type": "abort"})
                        interrupted, stop_at = reason, now
                        if stop_budget:
                            stop_reason = str(stop_budget)
                message = buffered if buffered is not None else th.incoming(0.1)
                buffered = None
                if message is None:
                    continue
                if "_transport_error" in message:
                    raise Fatal(message["_transport_error"])
                if message.get("type") == "lab_host_tool_call":
                    owned = (actual_tools and message.get("threadId") == thread
                             and message.get("turnId") == turn_id)
                    if owned and interrupted is None and not stop_reason:
                        try:
                            result = self.dispatch_host_tool(thread, turn_id, message.get("tool"),
                                message.get("arguments"), message.get("callId"))
                        except WorkLimitReached as exc:
                            tool_stop, stop_reason = exc, str(exc)
                            result = getattr(exc, "completed_tool_result", {
                                "success": False, "text": "Host operation stopped."})
                            th.send({"type": "abort"})
                            interrupted, stop_at = "budget", time.monotonic()
                        row.setdefault("host_tool_calls", []).append(message.get("callId"))
                    else:
                        result = {"success": False, "text": "Host tool call is not owned by an active author turn."}
                    th.host_result(message.get("callId"), result)
                    continue
                if message.get("type") == "extension_ui_request":
                    th.send({"type": "extension_ui_response", "id": message.get("id"), "cancelled": True})
                if message.get("type") == "response" and message.get("command") == "prompt" and message.get("id") == turn_id:
                    if not message.get("success"):
                        raise Fatal(f"prompt failed: {message.get('error')}")
                if cancellations.covers(message, interrupted is not None):
                    row["cancelled_requests"] = list(cancellations.accepted.values())
                    continue
                if (message.get("type") in ("message_start", "message_update")
                        and message.get("message", {}).get("role", "assistant") == "assistant"):
                    last_response_activity = now
                # Streaming snapshots reset for every response; they are not
                # cumulative conversation counters or completed usage records.
                if message.get("type") in ("message_end", "turn_end"):
                    m = message.get("message", {})
                    if m.get("role") == "assistant":
                        if m.get("stopReason") in ("error", "aborted") and interrupted is None:
                            stop_reason = m.get("errorMessage") or "Pi model response " + m["stopReason"]
                        text = "".join(c.get("text", "") for c in m.get("content", []) if isinstance(c, dict) and c.get("type") == "text")
                        if text and (not replies or replies[-1] != text):
                            replies.append(text)
                            last_output = now
                    if message.get("type") == "message_end" and m.get("usage"):
                        key = hashlib.sha256(json.dumps(m, sort_keys=True).encode()).digest()
                        if key not in counted_messages:
                            delta = pi_usage_tokens(m["usage"])
                            previous = self.usage.totals.get(thread, (0, 0, 0))
                            fresh = self.usage.observe_tokens(thread, *(a+b for a, b in zip(previous, delta)))
                            counted_messages.add(key)
                            if fresh:
                                priced, last_usage = True, now
                if message.get("type") == "agent_settled":
                    row.update(status="interrupted" if interrupted else "failed" if stop_reason else "completed", interrupt_reason=interrupted)
                    break

            before_stats = self.usage.totals.get(thread, (0, 0, 0))
            stats = th.rpc({"type": "get_session_stats"}, timeout=5)
            if not isinstance(stats, dict) or not stats.get("success") or not isinstance(stats.get("data"), dict):
                raise Fatal("Pi session usage could not be retrieved")
            row["session_tokens"] = stats["data"].get("tokens")
            totals = pi_usage_tokens(row["session_tokens"])
            self.usage.observe_tokens(thread, *totals)
            if self.usage.totals.get(thread) != totals:
                raise Fatal("Pi session usage does not cover the observed response totals")
            if sum(totals[:2]) <= before_raw:
                raise Fatal("Pi session usage did not advance for this turn")
            if totals[:2] != before_stats[:2]:
                priced, last_usage = True, time.monotonic()
            covered = (priced and last_usage >= max(last_output, last_response_activity)
                       and cancellations.complete())
            if not covered:
                self.missing_turns.append({"thread_id": thread, "turn_id": turn_id, "reason": "no fresh usage covering the last delivered message"})
            final = next((text for text in reversed(replies) if text.strip()), "")
            (folder / "reply.txt").write_text(final)
            save_json(folder / "messages.json", replies)
            row["usage_observed_after_last_message"] = covered
            stop_budget = self.budget_error() or tool_stop
            if settlement.error is not None:
                if stop_budget and not settlement.eligible(stop_budget):
                    settlement.outcome = "hard_limit"
                stop_budget = settlement.resolve(stop_budget)
                settlement.record(row, time.monotonic())
            if stop_budget:
                if isinstance(stop_budget, WorkLimitReached):
                    row["work_limit"] = stop_budget.signal
                raise stop_budget
            if stop_reason:
                raise Fatal(stop_reason)
            if not covered:
                raise Fatal("incomplete Pi token measurement; no further generation")
            self.settle_children()
            return final
        except BaseException as exc:
            if settlement.error is not None and "work_limit_settlement" not in row:
                settlement.outcome = settlement.outcome or "provider_error"
                settlement.record(row, time.monotonic())
            if interrupted is None and row.get("status") == "started":
                try:
                    th.send({"type": "abort"})
                    drain_end = time.monotonic() + 2
                    while time.monotonic() < drain_end:
                        th.incoming(min(0.1, drain_end - time.monotonic()))
                except (OSError, Fatal):
                    self.usage.uncertain.append("transport unavailable during cancellation drain")
            if row["status"] == "started":
                row["status"] = "failed"
            row.update(error=str(exc))
            if not row.get("usage_observed_after_last_message") and not any(
                missing.get("turn_id") == turn_id and missing.get("thread_id") == thread
                for missing in self.missing_turns
            ):
                self.missing_turns.append({"thread_id": thread, "turn_id": turn_id, "reason": "failed/incomplete turn; inspect retained transport"})
            raise
        finally:
            save_json(folder / "result.json", row)
            with (self.artifacts / "coverage.jsonl").open("a") as journal:
                journal.write(json.dumps({"turn_id": turn_id, "label": label,
                    "status": row["status"], "error": row.get("error"),
                    "usage_observed_after_last_message": row.get("usage_observed_after_last_message", False)}) + "\n")

    def report(self):
        child = self.child_report(force=True)
        return {
            **self.usage.report(),
            "turns": self.turns,
            "unpriced_or_incomplete_turns": self.missing_turns,
            "parent_observed_raw_tokens": self.usage.raw,
            "nested": child,
            "observed_raw_tokens": self.usage.raw + child["observed_raw_tokens"],
            "cached_input_tokens": self.usage.cached + child["cached_input_tokens"],
            "measurement_complete": (not self.missing_turns and not self.usage.uncertain and bool(self.turns)
                                     and child["measurement_complete"]),
            "qualification": "Pi finalized-message/session usage plus owned native child lifecycle/model/counters; cache read/write included in input"
        }

    def close(self):
        for th in self.threads.values():
            th.close()
        if hasattr(self, "commands"):
            self.commands.close()
        if hasattr(self, "log") and not self.log.closed:
            self.log.close()
        if hasattr(self, "stderr") and not self.stderr.closed:
            self.stderr.close()
