"""Run final checks with writable Cargo state and the existing command sandbox."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import time

from .environment import clean_env
from .host import execute_child, save_json


CARGO_CACHE_POLICY = "isolated-final-check-cargo-v1"


@contextmanager
def final_check_environment(environment=None):
    # Final checks must not trust an author's dependency cache or build output.
    # Scratch space is writable in every command profile without home access.
    with tempfile.TemporaryDirectory(prefix="agent-lab-final-check-") as directory:
        root = Path(directory)
        cache, target = root / "cargo", root / "target"
        cache.mkdir()
        target.mkdir()
        yield {**clean_env(environment), "CARGO_HOME": str(cache), "CARGO_TARGET_DIR": str(target)}


def execute_check(command, checkout, folder, deadline, *, command_argv, environment):
    folder = Path(folder)
    folder.mkdir()
    argv = command_argv(["/bin/sh", "-c", command])
    receipt = execute_child(argv, checkout, None, folder / "stdout.txt", folder / "stderr.txt",
                            min(300, deadline-time.monotonic()), environment)
    receipt.update(command=command, environment={"cargo_cache_policy": CARGO_CACHE_POLICY,
        "CARGO_HOME": environment["CARGO_HOME"], "CARGO_TARGET_DIR": environment["CARGO_TARGET_DIR"]})
    save_json(folder / "result.json", receipt)
    return receipt
