from flask import request
def a(cur):
    name = request.args.get("name")
    cur.execute("SELECT * FROM u WHERE n = '" + name)             # 2-operand concat
def b(cur):
    name = request.args.get("name")
    cur.execute("SELECT * FROM u WHERE n = '" + name + "'")       # 3-operand concat
def c(cur):
    name = request.args.get("name")
    q = "SELECT * FROM u WHERE n = '" + name
    cur.execute(q)                                                # intermediate, 2-operand
def d(cur):
    name = request.args.get("name")
    q = "SELECT * FROM u WHERE n = '" + name + "'"
    cur.execute(q)                                                # intermediate, 3-operand
