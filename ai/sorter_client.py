"""
SpotZero Nexus - AI sorting client (runs on the laptop)

1. Train an Image model on https://teachablemachine.withgoogle.com with 4 classes,
   named exactly: plastic, paper, glass, organic
   (do NOT train a "reject" class - low-confidence items go to reject automatically)
2. Export -> Tensorflow -> Keras -> download. Put keras_model.h5 and labels.txt in this folder.
3. pip install tensorflow opencv-python pyserial requests numpy
4. python sorter_client.py --port COM5          (with the sorter ESP32 plugged in)
   python sorter_client.py                      (no hardware: press SPACE to classify)

Add --verify to type the real class after each item -> builds AI and sorting accuracy
on the dashboard (these are your real test results for the report).
"""
import argparse
import os
import time

import cv2
import numpy as np
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CODES = {"plastic": "P", "paper": "A", "glass": "G", "organic": "O", "reject": "R"}

ap = argparse.ArgumentParser()
ap.add_argument("--port", help="Serial port of sorter ESP32, e.g. COM5")
ap.add_argument("--cam", type=int, default=0, help="Webcam index")
ap.add_argument("--threshold", type=float, default=0.70, help="Min confidence, else reject")
ap.add_argument("--server", default="http://localhost:5000")
ap.add_argument("--verify", action="store_true", help="Ask for the true class after each item")
args = ap.parse_args()

# ---- load model
from tensorflow.keras.models import load_model   # noqa: E402  (slow import)
model = load_model(os.path.join(HERE, "keras_model.h5"), compile=False)
labels = []
with open(os.path.join(HERE, "labels.txt"), encoding="utf-8") as f:
    for line in f:
        parts = line.strip().split(" ", 1)          # Teachable Machine format: "0 plastic"
        labels.append(parts[-1].strip().lower())
print("Classes:", labels)


def classify(frame):
    img = cv2.resize(frame, (224, 224), interpolation=cv2.INTER_AREA)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    x = (img.astype(np.float32) / 127.5) - 1.0     # Teachable Machine normalisation
    probs = model.predict(x[None, ...], verbose=0)[0]
    i = int(np.argmax(probs))
    return labels[i], float(probs[i])


ser = None
if args.port:
    import serial
    ser = serial.Serial(args.port, 115200, timeout=0.05)
    time.sleep(2)
    print("Connected to sorter on", args.port)

cam = cv2.VideoCapture(args.cam)
if not cam.isOpened():
    raise SystemExit("Camera not found - try --cam 1")

print("Running. Press Q in the video window to quit." + ("" if ser else " SPACE = classify."))
last_text = ""
while True:
    ok, frame = cam.read()
    if not ok:
        continue
    view = frame.copy()
    cv2.putText(view, last_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 0), 2)
    cv2.imshow("SpotZero sorter", view)
    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break

    trigger = key == ord(" ")
    if ser and ser.in_waiting:
        line = ser.readline().decode(errors="ignore").strip()
        if line:
            print("ESP32:", line)
        trigger = trigger or line == "ITEM"
    if not trigger:
        continue

    time.sleep(0.3)                          # let the item settle under the camera
    for _ in range(3):
        cam.read()                           # flush stale buffered frames
    ok, frame = cam.read()
    pred, conf = classify(frame)
    dest = pred if conf >= args.threshold else "reject"
    last_text = f"{pred} {conf:.0%} -> {dest}"
    print(last_text)
    if ser:
        ser.write(CODES[dest].encode())

    payload = {"predicted": pred, "confidence": round(conf, 3), "destination": dest}
    if args.verify:
        actual = input(f"  actual class {list(CODES)} (Enter = same as predicted): ").strip().lower() or pred
        ok_in = input("  did it land in the correct box? [y/n]: ").strip().lower()
        correct_box = actual if actual in CODES else "reject"
        payload.update(actual=actual, sorted_ok=(ok_in == "y") if ok_in else (dest == correct_box))
    try:
        requests.post(f"{args.server}/api/sort/event", json=payload, timeout=3)
    except requests.RequestException as e:
        print("  dashboard not reachable:", e)

cam.release()
cv2.destroyAllWindows()
