import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api.dart';

class HPointSession extends ChangeNotifier {
  HPointSession(this.api) {
    api.onExpired = _expire;
  }

  final HPointApi api;
  Json? data;
  Json? guest;
  bool starting = true;
  String? error;
  int _generation = 0;
  bool _disposed = false;

  Json get user => object(data?['user']);
  bool get signedIn => user.isNotEmpty;

  Future<void> start() async {
    try {
      await api.restore();
      await refresh();
    } catch (exception) {
      error = exception is ApiException
          ? exception.message
          : 'Не удалось открыть H-Point.';
    } finally {
      starting = false;
      _notify();
    }
  }

  Future<void> refresh() async {
    final generation = _generation;
    try {
      if (api.hasSession) {
        final next = await api.get('/api/sync');
        if (generation != _generation || !api.hasSession) return;
        data = next;
      } else {
        data = null;
        final next = await api.get('/api/guest');
        if (generation != _generation) return;
        guest = next;
      }
      error = null;
    } on ApiException catch (exception) {
      if (generation == _generation) error = exception.message;
      if (exception.code != 'auth_required') rethrow;
    } finally {
      _notify();
    }
  }

  Future<bool> authenticate(Json fields, {required bool register}) async {
    final result = await api.post(
      register ? '/api/auth/register' : '/api/auth/login',
      fields,
    );
    if (result['verification_required'] == true) return false;
    _generation++;
    await refresh();
    if (!signedIn) {
      throw const ApiException('Не удалось открыть аккаунт. Войдите ещё раз.');
    }
    return true;
  }

  Future<void> verifyEmail(String code) async {
    await api.post('/api/auth/email/verify', {'code': code});
    _generation++;
    await refresh();
    if (!signedIn) {
      throw const ApiException('Email подтверждён. Войдите в аккаунт ещё раз.');
    }
  }

  Future<void> signOut() async {
    _generation++;
    try {
      await api.post('/api/auth/logout');
    } finally {
      await api.forgetSession();
      data = null;
      _notify();
    }
    await refresh();
  }

  void _expire() {
    _generation++;
    data = null;
    _notify();
    unawaited(refresh().catchError((Object _) {}));
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    api.onExpired = null;
    api.close();
    super.dispose();
  }
}
