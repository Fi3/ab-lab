"""Exercise role changes in Pi's installed extension without a model request."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from lab.provider import Pi


class PiToolRoleTests(unittest.TestCase):
    def test_launch_allows_tools_needed_by_later_role_transitions(self):
        provider = object.__new__(Pi)
        provider.executable, provider.model, provider.effort = 'pi', 'test-model', 'high'
        argv = provider.launch_arguments()
        self.assertEqual(argv[argv.index('--tools') + 1], 'read,bash,edit,write')

    @unittest.skipUnless(shutil.which('pi') and shutil.which('node'), 'installed Pi SDK required')
    def test_extension_updates_tools_on_role_transition_and_retains_review_tool(self):
        from lab.pi_sandbox import PiSandbox
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sandbox = PiSandbox(root, 'codex', shutil.which('pi'))
            policy = root / 'policy.json'
            policy.write_text(json.dumps({'writable': False}))
            definitions = root / 'tools.json'
            definitions.write_text(json.dumps([{'name': 'submit_review', 'description': 'Submit verdict',
                'inputSchema': {'type': 'object', 'properties': {}}}]))
            script = """
import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import extension from './lab/pi_sandbox.mjs';
const sdk = await import(process.env.AGENT_LAB_PI_MODULE);
const cwd = process.env.AGENT_LAB_PI_TEST_ROOT;
const settingsManager = sdk.SettingsManager.inMemory({cacheWarming: 'off'});
const modelRuntime = await sdk.ModelRuntime.create({
  authPath: cwd + '/auth.json', modelsPath: null,
  modelsStorePath: cwd + '/models.json', refreshOnCreate: false,
});
modelRuntime.prepareRequest = () => {
  throw new Error('Model requests are forbidden in this test');
};
const resourceLoader = new sdk.DefaultResourceLoader({
  cwd, agentDir: cwd, settingsManager, extensionFactories: [extension],
  noExtensions: true, noSkills: true, noPromptTemplates: true,
  noThemes: true, noContextFiles: true,
});
await resourceLoader.reload();
const {session} = await sdk.createAgentSession({
  cwd, agentDir: cwd, settingsManager, modelRuntime, resourceLoader,
  model: modelRuntime.getModels()[0], sessionManager: sdk.SessionManager.inMemory(cwd),
  tools: [...JSON.parse(process.env.AGENT_LAB_PI_TEST_ALLOWED_TOOLS), 'submit_review'],
});
const errors = [];
await session.bindExtensions({onError: error => errors.push(error)});
assert.deepEqual(session.getActiveToolNames(), ['read', 'bash', 'submit_review']);
assert(session.getAllTools().some(tool => tool.name === 'edit'));
assert(session.getAllTools().some(tool => tool.name === 'write'));
for (const writable of [true, false]) {
  writeFileSync(process.env.AGENT_LAB_PI_POLICY, JSON.stringify({writable}));
  await session.extensionRunner.emitBeforeAgentStart('Role transition', undefined, {cwd});
  assert.deepEqual(session.getActiveToolNames(),
    ['read', 'bash', ...(writable ? ['edit', 'write'] : []), 'submit_review']);
}
assert.deepEqual(errors, []);
session.dispose();
process.exit(0);
"""
            provider = object.__new__(Pi)
            provider.executable, provider.model, provider.effort = 'pi', 'test-model', 'high'
            argv = provider.launch_arguments()
            result = subprocess.run(['node', '--input-type=module', '-e', script],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20,
                input='', env={**os.environ, 'AGENT_LAB_PI_MODULE': sandbox.module,
                    'AGENT_LAB_PI_POLICY': str(policy), 'AGENT_LAB_PI_HOST_TOOLS': str(definitions),
                    'AGENT_LAB_PI_TEST_ROOT': str(root),
                    'AGENT_LAB_PI_TEST_ALLOWED_TOOLS': json.dumps(argv[argv.index('--tools') + 1].split(',')),
                    'AGENT_LAB_PI_HOST_RESPONSE_FD': '0', 'AGENT_LAB_PI_HOST_REQUEST_FD': '1'})
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
