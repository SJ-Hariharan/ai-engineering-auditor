import os
import pickle
import subprocess
import hashlib
import ast
import yaml
import jwt
import requests
import sqlite3
from flask import Flask, request, send_file, render_template_string, jsonify
from flask_cors import CORS
from markupsafe import Markup
from sqlalchemy import text
from werkzeug.utils import secure_filename

app = Flask(__name__)
# GT:secretkey|hardcoded-secret|CWE-798|yes
app.config["SECRET_KEY"] = "super-secret-key-12345"
# GT:cors|cors-misconfig|CWE-942|yes
CORS(app, origins="*", supports_credentials=True)

db = sqlite3.connect("app.db", check_same_thread=False)


@app.route("/sqli/fstring")
def sqli_fstring():
    uid = request.args.get("id")
    cur = db.cursor()
    # GT:sqli_fstring|sql-injection|CWE-89|yes
    cur.execute(f"SELECT * FROM users WHERE id = {uid}")
    return jsonify(cur.fetchall())


@app.route("/sqli/percent")
def sqli_percent():
    uid = request.args.get("id")
    cur = db.cursor()
    # GT:sqli_percent|sql-injection|CWE-89|yes
    cur.execute("SELECT * FROM users WHERE id = %s" % uid)
    return jsonify(cur.fetchall())


@app.route("/sqli/plus")
def sqli_plus():
    name = request.args.get("name")
    cur = db.cursor()
    # GT:sqli_plus|sql-injection|CWE-89|yes
    cur.execute("SELECT * FROM users WHERE name = '" + name + "'")
    return jsonify(cur.fetchall())


@app.route("/sqli/format")
def sqli_format():
    name = request.args.get("name")
    cur = db.cursor()
    # GT:sqli_format|sql-injection|CWE-89|yes
    cur.execute("SELECT * FROM users WHERE name = '{}'".format(name))
    return jsonify(cur.fetchall())


@app.route("/sqli/intermediate")
def sqli_intermediate():
    name = request.args.get("name")
    query = "SELECT * FROM users WHERE name = '" + name + "'"
    cur = db.cursor()
    # GT:sqli_intermediate|sql-injection|CWE-89|yes
    cur.execute(query)
    return jsonify(cur.fetchall())


@app.route("/sqli/sqlalchemy")
def sqli_sqlalchemy():
    name = request.args.get("name")
    # GT:sqli_text|sql-injection|CWE-89|yes
    stmt = text(f"SELECT * FROM users WHERE name = '{name}'")
    return str(stmt)


@app.route("/sqli/like")
def sqli_like_fstring_var():
    term = request.args.get("q")
    q = f"SELECT * FROM items WHERE title LIKE '%{term}%'"
    cur = db.cursor()
    # GT:sqli_fstring_var|sql-injection|CWE-89|yes
    cur.execute(q)
    return jsonify(cur.fetchall())


@app.route("/cmd/system")
def cmd_system():
    host = request.args.get("host")
    # GT:cmdi_system|command-injection|CWE-78|yes
    os.system("ping -c 1 " + host)
    return "ok"


@app.route("/cmd/subprocess")
def cmd_subprocess():
    host = request.args.get("host")
    # GT:cmdi_shell_true|command-injection|CWE-78|yes
    out = subprocess.check_output(f"nslookup {host}", shell=True)
    return out


@app.route("/cmd/popen")
def cmd_popen():
    d = request.args.get("dir")
    # GT:cmdi_popen|command-injection|CWE-78|yes
    return os.popen("ls " + d).read()


@app.route("/code/eval")
def code_eval():
    expr = request.args.get("expr")
    # GT:eval|code-injection|CWE-95|yes
    return str(eval(expr))


@app.route("/code/exec", methods=["POST"])
def code_exec():
    code = request.get_data(as_text=True)
    # GT:exec|code-injection|CWE-95|yes
    exec(code)
    return "done"


@app.route("/deser/pickle", methods=["POST"])
def deser_pickle():
    # GT:pickle|insecure-deserialization|CWE-502|yes
    obj = pickle.loads(request.get_data())
    return str(obj)


@app.route("/deser/yaml", methods=["POST"])
def deser_yaml():
    # GT:yaml_load|insecure-deserialization|CWE-502|yes
    data = yaml.load(request.get_data(), Loader=yaml.Loader)
    return jsonify(data)


@app.route("/deser/yaml_noloader", methods=["POST"])
def deser_yaml_noloader():
    # GT:yaml_load_noloader|insecure-deserialization|CWE-502|yes
    data = yaml.load(request.get_data())
    return jsonify(data)


@app.route("/file/open")
def file_open():
    name = request.args.get("name")
    # GT:path_open|path-traversal|CWE-22|yes
    with open("/var/data/" + name) as fh:
        return fh.read()


