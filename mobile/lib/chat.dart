import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import 'api.dart';
import 'session.dart';

class ChatPage extends StatelessWidget {
  const ChatPage({
    super.key,
    required this.session,
    required this.onSignIn,
    this.requestId,
    this.chatId,
    this.active = true,
  });

  final HPointSession session;
  final VoidCallback onSignIn;
  final int? requestId;
  final int? chatId;
  final bool active;

  @override
  Widget build(BuildContext context) {
    final isThread = requestId != null || chatId != null;
    return AnimatedBuilder(
      animation: session,
      builder: (context, child) {
        if (!session.signedIn) {
          final prompt = Center(
            child: FilledButton.icon(
              onPressed: onSignIn,
              icon: const Icon(Icons.login),
              label: const Text('Войти для переписки'),
            ),
          );
          return isThread
              ? Scaffold(
                  appBar: AppBar(title: const Text('Чат')),
                  body: prompt,
                )
              : prompt;
        }
        final user = integer(session.data?['current_user_id']);
        if (isThread) {
          return _ThreadPage(
            key: ValueKey((user, requestId, chatId)),
            session: session,
            requestId: requestId,
            chatId: chatId,
            active: active,
          );
        }
        return _ChatList(
          key: ValueKey(user),
          session: session,
          onSignIn: onSignIn,
          active: active,
        );
      },
    );
  }
}

class _ChatList extends StatefulWidget {
  const _ChatList({
    super.key,
    required this.session,
    required this.onSignIn,
    required this.active,
  });

  final HPointSession session;
  final VoidCallback onSignIn;
  final bool active;

  @override
  State<_ChatList> createState() => _ChatListState();
}

class _ChatListState extends State<_ChatList> {
  Timer? _timer;
  List<Json>? _chats;
  String? _error;
  Object? _read;
  bool _includeArchived = false;

  @override
  void initState() {
    super.initState();
    if (widget.active) unawaited(_load());
    _timer = Timer.periodic(const Duration(seconds: 6), (_) {
      if (mounted &&
          widget.active &&
          (ModalRoute.of(context)?.isCurrent ?? true) &&
          WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed) {
        unawaited(_load(silent: true));
      }
    });
  }

  @override
  void didUpdateWidget(covariant _ChatList oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active && !oldWidget.active) unawaited(_load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (_read != null || !widget.session.signedIn) return;
    final read = Object();
    _read = read;
    try {
      final result = await widget.session.api.get('/api/chats', {
        if (_includeArchived) 'archived': '1',
      });
      if (!mounted || _read != read) return;
      setState(() {
        _chats = rows(result['chats']);
        _error = null;
      });
    } on Object catch (error) {
      if (!mounted || _read != read || (silent && _chats != null)) return;
      setState(() => _error = error.toString());
    } finally {
      if (_read == read) _read = null;
    }
  }

  Future<void> _open(Json row) async {
    final id = integer(row['chat_id'] ?? row['id']);
    if (id <= 0) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => ChatPage(
          session: widget.session,
          onSignIn: widget.onSignIn,
          chatId: id,
        ),
      ),
    );
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final chats = _chats;
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
        children: [
          SwitchListTile.adaptive(
            contentPadding: EdgeInsets.zero,
            title: const Text('Показывать архив'),
            value: _includeArchived,
            onChanged: (value) {
              setState(() {
                _includeArchived = value;
                _read = null;
                _chats = null;
                _error = null;
              });
              unawaited(_load());
            },
          ),
          if (_error != null)
            _Retry(message: _error!, retry: _load)
          else if (chats == null)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (chats.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 32, horizontal: 8),
              child: Text('Здесь появятся обсуждения по заявкам.'),
            )
          else
            for (final row in chats)
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  leading: CircleAvatar(
                    child: Icon(
                      row['archived'] == true
                          ? Icons.inventory_2_outlined
                          : Icons.chat_bubble_outline,
                    ),
                  ),
                  title: Text(string(row['what'], 'Заявка')),
                  subtitle: Text(
                    [
                      string(row['other_name'], 'Участник'),
                      if (integer(row['last_message_id']) > 0)
                        string(row['last_message'], 'Фото').trim(),
                    ].where((text) => text.isNotEmpty).join(' · '),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _open(row),
                ),
              ),
        ],
      ),
    );
  }
}

