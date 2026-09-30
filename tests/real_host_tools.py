"""Opt-in small live probe of native host tools; no benchmark solutions involved."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.config import settings
from lab.host import Host, git, save_json
from lab.host_tools import HOST_TOOLS, HostTools
from lab.provider import Codex, Pi


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", choices=("codex", "pi"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    repo = out / "checkout"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Host tool probe")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "value.txt").write_text("42\n")
    (repo / ".gitignore").write_text("__pycache__/\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "ADD host tool fixture")
    deadline = time.monotonic() + 240
    save_json(out / "admission.json", {"harness": args.harness, "seconds": 240,
        "max_raw": 120000, "max_turns": 1, "model": "gpt-5.5", "effort": "xhigh",
        "purpose": "native host tool read/edit/check and natural completion"})
    provider = None
    result = {"status": "failed"}
    try:
        backend = Codex if args.harness == "codex" else Pi
        provider = backend(repo, out / "provider", "gpt-5.5", "xhigh", deadline,
                           120000, 1)
        host = Host(repo, out / "host", "probe", "author", deadline, settings({}),
                    command_env=provider.command_env, command_argv=provider.command_argv)
        host_tools = HostTools(host)
        thread = provider.start_thread(tools=HOST_TOOLS, tool_handler=host_tools.execute)
        reply = provider.turn(thread,
            "This is a small tool integration test. Use host_read to read value.txt. "
            "Use host_edit to add answer.py containing Python code that prints that integer. "
            "Use host_run to execute python3 answer.py and verify the output. "
            "Use those host tools for all operations, then finish with a normal short summary.", "host-tools")
        host.unchanged()
        assert not host_tools.unfinished_calls(), "unfinished tool call"
        calls = [json.loads(path.read_text()) for path in (out / "host/tools").glob("call-*/request.json")]
        assert {row["name"] for row in calls} == {"host_read", "host_edit", "host_run"}, calls
        assert (repo / "answer.py").is_file(), "edit did not publish source"
        assert not git(repo, "status", "--porcelain"), "host left uncommitted changes"
        assert provider.turns[-1]["status"] == "completed", provider.turns
        assert provider.report()["measurement_complete"], provider.report()
        assert reply and "@standalone" not in reply, reply
        results = [json.loads(path.read_text())["result"] for path in (out / "host/tools").glob("call-*/result.json")]
        assert all(row["success"] for row in results), results
        result.update(status="passed", reply=reply, tool_calls=len(calls), head=host.expected["head"])
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        if provider:
            provider.close()
            result["usage"] = provider.report()
        save_json(out / "result.json", result)
    print(json.dumps({"status": result["status"], "error": result.get("error"),
        "raw": result.get("usage", {}).get("observed_raw_tokens"), "out": str(out)}))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
