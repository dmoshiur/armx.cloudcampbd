import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:speech_to_text/speech_to_text.dart';

enum WakeWordState { idle, listening, triggered, unavailable }

/// Wake-word + background listening for the native app (Android/desktop).
///
/// Honest limitations baked into the UI:
///  * Android throttles continuous recognition; the OS notification stays
///    visible the whole time the service listens - there is no silent mode.
///  * iOS does not permit this pattern at all; the app offers push-to-talk.
///  * Audio never leaves the device for wake-word detection: only the phrase
///    after a match is sent to the backend.
class WakeWordService extends ChangeNotifier {
  WakeWordService({this.phrase = 'hey armx'});

  final String phrase;
  final SpeechToText _speech = SpeechToText();

  WakeWordState state = WakeWordState.idle;
  String? lastError;
  bool _enabled = false;

  /// Fires with the full utterance once the wake phrase is heard.
  final _commands = StreamController<String>.broadcast();
  Stream<String> get commands => _commands.stream;

  bool get isListening => state == WakeWordState.listening;
  bool get enabled => _enabled;

  Future<bool> enable() async {
    final available = await _speech.initialize(
      onError: (error) {
        lastError = error.errorMsg;
        state = WakeWordState.unavailable;
        notifyListeners();
      },
      onStatus: (status) {
        if (status == 'notListening' && _enabled) {
          // Recognition sessions are short by design; restart to stay available.
          Future<void>.delayed(const Duration(milliseconds: 400), () {
            if (_enabled) _listen();
          });
        }
      },
    );
    if (!available) {
      state = WakeWordState.unavailable;
      lastError = 'Speech recognition is unavailable on this device.';
      notifyListeners();
      return false;
    }
    _enabled = true;
    _listen();
    return true;
  }

  Future<void> disable() async {
    _enabled = false;
    state = WakeWordState.idle;
    await _speech.stop();
    notifyListeners();
  }

  Future<void> _listen() async {
    if (!_enabled) return;
    state = WakeWordState.listening;
    notifyListeners();
    await _speech.listen(
      listenFor: const Duration(seconds: 30),
      pauseFor: const Duration(seconds: 5),
      partialResults: true,
      onResult: (result) {
        final spoken = result.recognizedWords.toLowerCase();
        if (spoken.contains(phrase)) {
          final command = spoken.split(phrase).last.trim();
          state = WakeWordState.triggered;
          notifyListeners();
          if (command.isNotEmpty) _commands.add(command);
          Future<void>.delayed(const Duration(seconds: 1), () {
            state = WakeWordState.listening;
            notifyListeners();
          });
        }
      },
    );
  }

  @override
  void dispose() {
    _enabled = false;
    _speech.stop();
    _commands.close();
    super.dispose();
  }
}
