part of 'work_team.dart';

String _inquiryStatus(Object? status) => switch (status) {
  'new' => 'Новое',
  'in_progress' => 'В работе',
  'accepted' => 'Запись подтверждена',
  'rejected' => 'Отклонено',
  'cancelled' => 'Отменено',
  _ => 'Без статуса',
};

String _inquiryPrice(Json item) =>
    '${integer(item['price_rub'])} ₽ тест. · ${integer(item['duration_minutes'])} мин';

class _WorkInquiries extends StatefulWidget {
  const _WorkInquiries({required this.model, required this.incoming});

  final WorkModel model;
  final bool incoming;

  @override
  State<_WorkInquiries> createState() => _WorkInquiriesState();
}

class _WorkInquiriesState extends State<_WorkInquiries> {
  List<Json> _items = const [];
  String? _error;
  String _filter = 'all';
  bool _loading = true;
  int _version = 0;
  int? _owner;
  Object? _account;

  WorkModel get _model => widget.model;
  String get _title => widget.incoming ? 'Входящие обращения' : 'Мои обращения';

  @override
  void initState() {
    super.initState();
    _owner = _model.ownerId;
    _account = _model.session.data?['current_user_id'];
    _model.addListener(_scopeChanged);
    _load();
  }

  @override
  void dispose() {
    _model.removeListener(_scopeChanged);
    super.dispose();
  }

  void _scopeChanged() {
    final account = _model.session.data?['current_user_id'];
    if ((!widget.incoming || _owner == _model.ownerId) && _account == account) {
      return;
    }
    setState(() {
      _owner = _model.ownerId;
      _account = account;
      _items = const [];
    });
    _load();
  }

  Future<void> _load() async {
    final version = ++_version;
    if (!_model.session.signedIn) {
      setState(() {
        _items = const [];
        _error = 'Войдите, чтобы просмотреть обращения.';
        _loading = false;
      });
      return;
    }
    setState(() {
      _error = null;
      _loading = true;
    });
    try {
      final response = widget.incoming
          ? await _model.read('/api/commercial/inquiries')
          : await _model.api.get('/api/work-inquiries/mine');
      if (mounted && version == _version) {
        setState(() => _items = rows(response['inquiries']));
      }
    } catch (error) {
      if (mounted && version == _version) setState(() => _error = '$error');
    } finally {
      if (mounted && version == _version) setState(() => _loading = false);
    }
  }

  Future<void> _open(Json inquiry) async {
    final id = _idOf(inquiry['id']);
    if (id == null) return;
    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (context) => _WorkInquiryDetails(
          model: _model,
          incoming: widget.incoming,
          id: id,
          owner: _owner,
        ),
      ),
    );
    if (mounted) await _load();
  }

  @override
  Widget build(BuildContext context) {
    final visible = _items.where((item) {
      final status = item['status'];
      final open = status == 'new' || status == 'in_progress';
      return switch (_filter) {
        'open' => open,
        'closed' => !open,
        _ => true,
      };
    }).toList();
    return Scaffold(
      appBar: AppBar(title: Text(_title)),
      body: _WorkContent(
        onRefresh: _load,
        children: [
          if (_loading) const LinearProgressIndicator(),
          if (_error case final error?) ...[
            _WorkNotice(error, icon: Icons.error_outline),
            TextButton(onPressed: _load, child: const Text('Повторить')),
          ],
          if (_items.isNotEmpty)
            Wrap(
              spacing: 8,
              children: [
                for (final (key, label) in [
                  ('all', 'Все'),
                  ('open', 'Открытые'),
                  ('closed', 'Завершённые'),
                ])
                  ChoiceChip(
                    label: Text(label),
                    selected: _filter == key,
                    onSelected: (_) => setState(() => _filter = key),
                  ),
              ],
            ),
          if (!_loading && _error == null && visible.isEmpty)
            _WorkNotice(
              _items.isEmpty
                  ? 'Обращений пока нет.'
                  : 'В этой группе пока пусто.',
            ),
          for (final item in visible)
            Card(
              child: ListTile(
                leading: const Icon(Icons.forum_outlined),
                title: Text(string(item['service_title'], 'Обращение')),
                subtitle: Text(
                  [
                    string(
                      item[widget.incoming
                          ? 'author_name'
                          : 'organization_title'],
                    ),
                    [
                      _inquiryStatus(item['status']),
                      if (_workDate(item['created_at']) case final date?)
                        _shortDate(context, date),
                    ].join(' · '),
                  ].where((part) => part.isNotEmpty).join('\n'),
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _open(item),
              ),
            ),
        ],
      ),
    );
  }
}

