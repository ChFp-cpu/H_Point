part of 'help.dart';

Future<bool?> openHelpRequestForm(
  BuildContext context,
  HPointSession session,
) => Navigator.of(
  context,
).push<bool>(MaterialPageRoute(builder: (_) => _RequestForm(session: session)));

class _RequestPhoto {
  const _RequestPhoto(this.bytes, this.mime);
  final Uint8List bytes;
  final String mime;
  String get encoded => 'data:$mime;base64,${base64Encode(bytes)}';
}

String? _imageMime(Uint8List bytes) {
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

class _RequestForm extends StatefulWidget {
  const _RequestForm({required this.session});
  final HPointSession session;

  @override
  State<_RequestForm> createState() => _RequestFormState();
}

class _RequestFormState extends State<_RequestForm> {
  final _form = GlobalKey<FormState>();
  final _title = TextEditingController();
  final _place = TextEditingController();
  final _time = TextEditingController();
  final _details = TextEditingController();
  final _reward = TextEditingController();
  final _photos = <_RequestPhoto>[];
  String? _category;
  String _urgency = 'В течение дня';
  String _checkedPlace = '';
  Json _point = {};
  DateTime? _schedule;
  int _expiresHours = 48;
  bool _busy = false;
  bool _geocoding = false;
  bool _picking = false;
  bool _paid = false;
  String? _error;
  int? _createdId;
  Json _quote = {};

  HPointSession get session => widget.session;

  @override
  void initState() {
    super.initState();
    final user = object(session.data?['user']);
    _place.text = string(user['saved_location']);
    if (_place.text.isNotEmpty && user['lat'] is num && user['lon'] is num) {
      _checkedPlace = _place.text.trim();
      _point = {'lat': user['lat'], 'lon': user['lon']};
    }
  }

  @override
  void dispose() {
    for (final field in [_title, _place, _time, _details, _reward]) {
      field.dispose();
    }
    super.dispose();
  }

  Future<void> _findPoint() async {
    final query = _place.text.trim();
    if (query.length < 4 || query.length > 180) {
      setState(
        () => _error = 'Для поиска точки укажите адрес от 4 до 180 символов.',
      );
      return;
    }
    setState(() {
      _geocoding = true;
      _error = null;
    });
    try {
      final result = await session.api.get('/api/geocode', {'q': query});
      if (!mounted || _place.text.trim() != query) return;
      final point = object(result['point']);
      if (point['lat'] is! num || point['lon'] is! num) {
        throw const FormatException('Не удалось определить точку.');
      }
      setState(() {
        _point = point;
        _checkedPlace = query;
      });
    } catch (error) {
      if (mounted) {
        setState(
          () => _error =
              'Точка не найдена. ${error.toString()} Можно продолжить с указанным местом.',
        );
      }
    } finally {
      if (mounted) setState(() => _geocoding = false);
    }
  }

  Future<void> _pickPhoto() async {
    if (_photos.length >= 3 || _picking) return;
    setState(() {
      _picking = true;
      _error = null;
    });
    try {
      final file = await ImagePicker().pickImage(
        source: ImageSource.gallery,
        maxWidth: 1600,
        maxHeight: 1600,
        imageQuality: 86,
        requestFullMetadata: false,
      );
      if (file == null || !mounted) return;
      if (await file.length() > 3 * 1024 * 1024) {
        throw const FormatException('Фото должно быть не больше 3 МБ.');
      }
      final bytes = await file.readAsBytes();
      final mime = _imageMime(bytes);
      if (mime == null) {
        throw const FormatException('Выберите фото JPEG, PNG или WebP.');
      }
      if (mounted) setState(() => _photos.add(_RequestPhoto(bytes, mime)));
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

  Future<void> _pickSchedule() async {
    final now = DateTime.now();
    final date = await showDatePicker(
      context: context,
      firstDate: DateUtils.dateOnly(now),
      lastDate: now.add(const Duration(days: 365)),
      initialDate: _schedule ?? now,
    );
    if (date == null || !mounted) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(_schedule ?? now),
    );
    if (time == null || !mounted) return;
    final picked = DateTime(
      date.year,
      date.month,
      date.day,
      time.hour,
      time.minute,
    );
    if (!picked.isAfter(DateTime.now())) {
      setState(() => _error = 'Укажите время в будущем.');
      return;
    }
    final locale = MaterialLocalizations.of(context);
    setState(() {
      _error = null;
      _schedule = picked;
      _time.text =
          '${locale.formatShortDate(picked)}, ${locale.formatTimeOfDay(time, alwaysUse24HourFormat: true)}';
    });
  }

  Future<void> _submit() async {
    if (_busy || _createdId != null || _form.currentState?.validate() != true) {
      return;
    }
    FocusScope.of(context).unfocus();
    final reward = _paid ? int.parse(_reward.text.trim()) : 0;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final payload = <String, dynamic>{
        'what': _title.text.trim(),
        'place': _place.text.trim(),
        'time_needed': _time.text.trim(),
        'urgency': _urgency,
        'details': _details.text.trim(),
        'category': _category,
        'expires_in_hours': _expiresHours,
        'reward_rub': reward,
        if (_schedule != null)
          'scheduled_at': _schedule!.toUtc().toIso8601String(),
        if (_checkedPlace == _place.text.trim() &&
            _point['lat'] is num &&
            _point['lon'] is num) ...{
          'lat': _point['lat'],
          'lon': _point['lon'],
        },
        if (_photos.isNotEmpty)
          'photos': _photos.map((photo) => photo.encoded).toList(),
      };
      if (reward > 0) {
        final response = await session.api.get('/api/requests/quote', {
          'reward_rub': '$reward',
        });
        final quote = object(response['quote']);
        if (!mounted) return;
        final confirm = await _confirmHelp(
          context,
          'Проверить сумму',
          'Помощнику ${integer(quote['helper_rub'])} тестовых ₽, сбор ${integer(quote['commission_rub'])} тестовых ₽. '
              'В резерв потребуется ${integer(quote['total_rub'])} тестовых ₽.',
          'Создать заявку',
        );
        if (!confirm || !mounted) return;
        payload['pricing_version'] = quote['version'];
        payload['expected_total_rub'] = quote['total_rub'];
      }
      final result = await session.api.post('/api/requests', payload);
      if (!mounted) return;
      final id = integer(result['request_id']);
      if (id <= 0) {
        throw const FormatException(
          'Сервер не вернул заявку. Обновите список перед повторной публикацией.',
        );
      }
      setState(() {
        _createdId = id;
        _quote = object(result['quote']);
      });
      if (reward == 0) _exit('Заявка опубликована');
    } catch (error) {
      if (mounted) {
        setState(
          () => _error = error is FormatException
              ? error.message
              : error.toString(),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _reserve() async {
    if (_busy || _createdId == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await session.api.post('/api/requests/reward/reserve', {
        'request_id': _createdId,
        'amount_rub': integer(_quote['reward_rub']),
      });
      if (mounted) _exit('Резерв создан. Заявка опубликована');
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _exit(String message) {
    _helpToast(context, message);
    Navigator.of(context).pop(true);
  }

  String? _required(String? value) =>
      value?.trim().isNotEmpty == true ? null : 'Заполните поле';

  Widget _field(
    TextEditingController controller,
    String label, {
    int lines = 1,
    int max = 500,
    ValueChanged<String>? onChanged,
  }) => TextFormField(
    controller: controller,
    enabled: !_busy,
    maxLength: max,
    minLines: lines,
    maxLines: lines + (lines > 1 ? 2 : 0),
    textCapitalization: TextCapitalization.sentences,
    validator: _required,
    onChanged: onChanged,
    decoration: InputDecoration(labelText: label, counterText: ''),
  );

  @override
  Widget build(BuildContext context) {
    final categories = _helpCategories(session);
    final pending = _createdId != null;
    return PopScope(
      canPop: !_busy && !pending,
      child: Scaffold(
        appBar: AppBar(
          title: Text(pending ? 'Резерв вознаграждения' : 'Новая заявка'),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            tooltip: 'Назад',
            onPressed: _busy ? null : () => Navigator.of(context).pop(pending),
          ),
        ),
        body: SafeArea(
          top: false,
          child: Form(
            key: _form,
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                if (pending) ...[
                  const _HelpNotice(
                    message: 'Создайте резерв в течение 5 минут. После этого заявка появится в поиске. Без резерва она отменится автоматически.',
                  ),
                  const SizedBox(height: 12),
                  _HelpNotice(
                    message:
                        'К резерву ${integer(_quote['total_rub'])} тестовых ₽',
                  ),
                ] else ...[
                  _field(_title, 'Что нужно сделать?'),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: categories.containsKey(_category)
                        ? _category
                        : null,
                    isExpanded: true,
                    items: [
                      for (final category in categories.entries)
                        DropdownMenuItem(
                          value: category.key,
                          child: Text(
                            category.value,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                    ],
                    onChanged: _busy
                        ? null
                        : (value) => setState(() => _category = value),
                    validator: (value) =>
                        value == null ? 'Выберите сферу' : null,
                    decoration: const InputDecoration(
                      labelText: 'Сфера помощи',
                    ),
                  ),
                  const SizedBox(height: 12),
                  _field(
                    _place,
                    'Город, район или адрес',
                    max: 180,
                    onChanged: (_) => setState(() {}),
                  ),
                  Row(
                    children: [
                      Flexible(
                        child: TextButton.icon(
                          onPressed: _busy || _geocoding ? null : _findPoint,
                          icon: Icon(
                            _checkedPlace == _place.text.trim() &&
                                    _point.isNotEmpty
                                ? Icons.check_circle_outline
                                : Icons.place_outlined,
                          ),
                          label: Text(
                            _geocoding
                                ? 'Ищем точку…'
                                : _checkedPlace == _place.text.trim() &&
                                      _point.isNotEmpty
                                ? 'Точка найдена'
                                : 'Уточнить точку для подбора',
                          ),
                        ),
                      ),
                    ],
                  ),
                  const Text('Точное место увидит только выбранный помощник.'),
                  const SizedBox(height: 12),
                  _field(
                    _time,
                    'Когда нужна помощь?',
                    onChanged: (_) {
                      if (_schedule != null) setState(() => _schedule = null);
                    },
                  ),
                  TextButton.icon(
                    onPressed: _busy ? null : _pickSchedule,
                    icon: const Icon(Icons.event_outlined),
                    label: const Text('Выбрать дату и время'),
                  ),
                  DropdownButtonFormField<String>(
                    initialValue: _urgency,
                    items: const ['Не срочно', 'В течение дня', 'Срочно']
                        .map(
                          (label) => DropdownMenuItem(
                            value: label,
                            child: Text(label),
                          ),
                        )
                        .toList(),
                    onChanged: _busy
                        ? null
                        : (value) => setState(
                            () => _urgency = value ?? 'В течение дня',
                          ),
                    decoration: const InputDecoration(labelText: 'Срочность'),
                  ),
                  const SizedBox(height: 12),
                  _field(_details, 'Подробности задачи', lines: 3),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<int>(
                    initialValue: _expiresHours,
                    items:
                        const {
                              1: '1 час',
                              6: '6 часов',
                              24: '1 день',
                              48: '2 дня',
                              168: '7 дней',
                            }.entries
                            .map(
                              (value) => DropdownMenuItem(
                                value: value.key,
                                child: Text(value.value),
                              ),
                            )
                            .toList(),
                    onChanged: _busy
                        ? null
                        : (value) =>
                              setState(() => _expiresHours = value ?? 48),
                    decoration: const InputDecoration(
                      labelText: 'Срок публикации',
                    ),
                  ),
                  const SizedBox(height: 12),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    value: _paid,
                    onChanged: _busy
                        ? null
                        : (value) => setState(() => _paid = value),
                    title: const Text('Вознаграждение'),
                    subtitle: const Text('Из тестового кошелька H-Point'),
                  ),
                  if (_paid)
                    TextFormField(
                      controller: _reward,
                      enabled: !_busy,
                      keyboardType: TextInputType.number,
                      inputFormatters: [
                        FilteringTextInputFormatter.digitsOnly,
                        LengthLimitingTextInputFormatter(6),
                      ],
                      decoration: const InputDecoration(
                        labelText: 'Сумма помощнику, тестовые ₽',
                      ),
                      validator: (value) {
                        final amount = int.tryParse(value ?? '');
                        return amount == null || amount < 1 || amount > 100000
                            ? 'Укажите от 1 до 100 000 ₽'
                            : null;
                      },
                    ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      for (var index = 0; index < _photos.length; index++)
                        SizedBox(
                          width: 80,
                          height: 80,
                          child: Stack(
                            fit: StackFit.expand,
                            children: [
                              ClipRRect(
                                borderRadius: BorderRadius.circular(12),
                                child: Image.memory(
                                  _photos[index].bytes,
                                  fit: BoxFit.cover,
                                ),
                              ),
                              Positioned(
                                top: 0,
                                right: 0,
                                child: IconButton.filledTonal(
                                  iconSize: 16,
                                  tooltip: 'Удалить фото',
                                  onPressed: _busy
                                      ? null
                                      : () => setState(
                                          () => _photos.removeAt(index),
                                        ),
                                  icon: const Icon(Icons.close),
                                ),
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: OutlinedButton.icon(
                      onPressed: _busy || _picking || _photos.length >= 3
                          ? null
                          : _pickPhoto,
                      icon: const Icon(Icons.add_a_photo_outlined),
                      label: Text('Добавить фото · ${_photos.length}/3'),
                    ),
                  ),
                ],
                if (_error != null)
                  _HelpNotice(
                    message: _error!,
                    icon: Icons.error_outline_rounded,
                  ),
                const SizedBox(height: 12),
                FilledButton.icon(
                  onPressed: _busy || _picking || _geocoding
                      ? null
                      : pending
                      ? _reserve
                      : _submit,
                  icon: Icon(
                    pending
                        ? Icons.account_balance_wallet_outlined
                        : Icons.send_outlined,
                  ),
                  label: Text(
                    _busy
                        ? 'Подождите…'
                        : pending
                        ? 'Создать резерв'
                        : 'Опубликовать',
                  ),
                ),
                if (pending)
                  TextButton(
                    onPressed: _busy
                        ? null
                        : () => Navigator.pop(context, true),
                    child: const Text('Перейти к моим заявкам'),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _RequestDetail extends StatefulWidget {
  const _RequestDetail({
    required this.session,
    required this.request,
    required this.requestId,
    required this.owner,
    required this.participant,
    required this.invitation,
  });

  final HPointSession session;
  final Json request;
  final int requestId;
  final bool owner;
  final bool participant;
  final bool invitation;

  @override
  State<_RequestDetail> createState() => _RequestDetailState();
}

class _RequestDetailState extends State<_RequestDetail> {
  late Json _request;
  bool _busy = false;
  String? _error;

  HPointSession get session => widget.session;
  int get id => widget.requestId;

  @override
  void initState() {
    super.initState();
    _request = Map.of(widget.request);
  }

  void _chat([int? chatId]) =>
      Navigator.of(context).pop(_HelpResult(openChat: true, chatId: chatId));

  Future<void> _mutation(
    String path, {
    Json extra = const {},
    void Function(Json)? success,
  }) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final result = await session.api.post(path, {'request_id': id, ...extra});
      if (mounted) success?.call(result);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _openMatch() async {
    final result = await Navigator.of(context).push<_HelpResult>(
      MaterialPageRoute(
        builder: (_) => _HelpMatchPage(session: session, request: _request),
      ),
    );
    if (!mounted || result == null) return;
    Navigator.of(context).pop(result);
  }

  Future<void> _cancel() async {
    if (!await _confirmHelp(
          context,
          'Отменить заявку?',
          'Заявка закроется. Если есть резерв, он вернётся автору.',
          'Отменить заявку',
        ) ||
        !mounted) {
      return;
    }
    await _mutation(
      '/api/requests/cancel',
      success: (_) {
        _helpToast(context, 'Заявка отменена');
        Navigator.of(context).pop(const _HelpResult());
      },
    );
  }

  Future<void> _finish() async {
    if (!await _confirmHelp(
          context,
          'Подтвердить помощь?',
          'Подтвердите, что исполнитель выполнил задачу.',
          'Завершить помощь',
        ) ||
        !mounted) {
      return;
    }
    await _mutation(
      '/api/requests/completion/confirm',
      success: (_) {
        _helpToast(context, 'Помощь завершена');
        setState(() {
          _request['status'] = 'done';
          _request['status_title'] = 'Завершена';
        });
      },
    );
  }

  Future<void> _review() async {
    final rating = await showDialog<int>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: const Text('Оцените взаимодействие'),
        content: Wrap(
          spacing: 4,
          children: [
            for (var i = 1; i <= 5; i++)
              OutlinedButton(
                onPressed: () => Navigator.pop(dialog, i),
                child: Text('$i'),
              ),
          ],
        ),
      ),
    );
    if (!mounted || rating == null) return;
    await _mutation(
      '/api/reviews',
      extra: {'rating': rating, 'side': widget.owner ? 'requester' : 'helper'},
      success: (_) {
        setState(
          () => _request[widget.owner ? 'requester_rating' : 'helper_rating'] =
              rating,
        );
        _helpToast(context, 'Спасибо за оценку');
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final status = string(_request['status'], 'open');
    final open = status == 'open';
    final active = status == 'in_progress';
    final paid = integer(_request['reward_rub']) > 0;
    final reserved = _request['reward_payment_status'] == 'paid';
    final canRate =
        widget.participant &&
        status == 'done' &&
        _request[widget.owner ? 'requester_rating' : 'helper_rating'] == null;
    final ownerOpen = widget.owner && open;
    final canReserve = ownerOpen && paid && !reserved;
    final quote = object(_request['reward_quote']);
    final time = _requestTime(context, _request);
    final photos = rows(_request['photos']);
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.invitation ? 'Приглашение' : 'Заявка о помощи'),
      ),
      body: SafeArea(
        top: false,
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            Text(
              _categoryTitle(_helpCategories(session), _request),
              style: theme.textTheme.labelLarge?.copyWith(
                color: theme.colorScheme.primary,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              string(_request['what'], 'Заявка о помощи'),
              style: theme.textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 8),
            if (string(_request['requester_name']).isNotEmpty)
              Text('Автор · ${_request['requester_name']}'),
            const SizedBox(height: 4),
            Text('${_statusTitle(_request)} · ${_requestReward(_request)}'),
            if (time.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text('Когда · $time'),
            ],
            if (widget.participant && string(_request['place']).isNotEmpty) ...[
              const SizedBox(height: 6),
              Text('Место · ${_request['place']}'),
            ],
            if (widget.participant &&
                string(_request['details']).isNotEmpty) ...[
              const SizedBox(height: 14),
              Text(string(_request['details'])),
            ],
            if (photos.isNotEmpty && session.signedIn) ...[
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final photo in photos)
                    if (string(photo['url']).startsWith('/api/photos?'))
                      _RequestPhotoPreview(
                        session: session,
                        path: string(photo['url']),
                      ),
                ],
              ),
            ],
            const SizedBox(height: 16),
            if (_error != null)
              _HelpNotice(message: _error!, icon: Icons.error_outline_rounded),
            if (canReserve) ...[
              _HelpNotice(
                message:
                    'Чтобы опубликовать платную заявку, создайте резерв на ${integer(quote['total_rub'])} тестовых ₽.',
              ),
              FilledButton.icon(
                onPressed: _busy
                    ? null
                    : () => _mutation(
                        '/api/requests/reward/reserve',
                        extra: {'amount_rub': integer(_request['reward_rub'])},
                        success: (_) {
                          setState(
                            () => _request['reward_payment_status'] = 'paid',
                          );
                          _helpToast(context, 'Резерв создан');
                        },
                      ),
                icon: const Icon(Icons.account_balance_wallet_outlined),
                label: const Text('Создать резерв'),
              ),
            ],
            if (ownerOpen && !canReserve)
              FilledButton.icon(
                onPressed: _busy ? null : _openMatch,
                icon: const Icon(Icons.auto_awesome_outlined),
                label: const Text('Подобрать помощника'),
              ),
            if (widget.participant && (active || status == 'done'))
              OutlinedButton.icon(
                onPressed: _busy ? null : () => _chat(),
                icon: const Icon(Icons.chat_bubble_outline),
                label: const Text('Открыть чат'),
              ),
            if (widget.owner && active)
              FilledButton(
                onPressed: _busy ? null : _finish,
                child: const Text('Завершить помощь'),
              ),
            if (widget.participant && (ownerOpen || active))
              TextButton(
                onPressed: _busy ? null : _cancel,
                child: const Text('Отменить заявку'),
              ),
            if (canRate)
              FilledButton.icon(
                onPressed: _busy ? null : _review,
                icon: const Icon(Icons.star_outline_rounded),
                label: const Text('Оценить взаимодействие'),
              ),
            if (widget.invitation) ...[
              const _HelpNotice(
                message: 'Принятие приглашения откроет чат. Исполнителя выбирает автор заявки.',
              ),
              FilledButton(
                onPressed: _busy ? null : () => _respond(true),
                child: const Text('Обсудить помощь'),
              ),
              TextButton(
                onPressed: _busy ? null : () => _respond(false),
                child: const Text('Отклонить'),
              ),
            ] else if (!widget.participant && open)
              FilledButton.icon(
                onPressed: _busy
                    ? null
                    : () {
                        if (!session.signedIn) {
                          Navigator.of(context)
                              .pop(const _HelpResult(signIn: true));
                          return;
                        }
                        _mutation(
                          '/api/requests/apply',
                          success: (result) =>
                              _chat(integer(result['chat_id'])),
                        );
                      },
                icon: const Icon(Icons.handshake_outlined),
                label: Text(
                  session.signedIn
                      ? 'Откликнуться'
                      : 'Войти, чтобы откликнуться',
                ),
              ),
            if (_busy) const LinearProgressIndicator(),
          ],
        ),
      ),
    );
  }

  Future<void> _respond(bool accept) => _mutation(
    '/api/helper/offers/respond',
    extra: {'accept': accept, 'offer_token': string(_request['offer_token'])},
    success: (result) {
      if (accept) {
        _chat(integer(result['chat_id']));
      } else {
        Navigator.of(context).pop(const _HelpResult());
      }
    },
  );
}

class _RequestPhotoPreview extends StatefulWidget {
  const _RequestPhotoPreview({required this.session, required this.path});
  final HPointSession session;
  final String path;

  @override
  State<_RequestPhotoPreview> createState() => _RequestPhotoPreviewState();
}

class _RequestPhotoPreviewState extends State<_RequestPhotoPreview> {
  late final Future<Uint8List> _photo = widget.session.api.getBytes(
    widget.path,
  );

  @override
  Widget build(BuildContext context) => FutureBuilder<Uint8List>(
    future: _photo,
    builder: (context, snapshot) {
      final bytes = snapshot.data;
      return InkWell(
        onTap: bytes == null
            ? null
            : () => showDialog<void>(
                context: context,
                builder: (_) => Dialog(
                  child: InteractiveViewer(
                    child: Image.memory(bytes, fit: BoxFit.contain),
                  ),
                ),
              ),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(12),
          child: SizedBox(
            width: 88,
            height: 88,
            child: bytes == null
                ? Icon(
                    snapshot.hasError
                        ? Icons.broken_image_outlined
                        : Icons.photo_outlined,
                  )
                : Image.memory(bytes, fit: BoxFit.cover),
          ),
        ),
      );
    },
  );
}
