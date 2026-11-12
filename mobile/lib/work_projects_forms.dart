part of 'work_projects.dart';

Map<int, String> _recordChoices(
  List<Json> records, {
  required String label,
  required String empty,
  int current = 0,
  String idKey = 'id',
}) {
  final choices = <int, String>{0: empty};
  for (final record in records) {
    final id = record[idKey];
    if (id is int && id != 0) {
      choices[id] = string(record[label], 'Без названия');
    }
  }
  if (current != 0) choices.putIfAbsent(current, () => 'Недоступно');
  return choices;
}

bool _validateWorkForm(GlobalKey<FormState> form) {
  final errors = form.currentState!.validateGranularly();
  if (errors.isEmpty) return true;
  Scrollable.ensureVisible(
    errors.first.context,
    alignment: 0.15,
    duration: const Duration(milliseconds: 180),
  );
  return false;
}

class _WorkSelect<T extends Object> extends StatelessWidget {
  const _WorkSelect({
    required this.label,
    required this.value,
    required this.choices,
    this.onChanged,
  });

  final String label;
  final T value;
  final Map<T, String> choices;
  final ValueChanged<T>? onChanged;

  @override
  Widget build(BuildContext context) => DropdownButtonFormField<T>(
    key: ValueKey(value),
    initialValue: value,
    isExpanded: true,
    decoration: InputDecoration(labelText: label),
    items: [
      for (final option in choices.entries)
        DropdownMenuItem(
          value: option.key,
          child: Text(option.value, overflow: TextOverflow.ellipsis),
        ),
    ],
    onChanged: onChanged == null
        ? null
        : (next) {
            if (next != null) onChanged!(next);
          },
  );
}

class _WorkDate extends StatelessWidget {
  const _WorkDate({
    required this.label,
    required this.value,
    required this.onChanged,
    this.withTime = false,
  });

  final String label;
  final DateTime? value;
  final ValueChanged<DateTime?>? onChanged;
  final bool withTime;

  Future<void> _pick(BuildContext context) async {
    final now = DateTime.now();
    final initial = value ?? now;
    final date = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime(initial.year < 1900 ? initial.year : 1900),
      lastDate: DateTime(initial.year > 2100 ? initial.year : 2100, 12, 31),
    );
    if (date == null || !context.mounted) return;
    if (!withTime) {
      onChanged?.call(date);
      return;
    }
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(initial),
    );
    if (time == null || !context.mounted) return;
    onChanged?.call(
      DateTime(date.year, date.month, date.day, time.hour, time.minute),
    );
  }

  @override
  Widget build(BuildContext context) {
    final date = value;
    final text = date == null
        ? 'Выбрать'
        : withTime
        ? _dueLabel(context, date.toIso8601String())
        : _dayLabel(context, date.toIso8601String());
    return InputDecorator(
      decoration: InputDecoration(
        labelText: label,
        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextButton.icon(
              onPressed: onChanged == null ? null : () => _pick(context),
              icon: const Icon(Icons.event_outlined, size: 18),
              label: Text(text),
              style: TextButton.styleFrom(alignment: Alignment.centerLeft),
            ),
          ),
          if (date != null)
            IconButton(
              onPressed: onChanged == null ? null : () => onChanged!(null),
              icon: const Icon(Icons.close, size: 18),
              tooltip: 'Очистить дату',
            ),
        ],
      ),
    );
  }
}

class _ProjectEditor extends StatefulWidget {
  const _ProjectEditor({required this.model, required this.task, this.record});

  final WorkModel model;
  final bool task;
  final Json? record;

  @override
  State<_ProjectEditor> createState() => _ProjectEditorState();
}

