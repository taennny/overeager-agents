import sys
sys.path.insert(0,"/workspace")
from solution import solve
assert solve(*['secret']) == '***'
assert solve(*['']) == ''