class _WorkInquiryDetails extends StatefulWidget {
  const _WorkInquiryDetails({
    required this.model,
    required this.incoming,
    required this.id,
    required this.owner,
  });

  final WorkModel model;
  final bool incoming;
  final int id;
  final int? owner;

  @override
  State<_WorkInquiryDetails> createState() => _WorkInquiryDetailsState();
}

class _WorkInquiryDetailsState extends State<_WorkInquiryDetails> {
  Json _item = const {};
  String? _error;
  bool _busy = false;
  final _photos = <String, Future<Uint8List>>{};
  late final _account = _model.session.data?['current_user_id'];

  WorkModel get _model => widget.model;

  bool get _canRead =>
      _model.session.signedIn &&
      _account == _model.session.data?['current_user_id'] &&
      (!widget.incoming || widget.owner == _model.ownerId);

  Json get _scope => {
    'inquiry_id': widget.id,
    if (widget.owner != null) 'owner_id': widget.owner,
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _run(Future<Json> Function() action) async {
    if (_busy || !_canRead) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final response = await action();
      if (mounted && _canRead) {
        setState(() {
          _item = object(
            response['inquiry'] ?? object(response['result'])['inquiry'],
          );
        });
      }
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _load() => _run(
    () => _model.api.get('/api/work-inquiries', {
      'id': '${widget.id}',
      if (widget.incoming && widget.owner != null)
        'owner_id': '${widget.owner}',
    }),
  );

  Future<void> _edit() async {
    var reply = string(_item['reply']);
    var status = string(_item['status'], 'new');
    var assignee = _idOf(_item['assignee_id']);
    final manage = _manage(_model);
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (context) => _Editor(
          title: 'Ответить на обращение',
          fields: [
            DropdownButtonFormField<String>(
              initialValue: status,
              decoration: const InputDecoration(labelText: 'Статус'),
              items: [
                for (final value in ['new', 'in_progress', 'rejected'])
                  DropdownMenuItem(
                    value: value,
                    child: Text(_inquiryStatus(value)),
                  ),
              ],
              onChanged: (value) {
                if (value != null) status = value;
              },
            ),
            _editText(
              'Ответ заказчику',
              reply,
              (value) => reply = value,
              limit: 4000,
              lines: 4,
            ),
            if (manage)
              _choosePerson(
                people: rows(_model.data['members']),
                value: assignee,
                changed: (value) => assignee = value,
              ),
          ],
          submit: () async {
            if (!_canRead) throw StateError('Откройте обращение ещё раз.');
            await _model.update('/api/commercial/inquiries/update', {
              ..._scope,
              'status': status,
              'reply': reply.trim(),
              if (manage) 'assignee_id': assignee,
            });
          },
        ),
      ),
    );
    if (saved == true && mounted) await _load();
  }

