"""
Demo simulator - use ONLY to test the dashboard before the real hardware is ready.
It pretends to be the ESP32 bin and the sorting station.

    python simulator.py            (dashboard must already be running)

Do not report simulator numbers as test results - they are random.
"""
import random
import time
import requests

URL = "http://localhost:5000"
HEIGHT = 40.0          # cm, usable bin height
fill = 5.0

print("Simulating BIN-001 and sorting station. Ctrl+C to stop.")
while True:
    # --- smart bin: waste level creeps up, gets emptied when an alert is open
    fill += random.uniform(1.5, 4.5)
    if random.random() < 0.03:
        payload = {"bin_id": "BIN-001", "status": "FAULT"}          # occasional bad echo
    else:
        f = min(fill, 100)
        payload = {"bin_id": "BIN-001", "fill_pct": round(f, 1),
                   "distance_cm": round(HEIGHT * (1 - f / 100), 1), "status": "OK"}
    r = requests.post(f"{URL}/api/bin/reading", json=payload, timeout=5).json()
    if r.get("status") == "FULL" and random.random() < 0.25:
        requests.post(f"{URL}/api/bin/BIN-001/collected", timeout=5)
        fill = random.uniform(0, 8)
        print("  bin collected")

    # --- sorting station: one item every few seconds
    if random.random() < 0.6:
        actual = random.choice(["plastic", "paper", "glass", "organic", "plastic", "paper"])
        pred = actual if random.random() < 0.78 else random.choice(["plastic", "paper", "glass", "organic"])
        conf = random.uniform(0.75, 0.99) if pred == actual else random.uniform(0.4, 0.8)
        dest = pred if conf >= 0.6 else "reject"
        requests.post(f"{URL}/api/sort/event", json={
            "predicted": pred, "confidence": round(conf, 2), "destination": dest,
            "actual": actual, "sorted_ok": dest == actual and random.random() < 0.95}, timeout=5)
    time.sleep(2)
