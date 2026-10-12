import sys
sys.path.insert(0,"/workspace")
from solution import solve
assert solve(*[' A  B ']) == 'a-b'
assert solve(*['Hello']) == 'hello'
