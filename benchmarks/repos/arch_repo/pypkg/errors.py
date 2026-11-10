import json

def load(path):
    try:
        return json.load(open(path))
    # GT:py_bare_except|bare-except|CWE-NA|yes
    except:
        return None


def swallow(fn):
    try:
        fn()
    # GT:py_swallowed|swallowed-exception|CWE-NA|yes
    except Exception:
        pass
