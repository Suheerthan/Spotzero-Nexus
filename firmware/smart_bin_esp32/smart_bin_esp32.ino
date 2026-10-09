/*
  SpotZero Nexus - Smart Bin (ESP32 + HC-SR04)

  Wiring
    HC-SR04 VCC  -> 5V (VIN)          HC-SR04 GND -> GND
    HC-SR04 TRIG -> GPIO 5
    HC-SR04 ECHO -> GPIO 18  via divider (1k from ECHO, 2k to GND)  <- ECHO is 5V, ESP32 is 3.3V
    LED (+220R)  -> GPIO 2   (on-board LED also works)
    Buzzer (+)   -> GPIO 4   (active buzzer, GND to GND)

  Calibration (do this on the REAL bin):
    1. Upload, open Serial Monitor at 115200 with the bin EMPTY.
    2. Note the "dist" value -> put it in EMPTY_DIST_CM.
    3. Measure the distance from the sensor to the "full" line (e.g. 3 cm below the rim)
       -> FULL_DIST_CM. Fill % = (EMPTY - d) / (EMPTY - FULL) * 100
*/
#include <WiFi.h>
#include <HTTPClient.h>

// ---------- EDIT THESE ----------
const char* WIFI_SSID   = "YOUR_WIFI";
const char* WIFI_PASS   = "YOUR_PASSWORD";
const char* SERVER_URL  = "http://192.168.1.10:5000/api/bin/reading";   // laptop IP (run ipconfig)
const char* BIN_ID      = "BIN-001";
const float EMPTY_DIST_CM = 40.0;   // sensor -> bottom of empty bin
const float FULL_DIST_CM  = 3.0;    // sensor -> "full" line
const float ALERT_PCT     = 80.0;
const unsigned long SEND_EVERY_MS = 10000;
// --------------------------------

const int TRIG = 5, ECHO = 18, LED = 2, BUZZER = 4;
const int SAMPLES = 9;

float readOnceCm() {
  digitalWrite(TRIG, LOW);  delayMicroseconds(3);
  digitalWrite(TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG, LOW);
  unsigned long us = pulseIn(ECHO, HIGH, 30000);      // 30 ms timeout ~ 5 m
  if (us == 0) return -1;                             // no echo
  return us * 0.0343 / 2.0;
}

// Median of several readings -> rejects spikes from uneven waste surfaces
float readMedianCm() {
  float v[SAMPLES]; int n = 0;
  for (int i = 0; i < SAMPLES; i++) {
    float d = readOnceCm();
    if (d > 1.5 && d < 400) v[n++] = d;
    delay(60);
  }
  if (n < SAMPLES / 2 + 1) return -1;                 // too many failed echoes -> fault
  for (int i = 1; i < n; i++) {                       // insertion sort
    float k = v[i]; int j = i - 1;
    while (j >= 0 && v[j] > k) { v[j + 1] = v[j]; j--; }
    v[j + 1] = k;
  }
  return v[n / 2];
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(250); Serial.print("."); }
  Serial.println(WiFi.status() == WL_CONNECTED ? " connected: " + WiFi.localIP().toString() : " FAILED");
}

void sendReading(float dist, float pct, const char* status) {
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) return;
  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  String body = String("{\"bin_id\":\"") + BIN_ID + "\",\"status\":\"" + status + "\"";
  if (dist >= 0) body += ",\"distance_cm\":" + String(dist, 1) + ",\"fill_pct\":" + String(pct, 1);
  body += "}";
  int code = http.POST(body);
  Serial.printf("POST %s -> %d\n", body.c_str(), code);
  http.end();
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG, OUTPUT); pinMode(ECHO, INPUT);
  pinMode(LED, OUTPUT);  pinMode(BUZZER, OUTPUT);
  connectWiFi();
}

unsigned long lastSend = 0;
bool wasFull = false;

void loop() {
  float d = readMedianCm();
  const char* status;
  float pct = 0;

  if (d < 0 || d > EMPTY_DIST_CM + 5) {
    status = "FAULT";                                 // never treat a dead sensor as "empty"
    digitalWrite(LED, (millis() / 250) % 2);          // fast blink = fault
    digitalWrite(BUZZER, LOW);
  } else {
    pct = (EMPTY_DIST_CM - d) / (EMPTY_DIST_CM - FULL_DIST_CM) * 100.0;
    pct = constrain(pct, 0, 100);
    bool full = pct >= ALERT_PCT;
    status = full ? "FULL" : "OK";
    digitalWrite(LED, full);
    if (full && !wasFull) {                           // short beep once when crossing threshold
      digitalWrite(BUZZER, HIGH); delay(400); digitalWrite(BUZZER, LOW);
      lastSend = 0;                                   // report immediately
    }
    wasFull = full;
  }

  Serial.printf("dist=%.1f cm  fill=%.1f%%  %s\n", d, pct, status);

  if (millis() - lastSend >= SEND_EVERY_MS || lastSend == 0) {
    sendReading(d, pct, status);
    lastSend = millis();
  }
  delay(500);
}
