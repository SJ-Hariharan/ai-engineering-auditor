const express = require("express");
const cors = require("cors");
const jwt = require("jsonwebtoken");
const { exec, execFile } = require("child_process");
const https = require("https");
const crypto = require("crypto");
const { Pool } = require("pg");
const { MongoClient } = require("mongodb");
const path = require("path");
const _ = require("lodash");

const app = express();
app.use(express.json());
// GT:cors_true_credentials|cors-misconfig|CWE-942|yes
app.use(cors({ origin: true, credentials: true }));

const pool = new Pool();
const mongo = new MongoClient("mongodb://localhost:27017");

app.get("/sqli", async (req, res) => {
  // GT:sqli_template|sql-injection|CWE-89|yes
  const r = await pool.query(`SELECT * FROM users WHERE id = ${req.query.id}`);
  res.json(r.rows);
});

app.get("/sqli/concat", async (req, res) => {
  // GT:sqli_concat|sql-injection|CWE-89|yes
  const r = await pool.query("SELECT * FROM users WHERE name = '" + req.query.name + "'");
  res.json(r.rows);
});

app.get("/sqli/safe", async (req, res) => {
  // SAFE:safe_sql_param|sql-injection
  const r = await pool.query("SELECT * FROM users WHERE id = $1", [req.query.id]);
  res.json(r.rows);
});

app.get("/xss", (req, res) => {
  // GT:reflected_xss|xss|CWE-79|yes
  res.send(req.query.x);
});

app.get("/xss/tpl", (req, res) => {
  // GT:reflected_xss_template|xss|CWE-79|yes
  res.send(`<h1>Hello ${req.query.name}</h1>`);
});

app.get("/eval", (req, res) => {
  // GT:eval|code-injection|CWE-95|yes
  res.send(String(eval(req.query.expr)));
});

app.get("/exec", (req, res) => {
  // GT:cmd_exec_template|command-injection|CWE-78|yes
  exec(`ping -c 1 ${req.query.host}`, (err, out) => res.send(out));
});

app.get("/exec/safe", (req, res) => {
  // SAFE:safe_execfile_array|command-injection
  execFile("ping", ["-c", "1", req.query.host], (err, out) => res.send(out));
});

app.get("/redirect", (req, res) => {
  // GT:open_redirect|open-redirect|CWE-601|yes
  res.redirect(req.query.next);
});

app.get("/download", (req, res) => {
  // GT:path_sendfile|path-traversal|CWE-22|yes
  res.sendFile(req.query.f);
});

app.get("/download/readfile", (req, res) => {
  // GT:path_readfile|path-traversal|CWE-22|yes
  res.send(require("fs").readFileSync("/data/" + req.query.f, "utf8"));
});

app.get("/download/safe", (req, res) => {
  // SAFE:safe_sendfile_basename|path-traversal
  res.sendFile(path.join("/data", path.basename(req.query.f)));
});

app.get("/proxy", async (req, res) => {
  // GT:ssrf_fetch|ssrf|CWE-918|yes
  const r = await fetch(req.query.url);
  res.send(await r.text());
});

// GT:tls_reject_unauthorized|tls-verification|CWE-295|yes
const agent = new https.Agent({ rejectUnauthorized: false });

app.post("/token", (req, res) => {
  // GT:math_random_token|weak-random|CWE-338|yes
  const token = Math.random().toString(36).slice(2);
  res.json({ token });
});

app.post("/token/safe", (req, res) => {
  // SAFE:safe_crypto_random|weak-random
  res.json({ token: crypto.randomBytes(24).toString("hex") });
});

function authMiddleware(req, res, next) {
  // GT:jwt_decode_auth|jwt-verification|CWE-347|yes
  const user = jwt.decode(req.headers.authorization.split(" ")[1]);
  req.user = user;
  next();
}

function authSafe(req, res, next) {
  // SAFE:safe_jwt_verify|jwt-verification
  req.user = jwt.verify(req.headers.authorization.split(" ")[1], process.env.JWT_SECRET);
  next();
}

app.post("/settings", (req, res) => {
  const settings = {};
  // GT:proto_pollution_merge|prototype-pollution|CWE-1321|no
  _.merge(settings, req.body);
  res.json(settings);
});

app.post("/profile", (req, res) => {
  const profile = {};
  // GT:proto_pollution_assign|prototype-pollution|CWE-1321|no
  Object.assign(profile, req.body);
  res.json(profile);
});

app.post("/login", async (req, res) => {
  const col = mongo.db("app").collection("users");
  // GT:nosql_injection|nosql-injection|CWE-943|no
  const u = await col.findOne({ user: req.body.user, pass: req.body.pass });
  res.json(u);
});

// GT:noauth_delete|missing-auth|CWE-306|yes
app.delete("/users/:id", async (req, res) => {
  await pool.query("DELETE FROM users WHERE id = $1", [req.params.id]);
  res.status(204).end();
});

app.use(require("express-session")({
  // GT:insecure_cookie|insecure-cookie|CWE-614|yes
  secret: "keyboard cat", cookie: { secure: false, httpOnly: false }
}));

app.listen(3000);
