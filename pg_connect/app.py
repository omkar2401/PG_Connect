import os, sqlite3
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, g, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key-before-deployment")
app.config["DATABASE"] = os.path.join(os.path.dirname(__file__), "pg_connect.db")

def db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_error):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

def init_db():
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE,
      phone TEXT,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('owner','seeker')),
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS pgs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      city TEXT NOT NULL,
      area TEXT NOT NULL,
      address TEXT NOT NULL,
      description TEXT,
      monthly_rent INTEGER NOT NULL,
      deposit INTEGER NOT NULL DEFAULT 0,
      room_type TEXT NOT NULL DEFAULT 'Shared',
      gender_policy TEXT NOT NULL DEFAULT 'Any',
      facilities TEXT DEFAULT '',
      nearest_landmark TEXT DEFAULT '',
      commute_minutes INTEGER,
      photo_url TEXT DEFAULT '',
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS rooms (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      pg_id INTEGER NOT NULL REFERENCES pgs(id) ON DELETE CASCADE,
      floor_number INTEGER NOT NULL,
      room_number TEXT NOT NULL,
      room_type TEXT NOT NULL,
      total_beds INTEGER NOT NULL CHECK(total_beds > 0),
      available_beds INTEGER NOT NULL CHECK(available_beds >= 0 AND available_beds <= total_beds),
      monthly_rent INTEGER NOT NULL,
      UNIQUE(pg_id, floor_number, room_number)
    );
    CREATE TABLE IF NOT EXISTS booking_requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      pg_id INTEGER NOT NULL REFERENCES pgs(id) ON DELETE CASCADE,
      room_id INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
      move_in_date TEXT,
      message TEXT,
      status TEXT NOT NULL DEFAULT 'Pending',
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)
    # Seed demo listings and demo accounts once, so the app is immediately explorable.
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        conn.execute("INSERT INTO users(name,email,phone,password_hash,role) VALUES(?,?,?,?,?)",
                     ("Demo PG Owner","owner@example.com","9000000001",generate_password_hash("Owner@123"),"owner"))
        conn.execute("INSERT INTO users(name,email,phone,password_hash,role) VALUES(?,?,?,?,?)",
                     ("Demo Student","student@example.com","9000000002",generate_password_hash("Student@123"),"seeker"))
        owner_id = conn.execute("SELECT id FROM users WHERE email='owner@example.com'").fetchone()[0]
        samples = [
          ("Green Nest PG","Pune","Hinjewadi","Phase 1, Hinjewadi, Pune","Furnished PG close to IT offices.",8500,10000,"Shared","Any","Wi-Fi,Food,Laundry,Housekeeping", "Hinjewadi IT Park",12,""),
          ("Campus Comfort Stay","Pune","Kothrud","Near Kothrud Bus Depot, Pune","Clean rooms for students and interns.",7000,7000,"Double sharing","Any","Wi-Fi,Food,Water purifier,Study area", "Kothrud Bus Depot",15,""),
          ("Metro Homes PG","Bengaluru","BTM Layout","BTM 2nd Stage, Bengaluru","Budget-friendly rooms with daily essentials.",9500,15000,"Single","Any","Wi-Fi,AC,Laundry,Parking", "BTM Layout",10,"")
        ]
        for s in samples:
            cur = conn.execute("""INSERT INTO pgs(owner_id,name,city,area,address,description,monthly_rent,deposit,room_type,gender_policy,facilities,nearest_landmark,commute_minutes,photo_url)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (owner_id,*s))
            pg_id = cur.lastrowid
            room_rows = [(0,"G01","Shared",4,2,s[5]),(1,"101","Double sharing",2,1,s[5]),(2,"201","Single",1,1,s[5])]
            for floor, number, typ, total, available, rent in room_rows:
                conn.execute("INSERT INTO rooms(pg_id,floor_number,room_number,room_type,total_beds,available_beds,monthly_rent) VALUES(?,?,?,?,?,?,?)",
                             (pg_id,floor,number,typ,total,available,rent))
    conn.commit()
    conn.close()

def login_required(role=None):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get("user_id"):
                flash("Please log in to continue.", "warning")
                return redirect(url_for("login"))
            if role and session.get("role") != role:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return decorator

@app.route("/")
def index():
    filters = {
      "city": request.args.get("city","").strip(),
      "area": request.args.get("area","").strip(),
      "max_rent": request.args.get("max_rent","").strip(),
      "room_type": request.args.get("room_type","").strip(),
      "facility": request.args.get("facility","").strip(),
      "destination": request.args.get("destination","").strip(),
      "max_commute": request.args.get("max_commute","").strip(),
      "min_beds": request.args.get("min_beds","").strip()
    }
    sql = """SELECT p.*, u.name AS owner_name,
      COALESCE((SELECT SUM(r.available_beds) FROM rooms r WHERE r.pg_id=p.id),0) AS available_beds
      FROM pgs p JOIN users u ON u.id=p.owner_id WHERE p.active=1"""
    params = []
    if filters["city"]:
        sql += " AND p.city LIKE ?"; params.append(f"%{filters['city']}%")
    if filters["area"]:
        sql += " AND p.area LIKE ?"; params.append(f"%{filters['area']}%")
    if filters["max_rent"].isdigit():
        sql += " AND p.monthly_rent <= ?"; params.append(int(filters["max_rent"]))
    if filters["room_type"]:
        sql += " AND p.room_type = ?"; params.append(filters["room_type"])
    if filters["facility"]:
        sql += " AND p.facilities LIKE ?"; params.append(f"%{filters['facility']}%")
    if filters["destination"]:
        sql += " AND (p.nearest_landmark LIKE ? OR p.address LIKE ? OR p.area LIKE ?)"
        params += [f"%{filters['destination']}%"] * 3
    if filters["max_commute"].isdigit():
        sql += " AND p.commute_minutes <= ?"; params.append(int(filters["max_commute"]))
    sql += " GROUP BY p.id HAVING available_beds >= ?"
    params.append(int(filters["min_beds"]) if filters["min_beds"].isdigit() else 1)
    sql += " ORDER BY p.created_at DESC"
    listings = db().execute(sql, params).fetchall()
    cities = db().execute("SELECT DISTINCT city FROM pgs WHERE active=1 ORDER BY city").fetchall()
    return render_template("index.html", listings=listings, filters=filters, cities=cities)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip().lower()
        phone = request.form.get("phone","").strip()
        password = request.form.get("password","")
        role = request.form.get("role","seeker")
        if not name or not email or len(password) < 8 or role not in ("owner","seeker"):
            flash("Enter all required details. Password must be at least 8 characters.", "danger")
            return render_template("register.html")
        try:
            db().execute("INSERT INTO users(name,email,phone,password_hash,role) VALUES(?,?,?,?,?)",
                         (name,email,phone,generate_password_hash(password),role))
            db().commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That email is already registered.", "danger")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        user = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"], session["name"], session["role"] = user["id"], user["name"], user["role"]
            flash(f"Welcome back, {user['name']}!", "success")
            return redirect(url_for("owner_dashboard" if user["role"] == "owner" else "index"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))

@app.route("/pg/<int:pg_id>")
def pg_detail(pg_id):
    pg = db().execute("""SELECT p.*,u.name owner_name,u.phone owner_phone,
      COALESCE((SELECT SUM(available_beds) FROM rooms WHERE pg_id=p.id),0) available_beds
      FROM pgs p JOIN users u ON u.id=p.owner_id WHERE p.id=? AND p.active=1""", (pg_id,)).fetchone()
    if not pg:
        abort(404)
    rooms = db().execute("SELECT * FROM rooms WHERE pg_id=? ORDER BY floor_number,room_number", (pg_id,)).fetchall()
    return render_template("pg_detail.html", pg=pg, rooms=rooms)

@app.route("/owner")
@login_required("owner")
def owner_dashboard():
    pgs = db().execute("""SELECT p.*,
      COALESCE((SELECT SUM(total_beds) FROM rooms WHERE pg_id=p.id),0) total_beds,
      COALESCE((SELECT SUM(available_beds) FROM rooms WHERE pg_id=p.id),0) available_beds
      FROM pgs p WHERE p.owner_id=? ORDER BY p.id DESC""", (session["user_id"],)).fetchall()
    requests = db().execute("""SELECT b.*,p.name pg_name,u.name seeker_name,u.phone seeker_phone,
      r.floor_number,r.room_number FROM booking_requests b
      JOIN pgs p ON p.id=b.pg_id JOIN users u ON u.id=b.user_id
      LEFT JOIN rooms r ON r.id=b.room_id WHERE p.owner_id=? ORDER BY b.created_at DESC""",
      (session["user_id"],)).fetchall()
    return render_template("owner_dashboard.html", pgs=pgs, requests=requests)

@app.route("/owner/pg/new", methods=["GET","POST"])
@login_required("owner")
def add_pg():
    if request.method == "POST":
        f = request.form
        required = ["name","city","area","address","monthly_rent","deposit","room_type"]
        if any(not f.get(k,"").strip() for k in required):
            flash("Please complete all required fields.", "danger")
            return render_template("add_pg.html")
        try:
            cur = db().execute("""INSERT INTO pgs(owner_id,name,city,area,address,description,monthly_rent,deposit,room_type,gender_policy,facilities,nearest_landmark,commute_minutes,photo_url)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (session["user_id"],f["name"].strip(),f["city"].strip(),f["area"].strip(),f["address"].strip(),
               f.get("description","").strip(),int(f["monthly_rent"]),int(f["deposit"]),f["room_type"],
               f.get("gender_policy","Any"),",".join(x.strip() for x in f.getlist("facilities") if x.strip()),
               f.get("nearest_landmark","").strip(),int(f["commute_minutes"]) if f.get("commute_minutes","").isdigit() else None,
               f.get("photo_url","").strip()))
            pg_id = cur.lastrowid
            floor = int(f.get("floor_number","0") or 0)
            room_number = f.get("room_number","101").strip()
            room_type = f["room_type"]
            total_beds = int(f.get("total_beds","1") or 1)
            available_beds = int(f.get("available_beds","1") or 1)
            rent = int(f["monthly_rent"])
            if total_beds < 1 or available_beds < 0 or available_beds > total_beds:
                raise ValueError("Bed counts are invalid.")
            db().execute("""INSERT INTO rooms(pg_id,floor_number,room_number,room_type,total_beds,available_beds,monthly_rent)
              VALUES(?,?,?,?,?,?,?)""", (pg_id,floor,room_number,room_type,total_beds,available_beds,rent))
            db().commit()
            flash("Your PG listing has been published.", "success")
            return redirect(url_for("owner_dashboard"))
        except (ValueError, sqlite3.IntegrityError):
            db().rollback()
            flash("Check the rent, deposit, bed counts and unique room number. Available beds cannot exceed total beds.", "danger")
    return render_template("add_pg.html")

