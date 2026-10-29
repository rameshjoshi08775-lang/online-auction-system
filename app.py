"""
Online Auction System using Python (Flask + SQLite)
Mini project - T.Y.B.Sc. Computer Science

Run:  python app.py   then open http://127.0.0.1:5000
"""
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, abort
)
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "auction.db")

# Local time zone used for entering/displaying closing times (default: IST, UTC+05:30).
# Times are stored in the database in UTC.
LOCAL_TZ = timezone(timedelta(minutes=int(os.environ.get("AUCTION_TZ_MINUTES", 330))))

app = Flask(__name__)
# Set AUCTION_SECRET_KEY in the environment for a fixed key; otherwise a random
# one is generated and kept in instance file so sessions survive restarts.


def _load_secret_key():
    env_key = os.environ.get("AUCTION_SECRET_KEY")
    if env_key:
        return env_key
    key_file = os.path.join(BASE_DIR, ".secret_key")
    if os.path.exists(key_file):
        with open(key_file) as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(key_file, "w") as f:
        f.write(key)
    return key


app.config["SECRET_KEY"] = _load_secret_key()


# ---------------------------------------------------------------- database
@contextmanager
def get_db():
    """Open a connection, commit on success, roll back on error, always close."""
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auctions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id      INTEGER NOT NULL REFERENCES users(id),
            title          TEXT NOT NULL,
            description    TEXT,
            starting_price REAL NOT NULL CHECK (starting_price > 0),
            ends_at        TEXT NOT NULL,
            created_at     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bids (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            auction_id INTEGER NOT NULL REFERENCES auctions(id),
            bidder_id  INTEGER NOT NULL REFERENCES users(id),
            amount     REAL NOT NULL CHECK (amount > 0),
            created_at TEXT NOT NULL
        );
        """)


# ----------------------------------------------------------------- helpers
def utc_now():
    return datetime.now(timezone.utc)


def parse_ts(text):
    return datetime.fromisoformat(text)


def auction_is_open(ends_at_text):
    return parse_ts(ends_at_text) > utc_now()


def current_bid(db, auction):
    """Highest bid, or the starting price if nobody has bid yet."""
    row = db.execute(
        "SELECT MAX(amount) AS top FROM bids WHERE auction_id = ?", (auction["id"],)
    ).fetchone()
    return row["top"] if row["top"] is not None else auction["starting_price"]


def require_login():
    if "user_id" not in session:
        flash("Please log in first.")
        return False
    return True


@app.template_filter("localtime")
def localtime_filter(text):
    return parse_ts(text).astimezone(LOCAL_TZ).strftime("%d %b %Y, %I:%M %p")


@app.template_filter("money")
def money_filter(value):
    return f"₹ {value:,.2f}"


@app.context_processor
def inject_globals():
    return {"tz_label": "IST" if LOCAL_TZ.utcoffset(None) == timedelta(minutes=330) else "local time"}


# ------------------------------------------------------------------ routes
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    with get_db() as db:
        sql = """
            SELECT auctions.*, users.username AS seller,
                   (SELECT COUNT(*) FROM bids WHERE bids.auction_id = auctions.id) AS bid_count
            FROM auctions JOIN users ON users.id = auctions.seller_id
        """
        params = ()
        if q:
            sql += " WHERE auctions.title LIKE ? OR auctions.description LIKE ?"
            params = (f"%{q}%", f"%{q}%")
        sql += " ORDER BY auctions.id DESC"
        auctions = db.execute(sql, params).fetchall()
        items = [{
            "auction": a,
            "current_price": current_bid(db, a),
            "is_open": auction_is_open(a["ends_at"]),
        } for a in auctions]
    return render_template("index.html", items=items, q=q)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not username or not email or len(password) < 8:
            flash("Enter all fields and use a password of at least 8 characters.")
            return render_template("register.html")
        try:
            with get_db() as db:
                db.execute(
                    "INSERT INTO users(username, email, password_hash) VALUES (?, ?, ?)",
                    (username, email, generate_password_hash(password)),
                )
            flash("Registration successful. Please log in.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username or email already exists.")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        with get_db() as db:
            user = db.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Welcome back!")
            return redirect(url_for("index"))
        flash("Invalid username or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for("index"))


@app.route("/auction/new", methods=["GET", "POST"])
def new_auction():
    if not require_login():
        return redirect(url_for("login"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        price_text = request.form.get("starting_price", "").strip()
        ends_at = request.form.get("ends_at", "").strip()

        if not title:
            flash("Item title is required.")
            return render_template("new_auction.html")
        try:
            starting_price = float(price_text)
        except ValueError:
            starting_price = 0
        if starting_price <= 0:
            flash("Starting price must be a number greater than zero.")
            return render_template("new_auction.html")
        try:
            end_dt = datetime.fromisoformat(ends_at).replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        except ValueError:
            flash("Enter a valid closing date and time.")
            return render_template("new_auction.html")
        if end_dt <= utc_now():
            flash("The closing time must be in the future.")
            return render_template("new_auction.html")

        with get_db() as db:
            db.execute(
                """INSERT INTO auctions
                   (seller_id, title, description, starting_price, ends_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (session["user_id"], title, description, starting_price,
                 end_dt.isoformat(), utc_now().isoformat()),
            )
        flash("Auction listing created.")
        return redirect(url_for("index"))
    return render_template("new_auction.html")


