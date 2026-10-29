from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, time, timedelta
from pathlib import Path
import json
import sqlite3
from threading import Lock
from time import monotonic

from flask import Flask, jsonify, render_template, request, send_from_directory


BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder="static")
app.config["DATABASE"] = str(BASE_DIR / "instance" / "tester.sqlite3")

DEFAULT_GPIO_PINS = [4, 5, 12, 13, 14]

STAGES = [
    ("detection", "DUT Detection"),
    ("gpio", "GPIO Test"),
    ("uart", "UART Test"),
    ("spi", "SPI Test"),
    ("i2c", "I2C Test"),
    ("wifi", "WiFi Test"),
    ("bluetooth", "Bluetooth Test"),
    ("complete", "Final Result"),
]


def new_state():
    return {
        "tester_connected": False,
        "dut_detected": False,
        "running": False,
        "stage": "idle",
        "stage_label": "Ready to begin",
        "started_at": None,
        "recorded": False,
        "result": {
            "dut_detected": False,
            "gpio": {"tested": 0, "pass": 0, "fail": 0, "results": []},
            "uart": "NOT TESTED",
            "spi": "NOT TESTED",
            "i2c": "NOT TESTED",
            "wifi": {"count": 0, "names": [], "result": "NOT TESTED"},
            "bluetooth": {"count": 0, "names": [], "result": "NOT TESTED"},
            "overall": "NOT TESTED",
        },
    }


states = {"mode1": new_state(), "mode2": new_state()}
state_lock = Lock()


