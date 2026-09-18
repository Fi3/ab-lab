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

from .host import Fatal, Rejected, parse_operations, save_json
from .environment import clean_env
from .nested import CommandEnvironment, NestedUsage


class Usage:
    """Sum each thread's increasing provider counters once, not notification totals.

    These are observed counters, not inferred prices for missing responses.
    Cached input is already in input; reasoning is already in output.
    """
    def __init__(self):
        self.totals = {}
        self.uncertain = []

    def observe_tokens(self, thread, input_tokens, output_tokens, cached_input_tokens=0):
        if not thread or any(type(v) is not int or v < 0 for v in (input_tokens, output_tokens, cached_input_tokens)):
            self.uncertain.append("invalid usage notification")
            return False
        now = (input_tokens, output_tokens, cached_input_tokens)
        before = self.totals.get(thread, (0, 0, 0))
        if any(a < b for a, b in zip(now, before)):
            self.uncertain.append(f"provider counters decreased for {thread}; no negative charge inferred")
            return False
        self.totals[thread] = now
        return now[:2] != before[:2]

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
                "definition": "sum of observed per-thread input+output counters; cache/reasoning not added again"}


class InterruptGate:
    """Only a priced response boundary permits discretionary cancellation."""
    def __init__(self, enabled):
        self.enabled = enabled
        self.at = None
        self.fresh_usage = False

    def directive(self, now):
        if self.at is None:
            self.at = now

    def reason(self, now):
        if not self.enabled or self.at is None:
            return None
        if self.fresh_usage:
            return "usage_received"
        # A complete intermediate message or elapsed time is not a complete
        # model response. Cancelling there can lose its numeric usage report.
        return None


