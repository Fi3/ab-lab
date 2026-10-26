"""The live probe must receive the corrected function, not only an explanation."""
import unittest
from unittest.mock import patch

from real_native_capabilities import has_addition


class NativeProbeTests(unittest.TestCase):
    def test_correct_functions_survive_reply_formatting(self):
        correct = 'def add(a, b):\n    return a+b\n'
        wrong = '```python\ndef add(a, b):\n    return a-b\n```'
        indented = '    def add(a, b):\n        return a + b\n'
        replies = [
            correct,
            'def add(a,b): return a+b',
            '`def add(a,b): return a+b`',
            'The fix is `def add(a,b): result=a+b; return result`.',
            'def add(a,b):\n    result=a+b\n    return result\n',
            'def add(x,y):\n    total=x+y\n    result=total\n    return result\n',
            'def add(a,b):\n    a+b\n    return a+b\n',
            'def add(b,a): return a+b',
            'def add(x,y): return sum([x,y])',
            'def add(x,y):\n    if x < 0:\n        return y-abs(x)\n    return x+y\n',
            '```python\n' + correct + '```',
            '```py\ndef add(a,b):\n\treturn a\t+\tb\n```',
            '```\n' + correct + '```',
            indented,
            'def add(\n    a,\n    b,\n):\n    return (\n        a\n        + b\n    )\n',
            'def add(a: int, b: int) -> int:\n    return a+b\n',
            'def add(a, b=0): return a+b',
            'def add(a, b, /): return a+b',
            'def add(a, b, extra=0): return a+b',
            'def add(a, b, *args, **kwargs): return a+b',
            'def add(a, b, *, extra=None): return a+b',
            'def add(a, b):\n    """Return the sum."""\n    # Keep both arguments.\n    return a+b\n',
            wrong + '\n\nThe corrected function is:\n\n' + indented,
            wrong + '\n\nThe fix is `def add(x,y): result=x+y; return result`.',
            'The corrected function is:\n\n' + indented + '\nThe original was:\n' + wrong,
            'Use the sum of both arguments:\n\n' + indented,
        ]
        for reply in replies:
            with self.subTest(reply=reply):
                self.assertTrue(has_addition(reply))

    def test_explanations_and_incorrect_functions_do_not_pass(self):
        replies = [
            'It should return a + b.\n```python\ndef add(a, b):\n    return a-b\n```',
            'It should return a + b.',
            'a+b',
            'def add(a, b):\n    # return a+b\n    return a-b\n',
            'def add(a, b):\n    """return a+b"""\n    return a-b\n',
            'def add(a, b):\n    return "a+b"\n',
            'def other(a, b):\n    return a+b\n',
            'def outer():\n    def add(a, b):\n        return a+b\n',
            'Here is the code:\ndef outer():\n    def add(a, b):\n        return a+b\n',
            'def add(a, b):\n    a+b\n    return a-b\n',
            'def add(a, b):\n    a += 1\n    return a+b\n',
            'def add(a): return a+b',
            'def add(c, d): return a+b',
            'def add(a, b, required): return a+b',
            'def add(a, b, *, required): return a+b',
            '@alter_result\ndef add(a, b): return a+b',
            'Here is the code:\n@alter_result\ndef add(a, b): return a+b',
            '"""\ndef add(a, b):\n    return a+b\n"""',
            'Example text:\n"""\ndef add(a, b):\n    return a+b\n"""',
            '# `def add(a,b): return a+b`\ndef add(a,b): return a-b',
            '"""`def add(a,b): return a+b`"""\ndef add(a,b): return a-b',
        ]
        for reply in replies:
            with self.subTest(reply=reply):
                self.assertFalse(has_addition(reply))

    def test_unsafe_code_is_rejected_before_execution(self):
        replies = [
            'def add(a,b):\n    import os\n    return a+b',
            'def add(a,b): return a.__class__',
            'def add(a,b): return eval("a+b")',
            'def add(a,b, extra=__import__("os")): return a+b',
            'def add(a,b):\n    while True:\n        pass',
            '@alter_result\ndef add(a,b): return a+b',
        ]
        with patch('real_native_capabilities.subprocess.run') as execute:
            for reply in replies:
                with self.subTest(reply=reply):
                    self.assertFalse(has_addition(reply))
            execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
