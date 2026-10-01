"""The same retained role profiles drive Codex, Pi and host commands."""
from pathlib import Path
import tempfile
import unittest

from lab.sandbox import CommandSandbox, HOST_PROFILE, READ_ONLY_PROFILE, WRITE_PROFILE


class SandboxPolicyTests(unittest.TestCase):
    def test_retained_profiles_allow_scratch_and_protect_source_git_and_agent_state(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / 'checkout'
            private = Path(directory) / 'credentials'
            original = Path(directory) / 'original'
            sandbox = CommandSandbox(repo, 'codex', blocked_paths=[private], read_only_paths=[original])
            options = sandbox.thread_options(False)
            self.assertEqual(options['permissions'], READ_ONLY_PROFILE)
            self.assertEqual(options['config']['default_permissions'], READ_ONLY_PROFILE)
            for profile, source, git in ((READ_ONLY_PROFILE, 'read', 'read'),
                                         (HOST_PROFILE, 'write', 'read'),
                                         (WRITE_PROFILE, 'write', 'write')):
                paths = options['config'][f'permissions.{profile}.filesystem']
                self.assertEqual(paths[str(repo)], source)
                self.assertEqual(paths[str(repo / '.git')], git)
                self.assertEqual(paths[str(private)], 'none')
                self.assertEqual(paths[str(original)], 'read')
                self.assertEqual(paths[':slash_tmp'], 'write')
                self.assertEqual(paths[':tmpdir'], 'write')
                self.assertTrue(options['config'][f'permissions.{profile}.network.enabled'])

    def test_command_uses_same_role_selector_and_no_legacy_sandbox_override(self):
        sandbox = CommandSandbox('/repo', 'codex')
        for writable, protected, profile in ((False, False, READ_ONLY_PROFILE),
                                            (True, True, HOST_PROFILE),
                                            (True, False, WRITE_PROFILE)):
            with self.subTest(profile=profile):
                command = sandbox.command(writable, ['echo', 'ok'], protect_git=protected)
                self.assertEqual(command[-5:], ['--permission-profile', profile, '--', 'echo', 'ok'])
                self.assertEqual(sandbox.turn_options(writable, protected), {'permissions': profile})
                self.assertFalse(any('sandbox_mode=' in arg for arg in command))


if __name__ == '__main__':
    unittest.main()
