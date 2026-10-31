// A.R.M.X AI - ESP32 smart-home demo node.
//
// Publishes state on MQTT over TLS and accepts on/off commands from Home
// Assistant. Deliberately small: the security boundary is the Home Assistant
// entity allowlist plus the platform's tool gateway, not this firmware.
#include <Arduino.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <DHT.h>
#include "secrets.h"

#define RELAY_PIN 4
#define DHT_PIN 5
#define DEVICE_SLUG "living-room"

const char *BROKER = MQTT_HOST;
const int BROKER_PORT = 8883;

WiFiClientSecure net;
PubSubClient mqtt(net);
DHT dht(DHT_PIN, DHT22);

String topic(const char *suffix) {
  return String("armx/esp32/") + DEVICE_SLUG + "/" + suffix;
}

void publish(const char *suffix, const char *payload, bool retained = true) {
  mqtt.publish(topic(suffix).c_str(), payload, retained);
}

void setRelay(bool on) {
  digitalWrite(RELAY_PIN, on ? HIGH : LOW);
  publish("state", on ? "ON" : "OFF");
  Serial.printf("[relay] %s\n", on ? "ON" : "OFF");
}

void onMessage(char *incoming, byte *payload, unsigned int length) {
  String message;
  for (unsigned int i = 0; i < length; i++) {
    message += static_cast<char>(payload[i]);
  }
  message.trim();

  const String command = topic("set");
  if (command == incoming) {
    setRelay(message.equalsIgnoreCase("ON"));
  }
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.printf("\nwifi connected: %s\n", WiFi.localIP().toString().c_str());
}

void connectMqtt() {
  // TLS only: the CA is pinned in secrets.h, plain TCP is never attempted.
  net.setCACert(ROOT_CA);
  mqtt.setServer(BROKER, BROKER_PORT);
  mqtt.setCallback(onMessage);
  mqtt.setBufferSize(512);

  while (!mqtt.connected()) {
    String clientId = String("armx-esp32-") + DEVICE_SLUG;
    if (mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD)) {
      Serial.println("mqtt connected");
      mqtt.subscribe(topic("set").c_str(), 1);
      mqtt.subscribe(topic("brightness/set").c_str(), 1);
      publish("state", digitalRead(RELAY_PIN) == HIGH ? "ON" : "OFF");
    } else {
      Serial.printf("mqtt connect failed rc=%d\n", mqtt.state());
      delay(2000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);
  dht.begin();
  connectWifi();
  connectMqtt();
}

unsigned long lastReading = 0;

void loop() {
  if (!mqtt.connected()) {
    connectMqtt();
  }
  mqtt.loop();

  if (millis() - lastReading > 30000) {
    lastReading = millis();
    float temperature = dht.readTemperature();
    if (!isnan(temperature)) {
      publish("temperature", String(temperature, 1).c_str(), false);
    }
  }
}
