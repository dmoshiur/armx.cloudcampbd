import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

class ManagedApplication {
  const ManagedApplication({required this.packageName, required this.label, required this.systemApp});

  final String packageName;
  final String label;
  final bool systemApp;

  factory ManagedApplication.fromJson(Map<Object?, Object?> json) => ManagedApplication(
        packageName: json['packageName'] as String,
        label: json['label'] as String,
        systemApp: json['systemApp'] as bool? ?? false,
      );
}

/// Android Device Owner bridge. Owner passcodes are sent only over the local
/// platform channel and are never persisted in Dart or transmitted to the API.
class ManagedDeviceController extends ChangeNotifier {
  static const _channel = MethodChannel('ai.armx/managed_device');

  bool loading = false;
  String? error;
  Map<String, dynamic> state = const {'supported': false};
  List<ManagedApplication> applications = const [];
  Set<String> selectedPackages = {};

  bool get supported => !kIsWeb && defaultTargetPlatform == TargetPlatform.android && state['supported'] == true;
  bool get deviceOwner => state['deviceOwner'] == true;
  bool get passcodeConfigured => state['passcodeConfigured'] == true;
  bool get kioskEnabled => state['kioskEnabled'] == true;
  bool get notificationPermission => state['notificationPermission'] == true;
  bool get usageAccess => state['usageAccess'] == true;

  Future<void> init() async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return;
    await refresh();
  }

  Future<void> refresh() => _guard(_refreshRaw);

  Future<void> _refreshRaw() async {
    final raw = await _channel.invokeMapMethod<String, dynamic>('managementState');
    state = raw ?? const {'supported': true};
    selectedPackages = ((state['allowedPackages'] as List?) ?? const []).cast<String>().toSet();
    if (deviceOwner) await _loadApplicationsRaw();
  }

  Future<void> loadApplications() => _guard(_loadApplicationsRaw);

  Future<void> _loadApplicationsRaw() async {
    final raw = await _channel.invokeListMethod<Object?>('launchableApplications') ?? const [];
    applications = raw
        .map((item) => ManagedApplication.fromJson((item as Map).cast<Object?, Object?>()))
        .toList(growable: false);
  }

  Future<bool> requestNotificationPermission() async {
    var granted = false;
    await _guard(() async {
      granted = await _channel.invokeMethod<bool>('requestNotificationPermission') ?? false;
      await _refreshRaw();
    });
    return granted;
  }

  Future<bool> setInitialPasscode(String passcode) async {
    var changed = false;
    await _guard(() async {
      await _channel.invokeMethod('setInitialPasscode', {'passcode': passcode});
      changed = true;
      await _refreshRaw();
    });
    return changed;
  }

  Future<bool> changePasscode(String current, String replacement) async {
    var changed = false;
    await _guard(() async {
      changed = await _channel.invokeMethod<bool>('changePasscode', {
            'current': current,
            'replacement': replacement,
          }) ??
          false;
    });
    return changed;
  }

  void selectPackage(String packageName, bool allowed) {
    if (allowed) {
      selectedPackages.add(packageName);
    } else {
      selectedPackages.remove(packageName);
    }
    notifyListeners();
  }

  Future<bool> applyPolicy({required String passcode, required bool kiosk}) async {
    var applied = false;
    await _guard(() async {
      final raw = await _channel.invokeMapMethod<String, dynamic>('applyPolicy', {
        'passcode': passcode,
        'kioskEnabled': kiosk,
        'allowedPackages': selectedPackages.toList(growable: false),
      });
      if (raw != null) {
        state = {...state, ...raw};
        applied = true;
      }
      await _refreshRaw();
    });
    return applied;
  }

  Future<List<Map<String, dynamic>>> readUsage({Duration window = const Duration(hours: 24)}) async {
    var result = <Map<String, dynamic>>[];
    await _guard(() async {
      final now = DateTime.now().millisecondsSinceEpoch;
      final raw = await _channel.invokeListMethod<Object?>('usageTelemetry', {
        'since': now - window.inMilliseconds,
        'until': now,
      });
      result = (raw ?? const []).map((item) => (item as Map).cast<String, dynamic>()).toList();
    });
    return result;
  }

  Future<void> openUsageAccessSettings() => _guard(() async {
        await _channel.invokeMethod('openUsageAccessSettings');
      });

  Future<bool> deprovision(String passcode) async {
    var complete = false;
    await _guard(() async {
      await _channel.invokeMethod('deprovision', {'passcode': passcode});
      complete = true;
      await _refreshRaw();
    });
    return complete;
  }

  Future<void> requestUninstall() => _guard(() async {
        await _channel.invokeMethod('requestUninstall');
      });

  Future<Map<String, dynamic>?> requestScreenShare(String sessionId) async {
    Map<String, dynamic>? response;
    await _guard(() async {
      response = await _channel.invokeMapMethod<String, dynamic>('requestScreenShare', {'sessionId': sessionId});
    });
    return response;
  }

  Future<void> stopScreenShare() => _guard(() async {
        await _channel.invokeMethod('stopScreenShare');
      });

  Future<void> _guard(Future<void> Function() action) async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      await action();
    } on PlatformException catch (exception) {
      error = exception.message ?? exception.code;
    } catch (exception) {
      error = exception.toString();
    } finally {
      loading = false;
      notifyListeners();
    }
  }
}
