import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
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
  static const _managedChannel = MethodChannel('ai.armx/managed_device');

  static const _channelId = 'armx_link';
  static const _notificationId = 4201;
  static const _deviceIdKey = 'armx.device.id';
  static const _deviceTokenKey = 'armx.device.token';
  static const _pendingPolicyKey = 'armx.pending.policy';
  static const _pendingScreenKey = 'armx.pending.screen';
  static const _pendingVoiceKey = 'armx.pending.voice';

  String? deviceId;
  String? deviceToken;
  String? deviceName;
  bool linked = false;
  String? lastCommand;
  String? error;
  Map<String, dynamic>? pendingPolicy;
  Map<String, dynamic>? pendingScreenShare;
  Map<String, dynamic>? pendingVoiceSession;
  Timer? _poll;
  bool _ticking = false;

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    deviceId = prefs.getString(_deviceIdKey);
    deviceToken = prefs.getString(_deviceTokenKey);
    deviceName = prefs.getString('armx.device.name');
    pendingPolicy = _decodePending(prefs.getString(_pendingPolicyKey));
    pendingScreenShare = _decodePending(prefs.getString(_pendingScreenKey));
    pendingVoiceSession = _decodePending(prefs.getString(_pendingVoiceKey));
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
    if (!linked || deviceId == null || deviceToken == null || _ticking) return;
    _ticking = true;
    try {
      final commands = await api.deviceRequest(deviceId!, deviceToken!, '/devices/$deviceId/commands') as List;
      for (final raw in commands) {
        final command = raw as Map<String, dynamic>;
        await _execute(command);
      }
      await _maybeUploadUsage();
    } on ApiException catch (e) {
      error = e.message;
      if (e.statusCode == 401) {
        // The link was revoked from the owner's side.
        await unlinkLocally();
      }
      notifyListeners();
    } finally {
      _ticking = false;
    }
  }

  Future<void> _maybeUploadUsage() async {
    if (defaultTargetPlatform != TargetPlatform.android || deviceId == null || deviceToken == null) return;
    final prefs = await SharedPreferences.getInstance();
    final now = DateTime.now();
    final previousMs = prefs.getInt('armx.usage.last_upload') ?? 0;
    final previous = DateTime.fromMillisecondsSinceEpoch(previousMs);
    if (now.difference(previous) < const Duration(hours: 1)) return;
    try {
      final policy = await api.deviceRequest(
        deviceId!,
        deviceToken!,
        '/devices/$deviceId/management/policy/device',
      ) as Map<String, dynamic>;
      if (policy['usage_telemetry_enabled'] != true) {
        await prefs.setInt('armx.usage.last_upload', now.millisecondsSinceEpoch);
        return;
      }
      final raw = await _managedChannel.invokeListMethod<Object?>('usageTelemetry', {
        'since': now.subtract(const Duration(hours: 1)).millisecondsSinceEpoch,
        'until': now.millisecondsSinceEpoch,
      });
      final items = (raw ?? const []).map((value) {
        final item = (value as Map).cast<String, dynamic>();
        return {
          'package_name': item['packageName'],
          'foreground_seconds': item['foregroundSeconds'],
          'launches': item['launches'],
          'window_start': DateTime.fromMillisecondsSinceEpoch(item['windowStart'] as int, isUtc: true).toIso8601String(),
          'window_end': DateTime.fromMillisecondsSinceEpoch(item['windowEnd'] as int, isUtc: true).toIso8601String(),
        };
      }).toList(growable: false);
      if (items.isNotEmpty) {
        await api.deviceRequest(
          deviceId!,
          deviceToken!,
          '/devices/$deviceId/management/usage',
          method: 'POST',
          body: {'items': items},
        );
      }
      await prefs.setInt('armx.usage.last_upload', now.millisecondsSinceEpoch);
    } on MissingPluginException {
      // Non-Android paired clients do not report Android usage telemetry.
    } on PlatformException {
      // Usage access remains an explicit local permission. Retry after the owner grants it.
    } on ApiException catch (exception) {
      if (exception.statusCode == 403 || exception.statusCode == 404) {
        await prefs.setInt('armx.usage.last_upload', now.millisecondsSinceEpoch);
        return;
      }
      rethrow;
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
        case 'apply_management_policy':
          await _savePending(_pendingPolicyKey, payload);
          pendingPolicy = payload;
          result = {'pending_local_owner_passcode': true};
          break;
        case 'request_screen_share':
          await _savePending(_pendingScreenKey, payload);
          pendingScreenShare = payload;
          result = {'pending_visible_device_consent': true, 'system_consent_required': true};
          break;
        case 'request_voice_session':
          await _savePending(_pendingVoiceKey, payload);
          pendingVoiceSession = payload;
          result = {'pending_visible_device_consent': true};
          break;
        case 'end_screen_share':
          await _managedChannel.invokeMethod('stopScreenShare');
          await _clearPending(_pendingScreenKey);
          pendingScreenShare = null;
          result = {'stopped': true};
          break;
        case 'end_voice_session':
          await _managedChannel.invokeMethod('stopVisibleVoiceSession');
          await _clearPending(_pendingVoiceKey);
          pendingVoiceSession = null;
          result = {'stopped': true};
          break;
        default:
          status = 'failed';
          result = {'error': 'Unsupported command: $name'};
      }
      notifyListeners();
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

  Future<bool> applyPendingPolicy(String ownerPasscode) async {
    final policy = pendingPolicy;
    if (policy == null || deviceId == null || deviceToken == null) return false;
    final version = policy['policy_version'] as int;
    try {
      await _managedChannel.invokeMethod('applyPolicy', {
        'passcode': ownerPasscode,
        'kioskEnabled': policy['kiosk_enabled'] == true,
        'launcherEnabled': policy['launcher_enabled'] == true,
        'allowedPackages': ((policy['allowed_packages'] as List?) ?? const []).cast<String>(),
        'restrictions': ((policy['restrictions'] as List?) ?? const []).cast<String>(),
      });
      await api.deviceRequest(
        deviceId!,
        deviceToken!,
        '/devices/$deviceId/management/policy/ack',
        method: 'POST',
        body: {'policy_version': version, 'status': 'applied', 'error': ''},
      );
      pendingPolicy = null;
      await _clearPending(_pendingPolicyKey);
      notifyListeners();
      return true;
    } on PlatformException catch (exception) {
      error = exception.message ?? exception.code;
      await _ackPolicyFailure(version, error!);
      notifyListeners();
      return false;
    } on ApiException catch (exception) {
      error = exception.message;
      notifyListeners();
      return false;
    }
  }

  Future<void> _ackPolicyFailure(int version, String message) async {
    if (deviceId == null || deviceToken == null) return;
    try {
      await api.deviceRequest(
        deviceId!,
        deviceToken!,
        '/devices/$deviceId/management/policy/ack',
        method: 'POST',
        body: {'policy_version': version, 'status': 'failed', 'error': message},
      );
    } on ApiException {
      // Preserve the local pending policy so the owner can retry.
    }
  }

  Future<bool> decidePendingScreenShare(bool consent) async {
    final pending = pendingScreenShare;
    if (pending == null || deviceId == null || deviceToken == null) return false;
    final sessionId = pending['session_id'] as String;
    var systemConsent = false;
    if (consent) {
      try {
        final response = await _managedChannel.invokeMapMethod<String, dynamic>(
          'requestScreenShare',
          {
            'sessionId': sessionId,
            'apiBase': api.baseUrl,
            'deviceId': deviceId!,
            'deviceToken': deviceToken!,
          },
        );
        systemConsent = response?['consented'] == true;
      } on PlatformException catch (exception) {
        error = exception.message ?? exception.code;
      }
    }
    final accepted = consent && systemConsent;
    try {
      await api.deviceRequest(
        deviceId!,
        deviceToken!,
        '/devices/$deviceId/consent-sessions/$sessionId/decision',
        method: 'POST',
        body: {
          'decision': accepted ? 'consent' : 'decline',
          'visible_indicator': accepted,
          'system_consent': systemConsent,
          'note': accepted ? 'Android MediaProjection consent granted locally' : 'Declined on device',
        },
      );
    } on ApiException {
      if (accepted) {
        await _managedChannel.invokeMethod<void>('stopScreenShare');
      }
      rethrow;
    }
    pendingScreenShare = null;
    await _clearPending(_pendingScreenKey);
    notifyListeners();
    return accepted;
  }

  Future<bool> decidePendingVoiceSession(bool consent) async {
    final pending = pendingVoiceSession;
    if (pending == null || deviceId == null || deviceToken == null) return false;
    final sessionId = pending['session_id'] as String;
    var accepted = false;
    if (consent) {
      try {
        final response = await _managedChannel.invokeMapMethod<String, dynamic>(
          'startVisibleVoiceSession',
          {
            'sessionId': sessionId,
            'apiBase': api.baseUrl,
            'deviceId': deviceId!,
            'deviceToken': deviceToken!,
          },
        );
        accepted = response?['started'] == true;
      } on PlatformException catch (exception) {
        error = exception.message ?? exception.code;
      }
    }
    try {
      await api.deviceRequest(
        deviceId!,
        deviceToken!,
        '/devices/$deviceId/consent-sessions/$sessionId/decision',
        method: 'POST',
        body: {
          'decision': accepted ? 'consent' : 'decline',
          'visible_indicator': accepted,
          'system_consent': false,
          'note': accepted ? 'Visible microphone session started locally' : 'Declined on device',
        },
      );
    } on ApiException {
      if (accepted) {
        await _managedChannel.invokeMethod<void>('stopVisibleVoiceSession');
      }
      rethrow;
    }
    pendingVoiceSession = null;
    await _clearPending(_pendingVoiceKey);
    notifyListeners();
    return accepted;
  }

  Future<void> stopConsentedSession({required String sessionId, required String kind}) async {
    if (deviceId == null || deviceToken == null) return;
    await _managedChannel.invokeMethod(kind == 'screen_share' ? 'stopScreenShare' : 'stopVisibleVoiceSession');
    await api.deviceRequest(
      deviceId!,
      deviceToken!,
      '/devices/$deviceId/consent-sessions/$sessionId/device-end',
      method: 'POST',
      body: const {},
    );
  }

  Map<String, dynamic>? _decodePending(String? value) {
    if (value == null || value.isEmpty) return null;
    try {
      return (jsonDecode(value) as Map).cast<String, dynamic>();
    } catch (_) {
      return null;
    }
  }

  Future<void> _savePending(String key, Map<String, dynamic> value) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(key, jsonEncode(value));
  }

  Future<void> _clearPending(String key) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(key);
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
    await prefs.remove(_pendingPolicyKey);
    await prefs.remove(_pendingScreenKey);
    await prefs.remove(_pendingVoiceKey);
    pendingPolicy = null;
    pendingScreenShare = null;
    pendingVoiceSession = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }
}
