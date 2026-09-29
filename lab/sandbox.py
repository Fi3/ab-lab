"""Shared filesystem and network permissions for native tools and test commands."""
import json
from pathlib import Path


EXECUTION_POLICY = 'shared-checks-network-enabled-v1'
READ_ONLY_PROFILE = 'agent-lab-read-only-network'


class CommandSandbox:
    def __init__(self, repo, codex, writable_roots=()):
        self.repo, self.codex = Path(repo).resolve(), str(codex)
        self.roots = list(dict.fromkeys(str(Path(p).resolve()) for p in
            (self.repo, self.repo / '.git', *writable_roots)))

    def policy(self, writable):
        if writable:
            return {'type': 'workspaceWrite', 'writableRoots': self.roots,
                    'networkAccess': True}
        return {'type': 'readOnly', 'networkAccess': True}

    def thread_options(self, writable):
        if writable:
            return {'sandbox': 'workspace-write', 'config': {
                'sandbox_workspace_write.writable_roots': self.roots,
                'sandbox_workspace_write.network_access': True}}
        # The CLI's legacy read-only preset has no network toggle. A named
        # profile expresses the same readOnly/networkAccess policy as the RPC.
        # Persist the selector too: app-server rebuilds retained configuration
        # before a model request without thread/start's typed overrides.
        return {'permissions': READ_ONLY_PROFILE, 'config': {
            'default_permissions': READ_ONLY_PROFILE,
            f'permissions.{READ_ONLY_PROFILE}.filesystem': {':root': 'read'},
            f'permissions.{READ_ONLY_PROFILE}.network.enabled': True}}

    def command(self, writable, argv):
        options = self.thread_options(writable)
        config = {'approval_policy': 'never', **options['config']}
        if writable:
            config['sandbox_mode'] = options['sandbox']
        args = [self.codex, 'sandbox']
        for key, value in config.items():
            # Config overrides are TOML, not JSON objects.
            if isinstance(value, dict):
                value = '{' + ', '.join(json.dumps(k)+'='+json.dumps(v) for k, v in value.items()) + '}'
            else:
                value = json.dumps(value)
            args += ['-c', key+'='+value]
        if not writable:
            args += ['--permission-profile', READ_ONLY_PROFILE]
        return [*args, '--', *argv]
