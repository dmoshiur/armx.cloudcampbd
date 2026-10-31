# ESP32 smart-home demo

A single ESP32 driving one relay (light) and reporting temperature over MQTT with
TLS. It pairs with `examples/home_assistant/configuration.yaml`.

## Wiring

| ESP32 | Module |
|---|---|
| GPIO 4 | relay IN (through a transistor/opto-isolator, mains switching is not a beginner circuit) |
| GPIO 5 | DHT22 data (10 kΩ pull-up to 3V3) |
| GND | common ground |

Use a certified relay module for mains voltage, or a 5 V LED strip for a safe demo.

## Flash

```bash
pio init --board esp32dev
# copy the firmware below into src/main.cpp, put secrets in include/secrets.h
pio run --target upload
pio device monitor
```

## Topic contract (matches Home Assistant above)

```
armx/esp32/living-room/state        ON | OFF      (retained)
armx/esp32/living-room/set          ON | OFF
armx/esp32/living-room/brightness   percent       (retained)
armx/esp32/living-room/temperature  °C            (every 30 s)
```

TLS uses the broker's CA certificate; the device refuses to connect over plain TCP.