class Codex:
    def __init__(self, repo, artifacts, model, effort, deadline, max_raw, max_turns, executable="codex", *, require_git_write=False):
        self.repo, self.artifacts = Path(repo), Path(artifacts)
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.deadline, self.max_raw, self.max_turns = deadline, max_raw, max_turns
        self.model, self.effort = model, effort
        self.usage, self.turns, self.missing_turns = Usage(), [], []
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
            if config.get("model_provider", "openai") != "openai" or config.get("forced_login_method") != "chatgpt":
                raise Fatal("effective provider/login configuration does not match subscription-only policy")
            provider = config.get("model_providers", {}).get("openai", {})
            if provider.get("base_url") or provider.get("env_key") or provider.get("http_headers") or provider.get("env_http_headers"):
                raise Fatal("custom OpenAI provider endpoint/auth configuration is not admitted")
            normalized_config = json.dumps(config, sort_keys=True).replace(str(self.artifacts.resolve()), "<RUN_PROVIDER>")
            self.identity = {"codex_version": subprocess.check_output([self.commands.executable, "--version"], text=True, env=clean_env()).strip(),
                "auth": "chatgpt", "model": model, "effort": effort,
                "effective_config_sha256": hashlib.sha256(normalized_config.encode()).hexdigest(),
                "nested_policy": "same-model-subscription-supervised-native-history-v2"}
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
        if "id" in message and "method" in message:
            # Never approve extra permissions, external auth or interactive work.
            self.send({"id": message["id"], "error": {"code": -32601, "message": "interactive server requests are unsupported; approval policy is never"}})
        if message.get("method") == "thread/tokenUsage/updated":
            params = message.get("params", {})
            fresh = self.usage.observe(params)
            message["_fresh_usage"] = fresh
        return message

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
        # Workspace write protects Git metadata unless it is an explicit root.
        # Workflows own fresh plain clones; no parent or unrelated repository
        # receives write permission. Read-only roles do not use this policy.
        return {"type": "workspaceWrite",
                "writableRoots": [str(self.repo), str(self.repo / ".git")],
                "networkAccess": False}

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

    def start_thread(self, writable=False):
        result = self.rpc("thread/start", {"cwd": str(self.repo), "model": self.model,
            "modelProvider": "openai", "approvalPolicy": "never",
            "sandbox": "workspace-write" if writable else "read-only",
            "config": {"model_reasoning_effort": self.effort},
            "experimentalRawEvents": False})
        self.parent_threads.add(result["thread"]["id"])
        return result["thread"]["id"]

    def child_report(self, force=False):
        if not hasattr(self, "nested"):
            return {"observed_raw_tokens": 0, "cached_input_tokens": 0,
                    "measurement_complete": True, "errors": [], "incomplete": []}
        parents = self.parent_threads | set(self.usage.totals)
        self.nested.refresh(parents, force=force)
        report = self.nested.report(parents)
        if hasattr(self, "commands"):
            processes = self.commands.children.report()
            report["processes"] = processes
            report["measurement_complete"] &= processes["measurement_complete"]
            report["errors"].extend(processes["errors"])
        return report

    def settle_children(self):
        if not hasattr(self, "commands"):
            return
        def check_budget():
            if time.monotonic() >= self.deadline or self.observed_raw() >= self.max_raw:
                raise Fatal("workflow wall-time/observed-token limit reached while waiting for nested verification")
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

    def turn(self, thread, prompt, label, interrupt=False, host_request=False, writable=False):
        self.settle_children()
        if len(self.turns) >= self.max_turns:
            raise Fatal("workflow turn limit reached")
        if time.monotonic() >= self.deadline or self.observed_raw() >= self.max_raw:
            raise Fatal("workflow wall-time/observed-token limit reached")
        folder = self.artifacts / f"turn-{len(self.turns)+1:04d}"
        folder.mkdir()
        (folder / "prompt.txt").write_text(prompt)
        row = {"label": label, "thread_id": thread, "status": "started", "prompt_file": str(folder / "prompt.txt")}
        self.turns.append(row)
        result = self.rpc("turn/start", {"threadId": thread, "input": [{"type": "text", "text": prompt}],
            "model": self.model, "effort": self.effort, "approvalPolicy": "never",
            "sandboxPolicy": (self.writable_policy()
                              if writable else {"type": "readOnly"})})
        turn_id = result["turn"]["id"]
        self.active = thread, turn_id
        row["turn_id"] = turn_id
        gate = InterruptGate(interrupt)
        selected, replies, interrupted = None, [], None
        priced, last_output, last_usage = False, 0.0, 0.0
        stop_reason, stop_at = None, None
        try:
            while True:
                now = time.monotonic()
                if stop_at is not None and now-stop_at > 15:
                    raise Fatal("interrupted turn did not close within 15 seconds; retained with unknown tail")
                if interrupted is None:
                    budget = now >= self.deadline or self.observed_raw() >= self.max_raw
                    reason = "budget" if budget else gate.reason(now)
                    if reason:
                        self.counter += 1
                        self.send({"id": self.counter, "method": "turn/interrupt", "params": {"threadId": thread, "turnId": turn_id}})
                        interrupted, stop_at = reason, now
                        if budget:
                            stop_reason = "workflow wall-time/observed-token limit reached"
                message = self.pending.popleft() if self.pending else self.incoming(0.1)
                if message is None:
                    continue
                params = message.get("params", {})
                if params.get("threadId") != thread:
                    continue
                event_turn = params.get("turnId") or params.get("turn", {}).get("id")
                if event_turn != turn_id:
                    continue
                method = message.get("method")
                now = time.monotonic()
                if method == "thread/tokenUsage/updated" and message.get("_fresh_usage"):
                    priced, last_usage = True, now
                    if gate.at is not None:
                        gate.fresh_usage = True
                elif method == "item/completed" and params.get("item", {}).get("type") == "agentMessage":
                    text = params["item"]["text"]
                    replies.append(text)
                    last_output = now
                    gate.fresh_usage = False
                    if selected is None and host_request:
                        try:
                            if len(parse_operations(text)) == 1:
                                selected = text
                                gate.directive(now)
                        except Rejected:
                            pass
                elif method == "turn/completed":
                    status = params["turn"].get("status")
                    row.update(status=status, interrupt_reason=interrupted)
                    if status not in ("completed", "interrupted") or (status == "interrupted" and not interrupted):
                        raise Fatal(f"agent turn ended unexpectedly: {status}; {params['turn'].get('error')}")
                    break
            # Drain late usage even after cancellation. Never execute late text.
            minimum_end = time.monotonic()+1.0
            end = minimum_end+4.0
            while time.monotonic() < end:
                if priced and last_usage >= last_output and time.monotonic() >= minimum_end:
                    break
                message = self.incoming(min(0.1, end-time.monotonic()))
                if message:
                    p = message.get("params", {})
                    if p.get("threadId") == thread and p.get("turnId") == turn_id and message.get("_fresh_usage"):
                        priced, last_usage = True, time.monotonic()
                    elif (p.get("threadId") == thread and p.get("turnId") == turn_id
                          and message.get("method") == "item/completed"
                          and p.get("item", {}).get("type") == "agentMessage"):
                        replies.append(p["item"]["text"])
                        last_output = time.monotonic()
                    else:
                        self.pending.append(message)
            if not priced or last_output > last_usage:
                self.missing_turns.append({"thread_id": thread, "turn_id": turn_id, "reason": "no fresh usage covering the last delivered message"})
            final = selected if selected is not None else (replies[-1] if replies else "")
            (folder / "reply.txt").write_text(final)
            save_json(folder / "messages.json", replies)
            row["usage_observed_after_last_message"] = priced and last_usage >= last_output
            if stop_reason:
                raise Fatal(stop_reason)
            if not final:
                raise Fatal("turn supplied no executable request or final reply")
            self.settle_children()
            return final
        except BaseException as exc:
            if interrupted is None and row.get("status") == "started":
                # A user cancellation or client-side failure still owns a live
                # generation. Request cancellation and retain accounting tails.
                try:
                    self.counter += 1
                    self.send({"id": self.counter, "method": "turn/interrupt", "params": {"threadId": thread, "turnId": turn_id}})
                    drain_end = time.monotonic()+2
                    while time.monotonic() < drain_end:
                        self.incoming(min(0.1, drain_end-time.monotonic()))
                except (OSError, Fatal):
                    self.usage.uncertain.append("transport unavailable during cancellation drain")
            row.update(error=str(exc))
            self.missing_turns.append({"thread_id": thread, "turn_id": turn_id, "reason": "failed/incomplete turn; inspect retained transport"})
            raise
        finally:
            save_json(folder / "result.json", row)
            with (self.artifacts / "coverage.jsonl").open("a") as journal:
                journal.write(json.dumps({"turn_id": turn_id, "label": label,
                    "status": row["status"], "error": row.get("error"),
                    "usage_observed_after_last_message": row.get("usage_observed_after_last_message", False)})+"\n")
            self.active = None

    def report(self):
        child = self.child_report(force=True)
        return {**self.usage.report(), "turns": self.turns, "unpriced_or_incomplete_turns": self.missing_turns,
                "parent_observed_raw_tokens": self.usage.raw, "nested": child,
                "observed_raw_tokens": self.usage.raw+child["observed_raw_tokens"],
                "cached_input_tokens": self.usage.cached+child["cached_input_tokens"],
                "measurement_complete": (not self.missing_turns and not self.usage.uncertain and bool(self.turns)
                                         and child["measurement_complete"]),
                "qualification": "parent per-turn last-message coverage plus owned native child lifecycle/model/counters; not a proof that every internal response was priced"}

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
    def __init__(self, thread_id, argv, cwd, env, stderr, log_fn):
        self.thread_id = thread_id
        self.log_fn = log_fn
        self.events = queue.Queue()
        self.process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            bufsize=1,
            start_new_session=True
        )
        self.reader = threading.Thread(target=self._reader, daemon=True)
        self.reader.start()

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