class _ThreadPage extends StatefulWidget {
  const _ThreadPage({
    super.key,
    required this.session,
    this.requestId,
    this.chatId,
    required this.active,
  });

  final HPointSession session;
  final int? requestId;
  final int? chatId;
  final bool active;

  @override
  State<_ThreadPage> createState() => _ThreadPageState();
}

enum _ChatAction { select, finish, cancel, withdraw, decline, archive, restore }

class _ThreadPageState extends State<_ThreadPage> {
  final _draft = TextEditingController();
  final _scroll = ScrollController();
  final _picker = ImagePicker();
  final _photos = <_PhotoDraft>[];
  Timer? _timer;
  Json? _chat;
  String? _error;
  Object? _read;
  bool _busy = false;
  bool _picking = false;

  @override
  void initState() {
    super.initState();
    if (widget.active) unawaited(_load());
    _timer = Timer.periodic(const Duration(seconds: 3), (_) {
      if (mounted &&
          widget.active &&
          (ModalRoute.of(context)?.isCurrent ?? true) &&
          WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed) {
        unawaited(_load(silent: true));
      }
    });
  }

  @override
  void didUpdateWidget(covariant _ThreadPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active && !oldWidget.active) unawaited(_load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _draft.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (_read != null || _busy || !widget.session.signedIn) return;
    final read = Object();
    _read = read;
    try {
      final chatId = _chat?['id'] ?? widget.chatId;
      final result = await widget.session.api.get('/api/chats', {
        if (chatId != null) 'chat_id': '$chatId',
        if (widget.requestId != null) 'request_id': '${widget.requestId}',
      });
      if (!mounted || _read != read) return;
      final chats = rows(result['chats']);
      setState(() {
        _chat = chats.isEmpty ? null : chats.first;
        _error = chats.isEmpty ? 'Обсуждение пока недоступно.' : null;
      });
    } on Object catch (error) {
      if (!mounted || _read != read || (silent && _chat != null)) return;
      setState(() => _error = error.toString());
    } finally {
      if (_read == read) _read = null;
    }
  }

