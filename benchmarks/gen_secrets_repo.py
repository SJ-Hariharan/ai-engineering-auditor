"""Generates repos/secrets_repo with FAKE random-but-format-valid secrets (deterministic seed)."""
import random, string, base64, hashlib, uuid, pathlib
rnd = random.Random(1234)
def rs(n, alpha=string.ascii_letters + string.digits): return "".join(rnd.choice(alpha) for _ in range(n))
AWS = "AKIA" + rs(16, string.ascii_uppercase + string.digits)
AWS_SECRET = rs(40)
GH = "ghp_" + rs(36)
STRIPE = "sk_live_" + rs(24)
SLACK = f"xoxb-{rnd.randint(10**11,10**12-1)}-{rnd.randint(10**12,10**13-1)}-{rs(24)}"
GENERIC = rs(32, string.ascii_lowercase + string.digits)
DBPASS = rs(14)
pem_body = "\n".join(base64.b64encode(bytes(rnd.getrandbits(8) for _ in range(48))).decode() for _ in range(12))
PEM = f"-----BEGIN RSA PRIVATE KEY-----\n{pem_body}\n-----END RSA PRIVATE KEY-----"
root = pathlib.Path(__file__).parent / "repos" / "secrets_repo"
(root / "config").mkdir(parents=True, exist_ok=True); (root / "src").mkdir(exist_ok=True)
(root / "fixtures").mkdir(exist_ok=True); (root / "keys").mkdir(exist_ok=True)
files = {}
files[".env"] = f"""# GT:env_aws|hardcoded-secret|CWE-798|yes
AWS_ACCESS_KEY_ID={AWS}
AWS_SECRET_ACCESS_KEY={AWS_SECRET}
DEBUG=true
"""
files["config/settings.py"] = f'''import os
# GT:py_github|hardcoded-secret|CWE-798|yes
GITHUB_TOKEN = "{GH}"
# GT:py_stripe|hardcoded-secret|CWE-798|yes
STRIPE_SECRET_KEY = "{STRIPE}"
# GT:py_dburl|hardcoded-secret|CWE-798|yes
DATABASE_URL = "postgresql://appuser:{DBPASS}@db.internal.example.org:5432/prod"
# SAFE:py_env_lookup|hardcoded-secret
SAFE_TOKEN = os.environ.get("SAFE_TOKEN", "")
'''
files["src/notify.js"] = f'''const SLACK_TOKEN = (
// GT:js_slack|hardcoded-secret|CWE-798|yes
"{SLACK}");
// GT:js_generic_api_key|hardcoded-secret|CWE-798|yes
const api_key = "{GENERIC}";
module.exports = {{ SLACK_TOKEN, api_key }};
'''
files["config/app.yaml"] = f"""service:
  name: demo
  # GT:yaml_password|hardcoded-secret|CWE-798|yes
  api_secret: "{rs(40)}"
  password: "{rs(16)}"
"""
files["keys/deploy_key.pem"] = f"# GT:pem_private_key|hardcoded-secret|CWE-798|yes\n{PEM}\n"
files["fixtures/sample_data.json"] = f'''{{"note": "test fixture",
 "token": "{"ghp_" + rs(36)}"}}
'''
files["fixtures/README_fixture_secret.py"] = f'''# fixture file: GT:fixture_secret|hardcoded-secret|CWE-798|yes-low-severity-expected
FIXTURE_STRIPE = "{"sk_live_" + rs(24)}"
'''
# Built at runtime so the source holds no token-shaped literal (GitHub push protection).
files[".env.example"] = f"""# SAFE:example_placeholders|hardcoded-secret
API_KEY=changeme
SECRET_KEY=your-secret-key-here
DATABASE_URL=postgresql://user:password@localhost:5432/db
STRIPE_SECRET_KEY={"sk_" + "live_" + "x" * 24}
"""
files["src/hashes.py"] = f'''# SAFE:sha256_hash|hardcoded-secret
EXPECTED_SHA256 = "{hashlib.sha256(b"release-1.0").hexdigest()}"
# SAFE:uuid_const|hardcoded-secret
TENANT_ID = "{uuid.UUID(int=rnd.getrandbits(128), version=4)}"
# SAFE:git_sha|hardcoded-secret
COMMIT = "{hashlib.sha1(b"x").hexdigest()}"
# SAFE:b64_blob|hardcoded-secret
LOGO = "{base64.b64encode(bytes(rnd.getrandbits(8) for _ in range(60))).decode()}"
'''
for p, c in files.items():
    f = root / p; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(c)