class Pi:
    transport = "pi-rpc-stdio"

    def __init__(self, repo, artifacts, model, effort, deadline, max_raw, max_turns, executable="pi", *, require_git_write=False):
        self.repo, self.artifacts = Path(repo), Path(artifacts)
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.deadline, self.max_raw, self.max_turns = deadline, max_raw, max_turns
        self.model, self.effort = model, effort
        self.usage, self.turns, self.missing_turns = Usage(), [], []
        self.threads = {}
        self.thread_counter = 0
        self.log = (self.artifacts / "transport.jsonl").open("x")
        self.stderr = (self.artifacts / "stderr.txt").open("x")
        self.command_env = clean_env()
        self.sessions_dir = self.artifacts / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        if os.environ.get("AGENT_LAB_CHILD") == "1":
            raise Fatal("recursive benchmark generation is forbidden")
        resolved = shutil.which(executable)
        if not resolved:
            raise ValueError(f"Pi executable not found: {executable}")
        self.executable = str(Path(resolved).absolute())
        try:
            self._probe()
            if require_git_write:
                self.verify_git_write()
        except BaseException:
            self.close()
            raise

    def _probe(self):
        version = subprocess.check_output([self.executable, "--version"], text=True, env=self.command_env).strip()
        auth = "default"
        probe = subprocess.Popen(
            [self.executable, "--mode", "rpc", "--approve", "--no-session"],
            cwd=self.repo,
            env=self.command_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
            bufsize=1,
            start_new_session=True
        )
        try:
            probe.stdin.write(json.dumps({"id": "probe-state", "type": "get_state"}) + "\n")
            probe.stdin.flush()
            line = probe.stdout.readline()
            probe_state = json.loads(line) if line else {}
            data = probe_state.get("data") or {}
            model_info = data.get("model") or {}
            if not self.model:
                self.model = model_info.get("id") or "default"
            auth = model_info.get("provider") or auth
        finally:
            if probe.stdin is not None:
                try:
                    probe.stdin.close()
                except Exception:
                    pass
            if probe.poll() is None:
                try:
                    probe.terminate()
                    probe.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    probe.kill()
            if probe.stdout is not None:
                try:
                    probe.stdout.close()
                except Exception:
                    pass
        self.identity = {
            "pi_version": version,
            "harness": "pi",
            "auth": auth,
            "model": self.model,
            "effort": self.effort,
            "effective_config_sha256": hashlib.sha256(json.dumps({
                "pi_version": version, "model": self.model, "effort": self.effort, "auth": auth
            }, sort_keys=True).encode()).hexdigest(),
        }
        save_json(self.artifacts / "provider.json", self.identity)

    def verify_git_write(self):
        proc = subprocess.Popen(
            [self.executable, "--mode", "rpc", "--approve", "--no-session"],
            cwd=self.repo,
            env=self.command_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
            bufsize=1,
            start_new_session=True
        )
        try:
            req = {"id": "git-preflight", "type": "bash", "command": "git update-index --refresh"}
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            receipt = {}
            while line := proc.stdout.readline():
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") == "git-preflight" and msg.get("type") == "response":
                    receipt = msg.get("data", {})
                    break
            save_json(self.artifacts / "git-write-preflight.json", {"request": req, "response": receipt})
            if receipt.get("exitCode") != 0:
                raise Fatal("Git-write preflight failed before model generation: " + str(receipt.get("output", "unknown error")))
        finally:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    proc.kill()
            if proc.stdout is not None:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

    def record(self, direction, event):
        self.log.write(json.dumps({"time": time.time(), "direction": direction, "event": event}) + "\n")
        self.log.flush()

    def start_thread(self, writable=False):
        self.thread_counter += 1
        thread_id = f"pi-thread-{self.thread_counter}"
        session_dir = self.sessions_dir / thread_id
        session_dir.mkdir(parents=True, exist_ok=True)
        argv = [self.executable, "--mode", "rpc", "--approve", "--session-dir", str(session_dir)]
        if self.model:
            argv.extend(["--model", self.model])
        if self.effort:
            argv.extend(["--thinking", self.effort])
        th = PiThread(thread_id, argv, self.repo, self.command_env, self.stderr, self.record)
        self.threads[thread_id] = th
        return thread_id

    def observed_raw(self):
        return self.usage.raw

    def turn(self, thread, prompt, label, interrupt=False, host_request=False, writable=False):
        if len(self.turns) >= self.max_turns:
            raise Fatal("workflow turn limit reached")
        if time.monotonic() >= self.deadline or self.observed_raw() >= self.max_raw:
            raise Fatal("workflow wall-time/observed-token limit reached")
        folder = self.artifacts / f"turn-{len(self.turns)+1:04d}"
        folder.mkdir()
        (folder / "prompt.txt").write_text(prompt)
        turn_id = f"turn-{len(self.turns)+1:04d}"
        row = {"label": label, "thread_id": thread, "turn_id": turn_id, "status": "started", "prompt_file": str(folder / "prompt.txt")}
        self.turns.append(row)
        th = self.threads[thread]
        gate = InterruptGate(interrupt)
        selected, replies, interrupted = None, [], None
        priced, last_output, last_usage = False, 0.0, 0.0
        stop_reason, stop_at = None, None
        try:
            th.send({"id": turn_id, "type": "prompt", "message": prompt})
            while True:
                now = time.monotonic()
                if stop_at is not None and now - stop_at > 15:
                    raise Fatal("interrupted turn did not close within 15 seconds; retained with unknown tail")
                if interrupted is None:
                    budget = now >= self.deadline or self.observed_raw() >= self.max_raw
                    reason = "budget" if budget else gate.reason(now)
                    if reason:
                        th.send({"type": "abort"})
                        interrupted, stop_at = reason, now
                        if budget:
                            stop_reason = "workflow wall-time/observed-token limit reached"
                message = th.incoming(0.1)
                if message is None:
                    continue
                if "_transport_error" in message:
                    raise Fatal(message["_transport_error"])
                if message.get("type") == "extension_ui_request":
                    th.send({"type": "extension_ui_response", "id": message.get("id"), "cancelled": True})
                if message.get("type") == "response" and message.get("command") == "prompt" and message.get("id") == turn_id:
                    if not message.get("success"):
                        raise Fatal(f"prompt failed: {message.get('error')}")
                if message.get("type") == "message_update" and message.get("usage"):
                    u = message["usage"]
                    fresh = self.usage.observe_tokens(thread, u.get("input", 0), u.get("output", 0), u.get("cacheRead", 0))
                    if fresh:
                        priced, last_usage = True, now
                        if gate.at is not None:
                            gate.fresh_usage = True
                if message.get("type") in ("message_end", "turn_end"):
                    m = message.get("message", {})
                    if m.get("role") == "assistant":
                        text = "".join(c.get("text", "") for c in m.get("content", []) if isinstance(c, dict) and c.get("type") == "text")
                        if text and (not replies or replies[-1] != text):
                            replies.append(text)
                            last_output = now
                            gate.fresh_usage = False
                            if selected is None and host_request:
                                try:
                                    if len(parse_operations(text)) == 1:
                                        selected = text
                                        gate.directive(now)
                                except Rejected:
                                    pass
                    if m.get("usage"):
                        u = m["usage"]
                        fresh = self.usage.observe_tokens(thread, u.get("input", 0), u.get("output", 0), u.get("cacheRead", 0))
                        if fresh:
                            priced, last_usage = True, now
                            if gate.at is not None:
                                gate.fresh_usage = True
                if message.get("type") == "agent_settled":
                    row.update(status="interrupted" if interrupted else "completed", interrupt_reason=interrupted)
                    break

            try:
                stats = th.rpc({"type": "get_session_stats"}, timeout=5)
                if stats and stats.get("success") and "tokens" in stats.get("data", {}):
                    tok = stats["data"]["tokens"]
                    self.usage.observe_tokens(thread, tok.get("input", 0), tok.get("output", 0), tok.get("cacheRead", 0))
                    priced = True
                    last_usage = time.monotonic()
            except Exception:
                pass

            if not priced or last_output > last_usage:
                self.missing_turns.append({"thread_id": thread, "turn_id": turn_id, "reason": "no fresh usage covering the last delivered message"})
            final = selected if selected is not None else (replies[-1] if replies else "")
            (folder / "reply.txt").write_text(final)
            save_json(folder / "messages.json", replies)
            row["usage_observed_after_last_message"] = priced and last_usage >= last_output
            if stop_reason:
                raise Fatal(stop_reason)
            if not final:
                raise Fatal("turn supplied no executable request or final reply")
            return final
        except BaseException as exc:
            if interrupted is None and row.get("status") == "started":
                try:
                    th.send({"type": "abort"})
                    drain_end = time.monotonic() + 2
                    while time.monotonic() < drain_end:
                        th.incoming(min(0.1, drain_end - time.monotonic()))
                except (OSError, Fatal):
                    self.usage.uncertain.append("transport unavailable during cancellation drain")
            row.update(error=str(exc))
            self.missing_turns.append({"thread_id": thread, "turn_id": turn_id, "reason": "failed/incomplete turn; inspect retained transport"})
            raise
        finally:
            save_json(folder / "result.json", row)
            with (self.artifacts / "coverage.jsonl").open("a") as journal:
                journal.write(json.dumps({"turn_id": turn_id, "label": label,
                    "status": row["status"], "error": row.get("error"),
                    "usage_observed_after_last_message": row.get("usage_observed_after_last_message", False)}) + "\n")

    def report(self):
        return {
            **self.usage.report(),
            "turns": self.turns,
            "unpriced_or_incomplete_turns": self.missing_turns,
            "parent_observed_raw_tokens": self.usage.raw,
            "nested": {"observed_raw_tokens": 0, "cached_input_tokens": 0, "measurement_complete": True, "errors": [], "incomplete": []},
            "observed_raw_tokens": self.usage.raw,
            "cached_input_tokens": self.usage.cached,
            "measurement_complete": (not self.missing_turns and not self.usage.uncertain and bool(self.turns)),
            "qualification": "pi rpc per-turn coverage and session tokens"
        }

    def close(self):
        for th in self.threads.values():
            th.close()
        if hasattr(self, "log") and not self.log.closed:
            self.log.close()
        if hasattr(self, "stderr") and not self.stderr.closed:
            self.stderr.close()
