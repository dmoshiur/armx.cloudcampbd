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

* **Android** — wake word, floating overlay, visible device link, and a native
  Device Owner host with a custom HOME activity, passcode-authorized app allowlist,
  lock-task policy, aggregate usage telemetry, and user-consented MediaProjection.
* **Desktop** — same screens; wake word depends on the OS speech service.
* **Wear OS companion** — the adaptive layout collapses to a single-column,
  large-target UI; admin is read-only there.

## Android Device Owner provisioning

Device Owner is an Android platform role; an installed app cannot grant it to
itself. Use a dedicated factory-reset device with no accounts. For development:

```bash
flutter build apk --debug
adb install -r build/app/outputs/flutter-apk/app-debug.apk
adb shell dpm set-device-owner ai.armx.managed/.management.ArmxDeviceAdminReceiver
```

For production, sign the release APK/AAB with a protected release key and use
Android Enterprise zero-touch/QR provisioning with the same admin component and
an HTTPS APK location plus its signing-certificate checksum. Never use the debug
certificate in a provisioning profile. The in-app **Managed** screen then requires
the owner to:

1. grant visible notifications;
2. create a local passcode (PBKDF2 hash; never sent to the API);
3. choose allowed launcher apps and explicitly enable kiosk mode; and
4. optionally grant Android Usage Access for package/duration/count telemetry.

Deprovisioning requires that local passcode, unsuspends apps, clears lock-task and
HOME policy, and calls Android's official `clearDeviceOwnerApp`. Removing the APK
still uses Android's normal system-confirmed uninstall flow.

## Honest limits (shown in the UI, not hidden)

* Browser surface has **push-to-talk only** — no wake word, no background listening.
* Wake word audio never leaves the device; only the utterance after the phrase is sent.
* There is no silent mode for a linked device: the notification is ongoing and sticky.
* Call recording, SMS reading and hidden screen capture are not implemented anywhere.
