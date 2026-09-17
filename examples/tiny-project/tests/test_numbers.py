import unittest

from numbers_demo import identity


class IdentityTests(unittest.TestCase):
    def test_identity(self):
        self.assertEqual(identity(3), 3)


if __name__ == "__main__":
    unittest.main()
