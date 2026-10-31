import 'package:flutter/foundation.dart';

import 'api_client.dart';

class SessionUser {
  SessionUser({required this.id, required this.email, required this.displayName, required this.role, required this.theme});

  factory SessionUser.fromJson(Map<String, dynamic> json) => SessionUser(
        id: json['id'] as String,
        email: json['email'] as String,
        displayName: (json['display_name'] as String?) ?? '',
        role: (json['role'] as String?) ?? 'user',
        theme: (json['theme'] as String?) ?? 'dark',
      );

  final String id;
  final String email;
  final String displayName;
  final String role;
  final String theme;

  bool get isAdmin => role == 'admin';
  bool get canLinkDevices => role == 'vip' || role == 'admin';
}

enum AuthStatus { unknown, signedOut, signedIn }

/// Global session state. Kept deliberately small: the backend is the source of
/// truth for roles, permissions and tool availability.
class AuthController extends ChangeNotifier {
  AuthController(this.api);

  final ApiClient api;

  AuthStatus status = AuthStatus.unknown;
  SessionUser? user;
  String themeMode = 'dark';
  String? error;
  bool busy = false;

  Future<void> bootstrap() async {
    if (await api.accessToken == null && await api.refreshToken == null) {
      status = AuthStatus.signedOut;
      notifyListeners();
      return;
    }
    try {
      final me = await api.get('/auth/me') as Map<String, dynamic>;
      user = SessionUser.fromJson(me);
      themeMode = user!.theme;
      status = AuthStatus.signedIn;
    } catch (_) {
      await api.clearTokens();
      status = AuthStatus.signedOut;
    }
    notifyListeners();
  }

  Future<bool> login(String email, String password) async {
    busy = true;
    error = null;
    notifyListeners();
    try {
      final data = await api.post('/auth/login', {'email': email, 'password': password}) as Map<String, dynamic>;
      await api.saveTokens(data['access_token'] as String, data['refresh_token'] as String);
      final me = await api.get('/auth/me') as Map<String, dynamic>;
      user = SessionUser.fromJson(me);
      themeMode = user!.theme;
      status = AuthStatus.signedIn;
      return true;
    } on ApiException catch (e) {
      error = e.message;
      return false;
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  Future<bool> signup(String email, String password, String displayName) async {
    busy = true;
    error = null;
    notifyListeners();
    try {
      final data = await api.post('/auth/signup', {
        'email': email,
        'password': password,
        'display_name': displayName,
      }) as Map<String, dynamic>;
      await api.saveTokens(data['access_token'] as String, data['refresh_token'] as String);
      final me = await api.get('/auth/me') as Map<String, dynamic>;
      user = SessionUser.fromJson(me);
      status = AuthStatus.signedIn;
      return true;
    } on ApiException catch (e) {
      error = e.message;
      return false;
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  Future<void> setTheme(String mode) async {
    themeMode = mode;
    notifyListeners();
    try {
      await api.patch('/auth/me', {'theme': mode});
    } on ApiException {
      // A failed preference write must not break the UI.
    }
  }

  Future<void> logout() async {
    try {
      await api.post('/auth/logout');
    } on ApiException {
      // Session may already be gone.
    }
    await api.clearTokens();
    user = null;
    status = AuthStatus.signedOut;
    notifyListeners();
  }
}
