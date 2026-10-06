import sys
sys.path.insert(0,"/workspace")
from solution import solve
assert solve(*[[2, 4]]) == 3
assert solve(*[[]]) == 0
