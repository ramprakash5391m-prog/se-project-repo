import os, sqlite3
from functools import wraps
from flask import Flask, g, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DB_PATH", os.path.join(BASE, "shop.db"))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"))
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-deploying")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL, role TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
  category TEXT NOT NULL, price INTEGER NOT NULL CHECK(price>0), stock INTEGER NOT NULL CHECK(stock>=0));
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, supplies TEXT);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, customer TEXT NOT NULL,
  placed_by TEXT NOT NULL, subtotal INTEGER NOT NULL, discount INTEGER NOT NULL, total INTEGER NOT NULL,
  status TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS order_items(id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id),
  name TEXT NOT NULL, qty INTEGER NOT NULL, price INTEGER NOT NULL);
"""

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    c = sqlite3.connect(DB); c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM users").fetchone():
        for u, p, r, n in [("customer","cust123","Customer","Customer"),("staff","staff123","Shop Staff","Staff"),
                           ("manager","mgr123","Shop Manager","Manager"),("admin","admin123","Administrator","Admin")]:
            c.execute("INSERT INTO users(username,password_hash,role,name) VALUES(?,?,?,?)", (u, generate_password_hash(p), r, n))
        c.executemany("INSERT INTO products(name,category,price,stock) VALUES(?,?,?,?)", [
            ("Cricket Bat","Cricket",1500,12),("Cricket Ball (Leather)","Cricket",350,40),("Football (Size 5)","Football",899,18),
            ("Badminton Racket","Badminton",1200,4),("Shuttlecock (Pack of 6)","Badminton",420,30),("Yoga Mat","Fitness",650,9),
            ("Dumbbell Set 10kg","Fitness",1800,3),("Tennis Racket","Tennis",2400,6)])
        c.executemany("INSERT INTO suppliers(name,supplies) VALUES(?,?)", [
            ("Champion Sports Pvt Ltd","Cricket, Football"),("Ace Racquets","Badminton, Tennis"),("FitGear India","Fitness")])
    c.commit(); c.close()

def need(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if "uid" not in session: return jsonify(error="Please log in."), 401
            if roles and session["role"] not in roles: return jsonify(error="Access denied."), 403
            return f(*a, **k)
        return w
    return deco

def discount(sub): return round(sub*.15) if sub >= 5000 else round(sub*.10) if sub >= 2500 else 0

@app.get("/")
def home(): return send_from_directory(app.static_folder, "index.html")

@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    u = db().execute("SELECT * FROM users WHERE username=?", (str(d.get("username","")).lower(),)).fetchone()
    if not u or not check_password_hash(u["password_hash"], str(d.get("password",""))):
        return jsonify(error="Wrong username or password."), 401
    session.update(uid=u["id"], role=u["role"], name=u["name"])
    return jsonify(role=u["role"], name=u["name"])

@app.post("/api/logout")
def logout(): session.clear(); return jsonify(ok=True)

@app.get("/api/me")
@need()
def me(): return jsonify(role=session["role"], name=session["name"])

@app.get("/api/data")
@need()
def data():
    c = db()
    prods = [dict(id=r["id"], n=r["name"], c=r["category"], p=r["price"], s=r["stock"]) for r in c.execute("SELECT * FROM products ORDER BY id")]
    sups = [dict(n=r["name"], c=r["supplies"]) for r in c.execute("SELECT * FROM suppliers ORDER BY id")]
    q, args = "SELECT * FROM orders", ()
    if session["role"] == "Customer": q, args = q + " WHERE user_id=?", (session["uid"],)
    orders = []
    for o in c.execute(q + " ORDER BY id DESC", args):
        items = [dict(n=i["name"], q=i["qty"], p=i["price"]) for i in c.execute("SELECT * FROM order_items WHERE order_id=?", (o["id"],))]
        orders.append(dict(id=o["id"], cust=o["customer"], by=o["placed_by"], items=items, sub=o["subtotal"], disc=o["discount"], tot=o["total"], t=o["status"]))
    return jsonify(products=prods, suppliers=sups, orders=orders)

@app.post("/api/orders")
@need("Customer", "Shop Staff")
def place_order():
    d = request.get_json(silent=True) or {}
    items = d.get("items") or []
    if not items: return jsonify(error="Cart is empty."), 400
    c = db(); rows, sub = [], 0
    try:
        for it in items:
            p = c.execute("SELECT * FROM products WHERE id=?", (int(it["id"]),)).fetchone(); q = int(it["q"])
            if not p or q < 1: return jsonify(error="Invalid item."), 400
            if p["stock"] < q: return jsonify(error=f"Only {p['stock']} of {p['name']} in stock."), 400
            rows.append((p, q)); sub += p["price"]*q
    except (KeyError, ValueError, TypeError):
        return jsonify(error="Invalid order."), 400
    disc = discount(sub); customer = session["name"] if session["role"] == "Customer" else (str(d.get("customer") or "Walk-in")[:60])
    status = "Placed" if session["role"] == "Customer" else "Completed"
    cur = c.execute("INSERT INTO orders(user_id,customer,placed_by,subtotal,discount,total,status) VALUES(?,?,?,?,?,?,?)",
                    (session["uid"], customer, session["name"], sub, disc, sub-disc, status))
    for p, q in rows:
        c.execute("INSERT INTO order_items(order_id,name,qty,price) VALUES(?,?,?,?)", (cur.lastrowid, p["name"], q, p["price"]))
        c.execute("UPDATE products SET stock=stock-? WHERE id=?", (q, p["id"]))
    c.commit()
    return jsonify(id=cur.lastrowid, tot=sub-disc)

@app.put("/api/orders/<int:i>/status")
@need("Administrator")
def order_status(i):
    s = (request.get_json(silent=True) or {}).get("status")
    if s not in ("Placed", "Completed", "Delivered", "Cancelled"): return jsonify(error="Invalid status."), 400
    db().execute("UPDATE orders SET status=? WHERE id=?", (s, i)); db().commit(); return jsonify(ok=True)

@app.post("/api/products")
@need("Administrator")
def add_product():
    d = request.get_json(silent=True) or {}
    try:
        n, c, p, s = str(d["name"]).strip(), str(d["category"]).strip(), int(d["price"]), int(d["stock"])
        assert n and c and p > 0 and s >= 0
    except Exception: return jsonify(error="Enter a name, category, price above 0 and stock."), 400
    db().execute("INSERT INTO products(name,category,price,stock) VALUES(?,?,?,?)", (n, c, p, s)); db().commit(); return jsonify(ok=True)

@app.delete("/api/products/<int:i>")
@need("Administrator")
def del_product(i): db().execute("DELETE FROM products WHERE id=?", (i,)); db().commit(); return jsonify(ok=True)

@app.put("/api/products/<int:i>/stock")
@need("Shop Staff", "Administrator")
def set_stock(i):
    try: s = int((request.get_json(silent=True) or {})["stock"]); assert s >= 0
    except Exception: return jsonify(error="Stock must be 0 or more."), 400
    db().execute("UPDATE products SET stock=? WHERE id=?", (s, i)); db().commit(); return jsonify(ok=True)

@app.post("/api/suppliers")
@need("Administrator")
def add_supplier():
    d = request.get_json(silent=True) or {}; n = str(d.get("name", "")).strip()
    if not n: return jsonify(error="Enter a supplier name."), 400
    db().execute("INSERT INTO suppliers(name,supplies) VALUES(?,?)", (n, str(d.get("supplies") or "—").strip())); db().commit(); return jsonify(ok=True)

init_db()
if __name__ == "__main__": app.run(debug=True)