  void _notice(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _pick() async {
    if (_busy || _picking || _photos.length >= 3) return;
    setState(() => _picking = true);
    try {
      final image = await _picker.pickImage(
        source: ImageSource.gallery,
        maxWidth: 1600,
        maxHeight: 1600,
        imageQuality: 80,
        requestFullMetadata: false,
      );
      if (image == null) return;
      if (await image.length() > 3 * 1024 * 1024) {
        throw const FormatException('Фото должно быть не больше 3 МБ.');
      }
      final bytes = await image.readAsBytes();
      final mime = _mime(bytes);
      if (mime == null) {
        throw const FormatException('Поддерживаются фото JPEG, PNG и WebP.');
      }
      if (mounted) setState(() => _photos.add(_PhotoDraft(bytes, mime)));
    } on FormatException catch (error) {
      _notice(error.message);
    } on Object {
      _notice('Не удалось открыть фото. Попробуйте ещё раз.');
    } finally {
      if (mounted) setState(() => _picking = false);
    }
  }

  Future<void> _send() async {
    final chat = _chat;
    final text = _draft.text.trim();
    if (_busy ||
        _picking ||
        chat?['can_send'] != true ||
        (text.isEmpty && _photos.isEmpty)) {
      return;
    }
    _read = null;
    setState(() => _busy = true);
    try {
      final result = await widget.session.api.post('/api/chats/send', {
        'chat_id': chat!['id'],
        'text': text,
        'photos': [for (final photo in _photos) photo.dataUrl],
      });
      if (!mounted) return;
      final updated = object(result['chat']);
      setState(() {
        if (updated.isNotEmpty) _chat = updated;
        _draft.clear();
        _photos.clear();
      });
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && _scroll.hasClients) {
          _scroll.jumpTo(_scroll.position.minScrollExtent);
        }
      });
    } on Object catch (error) {
      _notice(error.toString());
    } finally {
      if (mounted) {
        setState(() => _busy = false);
        unawaited(_load(silent: true));
      }
    }
  }

  String _actionTitle(_ChatAction action) => switch (action) {
    _ChatAction.select => 'Выбрать исполнителя',
    _ChatAction.finish => 'Завершить помощь',
    _ChatAction.cancel => 'Отменить заявку',
    _ChatAction.withdraw => 'Отозвать отклик',
    _ChatAction.decline => 'Отклонить приглашение',
    _ChatAction.archive => 'Убрать в архив',
    _ChatAction.restore => 'Вернуть из архива',
  };

  Future<void> _act(_ChatAction action) async {
    final chat = _chat;
    if (_busy || chat == null) return;
    final title = _actionTitle(action);
    if (action != _ChatAction.archive && action != _ChatAction.restore) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('$title?'),
          content: Text(switch (action) {
            _ChatAction.select => 'Заявка перейдёт в работу с этим участником.',
            _ChatAction.finish =>
              integer(chat['reward_rub']) > 0
                  ? 'Подтвердите, что помощь оказана. Вознаграждение будет перечислено из тестового резерва.'
                  : 'Подтвердите, что помощь оказана полностью.',
            _ChatAction.cancel => 'Обсуждения по заявке будут закрыты.',
            _ => 'История переписки сохранится.',
          }),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Назад'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Подтвердить'),
            ),
          ],
        ),
      );
      if (confirmed != true || !mounted || _busy) return;
    }
    final request = <String, dynamic>{'request_id': chat['request_id']};
    final response = <String, dynamic>{
      ...request,
      'helper_id': chat['candidate_id'],
      'application_token': chat['application_token'],
    };
    final (path, body) = switch (action) {
      _ChatAction.select => ('/api/requests/response/accept', response),
      _ChatAction.finish => ('/api/requests/finish', request),
      _ChatAction.cancel => ('/api/requests/cancel', request),
      _ChatAction.withdraw => ('/api/requests/response/cancel', response),
      _ChatAction.decline => (
        '/api/helper/offers/respond',
        <String, dynamic>{
          ...request,
          'offer_token': chat['application_token'],
          'accept': false,
        },
      ),
      _ChatAction.archive => (
        '/api/chats/archive',
        <String, dynamic>{'chat_id': chat['id']},
      ),
      _ChatAction.restore => (
        '/api/chats/restore',
        <String, dynamic>{'chat_id': chat['id']},
      ),
    };
    _read = null;
    setState(() => _busy = true);
    try {
      await widget.session.api.post(path, body);
      if (!mounted) return;
      if (action == _ChatAction.archive && Navigator.of(context).canPop()) {
        Navigator.of(context).pop();
        return;
      }
      if (action != _ChatAction.archive && action != _ChatAction.restore) {
        unawaited(_refreshSession());
      }
    } on Object catch (error) {
      _notice(error.toString());
    } finally {
      if (mounted) {
        setState(() => _busy = false);
        unawaited(_load());
      }
    }
  }

  Future<void> _refreshSession() async {
    try {
      await widget.session.refresh();
    } on Exception {
      // The action already succeeded. Its result is shown by the chat refresh.
    }
  }

  @override
  Widget build(BuildContext context) {
    final chat = _chat;
    return Scaffold(
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(string(chat?['what'], 'Чат'), overflow: TextOverflow.ellipsis),
            if (chat != null)
              Text(
                string(chat['other_name'], 'Участник'),
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.bodySmall,
              ),
          ],
        ),
        actions: [if (chat != null) _menu(chat)],
      ),
      body: SafeArea(
        top: false,
        child: chat == null
            ? Center(
                child: _error == null
                    ? const CircularProgressIndicator()
                    : _Retry(message: _error!, retry: _load),
              )
            : Column(
                children: [
                  if (_error != null) _Retry(message: _error!, retry: _load),
                  if (chat['can_select'] == true ||
                      chat['can_complete'] == true)
                    Align(
                      alignment: Alignment.centerRight,
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(16, 4, 16, 4),
                        child: FilledButton.tonal(
                          onPressed: _busy
                              ? null
                              : () => _act(
                                  chat['can_select'] == true
                                      ? _ChatAction.select
                                      : _ChatAction.finish,
                                ),
                          child: Text(
                            chat['can_select'] == true
                                ? 'Выбрать исполнителя'
                                : 'Завершить помощь',
                          ),
                        ),
                      ),
                    ),
                  Expanded(child: _messages(chat)),
                  if (chat['can_send'] == true)
                    _composer()
                  else
                    const Padding(
                      padding: EdgeInsets.all(16),
                      child: Text(
                        'Обсуждение закрыто. История переписки сохранена.',
                      ),
                    ),
                ],
              ),
      ),
    );
  }

  Widget _menu(Json chat) {
    final choices = [
      if (chat['can_cancel'] == true) _ChatAction.cancel,
      if (chat['can_withdraw'] == true) _ChatAction.withdraw,
      if (chat['can_decline'] == true) _ChatAction.decline,
      chat['archived'] == true ? _ChatAction.restore : _ChatAction.archive,
    ];
    return PopupMenuButton<_ChatAction>(
      enabled: !_busy,
      tooltip: 'Действия с чатом',
      onSelected: _act,
      itemBuilder: (_) => [
        for (final action in choices)
          PopupMenuItem(value: action, child: Text(_actionTitle(action))),
      ],
    );
  }

  Widget _messages(Json chat) {
    final messages = rows(chat['messages']);
    if (messages.isEmpty) {
      return const Center(child: Text('Начните с сообщения.'));
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final colors = Theme.of(context).colorScheme;
        return ListView.builder(
          controller: _scroll,
          reverse: true,
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
          itemCount: messages.length,
          findChildIndexCallback: (key) {
            if (key is! ValueKey) return null;
            final index = messages.indexWhere((row) => row['id'] == key.value);
            return index == -1 ? null : messages.length - 1 - index;
          },
          itemBuilder: (context, index) {
            final message = messages[messages.length - 1 - index];
            final mine = message['mine'] == true;
            final text = string(message['text']);
            final time = _time(string(message['created_at']));
            return Align(
              key: ValueKey(message['id']),
              alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
              child: Container(
                constraints: BoxConstraints(
                  maxWidth: constraints.maxWidth * .82,
                ),
                margin: const EdgeInsets.symmetric(vertical: 4),
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 8,
                ),
                decoration: BoxDecoration(
                  color: mine
                      ? colors.primaryContainer
                      : colors.surfaceContainerHigh,
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (text.isNotEmpty) SelectableText(text),
                    for (final photo in rows(message['photos']))
                      _PrivatePhoto(
                        key: ValueKey(photo['id']),
                        session: widget.session,
                        source: string(photo['url']),
                      ),
                    if (time.isNotEmpty)
                      Text(time, style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  Widget _composer() => Padding(
    padding: const EdgeInsets.fromLTRB(8, 8, 8, 8),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_photos.isNotEmpty)
          Wrap(
            spacing: 8,
            children: [
              for (final photo in _photos)
                InputChip(
                  avatar: ClipOval(
                    child: Image.memory(
                      photo.bytes,
                      width: 24,
                      height: 24,
                      fit: BoxFit.cover,
                      cacheWidth: 64,
                    ),
                  ),
                  label: const Text('Фото'),
                  onDeleted: _busy
                      ? null
                      : () => setState(() => _photos.remove(photo)),
                ),
            ],
          ),
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            IconButton(
              tooltip: 'Прикрепить фото',
              icon: const Icon(Icons.add_photo_alternate_outlined),
              onPressed: _busy || _picking || _photos.length >= 3
                  ? null
                  : _pick,
            ),
            Expanded(
              child: TextField(
                controller: _draft,
                enabled: !_busy,
                minLines: 1,
                maxLines: 4,
                maxLength: 1000,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => unawaited(_send()),
                textCapitalization: TextCapitalization.sentences,
                decoration: const InputDecoration(
                  hintText: 'Сообщение',
                  counterText: '',
                ),
              ),
            ),
            ListenableBuilder(
              listenable: _draft,
              builder: (context, child) => IconButton.filled(
                tooltip: 'Отправить',
                onPressed:
                    _busy ||
                        _picking ||
                        (_draft.text.trim().isEmpty && _photos.isEmpty)
                    ? null
                    : _send,
                icon: const Icon(Icons.send_rounded),
              ),
            ),
          ],
        ),
      ],
    ),
  );
}

class _Retry extends StatelessWidget {
  const _Retry({required this.message, required this.retry});

  final String message;
  final VoidCallback retry;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(16),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(message),
        TextButton(onPressed: retry, child: const Text('Повторить')),
      ],
    ),
  );
}

