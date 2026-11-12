import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:share_plus/share_plus.dart';

import 'api.dart';
import 'session.dart';

/// One shared dashboard for the selected organization and its native screens.
class WorkModel extends ChangeNotifier {
  WorkModel(this.session) : _accountId = session.data?['current_user_id'] {
    session.addListener(_sessionChanged);
  }

  final HPointSession session;
  HPointApi get api => session.api;
  Json data = const {};
  int? ownerId;
  String? error;
  bool loading = false;
  bool _disposed = false;
  int _loadVersion = 0;
  Object? _accountId;

  void _sessionChanged() {
    final account = session.data?['current_user_id'];
    if (account == _accountId) return;
    _accountId = account;
    _loadVersion++;
    data = const {};
    ownerId = null;
    error = null;
    loading = false;
    _notify();
    if (session.signedIn) unawaited(reload());
  }

  Future<void> selectOrganization(int id) async {
    if (id == ownerId) return;
    data = const {};
    ownerId = id;
    await reload();
  }

  Future<void> reload() async {
    if (_disposed || !session.signedIn) return;
    final version = ++_loadVersion;
    final selectedOwner = ownerId;
    loading = true;
    error = null;
    _notify();
    try {
      Json response;
      try {
        response = await api.get('/api/commercial', {
          if (selectedOwner != null) 'owner_id': '$selectedOwner',
        });
      } on ApiException catch (exception) {
        // An invitation or a departure can change membership on either client.
        if (selectedOwner == null ||
            (exception.statusCode != 400 && exception.statusCode != 403)) {
          rethrow;
        }
        response = await api.get('/api/commercial');
      }
      if (version != _loadVersion || _disposed) return;
      data = object(response['commercial']);
      ownerId =
          data['selected_owner_id'] as int? ??
          (selectedOwner == _accountId ? selectedOwner : null);
    } catch (exception) {
      if (version == _loadVersion && !_disposed) error = exception.toString();
    } finally {
      if (version == _loadVersion && !_disposed) {
        loading = false;
        _notify();
      }
    }
  }

  Future<Json> update(String path, [Json fields = const {}]) async {
    _requireSession();
    final account = _accountId;
    final previousOwner = ownerId;
    final requestedOwner = fields['owner_id'] ?? previousOwner;
    final result = await api.post(path, {
      ...fields,
      'owner_id': ?requestedOwner,
    });
    if (!_disposed && _accountId == account && ownerId == previousOwner) {
      if (path == '/api/commercial/profile' && requestedOwner is int) {
        ownerId = requestedOwner;
      }
      await reload();
    }
    return result;
  }

  Future<Json> read(String path, [Map<String, String> query = const {}]) {
    _requireSession();
    return api.get(path, _query(query));
  }

  Future<void> shareExport(
    String path,
    Map<String, String> query, {
    required String fileName,
    required String mimeType,
  }) async {
    _requireSession();
    final account = _accountId;
    final bytes = await api.getBytes(path, _query(query));
    if (_disposed || account != _accountId) return;
    final name = fileName.replaceAll(RegExp(r'[\\/:*?"<>|\x00-\x1f]'), '_');
    await SharePlus.instance.share(
      ShareParams(
        files: [XFile.fromData(bytes, mimeType: mimeType)],
        fileNameOverrides: [name.isEmpty ? 'hpoint-export' : name],
      ),
    );
  }

  Map<String, String> _query(Map<String, String> fields) => {
    if (ownerId != null) 'owner_id': '$ownerId',
    ...fields,
  };

  void _requireSession() {
    if (_disposed || !session.signedIn) {
      throw const ApiException('Войдите, чтобы открыть рабочий кабинет.', 401);
    }
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    session.removeListener(_sessionChanged);
    super.dispose();
  }
}