class _ProjectEditorState extends State<_ProjectEditor> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _title;
  late final TextEditingController _address;
  late final TextEditingController _budget;
  late final TextEditingController _actual;
  late final TextEditingController _notes;
  late final int? _ownerId;
  late final Object? _accountId;
  late String _status;
  late int _client;
  late int _object;
  late int _assignee;
  DateTime? _starts;
  DateTime? _ends;
  DateTime? _due;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    final row = widget.record ?? {};
    _ownerId = widget.model.ownerId;
    _accountId = widget.model.session.data?['current_user_id'];
    _title = TextEditingController(text: string(row['title']));
    _address = TextEditingController(text: string(row['address']));
    _budget = TextEditingController(text: _value(row['budget_rub']));
    _actual = TextEditingController(text: _value(row['actual_rub']));
    _notes = TextEditingController(text: string(row['notes']));
    final statuses = widget.task ? _taskStatuses : _objectStatuses;
    final status = string(row['status']);
    _status = statuses.containsKey(status) ? status : statuses.keys.first;
    _client = row['client_id'] as int? ?? 0;
    _object = row['object_id'] as int? ?? 0;
    _assignee = row['assignee_id'] as int? ?? 0;
    _starts = DateTime.tryParse(_value(row['starts_on']));
    _ends = DateTime.tryParse(_value(row['ends_on']));
    _due = DateTime.tryParse(_value(row['due_at']))?.toLocal();
  }

  @override
  void dispose() {
    for (final controller in [_title, _address, _budget, _actual, _notes]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> _save() async {
    if (_busy || !_validateWorkForm(_form)) return;
    if (_ownerId == null ||
        _ownerId != widget.model.ownerId ||
        _accountId != widget.model.session.data?['current_user_id'] ||
        !_mayEdit(widget.model)) {
      setState(() => _error = 'Кабинет изменился. Откройте форму заново.');
      return;
    }
    if (_starts != null && _ends != null && _ends!.isBefore(_starts!)) {
      setState(() => _error = 'Дата окончания должна быть не раньше начала.');
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.model.update(
        widget.task ? '/api/commercial/tasks' : '/api/commercial/objects',
        {
          'owner_id': _ownerId,
          if (widget.record != null) 'id': widget.record!['id'],
          'title': _title.text.trim(),
          'status': _status,
          'assignee_id': _assignee == 0 ? null : _assignee,
          'notes': _notes.text.trim(),
          if (widget.task) ...{
            'object_id': _object == 0 ? null : _object,
            'due_at': _due?.toUtc().toIso8601String(),
          } else ...{
            'client_id': _client == 0 ? null : _client,
            'address': _address.text.trim(),
            'starts_on': _dayPayload(_starts),
            'ends_on': _dayPayload(_ends),
            'budget_rub': int.tryParse(_budget.text.trim()) ?? 0,
            'actual_rub': int.tryParse(_actual.text.trim()) ?? 0,
          },
        },
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted) setState(() => _error = '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _integerField(String label, TextEditingController controller) =>
      TextFormField(
        controller: controller,
        enabled: !_busy,
        decoration: InputDecoration(labelText: label, suffixText: 'тест. ₽'),
        keyboardType: TextInputType.number,
        textInputAction: TextInputAction.next,
        validator: (value) {
          final input = (value ?? '').trim();
          if (input.isEmpty) return null;
          final amount = int.tryParse(input);
          return amount == null || amount < 0 || amount > 1000000000
              ? 'Введите целое число от 0 до 1 000 000 000'
              : null;
        },
      );

  @override
  Widget build(BuildContext context) {
    final data = widget.model.data;
    final adding = widget.record == null;
    final title = widget.task
        ? (adding ? 'Новая задача' : 'Редактирование задачи')
        : (adding ? 'Новый объект' : 'Редактирование объекта');
    return _WorkEditorFrame(
      title: title,
      form: _form,
      busy: _busy,
      error: _error,
      onSave: _save,
      fields: [
        TextFormField(
          controller: _title,
          enabled: !_busy,
          maxLength: 160,
          textInputAction: TextInputAction.next,
          decoration: const InputDecoration(
            labelText: 'Название',
            counterText: '',
          ),
          validator: (value) =>
              (value ?? '').trim().isEmpty ? 'Введите название' : null,
        ),
        _WorkSelect<String>(
          label: 'Статус',
          value: _status,
          choices: widget.task ? _taskStatuses : _objectStatuses,
          onChanged: _busy ? null : (value) => setState(() => _status = value),
        ),
        if (widget.task)
          _WorkSelect<int>(
            label: 'Объект',
            value: _object,
            choices: _recordChoices(
              rows(data['objects']),
              label: 'title',
              empty: 'Без объекта',
              current: _object,
            ),
            onChanged: _busy
                ? null
                : (value) => setState(() => _object = value),
          )
        else ...[
          TextFormField(
            controller: _address,
            enabled: !_busy,
            maxLength: 400,
            textInputAction: TextInputAction.next,
            decoration: const InputDecoration(
              labelText: 'Адрес',
              counterText: '',
            ),
          ),
          _WorkSelect<int>(
            label: 'Клиент',
            value: _client,
            choices: _recordChoices(
              rows(data['clients']),
              label: 'name',
              empty: 'Без клиента',
              current: _client,
            ),
            onChanged: _busy
                ? null
                : (value) => setState(() => _client = value),
          ),
        ],
        _WorkSelect<int>(
          label: 'Ответственный',
          value: _assignee,
          choices: _recordChoices(
            rows(data['members']),
            label: 'name',
            empty: 'Не назначен',
            current: _assignee,
            idKey: 'user_id',
          ),
          onChanged: _busy
              ? null
              : (value) => setState(() => _assignee = value),
        ),
        if (widget.task)
          _WorkDate(
            label: 'Срок выполнения',
            value: _due,
            withTime: true,
            onChanged: _busy ? null : (value) => setState(() => _due = value),
          )
        else ...[
          _WorkDate(
            label: 'Начало',
            value: _starts,
            onChanged: _busy
                ? null
                : (value) => setState(() => _starts = value),
          ),
          _WorkDate(
            label: 'Окончание',
            value: _ends,
            onChanged: _busy ? null : (value) => setState(() => _ends = value),
          ),
          _integerField('Бюджет', _budget),
          _integerField('Фактические расходы', _actual),
        ],
        TextFormField(
          controller: _notes,
          enabled: !_busy,
          minLines: 2,
          maxLines: 5,
          maxLength: 4000,
          decoration: const InputDecoration(
            labelText: 'Заметки',
            alignLabelWithHint: true,
            counterText: '',
          ),
        ),
      ],
    );
  }
}

class _WorkEditorFrame extends StatelessWidget {
  const _WorkEditorFrame({
    required this.title,
    required this.form,
    required this.busy,
    required this.fields,
    required this.onSave,
    this.error,
  });

  final String title;
  final GlobalKey<FormState> form;
  final bool busy;
  final String? error;
  final List<Widget> fields;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(title)),
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 680),
          child: Form(
            key: form,
            child: SingleChildScrollView(
              keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final field in fields) ...[
                    field,
                    const SizedBox(height: 12),
                  ],
                  if (error != null) ...[
                    Text(
                      error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                    const SizedBox(height: 12),
                  ],
                  if (busy) const LinearProgressIndicator(),
                  FilledButton(
                    onPressed: busy ? null : onSave,
                    child: const Text('Сохранить'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );
}
