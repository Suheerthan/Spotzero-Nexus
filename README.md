# SpotZero Nexus

**Smart Roadside Waste Collection and AI-Assisted Segregation System**
Innovate4Environment Social Action Project by Suheerthan S (Easwari Engineering College, Chennai)

SpotZero Nexus has two parts that share one dashboard:

1. **Smart roadside bin**: an ESP32 with an HC-SR04 ultrasonic sensor measures how full the bin is and raises a collection alert at **80%**.
2. **AI-assisted sorting station**: a conveyor with a magnet (iron/steel), a camera and an image classifier (plastic, paper, glass, organic), and servo flaps that route each item to its bin. Low-confidence items go to reject.

```
Ultrasonic sensor → ESP32 → Wi-Fi → Dashboard alert (≥ 80%) → Collection crew
Conveyor → Magnet → Camera → AI classifier → Servo flaps → Plastic / Paper / Glass / Organic / Reject
```

## Repository layout

| Folder | Contents |
|---|---|
| `dashboard/` | Flask + SQLite web dashboard: live fill level, 80% alerts, collection log, alert history, sorting statistics, confusion matrix, CSV export |
| `firmware/smart_bin_esp32/` | ESP32 + HC-SR04 smart-bin firmware (median filter, sensor-fault state, LED/buzzer, HTTP POST) |
| `firmware/sorter_esp32/` | ESP32 sorting-station controller (belt motor via driver, two servo flaps, IR break-beam timing) |
| `ai/` | Laptop program: webcam + Teachable Machine model → sends the class to the sorter and logs it to the dashboard |

## Run the dashboard

```bash
cd dashboard
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000. On Windows you can double-click `dashboard/run_dashboard.bat` instead.

To try it before the hardware is ready, run `python simulator.py` in a second terminal. It sends **simulated** readings. Press **Reset data** on the dashboard before real tests.

Chart.js and Leaflet load from `dashboard/static/` if present (for offline demos) and otherwise from a CDN.

### API

| Method | Path | Body / purpose |
|---|---|---|
| POST | `/api/bin/reading` | `{"bin_id":"BIN-001","distance_cm":12.3,"fill_pct":69.2,"status":"OK"}`. `status` may be `OK`, `FULL` or `FAULT` |
| POST | `/api/bin/<bin_id>/collected` | Mark the bin as emptied (clears the open alert) |
| POST | `/api/sort/event` | `{"predicted":"plastic","confidence":0.91,"destination":"plastic","actual":"plastic","sorted_ok":true}` |
| POST | `/api/sort/<id>/verify` | `{"actual":"paper","sorted_ok":false}`. Adds ground truth later |
| GET | `/api/state` | Everything the dashboard shows |
| GET | `/export/<readings|alerts|sort_events>.csv` | Raw data for reports |
| POST | `/api/reset` | Clear all data |

## Smart bin firmware

1. Arduino IDE → install the **esp32 by Espressif** board package.
2. Open `firmware/smart_bin_esp32/smart_bin_esp32.ino` and set the Wi-Fi name, password and `SERVER_URL` (your laptop's IP, e.g. `http://192.168.1.10:5000/api/bin/reading`).
3. Calibrate on the real bin: empty-bin distance → `EMPTY_DIST_CM`, distance to the "full" line → `FULL_DIST_CM`.

   `Fill % = (D_empty − D) ÷ (D_empty − D_full) × 100`, using the median of 9 readings.
4. The HC-SR04 ECHO pin is 5 V. Use a 1 kΩ / 2 kΩ divider into the ESP32.

## Sorting station

1. Train an image model at https://teachablemachine.withgoogle.com with classes `plastic`, `paper`, `glass`, `organic`. Export → TensorFlow → Keras and put `keras_model.h5` and `labels.txt` in `ai/`.
2. `pip install tensorflow opencv-python pyserial requests numpy`
3. Upload `firmware/sorter_esp32` (needs the **ESP32Servo** library), then run:

```bash
python ai/sorter_client.py --port COM5 --verify
```

`--verify` asks for the true class after each item, so the dashboard reports real AI and sorting accuracy.

## Success targets

| Indicator | Target |
|---|---|
| Fill-level accuracy | 80–85% |
| AI classification accuracy | 70–75% |
| Items sorted into the correct bin | ≥ 70% |
| Successful alert demonstrations | ≥ 10 |

## Known limitations

- An ordinary magnet does not catch aluminium or copper. These go to reject for manual recovery.
- The classifier is trained for clean, single items. Dirty or overlapping waste lowers accuracy.
- The prototype bin uses Wi-Fi. A street deployment would need GSM, solar power and weatherproofing.
