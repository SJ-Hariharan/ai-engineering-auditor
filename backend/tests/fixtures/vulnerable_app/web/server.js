const express = require("express");
const { exec } = require("child_process");
const app = express();

app.get("/search", (req, res) => {
  db.query(`SELECT * FROM items WHERE name = '${req.query.q}'`);
  res.send("<h1>" + req.query.q + "</h1>");
});

app.get("/go", (req, res) => {
  res.redirect(req.query.next);
});

app.get("/run", (req, res) => {
  exec(`ls ${req.query.dir}`);
});
