import sys
sys.path.insert(0,"/workspace")
from solution import solve
assert solve(*[2, 3]) == 5
assert solve(*[-2, 5]) == 3
