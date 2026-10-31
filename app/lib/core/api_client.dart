import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;

/// One HTTP client shared by every feature. Tokens live in secure storage.
///
/// The base URL is injected at build time:
///   flutter run --dart-define=ARMX_API_BASE=https://api.armx.example/api
class ApiClient {
  ApiClient({required this.baseUrl, http.Client? client, FlutterSecureStorage? storage})
      : _client = client ?? http.Client(),
        _storage = storage ?? const FlutterSecureStorage();

  final String baseUrl;
  final http.Client _client;
  final FlutterSecureStorage _storage;

  static const _accessKey = 'armx.access';
  static const _refreshKey = 'armx.refresh';

  Future<String?> get accessToken => _storage.read(key: _accessKey);
  Future<String?> get refreshToken => _storage.read(key: _refreshKey);

  Future<void> saveTokens(String access, String refresh) async {
    await _storage.write(key: _accessKey, value: access);
    await _storage.write(key: _refreshKey, value: refresh);
  }

  Future<void> clearTokens() async {
    await _storage.delete(key: _accessKey);
    await _storage.delete(key: _refreshKey);
  }

  Map<String, String> _headers([String? token, Map<String, String>? extra]) => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
        ...?extra,
      };

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Future<dynamic> _decode(http.Response response) async {
    if (response.body.isEmpty) return null;
    try {
      return jsonDecode(response.body);
    } catch (_) {
      return response.body;
    }
  }

  String _errorMessage(dynamic payload, String fallback) {
    if (payload is Map && payload['detail'] != null) {
      final detail = payload['detail'];
      if (detail is String) return detail;
      if (detail is Map && detail['detail'] != null) return detail['detail'].toString();
      return detail.toString();
    }
    return fallback;
  }

  Future<bool> _refresh() async {
    final refresh = await refreshToken;
    if (refresh == null) return false;
    final response = await _client.post(
      _uri('/auth/refresh'),
      headers: _headers(),
      body: jsonEncode({'refresh_token': refresh}),
    );
    if (response.statusCode != 200) {
      await clearTokens();
      return false;
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    await saveTokens(data['access_token'] as String, data['refresh_token'] as String);
    return true;
  }

  Future<dynamic> request(
    String method,
    String path, {
    Map<String, dynamic>? body,
    Map<String, String>? headers,
    bool auth = true,
  }) async {
    Future<http.Response> send() async {
      final token = auth ? await accessToken : null;
      final uri = _uri(path);
      final encoded = body == null ? null : jsonEncode(body);
      switch (method) {
        case 'GET':
          return _client.get(uri, headers: _headers(token, headers));
        case 'POST':
          return _client.post(uri, headers: _headers(token, headers), body: encoded);
        case 'PATCH':
          return _client.patch(uri, headers: _headers(token, headers), body: encoded);
        case 'DELETE':
          return _client.delete(uri, headers: _headers(token, headers));
        default:
          throw ArgumentError('Unsupported method $method');
      }
    }

    var response = await send();
    if (response.statusCode == 401 && auth && await _refresh()) {
      response = await send();
    }

    final payload = await _decode(response);
    if (response.statusCode >= 400) {
      throw ApiException(
        _errorMessage(payload, 'Request failed (${response.statusCode})'),
        response.statusCode,
      );
    }
    return payload;
  }

  Future<dynamic> get(String path) => request('GET', path);
  Future<dynamic> post(String path, [Map<String, dynamic>? body]) => request('POST', path, body: body);
  Future<dynamic> patch(String path, [Map<String, dynamic>? body]) => request('PATCH', path, body: body);
  Future<dynamic> delete(String path) => request('DELETE', path);

  /// Device-authenticated endpoints use the device token, never a user token.
  Future<dynamic> deviceRequest(
    String deviceId,
    String deviceToken,
    String path, {
    String method = 'GET',
    Map<String, dynamic>? body,
  }) async {
    final uri = _uri(path);
    final headers = _headers(null, {'X-Device-Id': deviceId, 'X-Device-Token': deviceToken});
    final response = method == 'GET'
        ? await _client.get(uri, headers: headers)
        : await _client.post(uri, headers: headers, body: jsonEncode(body ?? {}));
    final payload = await _decode(response);
    if (response.statusCode >= 400) {
      throw ApiException(_errorMessage(payload, 'Device request failed'), response.statusCode);
    }
    return payload;
  }
}

class ApiException implements Exception {
  ApiException(this.message, this.statusCode);
  final String message;
  final int statusCode;

  /// Browsers/OS-level offline states should surface as a plain message.
  bool get isNetwork => statusCode == 0;

  @override
  String toString() => message;
}

String defaultApiBase() {
  const configured = String.fromEnvironment('ARMX_API_BASE');
  if (configured.isNotEmpty) return configured;
  // Emulator-friendly default; override with --dart-define in real builds.
  if (Platform.isAndroid) return 'http://10.0.2.2:8000/api';
  return 'http://127.0.0.1:8000/api';
}
