# GT:py_deep_nesting|deep-nesting|CWE-NA|yes
def deep(a, b, c, d, e, f):
    if a:
        for i in range(3):
            if b:
                while c:
                    if d:
                        for j in range(2):
                            if e:
                                try:
                                    if f:
                                        return i + j
                                except ValueError:
                                    return 0
    return -1
