# A.R.M.X AI — native clients (Android, desktop, Wear OS)

Flutter client for the same FastAPI backend the web app uses. No business logic is
duplicated here: the app calls `/api/assistant/chat`, gets back a run with an
optional approval, and asks the human to confirm before anything runs.

## Run

```bash
cd app
flutter pub get
flutter run --dart-define=ARMX_API_BASE=http://10.0.2.2:8000/api   # Android emulator
flutter run -d linux --dart-define=ARMX_API_BASE=http://127.0.0.1:8000/api
```

## Platforms

* **Android** — wake word (on-device detection), floating overlay bubble,
  foreground service with a permanent notification, device link for alarms, app
  launch, call control (via the Android Telecom APIs in the host layer).
* **Desktop** — same screens; wake word depends on the OS speech service.
* **Wear OS companion** — the adaptive layout collapses to a single-column,
  large-target UI; admin is read-only there.

## Honest limits (shown in the UI, not hidden)

* Browser surface has **push-to-talk only** — no wake word, no background listening.
* Wake word audio never leaves the device; only the utterance after the phrase is sent.
* There is no silent mode for a linked device: the notification is ongoing and sticky.
* Call recording, SMS reading and hidden screen capture are not implemented anywhere.
