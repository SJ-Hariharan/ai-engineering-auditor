"""Generates repos/arch_repo (architecture/quality ground truth). Markers: '# GT:id|category|rule-hint|yes'."""
import pathlib
root = pathlib.Path(__file__).parent / "repos" / "arch_repo"
F = {}
# --- python cycles
F["pypkg/__init__.py"] = ""
F["pypkg/a.py"] = "# GT:py_cycle2|circular-dependency|CWE-NA|yes\nfrom pypkg import b\n\ndef fa():\n    return b.fb()\n"
F["pypkg/b.py"] = "from pypkg import a\n\ndef fb():\n    return 1 if a else 0\n"
F["pypkg/c.py"] = "# GT:py_cycle3|circular-dependency|CWE-NA|yes\nfrom pypkg import d\n\ndef fc():\n    return d.fd()\n"
F["pypkg/d.py"] = "from pypkg import e\n\ndef fd():\n    return e.fe()\n"
F["pypkg/e.py"] = "from pypkg import c\n\ndef fe():\n    return c\n"
F["pypkg/broken.py"] = "# GT:py_broken_import|unresolved-import|CWE-NA|yes\nfrom .does_not_exist import thing\n\ndef use():\n    return thing\n"
# hub: imported by many
F["pypkg/hub.py"] = "# GT:py_hub|coupling-hub|CWE-NA|yes\nCONFIG = {}\n\ndef helper():\n    return CONFIG\n"
for i in range(14):
    F[f"pypkg/user{i}.py"] = f"from pypkg import hub\n\ndef run{i}():\n    return hub.helper()\n"
# god class
methods = "\n".join(f"    def method_{i}(self, x):\n        self.v{i} = x\n        return self.v{i} + {i}\n" for i in range(32))
F["pypkg/god.py"] = "# GT:py_god_class|large-class|CWE-NA|yes\nclass GodObject:\n    def __init__(self):\n        self.state = {}\n\n" + methods
# complexity > 30
branches = "\n".join(f"    if x == {i}:\n        r += {i}\n    elif y == {i} and z != {i}:\n        r -= {i}" for i in range(18))
F["pypkg/complex.py"] = "def classify(x, y, z):\n    r = 0\n" + branches + "\n    return r\n"
F["pypkg/complex.py"] = "# GT:py_high_complexity|high-complexity|CWE-NA|yes\n" + F["pypkg/complex.py"]
# deep nesting
F["pypkg/nested.py"] = """# GT:py_deep_nesting|deep-nesting|CWE-NA|yes
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
"""
# 200-line function
body = "\n".join(f"    v{i} = data.get('k{i}', {i})\n    out.append(v{i} * 2)" for i in range(100))
F["pypkg/long_fn.py"] = "# GT:py_long_function|long-function|CWE-NA|yes\ndef process(data):\n    out = []\n" + body + "\n    return out\n"
# duplicated blocks
dup = "\n".join(f"    total_{i} = sum(values) + {i}\n    scaled_{i} = total_{i} * factor / (len(values) or 1)\n    items.append((total_{i}, scaled_{i}, 'row-{i}'))" for i in range(12))
F["pypkg/dup1.py"] = "# GT:py_duplicate|duplicate-code|CWE-NA|yes\ndef build_one(values, factor):\n    items = []\n" + dup + "\n    return items\n"
F["pypkg/dup2.py"] = "def build_two(values, factor):\n    items = []\n" + dup + "\n    return items\n"
# error handling
F["pypkg/errors.py"] = """import json

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
"""
F["pypkg/params.py"] = "# GT:py_many_params|many-parameters|CWE-NA|yes\ndef many(a, b, c, d, e, f, g, h, i, j):\n    return a\n"
# --- TypeScript
F["tsapp/tsconfig.json"] = '{"compilerOptions":{"baseUrl":".","paths":{"@lib/*":["src/lib/*"]}}}'
F["tsapp/package.json"] = '{"name":"tsapp","version":"1.0.0"}'
F["tsapp/src/lib/x.ts"] = "// GT:ts_cycle2|circular-dependency|CWE-NA|yes\nimport { y } from './y';\nexport const x = () => y();\n"
F["tsapp/src/lib/y.ts"] = "import { x } from './x';\nexport const y = () => (x ? 1 : 0);\n"
F["tsapp/src/lib/p.ts"] = "// GT:ts_cycle3|circular-dependency|CWE-NA|yes\nimport { q } from './q';\nexport const p = () => q();\n"
F["tsapp/src/lib/q.ts"] = "import { r } from './r';\nexport const q = () => r();\n"
F["tsapp/src/lib/r.ts"] = "import { p } from './p';\nexport const r = () => (p ? 1 : 0);\n"
F["tsapp/src/lib/util.ts"] = "export const util = () => 1;\n"
F["tsapp/src/index.ts"] = """// GT:ts_broken_alias|unresolved-import|CWE-NA|yes
import { nope } from '@lib/nonexistent';
import { util } from '@lib/util';
// GT:ts_broken_relative|unresolved-import|CWE-NA|yes
import { gone } from './missing/module';
export const main = () => util() + nope + gone;
"""
F["tsapp/src/errors.ts"] = """export function a() {
  try {
    JSON.parse('{');
  // GT:ts_empty_catch|empty-catch|CWE-NA|yes
  } catch (e) {}
}
"""
tsb = "\n".join(f"  if (x === {i}) {{ r += {i}; }} else if (y === {i} && z !== {i}) {{ r -= {i}; }}" for i in range(18))
F["tsapp/src/complex.ts"] = "// GT:ts_high_complexity|high-complexity|CWE-NA|yes\nexport function classify(x: number, y: number, z: number) {\n  let r = 0;\n" + tsb + "\n  return r;\n}\n"
for i in range(10):
    F[f"tsapp/src/lib/m{i}.ts"] = f"import {{ util }} from './util';\nexport const m{i} = () => util() + {i};\n"
for p, c in F.items():
    f = root / p; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(c)
