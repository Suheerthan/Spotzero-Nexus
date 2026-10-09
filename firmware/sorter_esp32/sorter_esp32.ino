/*
  SpotZero Nexus - Sorting station controller (ESP32)

  The laptop runs the AI model (ai/sorter_client.py) and sends ONE letter over USB serial:
      P = plastic   A = paper   G = glass   O = organic   R = reject
  The ESP32 stops the belt, sets the diverter flaps, restarts the belt, waits until the item
  breaks the IR beam at the diverter, then resets the flaps.

  Wiring
    L298N / L9110 motor driver: IN1 -> GPIO 25, IN2 -> GPIO 26, ENA (PWM) -> GPIO 27
       Motor supply from a separate 6-12 V source; join its GND with ESP32 GND.
    Servo 1 (flap 1) signal -> GPIO 13     Servo 2 (flap 2) signal -> GPIO 14
       Power servos from a 5 V supply (NOT the ESP32 3.3 V pin); common GND.
    IR break-beam / IR obstacle sensor OUT -> GPIO 34 (LOW when beam blocked)
    Camera-zone IR sensor OUT              -> GPIO 35 (stops belt under the camera)

  Library: ESP32Servo (Arduino Library Manager)

  Two servos x two positions give 4 chutes; the 5th (reject) is the end of the belt.
  Adjust ANGLES[] to your flap geometry.
*/
#include <ESP32Servo.h>

const int IN1 = 25, IN2 = 26, ENA = 27;
const int S1 = 13, S2 = 14;
const int IR_DIVERT = 34, IR_CAMERA = 35;
const int BELT_SPEED = 170;            // 0-255
const unsigned long ITEM_TIMEOUT = 6000;

Servo flap1, flap2;
// {flap1, flap2} angle per class. 90 = closed (item passes straight)
struct Route { char code; int a1; int a2; const char* name; };
Route ROUTES[] = {
  {'P', 30, 90, "plastic"},
  {'A', 150, 90, "paper"},
  {'G', 90, 30, "glass"},
  {'O', 90, 150, "organic"},
  {'R', 90, 90, "reject"},
};

void belt(bool on) {
  digitalWrite(IN1, on); digitalWrite(IN2, LOW);
  analogWrite(ENA, on ? BELT_SPEED : 0);
}

void setFlaps(int a1, int a2) { flap1.write(a1); flap2.write(a2); delay(350); }

void setup() {
  Serial.begin(115200);
  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT); pinMode(ENA, OUTPUT);
  pinMode(IR_DIVERT, INPUT); pinMode(IR_CAMERA, INPUT);
  flap1.attach(S1); flap2.attach(S2);
  setFlaps(90, 90);
  belt(true);
  Serial.println("READY");
}

void loop() {
  // Item reached the camera -> stop and ask the laptop to classify
  if (digitalRead(IR_CAMERA) == LOW) {
    belt(false);
    Serial.println("ITEM");             // laptop captures a frame when it sees this
    unsigned long t0 = millis();
    while (!Serial.available() && millis() - t0 < 5000) delay(5);
    char c = Serial.available() ? toupper(Serial.read()) : 'R';   // no answer -> reject
    while (Serial.available()) Serial.read();

    Route r = ROUTES[4];
    for (Route x : ROUTES) if (x.code == c) r = x;
    setFlaps(r.a1, r.a2);
    belt(true);

    // wait for the item to pass the diverter (beam blocked then cleared)
    t0 = millis();
    bool seen = false;
    while (millis() - t0 < ITEM_TIMEOUT) {
      if (digitalRead(IR_DIVERT) == LOW) seen = true;
      else if (seen) break;
      delay(5);
    }
    delay(400);
    setFlaps(90, 90);
    Serial.printf("DONE %s %s\n", r.name, seen ? "passed" : "TIMEOUT");
    // make sure the same item does not retrigger the camera sensor
    while (digitalRead(IR_CAMERA) == LOW) delay(10);
  }
}
