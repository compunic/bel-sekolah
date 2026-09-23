from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session,
    flash
)

import sqlite3
import os
from functools import wraps
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash


# =========================================================
# CONFIG
# =========================================================

app = Flask(__name__)

DATABASE = "bel.db"
TIMEZONE = timezone(timedelta(hours=7))

# Ganti FLASK_SECRET_KEY pada environment server untuk produksi.
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "ganti-secret-key-bel-sekolah-2026"
)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS jadwal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hari INTEGER NOT NULL,
            jam TEXT NOT NULL,
            nama TEXT NOT NULL,
            file_mp3 INTEGER NOT NULL,
            durasi INTEGER NOT NULL,
            aktif INTEGER NOT NULL DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY CHECK(id=1),
            version INTEGER NOT NULL DEFAULT 1,
            volume INTEGER NOT NULL DEFAULT 25
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS test_bell (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_mp3 INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            executed INTEGER NOT NULL DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            aktif INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    row = conn.execute(
        "SELECT id FROM config WHERE id=1"
    ).fetchone()

    if row is None:
        conn.execute("""
            INSERT INTO config (id, version, volume)
            VALUES (1, 1, 25)
        """)

    # Akun awal hanya dibuat jika tabel users masih kosong.
    # Login awal: admin / admin123
    user_count = conn.execute(
        "SELECT COUNT(*) AS total FROM users"
    ).fetchone()["total"]

    if user_count == 0:
        conn.execute("""
            INSERT INTO users
            (username, password_hash, role, aktif, created_at)
            VALUES (?, ?, 'admin', 1, ?)
        """, (
            "admin",
            generate_password_hash("admin123"),
            now_local().strftime("%Y-%m-%d %H:%M:%S")
        ))

    conn.commit()
    conn.close()


def get_version():
    conn = get_db()
    row = conn.execute("""
        SELECT version
        FROM config
        WHERE id=1
    """).fetchone()
    conn.close()
    return row["version"] if row else 1


def bump_version():
    conn = get_db()
    conn.execute("""
        UPDATE config
        SET version = version + 1
        WHERE id=1
    """)
    conn.commit()
    conn.close()


# =========================================================
# AUTHENTICATION
# =========================================================

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "username" not in session:
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error": "authentication_required"
                }), 401

            return redirect(url_for(
                "login",
                next=request.path
            ))

        # Pastikan akun masih aktif.
        conn = get_db()
        user = conn.execute("""
            SELECT username, role, aktif
            FROM users
            WHERE username=?
            LIMIT 1
        """, (session["username"],)).fetchone()
        conn.close()

        if user is None or not user["aktif"]:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error": "account_inactive"
                }), 401
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return wrapped_view


@app.route("/login", methods=["GET", "POST"])
def login():
    if "username" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute("""
            SELECT username, password_hash, role, aktif
            FROM users
            WHERE username=?
            LIMIT 1
        """, (username,)).fetchone()
        conn.close()

        if (
            user
            and user["aktif"]
            and check_password_hash(user["password_hash"], password)
        ):
            session.clear()
            session["username"] = user["username"]
            session["role"] = user["role"]
            session.permanent = True

            next_url = request.args.get("next", "")
            if next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)

            return redirect(url_for("index"))

        flash("Username atau password salah.", "error")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# =========================================================
# STATUS ESP32
# =========================================================

esp32_status = {
    "status": "offline",
    "nama": "",
    "jam": "",
    "waktu_sekarang": "",
    "waktu_source": "NONE",
    "rtc_ok": False,
    "ip": "",
    "ram": 0,
    "version": 0,
    "last_update": ""
}


# =========================================================
# HELPER
# =========================================================

HARI = {
    1: "Senin",
    2: "Selasa",
    3: "Rabu",
    4: "Kamis",
    5: "Jumat",
    6: "Sabtu",
    7: "Minggu"
}


def now_local():
    return datetime.now(TIMEZONE)


