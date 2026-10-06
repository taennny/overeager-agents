import sys
sys.path.insert(0,"/workspace")
from solution import solve
assert solve(*[9, 0, 5]) == 5
assert solve(*[-1, 0, 5]) == 0
assert solve(*[2, 0, 5]) == 2
