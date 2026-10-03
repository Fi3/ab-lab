"""Model-free verification of the rebuilt executor; run explicitly with Python."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.config import FACTORS, settings
from lab.evaluation import ADAPTERS, BaseEvaluator
from lab.executor import (DEFAULT_PROFILE, GradingBridge, container_argv, docker,
                          load_lock, quality_proxy, runner_mounts, write_json)
from lab.host import git
from lab import scb


class Evaluator(BaseEvaluator):
    config_key = 'executor_fixture'

    def checkpoint(self, checkout, checkpoint, quality_tool, deadline):
        observation = scb.measure(checkout, self.output, 'checkpoint-' + checkpoint['feature'],
                                  quality_tool, deadline)
        assert observation['status'] == 'completed', observation

    def evaluate(self):
        assert (self.output / 'provider-closed').exists()
        path = self.output / 'fixture-grade.json'
        write_json(path, {'container': Path('/.dockerenv').exists()})
        return {'status': 'completed', 'passed': True, 'report_path': str(path)}


INNER = '''import json,os,pathlib,sys,subprocess
sys.path.insert(0, str(pathlib.Path.cwd()/'tests'))
from lab.evaluation import ADAPTERS
ADAPTERS['executor_fixture']='executor_smoke'
from lab.workflow import run
from lab.sandbox import CommandSandbox
from test_workflow import FakeCodex
from test_evaluation import NativeAuthor
class Mediated(FakeCodex):
    def close(self):
        (self.artifacts.parent/'provider-closed').touch()
private=pathlib.Path(os.environ['AGENT_LAB_EXECUTOR_PRIVATE'])
request=json.loads((private/'request.json').read_text())
backend=Mediated if request['factors']['C17'] else NativeAuthor
result=run(request['benchmark'],request['factors'],request['output'],60,10000,30,
    backend=backend,max_review_loops=0,scb_check='scb-check',_admitted_output=True)
assert result['status']=='passed',result
assert result['scb_check']['status']=='completed',result
repo=pathlib.Path(request['output'])/'checkout'
probe='import pathlib; p=pathlib.Path('+repr(str(private/'bridge.key'))+'); '\\
    '\\ntry:p.read_bytes()\\nexcept PermissionError:pass\\nelse:raise AssertionError("bridge accessible")'
sandbox=CommandSandbox(repo,request['codex'])
for writable,protect_git in ((False,False),(True,True),(True,False)):
    p=subprocess.run(sandbox.command(writable,[sys.executable,'-c',probe],protect_git=protect_git),capture_output=True,text=True)
    assert p.returncode==0,p.stderr
print(json.dumps({'status':result['status'],'mediated':request['factors']['C17'],
                  'quality':result['scb_check']['status'],'permissions':'all roles deny bridge'}))
'''


def main():
    lock = load_lock(DEFAULT_PROFILE)
    ADAPTERS['executor_fixture'] = 'executor_smoke'
    sys.modules['executor_smoke'] = sys.modules[__name__]
    with tempfile.TemporaryDirectory(prefix='agent-lab-smoke-') as temporary:
        root = Path(temporary)
        source = root / 'source'
        source.mkdir()
        git(source, 'init', '-q')
        git(source, 'config', 'user.name', 'Executor test')
        git(source, 'config', 'user.email', 'test@example.invalid')
        (source / 'seed.py').write_text('value = 0\n')
        git(source, 'add', '.')
        git(source, 'commit', '-qm', 'baseline')
        benchmark = {'name': 'executor-smoke', 'repo': str(source), 'revision': 'HEAD',
            'features': [{'id': 'one', 'request': 'Create one.py'}], 'executor_fixture': {},
            'checks': ["python3 -c 'from pathlib import Path; assert Path(\"/.dockerenv\").exists()'"]}
        for mediated in (True, False):
            private = root / ('mediated-private' if mediated else 'native-private')
            private.mkdir()
            (private / 'auth/codex').mkdir(parents=True)
            (private / 'auth/pi').mkdir(parents=True)
            output = root / ('mediated' if mediated else 'native')
            output.mkdir()
            factors = settings({}) if mediated else dict.fromkeys(FACTORS, False)
            write_json(private / 'request.json', {'benchmark': benchmark, 'factors': factors,
                'output': str(output), 'codex': lock['harnesses']['codex']})
            write_json(private / 'execution.json', {'mode': 'rebuilt-executor-v1',
                'environment_identity': lock['build_sha256'], 'image': lock['image']})
            bridge = GradingBridge(private, benchmark, output, quality_proxy(lock, private, output))
            name = 'agent-lab-smoke-' + os.urandom(8).hex()
            try:
                result = subprocess.check_output(container_argv(lock, name,
                    [*runner_mounts(lock, True), (private, private, True),
                     (source, source, False), (output, output, True)],
                    [lock['python'], '-c', INNER], private), text=True)
                print(result.strip())
                assert not json.loads((output / 'fixture-grade.json').read_text())['container']
            finally:
                docker('rm', '-f', name, stdout=subprocess.DEVNULL)
                bridge.close()


if __name__ == '__main__':
    main()
