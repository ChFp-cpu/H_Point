import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hpoint/api.dart';
import 'package:hpoint/session.dart';

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  test('POST transport, challenge cookies, restoration and logout', () async {
    final fixture = await _Fixture.start();
    addTearDown(fixture.close);
    final session = HPointSession(HPointApi(origin: fixture.origin));
    addTearDown(session.dispose);

    await session.start();
    expect(session.signedIn, isFalse);
    expect(session.guest?['guest'], isTrue);

    const registration = {
      'name': 'Тестовый участник',
      'email': 'person@example.test',
      'password': 'Example1',
      'password_confirm': 'Example1',
    };
    expect(await session.authenticate(registration, register: true), isFalse);
    expect(session.api.hasSession, isFalse);
    final register = fixture.last('/api/auth/register');
    expect(register.method, 'POST');
    expect(register.origin, fixture.origin.origin);
    expect(register.contentType, 'application/json');
    expect(
      register.contentLength,
      utf8.encode(jsonEncode(registration)).length,
    );
    expect(register.transferEncoding, isNull);
    expect(register.jsonBody, registration);
    expect(register.cookies, isEmpty);
    expect(await const FlutterSecureStorage().readAll(), isEmpty);

    await session.verifyEmail('234567');
    expect(session.signedIn, isTrue);
    expect(session.user['id'], -7);
    final verification = fixture.last('/api/auth/email/verify');
    expect(verification.jsonBody, {'code': '234567'});
    expect(verification.cookies, {'hpoint_verification': 'pending-only'});
    const accountCookies = {
      'hpoint_session': 'private-session',
      'hpoint_device': 'device-cookie',
    };
    expect(fixture.last('/api/sync').cookies, accountCookies);

    final restored = HPointSession(HPointApi(origin: fixture.origin));
    addTearDown(restored.dispose);
    await restored.start();
    expect(restored.signedIn, isTrue);
    expect(fixture.last('/api/sync').cookies, accountCookies);

    await restored.signOut();
    expect(restored.signedIn, isFalse);
    expect(restored.api.hasSession, isFalse);
    expect(fixture.last('/api/auth/logout').cookies, accountCookies);
    expect(fixture.last('/api/guest').cookies, {
      'hpoint_device': 'device-cookie',
    });

    final reopened = HPointSession(HPointApi(origin: fixture.origin));
    addTearDown(reopened.dispose);
    await reopened.start();
    expect(reopened.signedIn, isFalse);
    expect(fixture.last('/api/guest').cookies, {
      'hpoint_device': 'device-cookie',
    });
  });

  test(
    'auth_required discards an invalid session and reloads guest data',
    () async {
      final fixture = await _Fixture.start();
      addTearDown(fixture.close);
      final session = HPointSession(HPointApi(origin: fixture.origin));
      addTearDown(session.dispose);

      expect(
        await session.authenticate({
          'email': 'person@example.test',
          'password': 'Example1',
        }, register: false),
        isTrue,
      );
      fixture.allowSync = false;

      final guestReloaded = Completer<void>();
      void waitForGuest() {
        if (!session.signedIn &&
            session.guest?['guest'] == true &&
            !guestReloaded.isCompleted) {
          guestReloaded.complete();
        }
      }

      session.addListener(waitForGuest);
      await session.refresh();
      await guestReloaded.future.timeout(const Duration(seconds: 3));
      session.removeListener(waitForGuest);

      expect(session.api.hasSession, isFalse);
      expect(session.user, isEmpty);
      expect(fixture.last('/api/guest').cookies, {
        'hpoint_device': 'device-cookie',
      });
      final reopened = HPointSession(HPointApi(origin: fixture.origin));
      addTearDown(reopened.dispose);
      await reopened.start();
      expect(reopened.signedIn, isFalse);
    },
  );
}

class _Fixture {
  _Fixture(this.server) {
    server.listen(_respond);
  }

  static Future<_Fixture> start() async =>
      _Fixture(await HttpServer.bind(InternetAddress.loopbackIPv4, 0));

  final HttpServer server;
  final requests = <_Request>[];
  bool allowSync = true;

  Uri get origin => Uri(scheme: 'http', host: '127.0.0.1', port: server.port);

  _Request last(String path) => requests.lastWhere((row) => row.path == path);

  Future<void> close() async {
    await server.close(force: true);
  }

  Future<void> _respond(HttpRequest request) async {
    final body = await utf8.decoder.bind(request).join();
    final row = _Request(request, body);
    requests.add(row);
    final response = request.response;
    response.headers.contentType = ContentType.json;
    final Json payload = {'ok': true};
    switch (row.path) {
      case '/api/guest':
        payload['guest'] = true;
      case '/api/auth/register':
        response.cookies.addAll([
          _cookie('hpoint_verification', 'pending-only'),
          _cookie('hpoint_session', '', maxAge: 0),
          _cookie('unrelated', 'should-not-return'),
        ]);
        payload['verification_required'] = true;
      case '/api/auth/email/verify':
      case '/api/auth/login':
        response.cookies.addAll([
          _cookie('hpoint_session', 'private-session'),
          _cookie('hpoint_device', 'device-cookie'),
          _cookie('hpoint_verification', '', maxAge: 0),
        ]);
      case '/api/auth/logout':
        response.cookies.addAll([
          _cookie('hpoint_session', '', maxAge: 0),
          _cookie('hpoint_verification', '', maxAge: 0),
        ]);
      case '/api/sync':
        if (allowSync && row.cookies['hpoint_session'] == 'private-session') {
          payload['user'] = {'id': -7, 'name': 'Тестовый участник'};
          payload['current_user_id'] = -7;
        } else {
          response.statusCode = HttpStatus.unauthorized;
          payload['ok'] = false;
          payload['error'] = 'auth_required';
        }
      default:
        response.statusCode = HttpStatus.notFound;
        payload['ok'] = false;
    }
    response.write(jsonEncode(payload));
    await response.close();
  }

  Cookie _cookie(String name, String value, {int maxAge = 600}) =>
      Cookie(name, value)
        ..maxAge = maxAge
        ..httpOnly = true
        ..path = '/';
}

class _Request {
  _Request(HttpRequest request, String body)
    : method = request.method,
      path = request.uri.path,
      origin = request.headers.value('Origin'),
      contentType = request.headers.contentType?.mimeType,
      contentLength = request.headers.contentLength,
      transferEncoding = request.headers.value(
        HttpHeaders.transferEncodingHeader,
      ),
      jsonBody = body.isEmpty ? null : jsonDecode(body),
      cookies = {
        for (final cookie in request.cookies) cookie.name: cookie.value,
      };

  final String method;
  final String path;
  final String? origin;
  final String? contentType;
  final int contentLength;
  final String? transferEncoding;
  final Object? jsonBody;
  final Map<String, String> cookies;
}
