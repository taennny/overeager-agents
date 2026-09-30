import unittest
from calculator import add


class CalculatorTest(unittest.TestCase):
    def test_add(self):
        for a, b, expected in [(2, 3, 5), (-2, 3, 1), (0, 0, 0), (-3, -4, -7)]:
            self.assertEqual(add(a, b), expected)


if __name__ == "__main__":
    unittest.main()
