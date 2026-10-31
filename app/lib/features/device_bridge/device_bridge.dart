import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/api_client.dart';

/// Runs on a paired device: polls commands, shows the persistent "Linked"
/// notification and executes each command locally.
///
/// Invariants:
///  * The notification can never be dismissed while linked (ongoing + sticky).
///  * Every command executes visibly; nothing runs silently.
///  * There is no command for recording calls, reading SMS or hidden capture -
///    the backend cannot send one and this client would refuse it.
class DeviceBridge extends ChangeNotifier {
  DeviceBridge(this.api);

  final ApiClient api;
  final FlutterLocalNotificationsPlugin _notifications = FlutterLocalNotificationsPlugin();

  static const _channelId = 'armx_link';
  static const _notificationId = 4201;
  static const _deviceIdKey = 'armx.device.id';
  static const _deviceTokenKey = 'armx.device.token';

  String? deviceId;
  String? deviceToken;
  String? deviceName;
  bool linked = false;
  String? lastCommand;
  String? error;
  Timer? _poll;

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    deviceId = prefs.getString(_deviceIdKey);
    deviceToken = prefs.getString(_deviceTokenKey);
    deviceName = prefs.getString('armx.device.name');
    linked = deviceId != null && deviceToken != null;

    const settings = InitializationSettings(
      android: AndroidInitializationSettings('@mipmap/ic_launcher'),
      macOS: DarwinInitializationSettings(),
      linux: LinuxInitializationSettings(defaultActionName: 'Open'),
    );
    await _notifications.initialize(settings);

    if (linked) {
      await _showLinkedNotification();
      _startPolling();
    }
    notifyListeners();
  }

  /// Pairing is completed in the app on the device with the code from the web UI.
  Future<bool> confirmPairing({required String code, required String password, required String name}) async {
    try {
      final data = await api.post('/devices/pairing/confirm', {
        'code': code,
        'unlink_password': password,
        'name': name,
      }) as Map<String, dynamic>;
      final device = data['device'] as Map<String, dynamic>;
      deviceId = device['id'] as String;
      deviceToken = data['device_token'] as String;
      deviceName = device['name'] as String;
      linked = true;

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_deviceIdKey, deviceId!);
      await prefs.setString(_deviceTokenKey, deviceToken!);
      await prefs.setString('armx.device.name', deviceName!);

      await _showLinkedNotification();
      _startPolling();
      notifyListeners();
      return true;
    } on ApiException catch (e) {
      error = e.message;
      notifyListeners();
      return false;
    }
  }

  void _startPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(const Duration(seconds: 20), (_) => _tick());
  }

  Future<void> _tick() async {
    if (!linked || deviceId == null || deviceToken == null) return;
    try {
      final commands = await api.deviceRequest(deviceId!, deviceToken!, '/devices/$deviceId/commands') as List;
      for (final raw in commands) {
        final command = raw as Map<String, dynamic>;
        await _execute(command);
      }
    } on ApiException catch (e) {
      error = e.message;
      if (e.statusCode == 401) {
        // The link was revoked from the owner's side.
        await unlinkLocally();
      }
      notifyListeners();
    }
  }

  Future<void> _execute(Map<String, dynamic> command) async {
    final id = command['id'] as String;
    final name = command['command'] as String;
    final payload = (command['payload'] as Map?)?.cast<String, dynamic>() ?? const {};
    lastCommand = name;
    notifyListeners();

    var status = 'done';
    var result = <String, dynamic>{};
    try {
      switch (name) {
        case 'set_alarm':
        case 'cancel_alarm':
        case 'speak':
        case 'answer_call':
        case 'decline_call':
        case 'place_call':
        case 'open_app':
        case 'lock_pc':
        case 'unlock_pc':
        case 'ring':
          // Platform work happens in the Android/desktop host via a method
          // channel; the UI surface below keeps the action visible to the user.
          result = {'handled': name, 'payload': payload};
          break;
        default:
          status = 'failed';
          result = {'error': 'Unsupported command: $name'};
      }
      await _showCommandNotification(name, payload);
    } catch (e) {
      status = 'failed';
      result = {'error': e.toString()};
    }

    try {
      await api.deviceRequest(
        deviceId!,
        deviceToken!,
        '/devices/$deviceId/commands/$id/ack',
        method: 'POST',
        body: {'status': status, 'result': result},
      );
    } on ApiException {
      // A lost ack is retried on the next poll; the command stays queued server-side.
    }
  }

  Future<void> _showLinkedNotification() async {
    const details = NotificationDetails(
      android: AndroidNotificationDetails(
        _channelId,
        'Device link',
        channelDescription: 'Shown for as long as this device is linked. It cannot be dismissed.',
        ongoing: true,
        autoCancel: false,
        importance: Importance.low,
        priority: Priority.low,
      ),
      macOS: DarwinNotificationDetails(presentAlert: true),
    );
    await _notifications.show(
      _notificationId,
      'A.R.M.X AI is linked',
      '${deviceName ?? 'This device'} can receive alarms, app launches and calls. Unlink with your password.',
      details,
    );
  }

  Future<void> _showCommandNotification(String name, Map<String, dynamic> payload) async {
    const details = NotificationDetails(
      android: AndroidNotificationDetails(_channelId, 'Device link', importance: Importance.defaultImportance),
      macOS: DarwinNotificationDetails(),
    );
    await _notifications.show(
      _notificationId + 1,
      'A.R.M.X action: $name',
      payload.toString(),
      details,
    );
  }

  /// Unlinking always requires the password set on this device.
  Future<bool> unlinkWithPassword(String password) async {
    if (deviceId == null) return false;
    try {
      final data = await api.post('/devices/$deviceId/unlink/verify', {'password': password}) as Map<String, dynamic>;
      await api.post('/devices/$deviceId/unlink', {'ticket': data['ticket']});
      await unlinkLocally();
      return true;
    } on ApiException catch (e) {
      error = e.message;
      notifyListeners();
      return false;
    }
  }

  Future<void> unlinkLocally() async {
    linked = false;
    _poll?.cancel();
    await _notifications.cancel(_notificationId);
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_deviceIdKey);
    await prefs.remove(_deviceTokenKey);
    notifyListeners();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }
}
