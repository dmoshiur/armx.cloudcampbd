#pragma once
// Copy to include/secrets.h and fill in. Never commit the real file.
#define WIFI_SSID "your-wifi"
#define WIFI_PASSWORD "your-password"
#define MQTT_HOST "mqtt.local"
#define MQTT_USER "armx"
#define MQTT_PASSWORD "replace-me"

// Your broker's CA certificate (PEM), used for TLS with certificate pinning.
static const char ROOT_CA[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
... paste your broker CA here ...
-----END CERTIFICATE-----
)EOF";
