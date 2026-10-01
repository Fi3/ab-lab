"""Run Pi's own tool implementations inside the installed Codex OS sandbox."""
import json
from pathlib import Path
import shutil
import time

from .host import Fatal
from .sandbox import CommandSandbox


class PiSandbox:
    extension = Path(__file__).with_name('pi_sandbox.mjs').resolve()
    worker = Path(__file__).with_name('pi_tool.mjs').resolve()

    def __init__(self, repo, codex, pi, *, execution=None):
        self.repo, self.codex = Path(repo).resolve(), str(codex)
        self.execution = execution or CommandSandbox(self.repo, self.codex)
        self.node = shutil.which('node')
        if not self.node:
            raise Fatal('Node is required for sandboxed Pi tools')
        for parent in Path(pi).resolve().parents:
            package = parent / 'package.json'
            if package.is_file():
                metadata = json.loads(package.read_text())
                if metadata.get('name', '').endswith('/pi-coding-agent'):
                    module = parent / metadata['main']
                    if module.is_file():
                        self.module = module.as_uri()
                        break
        else:
            raise Fatal('Pi tool SDK could not be located; refusing unsandboxed execution')

    def command(self, writable, command=None):
        return self.execution.command(writable, command if command is not None else [self.node, str(self.worker)])

    def policy(self, writable, deadline=None, *, native_process=False):
        return {'argv': self.command(writable), 'shell_argv': self.command(writable, []), 'writable': writable, 'native_process': native_process,
                'deadline': time.time() + (max(0, deadline-time.monotonic()) if deadline is not None else 30)}

    def configure(self, path, writable, deadline, *, native_process=False):
        staged = path.with_name(path.name + '.next')
        staged.write_text(json.dumps(self.policy(writable, deadline, native_process=native_process)))
        staged.replace(path)
