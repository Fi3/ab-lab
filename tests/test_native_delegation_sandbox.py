"""Installed native harness probes without sending any model request."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from lab.nested import CommandEnvironment
from lab.pi_sandbox import PiSandbox


@unittest.skipUnless(shutil.which('codex') and shutil.which('pi') and shutil.which('node'),
                     'installed Codex/Pi/Node required')
class NativeDelegationSandboxTests(unittest.TestCase):
    def test_pi_extension_tools_keep_their_names_and_share_the_process_sandbox(self):
        from unittest.mock import patch
        import time
        with tempfile.TemporaryDirectory(prefix='native-process-', dir=Path(__file__).resolve().parents[1]) as directory:
            root = Path(directory)
            repo = root / 'checkout'
            repo.mkdir()
            state = root / 'original-state'
            state.mkdir()
            (state / 'auth.json').write_text('{}')
            with patch.dict(os.environ, {'CODEX_HOME': str(state), 'PI_CODING_AGENT_DIR': str(state)}):
                commands = CommandEnvironment(repo, root / 'commands', shutil.which('codex'),
                    pi_executable=shutil.which('pi'), allow_delegation=True, deadline=time.monotonic()+30)
            try:
                sandbox = PiSandbox(repo, commands.executable, shutil.which('pi'), execution=commands.sandbox)
                owned = commands.native_state.root
                policy = owned / 'policy.json'
                policy.write_text(json.dumps({'native_process': True, 'writable': True}))
                script = r'''
import assert from 'node:assert/strict';
import {writeFileSync, readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';
const extension = (await import(pathToFileURL(process.env.TEST_EXTENSION))).default;
const sdk = await import(process.env.AGENT_LAB_PI_MODULE);
const cwd = process.cwd();
const settingsManager = sdk.SettingsManager.inMemory({cacheWarming: 'off'});
const modelRuntime = await sdk.ModelRuntime.create({
  authPath: process.env.AGENT_LAB_TEST_STATE + '/auth.json', modelsPath: null,
  modelsStorePath: process.env.AGENT_LAB_TEST_STATE + '/models.json', refreshOnCreate: false,
});
modelRuntime.prepareRequest = () => { throw new Error('Model requests forbidden in this probe'); };
let delegate;
const standardExtension = pi => {
  delegate = {name:'delegate_fixture', label:'Delegate fixture', description:'Fixture native extension',
    parameters:{type:'object',properties:{}}, execute:async () => {
      writeFileSync(cwd+'/allowed.txt','ok');
      assert.throws(() => writeFileSync(process.env.AGENT_LAB_TEST_SHARED+'/auth.json','bad'));
      assert.throws(() => writeFileSync(process.env.AGENT_LAB_TEST_SIBLING,'bad'));
      return {content:[{type:'text',text:'ok'}]};
    }};
  pi.registerTool(delegate);
};
const resourceLoader = new sdk.DefaultResourceLoader({cwd, agentDir:process.env.AGENT_LAB_TEST_STATE,
  settingsManager, extensionFactories:[standardExtension,extension], noExtensions:true,
  noSkills:true,noPromptTemplates:true,noThemes:true,noContextFiles:true});
await resourceLoader.reload();
const {session} = await sdk.createAgentSession({cwd,agentDir:process.env.AGENT_LAB_TEST_STATE,
 settingsManager,modelRuntime,resourceLoader,model:modelRuntime.getModels()[0],
 sessionManager:sdk.SessionManager.inMemory(cwd)});
const errors=[];
await session.bindExtensions({onError:error=>errors.push(error)});
assert(session.getActiveToolNames().includes('delegate_fixture'));
assert(session.getActiveToolNames().includes('edit'));
await session.extensionRunner.emitBeforeAgentStart('No generation',undefined,{cwd});
assert(session.getActiveToolNames().includes('delegate_fixture'));
await delegate.execute();
assert.deepEqual(errors,[]);
session.dispose();
console.log('NATIVE_EXTENSION_SANDBOX_OK');
process.exit(0);
'''
                env = {**commands.env, 'AGENT_LAB_PI_MODULE': sandbox.module,
                    'AGENT_LAB_PI_POLICY': str(policy), 'AGENT_LAB_PI_NONCE': 'fixture',
                    'AGENT_LAB_PI_THREAD_ID': 'fixture',
                    'AGENT_LAB_PI_REQUEST_JOURNAL': str(owned / 'requests.jsonl'),
                    'AGENT_LAB_TEST_STATE': str(owned), 'AGENT_LAB_TEST_SHARED': str(state),
                    'AGENT_LAB_TEST_SIBLING': str(root / 'forbidden.txt'),
                    'TEST_EXTENSION': str(PiSandbox.extension)}
                result = subprocess.run(commands.sandbox.command(True, ['node','--input-type=module','-e',script]),
                    cwd=repo, env=env, capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('NATIVE_EXTENSION_SANDBOX_OK', result.stdout)
                self.assertEqual((state / 'auth.json').read_text(), '{}')
                self.assertEqual((repo / 'allowed.txt').read_text(), 'ok')
            finally:
                commands.close()

    def test_installed_native_providers_initialize_without_model_requests(self):
        import time
        from lab.provider import Codex, Pi
        with tempfile.TemporaryDirectory(prefix='native-startup-', dir=Path(__file__).resolve().parents[1]) as directory:
            root = Path(directory)
            repo = root / 'checkout'
            repo.mkdir()
            for name, backend in (('codex', Codex), ('pi', Pi)):
                with self.subTest(harness=name):
                    provider = backend(repo, root / name, 'gpt-5.5', 'high', time.monotonic()+30,
                                       1000, 1, allow_delegation=True)
                    try:
                        if name == 'codex':
                            provider.start_thread(writable=True)
                        self.assertFalse(provider.delegation_disabled)
                        self.assertEqual(provider.turns, [])
                        self.assertEqual(provider.observed_raw(), 0)
                    finally:
                        provider.close()
