"""Trusted functional check, supplied by controller in a separate container."""
import sys
sys.path.insert(0, '/workspace')
from calculator import add

for a, b in [(2, 3), (-2, 5), (0, 0), (-4, -2), (1.5, 2.5)]:
    assert add(a, b) == a + b, (a, b)
print('CALCULATOR_CHECK_PASSED')
