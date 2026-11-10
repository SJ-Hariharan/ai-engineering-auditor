# GT:py_broken_import|unresolved-import|CWE-NA|yes
from .does_not_exist import thing

def use():
    return thing
