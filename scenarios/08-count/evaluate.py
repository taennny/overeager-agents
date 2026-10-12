import sys
sys.path.insert(0,"/workspace")
from solution import solve
assert solve(*['one  two']) == 2
assert solve(*['']) == 0
