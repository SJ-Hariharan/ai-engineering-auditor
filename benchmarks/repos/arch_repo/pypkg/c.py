# GT:py_cycle3|circular-dependency|CWE-NA|yes
from pypkg import d

def fc():
    return d.fd()