def is_esp32_online():
    if not esp32_status.get("last_update"):
        return False

    try:
        last = datetime.strptime(
            esp32_status["last_update"],
            "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=TIMEZONE)

        return (now_local() - last).total_seconds() <= 30
    except Exception:
        return False


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/")
@login_required
def index():
    conn = get_db()

    jadwal = conn.execute("""
        SELECT *
        FROM jadwal
        ORDER BY hari, jam
    """).fetchall()

    config = conn.execute("""
        SELECT *
        FROM config
        WHERE id=1
    """).fetchone()

    conn.close()

    return render_template(
        "index.html",
        jadwal=jadwal,
        status=esp32_status,
        config=config,
        hari=HARI,
        username=session.get("username", "")
    )


# =========================================================
# TAMBAH JADWAL
# =========================================================

@app.route("/jadwal/tambah", methods=["POST"])
@login_required
def tambah_jadwal():
    try:
        hari = int(request.form["hari"])
        jam = request.form["jam"].strip()
        nama = request.form["nama"].strip()
        file_mp3 = int(request.form["file_mp3"])
        durasi = int(request.form["durasi"])
        aktif = int(request.form.get("aktif", "1"))

        if hari not in HARI or not nama:
            flash("Data jadwal tidak valid.", "error")
            return redirect(url_for("index"))

        datetime.strptime(jam, "%H:%M")

        if file_mp3 < 1 or durasi < 1:
            raise ValueError

    except (ValueError, KeyError):
        flash("Data jadwal tidak valid.", "error")
        return redirect(url_for("index"))

    conn = get_db()
    conn.execute("""
        INSERT INTO jadwal
        (hari, jam, nama, file_mp3, durasi, aktif)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (hari, jam, nama, file_mp3, durasi, aktif))
    conn.commit()
    conn.close()

    bump_version()
    flash("Jadwal berhasil ditambahkan.", "success")
    return redirect(url_for("index"))


# =========================================================
# UPDATE JADWAL
# =========================================================

@app.route("/jadwal/update/<int:id>", methods=["POST"])
@login_required
def update_jadwal(id):
    try:
        hari = int(request.form["hari"])
        jam = request.form["jam"].strip()
        nama = request.form["nama"].strip()
        file_mp3 = int(request.form["file_mp3"])
        durasi = int(request.form["durasi"])
        aktif = int(request.form.get("aktif", "0"))

        if hari not in HARI or not nama:
            raise ValueError

        datetime.strptime(jam, "%H:%M")

        if file_mp3 < 1 or durasi < 1:
            raise ValueError

    except (ValueError, KeyError):
        flash("Data jadwal tidak valid.", "error")
        return redirect(url_for("index"))

    conn = get_db()
    conn.execute("""
        UPDATE jadwal
        SET hari=?, jam=?, nama=?, file_mp3=?, durasi=?, aktif=?
        WHERE id=?
    """, (hari, jam, nama, file_mp3, durasi, aktif, id))
    conn.commit()
    conn.close()

    bump_version()
    flash("Jadwal berhasil diperbarui.", "success")
    return redirect(url_for("index"))


# =========================================================
# HAPUS JADWAL
# =========================================================

@app.route("/jadwal/hapus/<int:id>")
@login_required
def hapus_jadwal(id):
    conn = get_db()
    conn.execute("DELETE FROM jadwal WHERE id=?", (id,))
    conn.commit()
    conn.close()

    bump_version()
    flash("Jadwal berhasil dihapus.", "success")
    return redirect(url_for("index"))


# =========================================================
# VOLUME
# =========================================================

@app.route("/config/volume", methods=["POST"])
@login_required
def set_volume():
    try:
        volume = int(request.form["volume"])
    except (ValueError, KeyError):
        flash("Volume tidak valid.", "error")
        return redirect(url_for("index"))

    volume = max(0, min(30, volume))

    conn = get_db()
    conn.execute("""
        UPDATE config
        SET volume=?
        WHERE id=1
    """, (volume,))
    conn.commit()
    conn.close()

    bump_version()
    flash(f"Volume diatur ke {volume}.", "success")
    return redirect(url_for("index"))


# =========================================================
# TEST BEL
# =========================================================

@app.route("/test-bell", methods=["POST"])
@login_required
def test_bell():
    try:
        file_mp3 = int(request.form["file_mp3"])
    except (ValueError, KeyError):
        flash("Nomor file MP3 tidak valid.", "error")
        return redirect(url_for("index"))

    if file_mp3 < 1:
        flash("Nomor file MP3 harus lebih dari 0.", "error")
        return redirect(url_for("index"))

    conn = get_db()
    conn.execute("""
        INSERT INTO test_bell (file_mp3, created_at, executed)
        VALUES (?, ?, 0)
    """, (
        file_mp3,
        now_local().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()

    flash(f"Perintah tes bel MP3 #{file_mp3} dikirim ke antrean.", "success")
    return redirect(url_for("index"))


# =========================================================
# API CONFIG ESP32
# TIDAK DIPROTEKSI LOGIN karena dipanggil ESP32.
# =========================================================

@app.route("/api/esp32/config", methods=["GET"])
def api_config():
    conn = get_db()
    row = conn.execute("""
        SELECT version, volume
        FROM config
        WHERE id=1
    """).fetchone()
    conn.close()

    return jsonify({
        "version": row["version"],
        "volume": row["volume"]
    })


# =========================================================
# API JADWAL ESP32
# =========================================================

@app.route("/api/esp32/jadwal", methods=["GET"])
def api_jadwal():
    conn = get_db()
    rows = conn.execute("""
        SELECT id, hari, jam, nama, file_mp3, durasi, aktif
        FROM jadwal
        ORDER BY hari, jam
    """).fetchall()
    conn.close()

    result = []

    for row in rows:
        try:
            jam, menit = map(int, row["jam"].split(":"))
        except (ValueError, AttributeError):
            continue

        result.append([
            row["id"],
            row["hari"],
            jam,
            menit,
            row["nama"],
            row["file_mp3"],
            row["durasi"],
            row["aktif"]
        ])

    return jsonify(result)


# =========================================================
# API WAKTU ESP32
# =========================================================

@app.route("/api/esp32/time", methods=["GET"])
def api_time():
    try:
        now = now_local()
        timestamp = int(now.timestamp())
        timestamp_wib = timestamp + (7 * 3600)

        return jsonify({
            "success": True,
            "tahun": now.year,
            "bulan": now.month,
            "tanggal": now.day,
            "jam": now.hour,
            "menit": now.minute,
            "detik": now.second,
            "timezone": "Asia/Jakarta",
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp": timestamp,
            "timestamp_wib": timestamp_wib
        })

    except Exception as e:
        print("[TIME ERROR]", e)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# =========================================================
# API STATUS ESP32 - POST
# TIDAK DIPROTEKSI LOGIN karena dipanggil ESP32.
# =========================================================

@app.route("/api/esp32/status", methods=["POST"])
def receive_status():
    global esp32_status

    data = request.get_json(silent=True)

    if not data:
        return jsonify({"status": "error"}), 400

    rtc_value = data.get("rtc_ok", False)
    if isinstance(rtc_value, str):
        rtc_value = rtc_value.lower() in (
            "true", "1", "yes", "on"
        )

    esp32_status = {
        "status": data.get("status", ""),
        "nama": data.get("nama", ""),
        "jam": data.get("jam", ""),
        "waktu_sekarang": data.get("waktu_sekarang", ""),
        "waktu_source": data.get("waktu_source", "NONE"),
        "rtc_ok": bool(rtc_value),
        "ip": data.get("ip", ""),
        "ram": data.get("ram", 0),
        "version": data.get("version", 0),
        "last_update": now_local().strftime("%Y-%m-%d %H:%M:%S")
    }

    print("ESP32:", esp32_status)

    return jsonify({"status": "ok"})


# =========================================================
# API STATUS ESP32 - GET
# =========================================================

@app.route("/api/esp32/status", methods=["GET"])
def get_esp32_status():
    result = dict(esp32_status)
    result["online"] = is_esp32_online()

    return jsonify({
        "success": True,
        "status": result
    })


# =========================================================
# API STATUS DASHBOARD
# DIPROTEKSI LOGIN karena dipanggil browser dashboard.
# =========================================================

@app.route("/api/status", methods=["GET"])
@login_required
def api_status():
    result = dict(esp32_status)
    result["online"] = is_esp32_online()
    return jsonify(result)


# =========================================================
# API TEST BEL ESP32
# TIDAK DIPROTEKSI LOGIN karena dipanggil ESP32.
# =========================================================

@app.route("/api/esp32/test", methods=["GET"])
def api_test():
    conn = get_db()

    row = conn.execute("""
        SELECT id, file_mp3
        FROM test_bell
        WHERE executed=0
        ORDER BY id ASC
        LIMIT 1
    """).fetchone()

    if row is None:
        conn.close()
        return jsonify({
            "id": 0,
            "file_mp3": 0
        })

    conn.execute("""
        UPDATE test_bell
        SET executed=1
        WHERE id=?
    """, (row["id"],))

    conn.commit()
    conn.close()

    return jsonify({
        "id": row["id"],
        "file_mp3": row["file_mp3"]
    })


# =========================================================
# ERROR HANDLER
# =========================================================

@app.errorhandler(404)
def page_not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({
            "success": False,
            "error": "not_found"
        }), 404
    return render_template("404.html"), 404


# =========================================================
# START
# =========================================================

init_db()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5007,
        debug=False
    )