@app.route("/owner/pg/<int:pg_id>/room", methods=["POST"])
@login_required("owner")
def add_room(pg_id):
    pg = db().execute("SELECT * FROM pgs WHERE id=? AND owner_id=?", (pg_id,session["user_id"])).fetchone()
    if not pg: abort(404)
    f = request.form
    try:
        total, available = int(f["total_beds"]), int(f["available_beds"])
        rent, floor = int(f["monthly_rent"]), int(f["floor_number"])
        if total < 1 or available < 0 or available > total or rent < 0: raise ValueError()
        db().execute("""INSERT INTO rooms(pg_id,floor_number,room_number,room_type,total_beds,available_beds,monthly_rent)
          VALUES(?,?,?,?,?,?,?)""", (pg_id,floor,f["room_number"].strip(),f["room_type"],total,available,rent))
        db().commit()
        flash("Room added successfully.", "success")
    except (ValueError, KeyError, sqlite3.IntegrityError):
        db().rollback()
        flash("Could not add room. Check fields and ensure the room number is unique on that floor.", "danger")
    return redirect(url_for("owner_dashboard"))

@app.route("/owner/room/<int:room_id>/availability", methods=["POST"])
@login_required("owner")
def update_availability(room_id):
    room = db().execute("""SELECT r.* FROM rooms r JOIN pgs p ON p.id=r.pg_id
      WHERE r.id=? AND p.owner_id=?""", (room_id,session["user_id"])).fetchone()
    if not room: abort(404)
    try:
        available = int(request.form["available_beds"])
        if available < 0 or available > room["total_beds"]: raise ValueError()
        db().execute("UPDATE rooms SET available_beds=? WHERE id=?", (available,room_id))
        db().commit()
        flash("Availability updated.", "success")
    except (ValueError, KeyError):
        flash("Available beds must be between zero and total beds.", "danger")
    return redirect(url_for("owner_dashboard"))

