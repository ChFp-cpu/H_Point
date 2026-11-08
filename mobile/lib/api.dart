import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

typedef Json = Map<String, dynamic>;

Json object(dynamic value) => value is Json ? value : <String, dynamic>{};
List<Json> rows(dynamic value) =>
    value is List ? value.whereType<Json>().toList() : <Json>[];
String string(dynamic value, [String fallback = '']) =>
    value is String && value.trim().isNotEmpty ? value : fallback;
int integer(dynamic value) => value is num ? value.toInt() : 0;

class ApiException implements Exception {
  const ApiException(this.message, [this.statusCode = 0, this.code = '']);

  final String message;
  final int statusCode;
  final String code;

  @override
  String toString() => message;
}

/// Keeps H-Point cookies scoped to one origin. Passwords are never persisted.
class HPointApi {
  HPointApi({Uri? origin, FlutterSecureStorage? storage, HttpClient? client})
    : origin = origin ?? Uri.parse(_configuredOrigin),
      _storage = storage ?? const FlutterSecureStorage(),
      _client = client ?? HttpClient() {
    final localHost = {'localhost', '127.0.0.1', '10.0.2.2'};
    if (this.origin.scheme != 'https' &&
        !(this.origin.scheme == 'http' &&
            localHost.contains(this.origin.host))) {
      throw ArgumentError('H-Point API requires HTTPS.');
    }
    _client.connectionTimeout = const Duration(seconds: 12);
  }

  static const _configuredOrigin = String.fromEnvironment(
    'HPOINT_API_ORIGIN',
    defaultValue: 'https://gethpoint.ru',
  );
  static const _session = 'hpoint_session';
  static const _device = 'hpoint_device';
  static const _verification = 'hpoint_verification';
  static const _cookieNames = {_session, _device, _verification};
  static const _timeout = Duration(seconds: 25);

  final Uri origin;
  final FlutterSecureStorage _storage;
  final HttpClient _client;
  final Map<String, _SavedCookie> _cookies = {};
  void Function()? onExpired;

  String get _storageKey => 'hpoint.cookies.v1.${origin.origin}';
  bool get hasSession => _cookies[_session]?.active == true;

  Future<void> restore() async {
    final saved = await _storage.read(key: _storageKey);
    if (saved == null) return;
    try {
      final data = object(jsonDecode(saved));
      for (final name in [_session, _device]) {
        final record = object(data[name]);
        final token = string(record['value']);
        final expiry = DateTime.tryParse(string(record['expires']));
        if (token.isEmpty ||
            expiry == null ||
            !expiry.isAfter(DateTime.now())) {
          continue;
        }
        _cookies[name] = _SavedCookie(token, expiry);
      }
    } on FormatException {
      await _storage.delete(key: _storageKey);
    }
  }

  Future<void> forgetSession() async {
    _cookies.remove(_session);
    _cookies.remove(_verification);
    await _persist();
  }

  Future<void> _persist() async {
    final data = <String, Json>{};
    for (final name in [_session, _device]) {
      final cookie = _cookies[name];
      if (cookie != null && cookie.active) {
        data[name] = {
          'value': cookie.value,
          'expires': cookie.expires.toUtc().toIso8601String(),
        };
      }
    }
    if (data.isEmpty) {
      await _storage.delete(key: _storageKey);
    } else {
      await _storage.write(key: _storageKey, value: jsonEncode(data));
    }
  }

  Future<Json> get(String path, [Map<String, String>? query]) =>
      _json('GET', path, query: query);

  Future<Json> post(String path, [Json body = const {}]) =>
      _json('POST', path, body: body);

  Future<Uint8List> getBytes(String path, [Map<String, String>? query]) async {
    final response = await _send('GET', path, query: query);
    if (response.status >= 400) {
      throw ApiException('Не удалось загрузить фото.', response.status);
    }
    return response.bytes;
  }

  Future<Json> _json(
    String method,
    String path, {
    Map<String, String>? query,
    Json? body,
  }) async {
    final response = await _send(method, path, query: query, body: body);
    Json data;
    try {
      data = object(jsonDecode(utf8.decode(response.bytes)));
    } on FormatException {
      throw ApiException(
        'Сервер H-Point недоступен. Попробуйте позже.',
        response.status,
      );
    }
    if (response.status >= 400 || data['ok'] != true) {
      final code = string(data['code'], string(data['error']));
      if (code == 'auth_required') {
        if (response.session != null &&
            _cookies[_session]?.value == response.session) {
          await forgetSession();
          onExpired?.call();
        }
        throw const ApiException(
          'Войдите в H-Point ещё раз.',
          401,
          'auth_required',
        );
      }
      throw ApiException(
        string(
          data['error'],
          'Не удалось выполнить действие. Попробуйте ещё раз.',
        ),
        response.status,
        code,
      );
    }
    return data;
  }

  Future<_ApiResponse> _send(
    String method,
    String path, {
    Map<String, String>? query,
    Json? body,
  }) async {
    var uri = origin.resolve(path);
    if (uri.origin != origin.origin || !uri.path.startsWith('/api/')) {
      throw const ApiException('Некорректный адрес H-Point.');
    }
    if (query != null) uri = uri.replace(queryParameters: query);
    final session = _cookies[_session]?.value;
    HttpClientRequest? request;
    try {
      request = await _client.openUrl(method, uri).timeout(_timeout);
      request.followRedirects = false;
      request.headers.set(
        HttpHeaders.acceptHeader,
        'application/json, image/*',
      );
      for (final entry in _cookies.entries) {
        if (entry.value.active) {
          request.cookies.add(Cookie(entry.key, entry.value.value));
        }
      }
      if (body != null) {
        final encoded = utf8.encode(jsonEncode(body));
        request.headers.set('Origin', origin.origin);
        request.headers.contentType = ContentType.json;
        request.contentLength = encoded.length;
        request.add(encoded);
      }
      final response = await request.close().timeout(_timeout);
      final bytes = await _read(response).timeout(_timeout);
      var changed = false;
      for (final cookie in response.cookies) {
        if (!_cookieNames.contains(cookie.name)) continue;
        final age = cookie.maxAge;
        final now = DateTime.now();
        final expires = age == null
            ? (cookie.expires ?? now.add(const Duration(days: 30)))
            : now.add(Duration(seconds: age));
        if (cookie.value.isEmpty || !expires.isAfter(now)) {
          _cookies.remove(cookie.name);
        } else {
          _cookies[cookie.name] = _SavedCookie(cookie.value, expires);
        }
        if (cookie.name != _verification) changed = true;
      }
      if (changed) await _persist();
      return _ApiResponse(response.statusCode, bytes, session);
    } on TimeoutException {
      request?.abort();
      throw const ApiException('Сервер долго отвечает. Попробуйте ещё раз.');
    } on IOException {
      throw const ApiException(
        'Не удалось подключиться к H-Point. Проверьте интернет.',
      );
    }
  }

  static Future<Uint8List> _read(HttpClientResponse response) async {
    final bytes = BytesBuilder(copy: false);
    await for (final chunk in response) {
      bytes.add(chunk);
      if (bytes.length > 16 * 1024 * 1024) {
        throw const ApiException('Ответ сервера слишком большой.');
      }
    }
    return bytes.takeBytes();
  }

  void close() => _client.close(force: true);
}

class _SavedCookie {
  const _SavedCookie(this.value, this.expires);
  final String value;
  final DateTime expires;
  bool get active => expires.isAfter(DateTime.now());
}

class _ApiResponse {
  const _ApiResponse(this.status, this.bytes, this.session);
  final int status;
  final Uint8List bytes;
  final String? session;
}
