# GT:py_cycle2|circular-dependency|CWE-NA|yes
from pypkg import b

def fa():
    return b.fb()