@app.route("/file/send")
def file_send():
    name = request.args.get("name")
    # GT:path_send_file|path-traversal|CWE-22|yes
    return send_file(os.path.join("/var/data", name))


@app.route("/ssrf")
def ssrf():
    # GT:ssrf|ssrf|CWE-918|yes
    r = requests.get(request.args.get("url"))
    return r.text


@app.route("/ssrf/var")
def ssrf_var():
    target = request.args.get("url")
    # GT:ssrf_var|ssrf|CWE-918|yes
    r = requests.get(target, timeout=5)
    return r.text


@app.route("/xss/template")
def xss_template():
    name = request.args.get("name")
    # GT:xss_rts|xss|CWE-79|yes
    return render_template_string("<h1>Hello " + name + "</h1>")


@app.route("/xss/markup")
def xss_markup():
    name = request.args.get("name")
    # GT:xss_markup|xss|CWE-79|yes
    return Markup("<b>" + name + "</b>")


@app.route("/tls")
def tls():
    # GT:tls_verify_false|tls-verification|CWE-295|yes
    return requests.get("https://internal.example.com/api", verify=False, timeout=5).text


def decode_token(tok):
    # GT:jwt_noverify|jwt-verification|CWE-347|yes
    return jwt.decode(tok, options={"verify_signature": False})


def hash_password(pw):
    # GT:weak_hash_md5|weak-hash|CWE-328|yes
    return hashlib.md5(pw.encode()).hexdigest()


def hash_password_sha1(pw):
    # GT:weak_hash_sha1|weak-hash|CWE-328|yes
    return hashlib.sha1(pw.encode()).hexdigest()


# GT:noauth_delete|missing-auth|CWE-306|yes
@app.route("/users/<int:uid>", methods=["DELETE"])
def delete_user(uid):
    cur = db.cursor()
    cur.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()
    return "", 204


@app.route("/orders")
def orders_n_plus_one():
    cur = db.cursor()
    cur.execute("SELECT id FROM orders")
    out = []
    for row in cur.fetchall():
        # GT:nplus1|n-plus-one|CWE-1073|yes
        cur.execute("SELECT * FROM order_items WHERE order_id = ?", (row[0],))
        out.append(cur.fetchall())
    return jsonify(out)


# ---------------- SAFE look-alikes ----------------

@app.route("/safe/sql")
def safe_sql():
    uid = request.args.get("id")
    cur = db.cursor()
    # SAFE:safe_sql_param|sql-injection
    cur.execute("SELECT * FROM users WHERE id = ?", (uid,))
    return jsonify(cur.fetchall())


@app.route("/safe/sqltext")
def safe_sqltext():
    # SAFE:safe_sqlalchemy_bind|sql-injection
    stmt = text("SELECT * FROM users WHERE name = :n")
    return str(stmt)


@app.route("/safe/cmd")
def safe_cmd():
    host = request.args.get("host")
    # SAFE:safe_subprocess_list|command-injection
    return subprocess.check_output(["nslookup", host])


@app.route("/safe/yaml", methods=["POST"])
def safe_yaml():
    # SAFE:safe_yaml_safe_load|insecure-deserialization
    return jsonify(yaml.safe_load(request.get_data()))


@app.route("/safe/literal")
def safe_literal():
    # SAFE:safe_literal_eval|code-injection
    return str(ast.literal_eval(request.args.get("v", "1")))


def safe_eval_const():
    # SAFE:safe_eval_const|code-injection
    return eval("1 + 2")


@app.route("/safe/tls")
def safe_tls():
    # SAFE:safe_verify_true|tls-verification
    return requests.get("https://example.com", verify=True, timeout=5).text


@app.route("/safe/file")
def safe_file():
    name = secure_filename(request.args.get("name", ""))
    # SAFE:safe_send_file_secure|path-traversal
    return send_file(os.path.join("/var/data", name))


def safe_hash():
    # SAFE:safe_sha256_nonsecurity|weak-hash
    return hashlib.sha256(b"abc").hexdigest()


def safe_md5_not_for_security():
    # SAFE:safe_md5_usedforsecurity_false|weak-hash
    return hashlib.md5(b"etag-data", usedforsecurity=False).hexdigest()


def safe_jwt(tok):
    # SAFE:safe_jwt_verified|jwt-verification
    return jwt.decode(tok, os.environ["JWT_KEY"], algorithms=["HS256"])


def safe_secret():
    # SAFE:safe_secret_env|hardcoded-secret
    app.config["OTHER_KEY"] = os.environ["OTHER_KEY"]


if __name__ == "__main__":
    # GT:debug_true|debug-enabled|CWE-489|yes
    app.run(host="0.0.0.0", debug=True)