class _PrivatePhoto extends StatefulWidget {
  const _PrivatePhoto({super.key, required this.session, required this.source});

  final HPointSession session;
  final String source;

  @override
  State<_PrivatePhoto> createState() => _PrivatePhotoState();
}

class _PrivatePhotoState extends State<_PrivatePhoto> {
  late Future<Uint8List> _photo = _download();

  Future<Uint8List> _download() async {
    final uri = Uri.tryParse(widget.source);
    final id = uri?.queryParameters['id'] ?? '';
    if (uri == null ||
        uri.hasAuthority ||
        uri.hasScheme ||
        uri.path != '/api/photos' ||
        !RegExp(r'^[0-9a-f]{32}$').hasMatch(id)) {
      throw const FormatException('Некорректная ссылка на фото.');
    }
    return widget.session.api.getBytes('/api/photos', {'id': id});
  }

  @override
  void didUpdateWidget(covariant _PrivatePhoto oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.source != widget.source ||
        oldWidget.session != widget.session) {
      _photo = _download();
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = widget.session;
    final owner = integer(session.data?['current_user_id']);
    return FutureBuilder<Uint8List>(
      future: _photo,
      builder: (context, snapshot) {
        final bytes = snapshot.data;
        if (bytes == null) {
          return Text(
            snapshot.hasError ? 'Фото недоступно' : 'Загружаем фото…',
          );
        }
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: InkWell(
            onTap: () => showDialog<void>(
              context: context,
              builder: (context) => ListenableBuilder(
                listenable: session,
                builder: (context, child) => Dialog(
                  child:
                      session.signedIn &&
                          integer(session.data?['current_user_id']) == owner
                      ? InteractiveViewer(
                          child: Image.memory(bytes, fit: BoxFit.contain),
                        )
                      : const Padding(
                          padding: EdgeInsets.all(16),
                          child: Text('Войдите, чтобы посмотреть фото.'),
                        ),
                ),
              ),
            ),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(12),
              child: Image.memory(
                bytes,
                fit: BoxFit.contain,
                height: 150,
                cacheWidth: 600,
                semanticLabel: 'Прикреплённое фото',
              ),
            ),
          ),
        );
      },
    );
  }
}

class _PhotoDraft {
  const _PhotoDraft(this.bytes, this.mime);

  final Uint8List bytes;
  final String mime;

  String get dataUrl => 'data:$mime;base64,${base64Encode(bytes)}';
}

String? _mime(Uint8List bytes) {
  bool has(List<int> signature, [int offset = 0]) {
    if (bytes.length < offset + signature.length) return false;
    for (var index = 0; index < signature.length; index++) {
      if (bytes[offset + index] != signature[index]) return false;
    }
    return true;
  }

  if (has([0xff, 0xd8, 0xff])) return 'image/jpeg';
  if (has([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) return 'image/png';
  if (has([0x52, 0x49, 0x46, 0x46]) && has([0x57, 0x45, 0x42, 0x50], 8)) {
    return 'image/webp';
  }
  return null;
}

String _time(String value) {
  if (value.isEmpty) return '';
  final hasZone = RegExp(r'(?:[zZ]|[+-]\d{2}(?::?\d{2})?)$').hasMatch(value);
  final timestamp = DateTime.tryParse(hasZone ? value : '${value}Z');
  if (timestamp == null) return '';
  final local = timestamp.toLocal();
  return '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
}
