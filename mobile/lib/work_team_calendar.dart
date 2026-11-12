part of 'work_team.dart';

class _WorkCalendar extends StatefulWidget {
  const _WorkCalendar({required this.model});
  final WorkModel model;

  @override
  State<_WorkCalendar> createState() => _WorkCalendarState();
}

class _WorkCalendarState extends State<_WorkCalendar> {
  WorkModel get _model => widget.model;
  String _mode = 'all';
  DateTime? _day;
  int? _person;
  bool _exporting = false;
  bool _mutating = false;

  DateTime get _today {
    final now = DateTime.now();
    return DateTime(now.year, now.month, now.day);
  }

  Future<void> _reload() async => _model.reload();

  Future<void> _chooseDay() async {
    final today = _today;
    final day = await showDatePicker(
      context: context,
      initialDate: _day ?? today,
      firstDate: DateTime(today.year - 5),
      lastDate: DateTime(today.year + 20, 12, 31),
    );
    if (day != null && mounted) setState(() => _day = day);
  }

  Future<void> _export() async {
    if (_exporting) return;
    final first = _day ?? _today;
    final last = _day ?? DateTime(first.year, first.month, first.day + 29);
    final person = _selectedPerson(rows(_model.data['members']));
    setState(() => _exporting = true);
    try {
      await _model.shareExport(
        '/api/commercial/calendar/export',
        {
          'from': _dateKey(first),
          'to': _dateKey(last),
          'timezone_minutes': '${first.timeZoneOffset.inMinutes}',
          'type': _mode,
          if (person != null) 'person': '$person',
        },
        fileName: 'H-Point-${_dateKey(first)}.ics',
        mimeType: 'text/calendar',
      );
    } catch (error) {
      if (mounted) _feedback(context, error.toString());
    } finally {
      if (mounted) setState(() => _exporting = false);
    }
  }

  int? _selectedPerson(List<Json> people) =>
      people.any((row) => row['user_id'] == _person) ? _person : null;

  Future<void> _deleteShift(Json row) async {
    if (!await _confirm(context, 'Удалить смену?', 'Удалить')) return;
    if (!mounted || _mutating) return;
    setState(() => _mutating = true);
    try {
      await _model.update('/api/commercial/shifts/delete', {'id': row['id']});
      if (mounted) _feedback(context, 'Смена удалена');
    } catch (error) {
      if (mounted) _feedback(context, error.toString());
    } finally {
      if (mounted) setState(() => _mutating = false);
    }
  }

