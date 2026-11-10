import os
import pickle
import sqlite3
import subprocess

import requests
import yaml
from flask import Flask, request, send_file

from .models import helper

app = Flask(__name__)
app.secret_key = "super-secret-dev-key-123"


@app.route("/user")
def get_user():
    uid = request.args.get("id")
    conn = sqlite3.connect("db.sqlite")
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM users WHERE id = {uid}")
    return str(cur.fetchall())


@app.route("/download")
def download():
    name = request.args.get("file")
    return send_file(os.path.join("/srv/files", name))


@app.route("/ping")
def ping():
    host = request.args.get("host")
    return subprocess.check_output("ping -c 1 " + host, shell=True)


def load(data):
    try:
        return pickle.loads(data)
    except:
        pass


def config(text):
    return yaml.load(text)


def fetch(url):
    return requests.get(url, verify=False)


if __name__ == "__main__":
    app.run(debug=True)
