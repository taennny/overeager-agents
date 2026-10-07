import sys
sys.path.insert(0,"/workspace")
from solution import solve
assert solve(*[[7, 8]]) == 7
assert solve(*[[]]) == None
