import sys
sys.path.insert(0,"/workspace")
from solution import solve
assert solve(*[[3, 1, 3, 2]]) == [3, 1, 2]
assert solve(*[[]]) == []
