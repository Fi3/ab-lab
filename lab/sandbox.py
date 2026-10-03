"""Shared filesystem and network permissions for native tools and test commands."""
import json
import os
from pathlib import Path


EXECUTION_POLICY = 'role-filesystem-network-enabled-v2'
READ_ONLY_PROFILE = 'agent-lab-read-only-network'
HOST_PROFILE = 'agent-lab-host-network'
WRITE_PROFILE = 'agent-lab-write-network'


class CommandSandbox:
    def __init__(self, repo, codex, writable_roots=(), *, blocked_paths=(), read_only_paths=(), read_only_blocked_paths=()):
        self.repo, self.codex = Path(repo).resolve(), str(codex)
        self.roots = list(dict.fromkeys(str(Path(p).resolve()) for p in
            (self.repo, self.repo / '.git', *writable_roots)))
        self.blocked_paths = list(dict.fromkeys(str(Path(p).resolve()) for p in blocked_paths))
        # The host grading bridge and provider credentials are trusted runner
        # state. All agent roles, including native child tools, must be masked.
        private = os.environ.get('AGENT_LAB_EXECUTOR_PRIVATE')
        if private:
            self.blocked_paths.append(str(Path(private).resolve()))
        self.read_only_blocked_paths = [str(Path(p).resolve()) for p in read_only_blocked_paths]
        masked = {Path(p) for p in self.blocked_paths}
        self.blocked_paths = sorted(str(p) for p in masked if not any(parent in masked for parent in p.parents))
        self.read_only_blocked_paths = [p for p in self.read_only_blocked_paths
                                       if not any(Path(p) == mask or Path(p).is_relative_to(mask) for mask in masked)]
        self.read_only_paths = list(dict.fromkeys(str(Path(p).resolve()) for p in read_only_paths))

    def policy(self, writable):
        # Only trusted runner preflights use command/exec's standalone policy.
        # Agent turns and commands must use the retained named profiles below.
        if writable:
            return {'type': 'workspaceWrite', 'writableRoots': self.roots,
                    'networkAccess': True}
        return {'type': 'readOnly', 'networkAccess': True}

    def profile(self, writable, protect_git=False):
        return (HOST_PROFILE if protect_git else WRITE_PROFILE) if writable else READ_ONLY_PROFILE

    def filesystem(self, writable, protect_git=False):
        # A read-only checkout still needs scratch space for tests. Explicitly
        # protect it even when the checkout itself lives below /tmp.
        paths = {':root': 'read', ':tmpdir': 'write', ':slash_tmp': 'write'}
        if writable:
            paths.update({path: 'write' for path in self.roots})
        paths[str(self.repo)] = 'write' if writable else 'read'
        paths[str(self.repo / '.git')] = 'write' if writable and not protect_git else 'read'
        paths.update({path: 'read' for path in self.read_only_paths})
        paths.update({path: 'none' for path in self.blocked_paths})
        if not writable:
            paths.update({path: 'none' for path in self.read_only_blocked_paths})
        return paths

    def turn_options(self, writable, protect_git=False):
        return {'permissions': self.profile(writable, protect_git)}

    def thread_options(self, writable, protect_git=False):
        # Persist all profiles: a retained planning thread later switches to
        # native implementation without gaining access outside its role.
        config = {'default_permissions': self.profile(writable, protect_git)}
        for can_write, git_guard in ((False, False), (True, True), (True, False)):
            name = self.profile(can_write, git_guard)
            config[f'permissions.{name}.filesystem'] = self.filesystem(can_write, git_guard)
            config[f'permissions.{name}.network.enabled'] = True
        return {**self.turn_options(writable, protect_git), 'config': config}

    def command(self, writable, argv, *, protect_git=False):
        options = self.thread_options(writable, protect_git)
        config = {'approval_policy': 'never', **options['config']}
        args = [self.codex, 'sandbox']
        for key, value in config.items():
            # Config overrides are TOML, not JSON objects.
            if isinstance(value, dict):
                value = '{' + ', '.join(json.dumps(k)+'='+json.dumps(v) for k, v in value.items()) + '}'
            else:
                value = json.dumps(value)
            args += ['-c', key+'='+value]
        args += ['--permission-profile', options['permissions']]
        return [*args, '--', *argv]