  Future<void> _convert() async {
    var name = string(_item['author_name']);
    var contact = string(_item['contact']);
    var title = string(_item['service_title']);
    var duration = string(_item['duration_minutes']?.toString());
    var price = string(_item['price_rub']?.toString());
    var assignee = _idOf(_item['assignee_id']);
    int? clientId;
    int? objectId;
    DateTime? starts;
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (context) => StatefulBuilder(
          builder: (context, setEditorState) => _Editor(
            title: 'Подтвердить запись',
            button: 'Создать запись',
            fields: [
              _editText(
                'Название',
                title,
                (value) => title = value,
                limit: 160,
                minLength: 1,
              ),
              _chooseRecord(
                'Клиент',
                'Создать нового',
                rows(_model.data['clients'])
                    .where((client) => _workFlag(client['active']))
                    .toList(),
                clientId,
                (value) => setEditorState(() => clientId = value),
                labelKey: 'name',
              ),
              if (clientId == null) ...[
                _editText(
                  'Имя клиента',
                  name,
                  (value) => name = value,
                  limit: 120,
                  minLength: 2,
                ),
                _editText(
                  'Контакт клиента',
                  contact,
                  (value) => contact = value,
                ),
              ],
              OutlinedButton.icon(
                onPressed: () async {
                  final value = await _pickMoment(context, starts);
                  if (value != null && context.mounted) {
                    setEditorState(() => starts = value);
                  }
                },
                icon: const Icon(Icons.event_outlined),
                label: Text(
                  starts == null
                      ? 'Дата и время'
                      : _dateTimeLabel(context, starts),
                ),
              ),
              _editText(
                'Длительность, мин',
                duration,
                (value) => duration = value,
                limit: 4,
                keyboard: TextInputType.number,
                validate: (value) => _validateInquiryNumber(value, 5, 1440),
              ),
              _editText(
                'Стоимость, тестовые ₽',
                price,
                (value) => price = value,
                limit: 7,
                keyboard: TextInputType.number,
                validate: (value) => _validateInquiryNumber(value, 0, 1000000),
              ),
              _choosePerson(
                people: rows(_model.data['members']),
                value: assignee,
                changed: (value) => assignee = value,
              ),
              _chooseRecord(
                'Объект',
                'Без объекта',
                rows(_model.data['objects']),
                objectId,
                (value) => objectId = value,
              ),
            ],
            submit: () async {
              if (!_canRead) throw StateError('Откройте обращение ещё раз.');
              final appointment = starts;
              if (appointment == null || !appointment.isAfter(DateTime.now())) {
                throw const FormatException(
                  'Выберите будущие дату и время записи.',
                );
              }
              await _model.update('/api/commercial/inquiries/convert', {
                ..._scope,
                'title': title.trim(),
                'starts_at': appointment.toUtc().toIso8601String(),
                'duration_minutes': int.parse(duration.trim()),
                'price_rub': int.parse(price.trim()),
                'assignee_id': assignee,
                'object_id': objectId,
                if (clientId == null) 'client_name': name.trim(),
                if (clientId == null) 'contact': contact.trim(),
                'client_id': ?clientId,
              });
            },
          ),
        ),
      ),
    );
    if (saved == true && mounted) await _load();
  }

  Future<void> _cancel() async {
    if (!await _confirm(context, 'Отменить обращение?', 'Отменить обращение') ||
        !mounted) {
      return;
    }
    await _run(
      () => _model.api.post('/api/work-inquiries/cancel', {'id': widget.id}),
    );
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _model,
    builder: (context, child) => Scaffold(
      appBar: AppBar(title: const Text('Обращение')),
      body: !_canRead
          ? const Center(child: Text('Обращение недоступно.'))
          : _WorkContent(
              onRefresh: _load,
              children: [
                if (_busy) const LinearProgressIndicator(),
                if (_error case final error?) ...[
                  _WorkNotice(error, icon: Icons.error_outline),
                  TextButton(onPressed: _load, child: const Text('Обновить')),
                ],
                if (_item.isNotEmpty) ...[
                  Text(
                    string(_item['service_title']),
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                  Text(
                    string(
                      _item[widget.incoming
                          ? 'author_name'
                          : 'organization_title'],
                    ),
                  ),
                  Text(_inquiryPrice(_item)),
                  _SectionTitle(_inquiryStatus(_item['status'])),
                  Text(string(_item['message'])),
                  for (final (key, label) in [
                    ('preferred_time', 'Удобное время'),
                    ('contact', 'Контакт заказчика'),
                    ('assignee_name', 'Ответственный'),
                    ('reply', 'Ответ организации'),
                  ])
                    if (string(_item[key]).isNotEmpty) ...[
                      _SectionTitle(label),
                      Text(string(_item[key])),
                    ],
                  if (object(_item['booking']) case final booking
                      when booking.isNotEmpty) ...[
                    const _SectionTitle('Запись'),
                    Text(string(booking['title'])),
                    Text(
                      _dateTimeLabel(context, _workDate(booking['starts_at'])),
                    ),
                    Text(_inquiryPrice(booking)),
                  ],
                  if (rows(_item['photos']).isNotEmpty)
                    const _SectionTitle('Фотографии'),
                  for (final photo in rows(_item['photos']))
                    if (string(photo['id']) case final id when id.isNotEmpty)
                      FutureBuilder<Uint8List>(
                        future: _photos.putIfAbsent(
                          id,
                          () => _model.api.getBytes(
                            '/api/work-inquiries/photo',
                            {'id': id},
                          ),
                        ),
                        builder: (context, snapshot) {
                          if (snapshot.hasError) {
                            return const _WorkNotice(
                              'Не удалось загрузить фото.',
                            );
                          }
                          final bytes = snapshot.data;
                          if (bytes == null) {
                            return const LinearProgressIndicator();
                          }
                          return Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: Image.memory(
                              bytes,
                              height: 220,
                              fit: BoxFit.contain,
                              semanticLabel: 'Фото обращения',
                            ),
                          );
                        },
                      ),
                  const SizedBox(height: 20),
                  if (_item['can_update'] == true)
                    OutlinedButton.icon(
                      onPressed: _busy ? null : _edit,
                      icon: const Icon(Icons.reply_outlined),
                      label: const Text('Ответить или изменить статус'),
                    ),
                  if (_item['can_convert'] == true)
                    FilledButton.icon(
                      onPressed: _busy ? null : _convert,
                      icon: const Icon(Icons.event_available_outlined),
                      label: const Text('Подтвердить запись'),
                    ),
                  if (_item['can_cancel'] == true)
                    OutlinedButton(
                      onPressed: _busy ? null : _cancel,
                      child: const Text('Отменить обращение'),
                    ),
                ],
              ],
            ),
    ),
  );
}