@app.route("/booking/<int:pg_id>", methods=["POST"])
@login_required("seeker")
def request_booking(pg_id):
    pg = db().execute("SELECT * FROM pgs WHERE id=? AND active=1", (pg_id,)).fetchone()
    if not pg: abort(404)
    room_id = request.form.get("room_id") or None
    if room_id:
        room = db().execute("SELECT * FROM rooms WHERE id=? AND pg_id=?", (room_id,pg_id)).fetchone()
        if not room or room["available_beds"] < 1:
            flash("That room currently has no available beds.", "danger")
            return redirect(url_for("pg_detail",pg_id=pg_id))
    db().execute("""INSERT INTO booking_requests(user_id,pg_id,room_id,move_in_date,message)
      VALUES(?,?,?,?,?)""", (session["user_id"],pg_id,room_id,request.form.get("move_in_date") or None,request.form.get("message","").strip()))
    db().commit()
    flash("Booking request sent to the owner. Availability is not reserved until the owner confirms.", "success")
    return redirect(url_for("pg_detail",pg_id=pg_id))

@app.route("/owner/booking/<int:booking_id>/<action>", methods=["POST"])
@login_required("owner")
def booking_action(booking_id, action):
    if action not in ("Approved","Rejected"): abort(404)
    booking = db().execute("""SELECT b.*,r.available_beds,r.total_beds,r.id AS rid,p.owner_id
      FROM booking_requests b JOIN pgs p ON p.id=b.pg_id LEFT JOIN rooms r ON r.id=b.room_id
      WHERE b.id=? AND p.owner_id=?""", (booking_id,session["user_id"])).fetchone()
    if not booking: abort(404)
    if action == "Approved" and booking["rid"] and booking["available_beds"] < 1:
        flash("No beds remain available in this room.", "danger")
        return redirect(url_for("owner_dashboard"))
    if action == "Approved" and booking["status"] != "Approved" and booking["rid"]:
        db().execute("UPDATE rooms SET available_beds=available_beds-1 WHERE id=? AND available_beds>0", (booking["rid"],))
    db().execute("UPDATE booking_requests SET status=? WHERE id=?", (action,booking_id))
    db().commit()
    flash(f"Booking request {action.lower()}.", "success")
    return redirect(url_for("owner_dashboard"))

@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, message="You don't have permission to view this page."), 403

@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, message="We couldn't find that page or listing."), 404

with app.app_context():
    init_db()

if __name__ == "__main__":
    app.run(debug=True)
