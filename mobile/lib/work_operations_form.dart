part of 'work_operations.dart';

class _OperationsForm extends StatefulWidget {
  const _OperationsForm({
    required this.model,
    required this.account,
    required this.ownerId,
    required this.section,
    required this.row,
  });

  final WorkModel model;
  final int account;
  final int? ownerId;
  final _WorkRecord section;
  final Json row;

  @override
  State<_OperationsForm> createState() => _OperationsFormState();
}

class _OperationsFormState extends State<_OperationsForm> {
  final _formKey = GlobalKey<FormState>();
  final _controllers = <String, TextEditingController>{};
  bool _saving = false;
  String? _error;
  late bool _active;
  late String _kind;
  late String _status;
  late int _client;
  late int _service;
  late int _assignee;
  late int _object;
  Json? _serviceDefaults;
  DateTime? _startsAt;

  Json get _row => widget.row;
  late final Json _data = widget.model.data;
  bool get _creating => _row.isEmpty;

  @override
  void initState() {
    super.initState();
    _active = _creating || _enabled(_row['active']);
    _kind = string(_row['kind']);
    _status = string(_row['status'], 'planned');
    _client = integer(_row['client_id']);
    _service = integer(_row['service_id']);
    _serviceDefaults = _findService(_service);
    _assignee = integer(_row['assignee_id']);
    _object = integer(_row['object_id']);
    _startsAt = DateTime.tryParse(string(_row['starts_at']))?.toLocal();
  }

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  TextEditingController _controller(String key, [String fallback = '']) =>
      _controllers.putIfAbsent(
        key,
        () => TextEditingController(text: _row[key]?.toString() ?? fallback),
      );

  String _text(String key) => _controller(key).text.trim();

