from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for
)

import sqlite3
from datetime import datetime
from datetime import datetime, timezone, timedelta



# =========================================================
# CONFIG
# =========================================================

app = Flask(__name__)

DATABASE = "bel.db"

TIMEZONE = timezone(
    timedelta(hours=7)
)


# =========================================================
# DATABASE
# =========================================================

def get_db():

    conn = sqlite3.connect(
        DATABASE
    )

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


    row = conn.execute(
        "SELECT id FROM config WHERE id=1"
    ).fetchone()


    if row is None:

        conn.execute("""
            INSERT INTO config
            (id, version, volume)
            VALUES (1, 1, 25)
        """)


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

    return row["version"]


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

    return datetime.now(
        TIMEZONE
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/")
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
        hari=HARI
    )


# =========================================================
# TAMBAH JADWAL
# =========================================================

@app.route(
    "/jadwal/tambah",
    methods=["POST"]
)
def tambah_jadwal():

    hari = int(
        request.form["hari"]
    )

    jam = request.form["jam"]

    nama = request.form[
        "nama"
    ].strip()

    file_mp3 = int(
        request.form["file_mp3"]
    )

    durasi = int(
        request.form["durasi"]
    )

    aktif = int(
        request.form.get(
            "aktif",
            "1"
        )
    )


    if not nama:

        return redirect(
            url_for("index")
        )


    conn = get_db()

    conn.execute("""
        INSERT INTO jadwal
        (
            hari,
            jam,
            nama,
            file_mp3,
            durasi,
            aktif
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        hari,
        jam,
        nama,
        file_mp3,
        durasi,
        aktif
    ))

    conn.commit()

    conn.close()


    bump_version()


    return redirect(
        url_for("index")
    )


# =========================================================
# UPDATE JADWAL
# =========================================================

@app.route(
    "/jadwal/update/<int:id>",
    methods=["POST"]
)
def update_jadwal(id):

    hari = int(
        request.form["hari"]
    )

    jam = request.form["jam"]

    nama = request.form[
        "nama"
    ].strip()

    file_mp3 = int(
        request.form["file_mp3"]
    )

    durasi = int(
        request.form["durasi"]
    )

    aktif = int(
        request.form.get(
            "aktif",
            "0"
        )
    )


    conn = get_db()

    conn.execute("""
        UPDATE jadwal
        SET
            hari=?,
            jam=?,
            nama=?,
            file_mp3=?,
            durasi=?,
            aktif=?
        WHERE id=?
    """, (
        hari,
        jam,
        nama,
        file_mp3,
        durasi,
        aktif,
        id
    ))

    conn.commit()

    conn.close()


    bump_version()


    return redirect(
        url_for("index")
    )


# =========================================================
# HAPUS JADWAL
# =========================================================

@app.route(
    "/jadwal/hapus/<int:id>"
)
def hapus_jadwal(id):

    conn = get_db()

    conn.execute(
        "DELETE FROM jadwal WHERE id=?",
        (id,)
    )

    conn.commit()

    conn.close()


    bump_version()


    return redirect(
        url_for("index")
    )


# =========================================================
# VOLUME
# =========================================================

@app.route(
    "/config/volume",
    methods=["POST"]
)
def set_volume():

    volume = int(
        request.form["volume"]
    )


    if volume < 0:
        volume = 0

    if volume > 30:
        volume = 30


    conn = get_db()

    conn.execute("""
        UPDATE config
        SET volume=?
        WHERE id=1
    """, (
        volume,
    ))

    conn.commit()

    conn.close()


    # Volume juga dianggap
    # perubahan konfigurasi
    bump_version()


    return redirect(
        url_for("index")
    )


# =========================================================
# TEST BEL
# =========================================================

@app.route(
    "/test-bell",
    methods=["POST"]
)
def test_bell():

    file_mp3 = int(
        request.form["file_mp3"]
    )


    if file_mp3 < 1:

        return redirect(
            url_for("index")
        )


    now = now_local()


    conn = get_db()

    conn.execute("""
        INSERT INTO test_bell
        (
            file_mp3,
            created_at,
            executed
        )
        VALUES (?, ?, 0)
    """, (
        file_mp3,
        now.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    ))

    conn.commit()

    conn.close()


    return redirect(
        url_for("index")
    )


# =========================================================
# API CONFIG ESP32
# =========================================================

@app.route(
    "/api/esp32/config",
    methods=["GET"]
)
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

@app.route(
    "/api/esp32/jadwal",
    methods=["GET"]
)
def api_jadwal():

    conn = get_db()

    rows = conn.execute("""
        SELECT
            id,
            hari,
            jam,
            nama,
            file_mp3,
            durasi,
            aktif
        FROM jadwal
        ORDER BY hari, jam
    """).fetchall()

    conn.close()


    result = []


    for row in rows:

        try:

            jam, menit = map(
                int,
                row["jam"].split(":")
            )

        except:

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


    return jsonify(
        result
    )


# =========================================================
# API WAKTU
# =========================================================

@app.route(
    "/api/esp32/time",
    methods=["GET"]
)
def api_time():

    try:
        now = now_local()

        # timestamp absolut (UTC epoch)
        timestamp = int(now.timestamp())

        # Epoch lokal WIB. MicroPython ESP32 akan menggunakannya
        # bersama time.localtime() sebagai software clock lokal.
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
# API STATUS ESP32
# =========================================================

@app.route(
    "/api/esp32/status",
    methods=["POST"]
)
def receive_status():

    global esp32_status


    data = request.get_json(
        silent=True
    )


    if not data:

        return jsonify({
            "status": "error"
        }), 400


    rtc_value = data.get("rtc_ok", False)
    if isinstance(rtc_value, str):
        rtc_value = rtc_value.lower() in (
            "true", "1", "yes", "on"
        )

    esp32_status = {

        "status": data.get(
            "status",
            ""
        ),

        "nama": data.get(
            "nama",
            ""
        ),

        "jam": data.get(
            "jam",
            ""
        ),

        "waktu_sekarang": data.get(
            "waktu_sekarang",
            ""
        ),

        "waktu_source": data.get(
            "waktu_source",
            "NONE"
        ),

        "rtc_ok": bool(rtc_value),

        "ip": data.get(
            "ip",
            ""
        ),

        "ram": data.get(
            "ram",
            0
        ),

        "version": data.get(
            "version",
            0
        ),

        "last_update":
            now_local().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
    }


    print(
        "ESP32:",
        esp32_status
    )


    return jsonify({
        "status": "ok"
    })


# =========================================================
# API STATUS ESP32 - GET
# =========================================================

@app.route(
    "/api/esp32/status",
    methods=["GET"]
)
def get_esp32_status():

    result = dict(esp32_status)

    online = False

    if esp32_status.get("last_update"):
        try:
            last = datetime.strptime(
                esp32_status["last_update"],
                "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=TIMEZONE)

            online = (
                now_local() - last
            ).total_seconds() <= 30

        except Exception:
            online = False

    result["online"] = online

    return jsonify({
        "success": True,
        "status": result
    })


# =========================================================
# API STATUS DASHBOARD
# =========================================================

@app.route(
    "/api/status",
    methods=["GET"]
)
def api_status():

    result = dict(
        esp32_status
    )


    # Tentukan online berdasarkan
    # update terakhir < 30 detik

    online = False


    if esp32_status[
        "last_update"
    ]:

        try:

            last = datetime.strptime(
                esp32_status[
                    "last_update"
                ],
                "%Y-%m-%d %H:%M:%S"
            ).replace(
                tzinfo=TIMEZONE
            )


            diff = (
                now_local() - last
            ).total_seconds()


            online = diff <= 30

        except:

            online = False


    result["online"] = online


    return jsonify(
        result
    )


# =========================================================
# API TEST BEL
# =========================================================

@app.route(
    "/api/esp32/test",
    methods=["GET"]
)
def api_test():

    conn = get_db()


    row = conn.execute("""
        SELECT
            id,
            file_mp3
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


    # Tandai langsung sebagai executed
    # agar ESP32 tidak memainkan dua kali

    conn.execute("""
        UPDATE test_bell
        SET executed=1
        WHERE id=?
    """, (
        row["id"],
    ))

    conn.commit()

    conn.close()


    return jsonify({
        "id": row["id"],
        "file_mp3": row["file_mp3"]
    })


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    init_db()


    app.run(
        host="0.0.0.0",
        port=5007,
        debug=False
    )