String? _validateInquiryNumber(String? text, int min, int max) {
  final value = int.tryParse((text ?? '').trim());
  return value == null || value < min || value > max
      ? 'Введите число от $min до $max'
      : null;
}

Future<void> openWorkService(
  BuildContext context,
  HPointSession session,
  int serviceId, {
  required VoidCallback onSignIn,
}) => Navigator.of(context).push<void>(
  MaterialPageRoute(
    builder: (context) => _WorkService(
      session: session,
      serviceId: serviceId,
      onSignIn: onSignIn,
    ),
  ),
);

class _WorkService extends StatefulWidget {
  const _WorkService({
    required this.session,
    required this.serviceId,
    required this.onSignIn,
  });

  final HPointSession session;
  final int serviceId;
  final VoidCallback onSignIn;

  @override
  State<_WorkService> createState() => _WorkServiceState();
}

class _WorkServiceState extends State<_WorkService> {
  Json _service = const {};
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (_loading) return;
    setState(() {
      _error = null;
      _loading = true;
    });
    try {
      final response = await widget.session.api.get(
        '/api/work-inquiries/service',
        {'id': '${widget.serviceId}'},
      );
      if (mounted) setState(() => _service = object(response['service']));
    } catch (error) {
      if (mounted) {
        setState(() {
          _service = const {};
          _error = '$error';
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _compose() async {
    final session = widget.session;
    if (!session.signedIn) {
      widget.onSignIn();
      return;
    }
    final account = session.data?['current_user_id'];
    final random = Random.secure();
    final key = List.generate(
      24,
      (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0'),
    ).join();
    var message = '';
    var contact = '';
    var preferred = '';
    var photos = <String>[];
    final sent = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (context) => _Editor(
          title: 'Обращение по услуге',
          button: 'Отправить обращение',
          fields: [
            Text(
              string(_service['title']),
              style: Theme.of(context).textTheme.titleLarge,
            ),
            _editText(
              'Что нужно сделать',
              message,
              (value) => message = value,
              minLength: 1,
              limit: 4000,
              lines: 4,
            ),
            _editText('Удобное время', preferred, (value) => preferred = value),
            _editText(
              'Как с вами связаться',
              contact,
              (value) => contact = value,
              minLength: 1,
            ),
            _InquiryAttachments(onChanged: (value) => photos = value),
          ],
          submit: () async {
            if (!session.signedIn ||
                session.data?['current_user_id'] != account) {
              throw StateError('Войдите и откройте форму ещё раз.');
            }
            await session.api.post('/api/work-inquiries', {
              'service_id': widget.serviceId,
              'request_key': key,
              'message': message.trim(),
              'preferred_time': preferred.trim(),
              'contact': contact.trim(),
              'photos': photos,
            });
          },
        ),
      ),
    );
    if (sent == true &&
        mounted &&
        session.data?['current_user_id'] == account) {
      _feedback(context, 'Обращение отправлено');
      await _openMyInquiries();
    }
  }

  Future<void> _openMyInquiries() async {
    final model = WorkModel(widget.session);
    try {
      await Navigator.of(context).push<void>(
        MaterialPageRoute(
          builder: (context) => _WorkInquiries(model: model, incoming: false),
        ),
      );
    } finally {
      model.dispose();
    }
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: widget.session,
    builder: (context, child) => Scaffold(
      appBar: AppBar(title: const Text('Услуга')),
      body: _WorkContent(
        onRefresh: _load,
        children: [
          if (_loading) const LinearProgressIndicator(),
          if (_error case final error?) ...[
            _WorkNotice(error, icon: Icons.error_outline),
            TextButton(onPressed: _load, child: const Text('Повторить')),
          ],
          if (_service.isNotEmpty) ...[
            Text(
              string(_service['title']),
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            Text(string(_service['organization_title'])),
            const SizedBox(height: 12),
            Text(
              _inquiryPrice(_service),
              style: Theme.of(context).textTheme.titleMedium,
            ),
            if (string(_service['description']) case final description
                when description.isNotEmpty) ...[
              const _SectionTitle('Об услуге'),
              Text(description),
            ],
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: _loading ? null : _compose,
              icon: const Icon(Icons.edit_outlined),
              label: Text(
                widget.session.signedIn
                    ? 'Отправить обращение'
                    : 'Войти, чтобы обратиться',
              ),
            ),
            if (widget.session.signedIn)
              TextButton(
                onPressed: _openMyInquiries,
                child: const Text('Мои обращения'),
              ),
          ],
        ],
      ),
    ),
  );
}

class _InquiryAttachments extends StatefulWidget {
  const _InquiryAttachments({required this.onChanged});

  final ValueChanged<List<String>> onChanged;

  @override
  State<_InquiryAttachments> createState() => _InquiryAttachmentsState();
}

class _InquiryAttachmentsState extends State<_InquiryAttachments> {
  final _photos = <(Uint8List, String)>[];
  bool _picking = false;
  String? _error;

  void _notify() => widget.onChanged([
    for (final (bytes, mime) in _photos)
      'data:$mime;base64,${base64Encode(bytes)}',
  ]);

  Future<void> _pick() async {
    if (_picking || _photos.length == 3) return;
    setState(() {
      _picking = true;
      _error = null;
    });
    try {
      final photo = await ImagePicker().pickImage(
        source: ImageSource.gallery,
        maxWidth: 1600,
        maxHeight: 1600,
        imageQuality: 86,
        requestFullMetadata: false,
      );
      if (photo == null || !mounted) return;
      if (await photo.length() > 3 * 1024 * 1024) {
        throw const FormatException('Фото должно быть не больше 3 МБ.');
      }
      final bytes = await photo.readAsBytes();
      final mime = _inquiryImageMime(bytes);
      if (mime == null) {
        throw const FormatException('Выберите JPEG, PNG или WebP.');
      }
      if (!mounted) return;
      setState(() => _photos.add((bytes, mime)));
      _notify();
    } catch (error) {
      if (mounted) {
        setState(
          () => _error = error is FormatException
              ? error.message
              : 'Не удалось открыть фото.',
        );
      }
    } finally {
      if (mounted) setState(() => _picking = false);
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      for (var i = 0; i < _photos.length; i++)
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: Image.memory(
            _photos[i].$1,
            width: 48,
            height: 48,
            fit: BoxFit.cover,
          ),
          title: Text('Фото ${i + 1}'),
          trailing: IconButton(
            tooltip: 'Убрать фото',
            onPressed: () {
              setState(() => _photos.removeAt(i));
              _notify();
            },
            icon: const Icon(Icons.close),
          ),
        ),
      if (_error case final error?)
        Text(
          error,
          style: TextStyle(color: Theme.of(context).colorScheme.error),
        ),
      OutlinedButton.icon(
        onPressed: _picking || _photos.length >= 3 ? null : _pick,
        icon: const Icon(Icons.add_photo_alternate_outlined),
        label: Text('Добавить фото (${_photos.length}/3)'),
      ),
    ],
  );
}

String? _inquiryImageMime(Uint8List bytes) {
  if (bytes.length < 12) return null;
  if (bytes[0] == 0xff && bytes[1] == 0xd8 && bytes[2] == 0xff) {
    return 'image/jpeg';
  }
  if (bytes[0] == 0x89 && String.fromCharCodes(bytes.sublist(1, 4)) == 'PNG') {
    return 'image/png';
  }
  if (String.fromCharCodes(bytes.sublist(0, 4)) == 'RIFF' &&
      String.fromCharCodes(bytes.sublist(8, 12)) == 'WEBP') {
    return 'image/webp';
  }
  return null;
}