  Widget _field(
    String key,
    String label, {
    required int maximum,
    int minimum = 0,
    int lines = 1,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextFormField(
      controller: _controller(key),
      enabled: !_saving,
      maxLength: maximum,
      minLines: lines,
      maxLines: lines,
      textCapitalization: TextCapitalization.sentences,
      textInputAction: lines == 1
          ? TextInputAction.next
          : TextInputAction.newline,
      decoration: InputDecoration(labelText: label, counterText: ''),
      validator: (value) {
        final length = (value ?? '').trim().runes.length;
        if (length < minimum) return 'Не менее $minimum символов';
        if (length > maximum) return 'Не более $maximum символов';
        return null;
      },
    ),
  );

  Widget _number(
    String key,
    String label, {
    required int minimum,
    required int maximum,
    required int initial,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextFormField(
      controller: _controller(key, '$initial'),
      enabled: !_saving,
      keyboardType: TextInputType.number,
      textInputAction: TextInputAction.next,
      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
      decoration: InputDecoration(labelText: label),
      validator: (value) {
        final number = int.tryParse(value ?? '');
        return number != null && number >= minimum && number <= maximum
            ? null
            : 'Введите число от $minimum до $maximum';
      },
    ),
  );

  Widget _select<T>(
    String label,
    Map<T, String> options,
    T value,
    ValueChanged<T> onChanged, {
    String? Function(T?)? validator,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: DropdownButtonFormField<T>(
      initialValue: options.containsKey(value) ? value : null,
      isExpanded: true,
      decoration: InputDecoration(labelText: label),
      validator: validator,
      onChanged: _saving
          ? null
          : (next) {
              if (next != null) setState(() => onChanged(next));
            },
      items: [
        for (final option in options.entries)
          DropdownMenuItem<T>(
            value: option.key,
            child: Text(
              option.value,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ),
      ],
    ),
  );

  List<Widget> _profileFields() {
    final kinds = {
      for (final option in object(_data['kinds']).entries)
        option.key: string(option.value),
    };
    final catalog = rows(object(_data['professional'])['catalog']);
    final detail = catalog
        .where((row) => row['key'] == _kind)
        .map((row) => string(row['description']))
        .firstOrNull;
    return [
      _select(
        'Направление работы',
        kinds,
        _kind,
        (value) => _kind = value,
        validator: (value) => value == null ? 'Выберите направление' : null,
      ),
      if (detail != null && detail.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Text(detail),
        ),
      _field('title', 'Название', minimum: 2, maximum: 120),
      _field('description', 'О вашей работе', maximum: 2000, lines: 4),
      _field('contact', 'Контакт', maximum: 240),
    ];
  }

  List<Widget> _clientFields() => [
    _field('name', 'Имя клиента', minimum: 2, maximum: 120),
    _field('contact', 'Контакт', maximum: 240),
    _field('notes', 'Заметки', maximum: 4000, lines: 4),
    SwitchListTile(
      contentPadding: EdgeInsets.zero,
      value: _active,
      onChanged: _saving ? null : (value) => setState(() => _active = value),
      title: const Text('Активный клиент'),
      subtitle: Text(_active ? 'Доступен при создании записи' : 'В архиве'),
    ),
  ];

  List<Widget> _serviceFields() => [
    _field('title', 'Название услуги', minimum: 2, maximum: 120),
    _field('description', 'Описание', maximum: 2000, lines: 4),
    ..._priceAndDuration(),
    SwitchListTile(
      contentPadding: EdgeInsets.zero,
      value: _active,
      onChanged: _saving ? null : (value) => setState(() => _active = value),
      title: const Text('Услуга доступна'),
      subtitle: Text(
        _active ? 'Можно выбрать при создании записи' : 'В архиве',
      ),
    ),
  ];

  List<Widget> _priceAndDuration() => [
    _number(
      'price_rub',
      'Стоимость, тестовые ₽',
      minimum: 0,
      maximum: 1000000,
      initial: 0,
    ),
    _number(
      'duration_minutes',
      'Длительность, мин',
      minimum: 5,
      maximum: 1440,
      initial: 60,
    ),
  ];

  List<Widget> _bookingFields() {
    final clients = rows(_data['clients']).where(
      (row) =>
          _enabled(row['active']) ||
          integer(row['id']) == integer(_row['client_id']),
    );
    final services = rows(_data['services']).where(
      (row) =>
          _enabled(row['active']) ||
          integer(row['id']) == integer(_row['service_id']),
    );
    final members = rows(_data['members']);
    final objects = {
      0: 'Без объекта',
      if (integer(_row['object_id']) != 0)
        integer(_row['object_id']): string(
          _row['object_title'],
          'Текущий объект',
        ),
      for (final row in rows(_data['objects']))
        integer(row['id']): string(row['title']),
    };
    return [
      _select(
        'Клиент',
        {for (final row in clients) integer(row['id']): string(row['name'])},
        _client,
        (value) => _client = value,
        validator: (value) => value == null ? 'Выберите клиента' : null,
      ),
      _select(
        'Услуга',
        {
          0: 'Отдельная работа',
          for (final row in services) integer(row['id']): string(row['title']),
        },
        _service,
        _selectService,
      ),
      if (members.isNotEmpty)
        _select(
          'Ответственный',
          {
            0: 'Без назначения',
            for (final row in members)
              integer(row['user_id']): string(row['name']),
          },
          _assignee,
          (value) => _assignee = value,
        ),
      if (objects.length > 1)
        _select('Объект', objects, _object, (value) => _object = value),
      _field('title', 'Тема записи', minimum: 2, maximum: 160),
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: FormField<DateTime>(
          initialValue: _startsAt,
          validator: (value) => value == null ? 'Выберите дату и время' : null,
          builder: (field) => InkWell(
            borderRadius: BorderRadius.circular(12),
            onTap: _saving
                ? null
                : () async {
                    final value = await _pickStart();
                    if (value == null || !field.mounted) return;
                    _startsAt = value;
                    field.didChange(value);
                  },
            child: InputDecorator(
              decoration: InputDecoration(
                labelText: 'Дата и время',
                errorText: field.errorText,
                suffixIcon: const Icon(Icons.event_outlined),
              ),
              child: Text(
                field.value == null
                    ? 'Выбрать'
                    : _workDate(context, field.value),
              ),
            ),
          ),
        ),
      ),
      ..._priceAndDuration(),
      _select('Статус', _bookingStatuses, _status, (value) => _status = value),
      _field('notes', 'Заметки', maximum: 4000, lines: 4),
    ];
  }

  Json? _findService(int value) =>
      rows(_data['services']).where((row) => row['id'] == value).firstOrNull;

  void _selectService(int value) {
    _service = value;
    if (value == 0) return;
    final service = _findService(value);
    if (service == null) return;
    final previous = _serviceDefaults;
    _serviceDefaults = service;
    final title = _controller('title');
    if (title.text.trim().isEmpty || title.text == string(previous?['title'])) {
      title.text = string(service['title']);
    }
    if (!_creating && previous == null) return;
    final price = _controller('price_rub', '0');
    final duration = _controller('duration_minutes', '60');
    final notes = _controller('notes');
    if (price.text == '${previous?['price_rub'] ?? 0}') {
      price.text = '${integer(service['price_rub'])}';
    }
    if (duration.text == '${previous?['duration_minutes'] ?? 60}') {
      duration.text = '${integer(service['duration_minutes'])}';
    }
    if (_creating && notes.text == string(previous?['description'])) {
      notes.text = string(service['description']);
    }
  }

  Future<DateTime?> _pickStart() async {
    final start = _startsAt ?? DateTime.now().add(const Duration(hours: 1));
    final day = await showDatePicker(
      context: context,
      initialDate: start,
      firstDate: DateTime(min(start.year, DateTime.now().year - 10)),
      lastDate: DateTime(max(2100, start.year), 12, 31),
    );
    if (day == null || !mounted) return null;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(start),
    );
    if (time == null) return null;
    return DateTime(day.year, day.month, day.day, time.hour, time.minute);
  }

  Json _amountFields() => {
    'price_rub': int.parse(_text('price_rub')),
    'duration_minutes': int.parse(_text('duration_minutes')),
  };

  Json _payload() {
    final id = _row['id'];
    return switch (widget.section) {
      _WorkRecord.profile => {
        'kind': _kind,
        'title': _text('title'),
        'description': _text('description'),
        'contact': _text('contact'),
      },
      _WorkRecord.clients => {
        'id': ?id,
        'name': _text('name'),
        'contact': _text('contact'),
        'notes': _text('notes'),
        'active': _active,
      },
      _WorkRecord.services => {
        'id': ?id,
        'title': _text('title'),
        'description': _text('description'),
        'active': _active,
        ..._amountFields(),
      },
      _WorkRecord.bookings => {
        'id': ?id,
        'client_id': _client,
        'service_id': _service == 0 ? null : _service,
        'assignee_id': _assignee == 0 ? null : _assignee,
        'object_id': _object == 0 ? null : _object,
        'starts_at': _startsAt!.toUtc().toIso8601String(),
        'title': _text('title'),
        'notes': _text('notes'),
        'status': _status,
        ..._amountFields(),
      },
      _WorkRecord.subscription => throw StateError(
        'A subscription has no editor',
      ),
    };
  }

  Future<void> _save() async {
    if (_saving) return;
    final invalid = _formKey.currentState!.validateGranularly();
    if (invalid.isNotEmpty) {
      await Scrollable.ensureVisible(
        invalid.first.context,
        duration: const Duration(milliseconds: 200),
        alignment: 0.1,
      );
      return;
    }
    if (widget.account == 0 ||
        integer(widget.model.session.data?['current_user_id']) !=
            widget.account) {
      setState(() => _error = 'Войдите в H-Point и откройте форму заново.');
      return;
    }
    FocusManager.instance.primaryFocus?.unfocus();
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.model.update(widget.section.path, {
        ..._payload(),
        'owner_id': widget.ownerId,
      });
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final section = widget.section;
    final fields = switch (section) {
      _WorkRecord.profile => _profileFields(),
      _WorkRecord.clients => _clientFields(),
      _WorkRecord.services => _serviceFields(),
      _WorkRecord.bookings => _bookingFields(),
      _WorkRecord.subscription => <Widget>[],
    };
    return PopScope(
      canPop: !_saving,
      child: Scaffold(
        appBar: AppBar(
          title: Text(_creating ? section.createLabel : section.title),
        ),
        body: SafeArea(
          child: Form(
            key: _formKey,
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  ...fields,
                  if (_error case final message?)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: Text(
                        message,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                  const SizedBox(height: 8),
                  FilledButton(
                    onPressed: _saving ? null : _save,
                    child: Text(
                      _saving
                          ? 'Сохраняем…'
                          : _creating
                          ? section.createLabel
                          : 'Сохранить',
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