  Future<void> _editShift([Json row = const {}]) async {
    final id = _idOf(row['id']);
    final people = rows(_model.data['members']);
    var title = string(row['title']);
    var notes = string(row['notes']);
    var person = _idOf(row['assignee_id']);
    var objectId = _idOf(row['object_id']);
    var begins = _workDate(row['starts_at']);
    var ends = _workDate(row['ends_at']);
    if (id == null && _day != null) {
      begins = DateTime(_day!.year, _day!.month, _day!.day, 9);
      ends = begins.add(const Duration(hours: 8));
    }
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (context) => _Editor(
          title: id == null ? 'Новая смена' : 'Изменить смену',
          submit: () async {
            final start = begins;
            final end = ends;
            if (start == null || end == null) {
              throw const ApiException('Выберите начало и окончание смены.');
            }
            if (end.difference(start).inMinutes < 1 ||
                end.difference(start) > const Duration(days: 7)) {
              throw const ApiException(
                'Смена должна длиться от одной минуты до 7 дней.',
              );
            }
            await _model.update('/api/commercial/shifts', {
              'id': ?id,
              'title': title.trim(),
              'assignee_id': person,
              'object_id': objectId,
              'starts_at': start.toUtc().toIso8601String(),
              'ends_at': end.toUtc().toIso8601String(),
              'notes': notes.trim(),
            });
          },
          fields: [
            _editText(
              'Название смены',
              title,
              (value) => title = value,
              limit: 160,
              minLength: 1,
            ),
            _choosePerson(
              people: people,
              value: person,
              changed: (value) => person = value,
              required: true,
            ),
            _chooseRecord(
              'Объект',
              'Без объекта',
              rows(_model.data['objects']),
              objectId,
              (value) => objectId = value,
            ),
            _MomentField(
              label: 'Начало смены',
              value: begins,
              onChanged: (value) => begins = value,
            ),
            _MomentField(
              label: 'Окончание смены',
              value: ends,
              onChanged: (value) => ends = value,
            ),
            _editText(
              'Заметка',
              notes,
              (value) => notes = value,
              limit: 4000,
              lines: 3,
            ),
          ],
        ),
      ),
    );
  }

  void _bookingDetails(_CalendarEntry entry) {
    final row = entry.row;
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
          child: ListView(
            shrinkWrap: true,
            children: [
              Text(
                string(row['title'], 'Запись'),
                style: Theme.of(context).textTheme.titleLarge,
              ),
              ListTile(
                leading: const Icon(Icons.schedule),
                title: Text(_dateTimeLabel(context, entry.starts)),
                subtitle: Text(
                  '${integer(row['duration_minutes'])} мин. · ${integer(row['price_rub'])} тест. ₽',
                ),
              ),
              if (string(row['client_name']).isNotEmpty)
                ListTile(
                  leading: const Icon(Icons.person_outline),
                  title: Text(string(row['client_name'])),
                  subtitle: const Text('Клиент'),
                ),
              if (string(row['assignee_name']).isNotEmpty)
                ListTile(
                  leading: const Icon(Icons.assignment_ind_outlined),
                  title: Text(string(row['assignee_name'])),
                  subtitle: const Text('Ответственный'),
                ),
              if (string(row['object_title']).isNotEmpty)
                ListTile(
                  leading: const Icon(Icons.apartment_outlined),
                  title: Text(string(row['object_title'])),
                  subtitle: const Text('Объект'),
                ),
              if (string(row['notes']).isNotEmpty)
                ListTile(
                  leading: const Icon(Icons.notes),
                  title: Text(string(row['notes'])),
                ),
            ],
          ),
        ),
      ),
    );
  }

  List<_CalendarEntry> _entries(List<Json> people) {
    final first = _day ?? _today;
    final end = DateTime(
      first.year,
      first.month,
      first.day + (_day == null ? 30 : 1),
    );
    final selectedPerson = _selectedPerson(people);
    final entries = <_CalendarEntry>[];
    for (final (key, shift) in const [('bookings', false), ('shifts', true)]) {
      if (_mode != 'all' && _mode != key) continue;
      for (final row in rows(_model.data[key])) {
        if (!shift && row['status'] != 'planned') continue;
        if (selectedPerson != null && selectedPerson != row['assignee_id']) {
          continue;
        }
        final starts = _workDate(row['starts_at']);
        if (starts == null || !starts.isBefore(end)) continue;
        final ends = shift
            ? _workDate(row['ends_at'])
            : starts.add(Duration(minutes: integer(row['duration_minutes'])));
        if (ends != null && !ends.isAfter(first)) continue;
        entries.add(_CalendarEntry(row, starts, ends, shift));
      }
    }
    entries.sort((a, b) => a.starts.compareTo(b.starts));
    return entries;
  }

  List<Widget> _content() {
    if (_model.ownerId == null) {
      return const [_WorkNotice('Сначала создайте кабинет для работы.')];
    }
    final people = rows(_model.data['members']);
    final entries = _entries(people);
    final canWrite =
        _workActive(_model) &&
        object(_model.data['permissions'])['write'] == true &&
        !_mutating;
    return [
      if (_model.loading || _mutating || _exporting)
        const LinearProgressIndicator(),
      if (_model.error case final message?)
        _WorkNotice(message, icon: Icons.error_outline),
      Wrap(
        spacing: 8,
        runSpacing: 4,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          OutlinedButton.icon(
            onPressed: _chooseDay,
            icon: const Icon(Icons.calendar_today_outlined),
            label: Text(
              _day == null ? 'Ближайшие 30 дней' : _shortDate(context, _day!),
            ),
          ),
          if (_day != null)
            IconButton(
              tooltip: 'Показать ближайшие 30 дней',
              onPressed: () => setState(() => _day = null),
              icon: const Icon(Icons.close),
            ),
        ],
      ),
      const SizedBox(height: 12),
      SegmentedButton<String>(
        showSelectedIcon: false,
        segments: const [
          ButtonSegment(value: 'all', label: Text('Все')),
          ButtonSegment(value: 'bookings', label: Text('Записи')),
          ButtonSegment(value: 'shifts', label: Text('Смены')),
        ],
        selected: {_mode},
        onSelectionChanged: (value) => setState(() => _mode = value.single),
      ),
      if (people.isNotEmpty) ...[
        const SizedBox(height: 12),
        DropdownButtonFormField<int>(
          key: ValueKey(_selectedPerson(people)),
          initialValue: _selectedPerson(people),
          decoration: const InputDecoration(labelText: 'Сотрудник'),
          isExpanded: true,
          items: [
            const DropdownMenuItem<int>(
              value: null,
              child: Text('Вся команда'),
            ),
            for (final person in people)
              if (_idOf(person['user_id']) case final id?)
                DropdownMenuItem(
                  value: id,
                  child: Text(
                    string(person['name'], 'Участник'),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
          ],
          onChanged: (value) => setState(() => _person = value),
        ),
      ],
      const SizedBox(height: 12),
      Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          if (canWrite)
            FilledButton.tonalIcon(
              onPressed: _editShift,
              icon: const Icon(Icons.add),
              label: const Text('Добавить смену'),
            ),
          OutlinedButton.icon(
            onPressed: _exporting ? null : _export,
            icon: const Icon(Icons.calendar_month_outlined),
            label: const Text('Поделиться .ics'),
          ),
        ],
      ),
      const _SectionTitle('Расписание'),
      if (entries.isEmpty)
        const _WorkNotice('На выбранный период ничего не запланировано.'),
      for (final entry in entries)
        Card(
          margin: const EdgeInsets.only(bottom: 8),
          child: ListTile(
            leading: Icon(
              entry.shift ? Icons.badge_outlined : Icons.event_note_outlined,
            ),
            title: Text(
              string(entry.row['title'], entry.shift ? 'Смена' : 'Запись'),
            ),
            subtitle: Text(
              [
                _dateTimeLabel(context, entry.starts),
                if (entry.shift && entry.ends != null)
                  'До ${_dateTimeLabel(context, entry.ends)}',
                if (string(entry.row['assignee_name']).isNotEmpty)
                  string(entry.row['assignee_name']),
              ].join('\n'),
            ),
            onTap: entry.shift
                ? (canWrite ? () => _editShift(entry.row) : null)
                : () => _bookingDetails(entry),
            trailing: entry.shift && canWrite
                ? PopupMenuButton<String>(
                    tooltip: 'Действия со сменой',
                    onSelected: (value) => value == 'edit'
                        ? _editShift(entry.row)
                        : _deleteShift(entry.row),
                    itemBuilder: (context) => const [
                      PopupMenuItem(value: 'edit', child: Text('Изменить')),
                      PopupMenuItem(value: 'delete', child: Text('Удалить')),
                    ],
                  )
                : null,
          ),
        ),
    ];
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Расписание')),
    body: AnimatedBuilder(
      animation: _model,
      builder: (context, _) =>
          _WorkContent(onRefresh: _reload, children: _content()),
    ),
  );
}

class _CalendarEntry {
  const _CalendarEntry(this.row, this.starts, this.ends, this.shift);
  final Json row;
  final DateTime starts;
  final DateTime? ends;
  final bool shift;
}

class _MomentField extends StatefulWidget {
  const _MomentField({
    required this.label,
    required this.value,
    required this.onChanged,
  });
  final String label;
  final DateTime? value;
  final ValueChanged<DateTime> onChanged;

  @override
  State<_MomentField> createState() => _MomentFieldState();
}

class _MomentFieldState extends State<_MomentField> {
  DateTime? _value;

  @override
  void initState() {
    super.initState();
    _value = widget.value;
  }

  Future<void> _choose() async {
    final moment = await _pickMoment(context, _value);
    if (moment != null && mounted) {
      setState(() => _value = moment);
      widget.onChanged(moment);
    }
  }

  @override
  Widget build(BuildContext context) => InkWell(
    borderRadius: BorderRadius.circular(12),
    onTap: _choose,
    child: InputDecorator(
      decoration: InputDecoration(
        labelText: widget.label,
        suffixIcon: const Icon(Icons.schedule),
      ),
      child: Text(_dateTimeLabel(context, _value)),
    ),
  );
}
