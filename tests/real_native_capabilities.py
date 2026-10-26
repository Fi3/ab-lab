"""Bounded live verification of native delegation and complete child usage."""
import argparse
import ast
import inspect
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import time
import tokenize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.host import git, save_json
from lab.provider import Codex
from lab.config import NATIVE_DELEGATION_REQUEST


ADDITION_CHECK = '''import resource, sys
resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
resource.setrlimit(resource.RLIMIT_AS, (128*1024*1024, 128*1024*1024))
scope = {"__builtins__": {"abs": abs, "min": min, "max": max, "sum": sum}}
exec(sys.stdin.read(), scope)
for a, b in ((0,0), (1,2), (2,1), (-3,5), (7,-4), (-5,-8), (0,5), (5,0), (.25,.5), (.5,-.25)):
    assert scope["add"](a, b) == a + b
'''


def statements(code):
    try:
        yield from ast.parse(textwrap.dedent(code)).body
        return
    except SyntaxError:
        pass
    lines, end, inline_end = code.splitlines(keepends=True), 0, (0, 0)
    try:
        for token in tokenize.generate_tokens(io.StringIO(code).readline):
            line, column = token.start
            if line <= end or token.start <= inline_end:
                continue
            if token.type in (tokenize.ERRORTOKEN, tokenize.OP) and token.string == '`':
                closing = lines[line-1].find('`', column+1)
                if closing < 0:
                    continue
                block = [lines[line-1][column+1:closing]]
                inline_end = (line, closing)
            elif (token.string in ('def', 'class', 'async', '@')
                    and token.type in (tokenize.NAME, tokenize.OP)
                    and not lines[line-1][:column].strip()):
                block = inspect.getblock(lines[line-1:])
                end = line + len(block) - 1
            else:
                continue
            try:
                yield from ast.parse(textwrap.dedent(''.join(block))).body
            except SyntaxError:
                continue
    except (tokenize.TokenError, SyntaxError):
        pass


def correct_addition(node):
    if not isinstance(node, ast.FunctionDef) or node.name != 'add' or node.decorator_list:
        return False
    node.returns = None
    for part in ast.walk(node):
        if isinstance(part, (ast.arg, ast.AnnAssign)):
            part.annotation = None if isinstance(part, ast.arg) else ast.Constant(None)
    allowed = (ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign, ast.AnnAssign,
               ast.AugAssign, ast.Expr, ast.If, ast.IfExp, ast.Pass, ast.Name, ast.Constant,
               ast.List, ast.Tuple, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Call,
               ast.keyword, ast.expr_context, ast.operator, ast.unaryop, ast.boolop, ast.cmpop)
    for part in ast.walk(node):
        if (not isinstance(part, allowed) or isinstance(part, ast.FunctionDef) and part is not node
                or isinstance(part, ast.Call) and (not isinstance(part.func, ast.Name)
                    or part.func.id not in ('abs', 'min', 'max', 'sum'))):
            return False
    try:
        return subprocess.run([sys.executable, '-I', '-c', ADDITION_CHECK], input=ast.unparse(node),
            text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def has_addition(reply):
    for code in re.split(r'```(?:python|py)?\s*\n(.*?)```', reply, flags=re.DOTALL):
        for node in statements(code):
            if correct_addition(node):
                return True
    return False


def verify(provider, thread, usage):
    assert provider.identity['delegation_mode'] == 'task-requested', provider.identity
    assert usage['measurement_complete'], usage
    children = usage['native_children']
    assert children['threads'] and children['measurement_complete'], children
    for child, state in children['threads'].items():
        assert state['turns'] and all(turn['status'] == 'completed' for turn in state['turns'].values()), state
        assert sum(usage['native_usage'][child]['thread_totals'][:2]) > 0, child
    path = Path(usage['native_usage'][thread]['path'])
    messages = [json.loads(line) for line in path.read_text().splitlines()]
    instructions = '\n'.join(part.get('text', '') for row in messages
        if row.get('type') == 'response_item' and row['payload'].get('role') == 'user'
        for part in row['payload'].get('content', []))
    assert NATIVE_DELEGATION_REQUEST in instructions, 'Native delegation request is missing'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--effort', default='xhigh')
    parser.add_argument('--codex', default='codex')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    repo = out / 'checkout'
    repo.mkdir()
    git(repo, 'init', '-q')
    (repo / 'arithmetic.py').write_text('def add(a, b):\n    return a - b\n')
    save_json(out / 'admission.json', {'model': args.model, 'effort': args.effort,
        'seconds': 180, 'max_observed_raw': 150000, 'parent_turns': 1,
        'purpose': 'native capability verification; no benchmark', 'codex': args.codex})
    prompt = ('Start exactly one native review subagent. Ask it to check arithmetic.py for correctness. '
              'Use the same model and reasoning effort. Do not start any other agents or edit files. '
              'Wait for the child to finish, then explain the defect and return the corrected function.')
    save_json(out / 'request.json', {'prompt': prompt})
    provider, thread, result = None, None, {'status': 'failed'}
    started = time.monotonic()
    try:
        provider = Codex(repo, out / 'provider', args.model, args.effort, started+180,
                         150000, 1, executable=args.codex, allow_delegation=True, native_capabilities=True)
        thread = provider.start_thread(writable=True)
        result['reply'] = provider.turn(thread, prompt, 'native-capabilities', writable=True)
        provider.settle_children()
        assert has_addition(result['reply']), result['reply']
        result['status'] = 'passed'
    except (Exception, KeyboardInterrupt) as exc:
        result['error'] = str(exc)
    finally:
        if provider:
            try:
                provider.close()
                result['usage'] = provider.report()
                verify(provider, thread, result['usage'])
            except (Exception, KeyboardInterrupt) as exc:
                result.update(status='failed', error=result.get('error') or str(exc))
        result['duration_seconds'] = time.monotonic()-started
        save_json(out / 'result.json', result)
    print(json.dumps({key: value for key, value in result.items() if key != 'usage'}))
    return int(result['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