@contextmanager
def database_connection():
    database_path = Path(app.config["DATABASE"])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database():
    with database_connection() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS completed_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                outcome TEXT NOT NULL CHECK (outcome IN ('PASS', 'FAIL')),
                completed_at REAL NOT NULL
            )"""
        )
        connection.execute(
            """CREATE INDEX IF NOT EXISTS completed_tests_mode_time
               ON completed_tests (mode, completed_at)"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS gpio_configuration (
                mode TEXT PRIMARY KEY,
                pins_json TEXT NOT NULL
            )"""
        )
        for mode in states:
            connection.execute(
                "INSERT OR IGNORE INTO gpio_configuration (mode, pins_json) VALUES (?, ?)",
                (mode, json.dumps(DEFAULT_GPIO_PINS)),
            )


initialize_database()


def get_gpio_pins(mode):
    with database_connection() as connection:
        row = connection.execute(
            "SELECT pins_json FROM gpio_configuration WHERE mode = ?", (mode,)
        ).fetchone()
    return json.loads(row[0]) if row else list(DEFAULT_GPIO_PINS)


def set_gpio_pins(mode, pins):
    with database_connection() as connection:
        connection.execute(
            """INSERT INTO gpio_configuration (mode, pins_json) VALUES (?, ?)
               ON CONFLICT(mode) DO UPDATE SET pins_json = excluded.pins_json""",
            (mode, json.dumps(pins)),
        )


def today_bounds():
    now = datetime.now().astimezone()
    start = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo)
    end = start + timedelta(days=1)
    return now, start.timestamp(), end.timestamp()


def today_test_counts(mode):
    now, start, end = today_bounds()
    hourly = [0] * 24
    with database_connection() as connection:
        rows = connection.execute(
            """SELECT completed_at FROM completed_tests
               WHERE mode = ? AND completed_at >= ? AND completed_at < ?""",
            (mode, start, end),
        ).fetchall()
    for (completed_at,) in rows:
        hourly[datetime.fromtimestamp(completed_at).hour] += 1
    return {"count_today": len(rows), "hourly": hourly, "date": now.date().isoformat()}


def record_completed_test(mode, state):
    if state["recorded"]:
        return
    outcome = state["result"]["overall"]
    if outcome not in ("PASS", "FAIL"):
        return
    with database_connection() as connection:
        connection.execute(
            "INSERT INTO completed_tests (mode, outcome, completed_at) VALUES (?, ?, ?)",
            (mode, outcome, datetime.now().astimezone().timestamp()),
        )
    state["recorded"] = True


def get_mode(mode):
    if mode not in states:
        return None
    return states[mode]


def advance_mock_test(mode, state):
    if not state["running"] or state["started_at"] is None:
        return

    elapsed = monotonic() - state["started_at"]
    stage_index = min(int(elapsed // 1.2), len(STAGES) - 1)
    stage_key, stage_label = STAGES[stage_index]
    state["stage"] = stage_key
    state["stage_label"] = stage_label

    result = state["result"]
    if stage_index >= 1:
        gpio_rows = []
        for gpio in get_gpio_pins(mode):
            if gpio == 14:
                high_voltage, low_voltage = 2.10, 0.12
            else:
                high_voltage, low_voltage = 3.29, 0.01
            passed = 3.0 <= high_voltage <= 3.6 and 0.0 <= low_voltage <= 0.3
            gpio_rows.append({
                "gpio": gpio,
                "high_voltage": high_voltage,
                "low_voltage": low_voltage,
                "status": "PASS" if passed else "FAIL",
            })
        result["gpio"] = {
            "tested": len(gpio_rows),
            "pass": sum(row["status"] == "PASS" for row in gpio_rows),
            "fail": sum(row["status"] == "FAIL" for row in gpio_rows),
            "results": gpio_rows,
        }
    if stage_index >= 2:
        result["uart"] = "PASS"
    if stage_index >= 3:
        result["spi"] = "PASS"
    if stage_index >= 4:
        result["i2c"] = "PASS"
    if stage_index >= 5:
        result["wifi"] = {"count": 3, "names": ["Factory-Net", "Lab-Guest", "ESP32-Test"], "result": "PASS"}
    if stage_index >= 6:
        result["bluetooth"] = {"count": 2, "names": ["ESP32_SENSOR", "TEST_FIXTURE"], "result": "PASS"}
    if stage_index >= 7:
        result["overall"] = "FAIL" if result["gpio"]["fail"] else "PASS"
        state["running"] = False
        record_completed_test(mode, state)


def public_state(mode, state):
    advance_mock_test(mode, state)
    return {
        "tester_connected": state["tester_connected"],
        "dut_detected": state["dut_detected"],
        "running": state["running"],
        "stage": state["stage"],
        "stage_label": state["stage_label"],
        "result": deepcopy(state["result"]),
        "count_today": today_test_counts(mode)["count_today"],
    }


@app.get("/")
def mode_selection():
    return render_template("index.html")


@app.get("/mode1")
def mode1():
    return render_template("mode1.html", mode="mode1", mode_title="ESP32 38 pin — MODE 1")


@app.get("/mode2")
def mode2():
    return render_template("mode2.html", mode="mode2", mode_title="ESP32 30 pin — MODE 2")


@app.get("/<mode>/history")
def history(mode):
    state = get_mode(mode)
    if state is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    mode_label = "ESP32 38 pin — MODE 1" if mode == "mode1" else "ESP32 30 pin — MODE 2"
    return render_template("history.html", mode=mode, mode_title=mode_label)


@app.get("/api/<mode>/history")
def history_data(mode):
    state = get_mode(mode)
    if state is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    counts = today_test_counts(mode)
    return jsonify({
        "mode": mode,
        "date": counts["date"],
        "count_today": counts["count_today"],
        "hourly": [{"hour": hour, "count": count} for hour, count in enumerate(counts["hourly"])],
    })


@app.get("/portfolio")
def portfolio():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/portfolio/<path:filename>")
def portfolio_assets(filename):
    return send_from_directory(BASE_DIR, filename)


@app.get("/api/<mode>/status")
def status(mode):
    state = get_mode(mode)
    if state is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    with state_lock:
        return jsonify(public_state(mode, state))


@app.get("/api/<mode>/gpio-config")
def gpio_config(mode):
    if get_mode(mode) is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    return jsonify({"gpios": get_gpio_pins(mode)})


@app.post("/api/<mode>/gpio-config")
def update_gpio_config(mode):
    state = get_mode(mode)
    if state is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    payload = request.get_json(silent=True)
    pins = payload.get("gpios") if isinstance(payload, dict) else None
    if (
        not isinstance(pins, list)
        or not pins
        or len(pins) > 40
        or any(type(pin) is not int or pin < 0 or pin > 39 for pin in pins)
        or len(set(pins)) != len(pins)
    ):
        return jsonify({"error": "Provide a non-empty list of unique GPIO numbers from 0 to 39"}), 400
    with state_lock:
        if state["running"]:
            return jsonify({"error": "GPIO configuration cannot be changed while a test is running"}), 409
        set_gpio_pins(mode, pins)
        return jsonify({"gpios": pins})


@app.post("/api/<mode>/results")
def receive_results(mode):
    state = get_mode(mode)
    if state is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON object is required"}), 400
    outcome = payload.get("overall")
    if outcome not in ("PASS", "FAIL"):
        return jsonify({"error": "Completed results must include overall as PASS or FAIL"}), 400
    with state_lock:
        result = state["result"]
        for key in ("dut_detected", "gpio", "uart", "spi", "i2c", "wifi", "bluetooth", "overall"):
            if key in payload:
                result[key] = payload[key]
        if "dut_detected" in payload:
            state["dut_detected"] = bool(payload["dut_detected"])
        state["stage"] = "complete"
        state["stage_label"] = "Final Result"
        state["running"] = False
        record_completed_test(mode, state)
        return jsonify(public_state(mode, state))


@app.post("/api/<mode>/connect")
def connect(mode):
    state = get_mode(mode)
    if state is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    with state_lock:
        state["tester_connected"] = True
        return jsonify(public_state(mode, state))


@app.post("/api/<mode>/detect")
def detect(mode):
    state = get_mode(mode)
    if state is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    with state_lock:
        if not state["tester_connected"]:
            return jsonify({"error": "Connect the tester before detecting the DUT"}), 409
        state["dut_detected"] = True
        state["result"]["dut_detected"] = True
        return jsonify(public_state(mode, state))


@app.post("/api/<mode>/start")
def start(mode):
    state = get_mode(mode)
    if state is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    with state_lock:
        if not state["tester_connected"]:
            return jsonify({"error": "Connect the tester before starting a test"}), 409
        if not state["dut_detected"]:
            return jsonify({"error": "Detect the DUT before starting a test"}), 409
        state["running"] = True
        state["started_at"] = monotonic()
        state["recorded"] = False
        state["stage"] = "detection"
        state["stage_label"] = "DUT Detection"
        state["result"] = new_state()["result"]
        state["result"]["dut_detected"] = True
        return jsonify(public_state(mode, state))


@app.post("/api/<mode>/stop")
def stop(mode):
    state = get_mode(mode)
    if state is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    with state_lock:
        state["running"] = False
        state["stage"] = "stopped"
        state["stage_label"] = "Test stopped"
        return jsonify(public_state(mode, state))


@app.post("/api/<mode>/clear")
def clear(mode):
    state = get_mode(mode)
    if state is None:
        return jsonify({"error": "Unknown testing mode"}), 404
    with state_lock:
        states[mode] = new_state()
        return jsonify(public_state(mode, states[mode]))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