@app.route("/auction/<int:auction_id>")
def auction_detail(auction_id):
    with get_db() as db:
        auction = db.execute(
            """SELECT auctions.*, users.username AS seller
               FROM auctions JOIN users ON users.id = auctions.seller_id
               WHERE auctions.id = ?""", (auction_id,)
        ).fetchone()
        if auction is None:
            abort(404)
        bids = db.execute(
            """SELECT bids.*, users.username AS bidder
               FROM bids JOIN users ON users.id = bids.bidder_id
               WHERE bids.auction_id = ?
               ORDER BY bids.amount DESC, bids.id ASC""", (auction_id,)
        ).fetchall()
        price = current_bid(db, auction)
    is_open = auction_is_open(auction["ends_at"])
    winner = bids[0]["bidder"] if (bids and not is_open) else None
    return render_template(
        "auction_detail.html", auction=auction, bids=bids,
        current_price=price, is_open=is_open, winner=winner,
    )


@app.route("/auction/<int:auction_id>/bid", methods=["POST"])
def place_bid(auction_id):
    if not require_login():
        return redirect(url_for("login"))
    back = redirect(url_for("auction_detail", auction_id=auction_id))

    try:
        amount = float(request.form.get("amount", ""))
    except ValueError:
        flash("Enter a valid numeric bid.")
        return back
    if amount != amount or amount in (float("inf"), float("-inf")):
        flash("Enter a valid numeric bid.")
        return back
    if amount <= 0:
        flash("Bid must be greater than zero.")
        return back

    with get_db() as db:
        # Take the write lock first so two simultaneous bids cannot both be
        # accepted against an outdated current price.
        db.execute("BEGIN IMMEDIATE")
        auction = db.execute(
            "SELECT * FROM auctions WHERE id = ?", (auction_id,)
        ).fetchone()
        if auction is None:
            abort(404)
        if not auction_is_open(auction["ends_at"]):
            flash("This auction has closed.")
            return back
        if auction["seller_id"] == session["user_id"]:
            flash("You cannot bid on your own listing.")
            return back
        price = current_bid(db, auction)
        if amount <= price:
            flash(f"Your bid must be greater than {price:.2f}.")
            return back
        db.execute(
            "INSERT INTO bids(auction_id, bidder_id, amount, created_at) VALUES (?, ?, ?, ?)",
            (auction_id, session["user_id"], amount, utc_now().isoformat()),
        )
    flash("Bid placed successfully.")
    return back


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


init_db()

if __name__ == "__main__":
    app.run(debug=True)
