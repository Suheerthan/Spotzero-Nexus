"""
SpotZero Nexus - Monitoring Dashboard (Flask + SQLite)

Receives readings from the ESP32 smart bin and results from the AI sorting
station, stores them in SQLite, and serves a live dashboard.

Run:   python app.py          -> open http://localhost:5000
The ESP32 must post to http://<your-laptop-IP>:5000/api/bin/reading
"""
import os
import sqlite3
from datetime import datetime, timezone
from flask import Flask, g, jsonify, render_template, request

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "spotzero.db")
ALERT_THRESHOLD = 80          # % fill that triggers a collection alert
OFFLINE_AFTER_S = 120         # bin is "offline" if silent for this long

# Bins known to the system. Edit the location / lat / lng for your pilot site.
BINS = {
    "BIN-001": {"location": "Ramapuram, Chennai", "lat": 13.0300, "lng": 80.1800, "height_cm": 40},
}

app = Flask(__name__)


# ---------------------------------------------------------------- database
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bin_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            distance_cm REAL,
            fill_pct REAL,
            status TEXT NOT NULL            -- OK | FULL | FAULT
        );
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bin_id TEXT NOT NULL,
            raised_ts TEXT NOT NULL,
            fill_pct REAL,
            kind TEXT NOT NULL,             -- FULL | FAULT
            cleared_ts TEXT                 -- set when bin is marked collected
        );
        CREATE TABLE IF NOT EXISTS sort_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            predicted TEXT NOT NULL,
            confidence REAL,
            actual TEXT,                    -- ground truth, entered by a person
            destination TEXT NOT NULL,
            sorted_ok INTEGER               -- 1/0: did it land in the right box?
        );
        """
    )
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- ESP32 API
@app.post("/api/bin/reading")
def bin_reading():
    """ESP32 posts: {"bin_id":"BIN-001","distance_cm":12.3,"fill_pct":69.2,"status":"OK"}"""
    d = request.get_json(force=True, silent=True) or {}
    bin_id = d.get("bin_id", "BIN-001")
    status = str(d.get("status", "OK")).upper()
    fill = d.get("fill_pct")
    dist = d.get("distance_cm")
    if status not in ("OK", "FULL", "FAULT"):
        return jsonify(error="bad status"), 400
    if status != "FAULT" and fill is None:
        return jsonify(error="fill_pct required"), 400
    if fill is not None:
        fill = max(0.0, min(100.0, float(fill)))
        if status == "OK" and fill >= ALERT_THRESHOLD:
            status = "FULL"

    conn = db()
    ts = now_iso()
    conn.execute(
        "INSERT INTO readings(bin_id, ts, distance_cm, fill_pct, status) VALUES (?,?,?,?,?)",
        (bin_id, ts, dist, fill, status),
    )
    # Raise an alert only if no open alert of that kind exists
    if status in ("FULL", "FAULT"):
        open_alert = conn.execute(
            "SELECT id FROM alerts WHERE bin_id=? AND kind=? AND cleared_ts IS NULL",
            (bin_id, status),
        ).fetchone()
        if not open_alert:
            conn.execute(
                "INSERT INTO alerts(bin_id, raised_ts, fill_pct, kind) VALUES (?,?,?,?)",
                (bin_id, ts, fill, status),
            )
    elif status == "OK":
        # Sensor is healthy again -> close any open fault alert automatically
        conn.execute(
            "UPDATE alerts SET cleared_ts=? WHERE bin_id=? AND kind='FAULT' AND cleared_ts IS NULL",
            (ts, bin_id),
        )
    conn.commit()
    return jsonify(ok=True, status=status, alert_threshold=ALERT_THRESHOLD)


@app.post("/api/bin/<bin_id>/collected")
def bin_collected(bin_id):
    """Collection staff (or the dashboard button) marks a bin as emptied."""
    conn = db()
    ts = now_iso()
    cur = conn.execute(
        "UPDATE alerts SET cleared_ts=? WHERE bin_id=? AND kind='FULL' AND cleared_ts IS NULL",
        (ts, bin_id),
    )
    conn.commit()
    return jsonify(ok=True, cleared=cur.rowcount)


# ---------------------------------------------------------------- Sorter API
VALID_CLASSES = {"plastic", "paper", "glass", "organic", "metal", "reject"}


@app.post("/api/sort/event")
def sort_event():
    """Sorting PC posts: {"predicted":"plastic","confidence":0.91,"destination":"plastic",
                          "actual":"plastic","sorted_ok":true}"""
    d = request.get_json(force=True, silent=True) or {}
    pred = str(d.get("predicted", "")).lower()
    dest = str(d.get("destination", pred)).lower()
    actual = d.get("actual")
    actual = str(actual).lower() if actual else None
    if pred not in VALID_CLASSES or dest not in VALID_CLASSES:
        return jsonify(error=f"class must be one of {sorted(VALID_CLASSES)}"), 400
    ok = d.get("sorted_ok")
    ok = None if ok is None else int(bool(ok))
    conn = db()
    cur = conn.execute(
        "INSERT INTO sort_events(ts, predicted, confidence, actual, destination, sorted_ok) VALUES (?,?,?,?,?,?)",
        (now_iso(), pred, d.get("confidence"), actual, dest, ok),
    )
    conn.commit()
    return jsonify(ok=True, id=cur.lastrowid)


@app.post("/api/sort/<int:event_id>/verify")
def sort_verify(event_id):
    """Fill in ground truth afterwards: {"actual":"paper","sorted_ok":false}"""
    d = request.get_json(force=True, silent=True) or {}
    actual = str(d.get("actual", "")).lower()
    if actual not in VALID_CLASSES:
        return jsonify(error="bad class"), 400
    ok = d.get("sorted_ok")
    conn = db()
    conn.execute(
        "UPDATE sort_events SET actual=?, sorted_ok=COALESCE(?, sorted_ok) WHERE id=?",
        (actual, None if ok is None else int(bool(ok)), event_id),
    )
    conn.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- Dashboard data
@app.get("/api/state")
def state():
    conn = db()
    now = datetime.now(timezone.utc)
    bins_out = []
    for bin_id, meta in BINS.items():
        last = conn.execute(
            "SELECT * FROM readings WHERE bin_id=? ORDER BY id DESC LIMIT 1", (bin_id,)
        ).fetchone()
        hist = conn.execute(
            "SELECT ts, fill_pct, status FROM readings WHERE bin_id=? ORDER BY id DESC LIMIT 120",
            (bin_id,),
        ).fetchall()
        online = False
        if last:
            age = (now - datetime.fromisoformat(last["ts"])).total_seconds()
            online = age <= OFFLINE_AFTER_S
        pending = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE bin_id=? AND kind='FULL' AND cleared_ts IS NULL",
            (bin_id,),
        ).fetchone()[0]
        bins_out.append(
            {
                "bin_id": bin_id,
                **meta,
                "last": dict(last) if last else None,
                "online": online,
                "collection": "PENDING" if pending else "OK",
                "history": [dict(r) for r in reversed(hist)],
            }
        )

    alerts = [dict(r) for r in conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 50")]
    n_alerts = conn.execute("SELECT COUNT(*) FROM alerts WHERE kind='FULL'").fetchone()[0]
    n_collected = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE kind='FULL' AND cleared_ts IS NOT NULL"
    ).fetchone()[0]

    # Sorting stats
    by_class = {r[0]: r[1] for r in conn.execute(
        "SELECT destination, COUNT(*) FROM sort_events GROUP BY destination")}
    verified = conn.execute(
        "SELECT COUNT(*), SUM(predicted=actual) FROM sort_events WHERE actual IS NOT NULL"
    ).fetchone()
    sorted_chk = conn.execute(
        "SELECT COUNT(*), SUM(sorted_ok) FROM sort_events WHERE sorted_ok IS NOT NULL"
    ).fetchone()
    confusion = [dict(r) for r in conn.execute(
        "SELECT actual, predicted, COUNT(*) AS n FROM sort_events WHERE actual IS NOT NULL GROUP BY actual, predicted")]
    recent_sorts = [dict(r) for r in conn.execute("SELECT * FROM sort_events ORDER BY id DESC LIMIT 15")]

    def pct(num, den):
        return round(100.0 * (num or 0) / den, 1) if den else None

    return jsonify(
        threshold=ALERT_THRESHOLD,
        bins=bins_out,
        alerts=alerts,
        totals={
            "alerts_raised": n_alerts,
            "collections_done": n_collected,
            "items_sorted": sum(by_class.values()),
            "ai_accuracy": pct(verified[1], verified[0]),
            "ai_verified": verified[0],
            "sort_accuracy": pct(sorted_chk[1], sorted_chk[0]),
            "sort_checked": sorted_chk[0],
        },
        by_class=by_class,
        confusion=confusion,
        recent_sorts=recent_sorts,
        server_time=now_iso(),
    )


@app.post("/api/reset")
def reset():
    """Wipe all data (use before a fresh demo / test run)."""
    conn = db()
    conn.executescript("DELETE FROM readings; DELETE FROM alerts; DELETE FROM sort_events;")
    conn.commit()
    return jsonify(ok=True)


@app.get("/export/<table>.csv")
def export_csv(table):
    """Download raw test data for the report: /export/readings.csv, alerts.csv, sort_events.csv"""
    if table not in ("readings", "alerts", "sort_events"):
        return "unknown table", 404
    import csv
    import io
    rows = db().execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    if rows:
        w.writerow(rows[0].keys())
        w.writerows([tuple(r) for r in rows])
    return app.response_class(buf.getvalue(), mimetype="text/csv",
                              headers={"Content-Disposition": f"attachment; filename={table}.csv"})


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    init_db()
    # host 0.0.0.0 so the ESP32 on the same Wi-Fi can reach the laptop
    app.run(host="0.0.0.0", port=5000, debug=False)
