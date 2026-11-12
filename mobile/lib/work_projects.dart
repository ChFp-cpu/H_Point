import 'package:flutter/material.dart';

import 'api.dart';
import 'work_state.dart';

part 'work_projects_forms.dart';
part 'work_projects_estimates.dart';

const _objectStatuses = {
  'planned': 'Запланирован',
  'active': 'В работе',
  'completed': 'Завершён',
  'cancelled': 'Отменён',
};
const _taskStatuses = {
  'todo': 'К выполнению',
  'in_progress': 'В работе',
  'done': 'Готово',
  'cancelled': 'Отменена',
};
const _estimateStatuses = {
  'draft': 'Черновик',
  'approved': 'Согласована',
  'completed': 'Выполнена',
  'cancelled': 'Отменена',
};

bool _mayEdit(WorkModel model, {bool manage = false}) {
  final permissions = object(model.data['permissions']);
  return object(model.data['profile'])['active'] == true &&
      permissions[manage ? 'manage' : 'write'] == true;
}

String _value(dynamic value, [String fallback = '']) =>
    value is num ? '$value' : string(value, fallback);

String _money(dynamic amount) =>
    '${_value(amount, '0').replaceAll('.', ',')} тест. ₽';

String _nameIn(List<Json> list, dynamic id, String field) {
  if (id == null) return '';
  for (final record in list) {
    if (record['id'] == id) return string(record[field]);
  }
  return '';
}

String _dayLabel(BuildContext context, dynamic value) {
  final date = DateTime.tryParse(_value(value));
  return date == null
      ? ''
      : MaterialLocalizations.of(context).formatShortDate(date);
}

String _dueLabel(BuildContext context, dynamic value) {
  final date = DateTime.tryParse(_value(value))?.toLocal();
  if (date == null) return '';
  final localizations = MaterialLocalizations.of(context);
  final time = localizations.formatTimeOfDay(
    TimeOfDay.fromDateTime(date),
    alwaysUse24HourFormat: MediaQuery.alwaysUse24HourFormatOf(context),
  );
  return '${localizations.formatShortDate(date)} · $time';
}

String _dayPayload(DateTime? date) => date == null
    ? ''
    : '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';

void _notice(BuildContext context, String message) =>
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));

class WorkProjectsPage extends StatefulWidget {
  const WorkProjectsPage({
    super.key,
    required this.model,
    required this.section,
  });

  final WorkModel model;
  final String section;

  @override
  State<WorkProjectsPage> createState() => _WorkProjectsPageState();
}

class _WorkProjectsPageState extends State<WorkProjectsPage> {
  String _query = '';
  String _status = '';
  int _objectFilter = 0;
  bool _busy = false;

  WorkModel get _model => widget.model;
  bool get _estimates => widget.section == 'estimates';
  bool get _tasks => widget.section == 'tasks';
  String get _collection =>
      _estimates ? 'estimates' : (_tasks ? 'tasks' : 'objects');
  String get _title => _estimates ? 'Сметы' : (_tasks ? 'Задачи' : 'Объекты');
  String get _addLabel =>
      _estimates ? 'Новая смета' : (_tasks ? 'Новая задача' : 'Новый объект');
  Map<String, String> get _statuses => _estimates
      ? _estimateStatuses
      : (_tasks ? _taskStatuses : _objectStatuses);

  Future<void> _edit([Json? record]) async {
    if (!_mayEdit(_model, manage: _estimates)) return;
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => _estimates
            ? _EstimateEditor(model: _model, record: record)
            : _ProjectEditor(model: _model, task: _tasks, record: record),
      ),
    );
    if (saved == true && mounted) {
      _notice(
        context,
        _estimates
            ? 'Смета сохранена'
            : (_tasks ? 'Задача сохранена' : 'Объект сохранён'),
      );
    }
  }

  Future<void> _completeTask(Json record) async {
    if (_busy || !_mayEdit(_model)) return;
    setState(() => _busy = true);
    try {
      await _model.update('/api/commercial/tasks/status', {
        'id': record['id'],
        'status': 'done',
      });
      if (mounted) _notice(context, 'Задача выполнена');
    } catch (error) {
      if (mounted) _notice(context, '$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _card(Json row, bool editable) {
    if (_estimates) {
      return _EstimateCard(
        model: _model,
        row: row,
        onEdit: editable ? () => _edit(row) : null,
      );
    }
    final data = _model.data;
    final title = string(row['title'], _tasks ? 'Задача' : 'Объект');
    final status = string(row['status']);
    final assignee = string(row['assignee_name']);
    final objectTitle = string(row['object_title']);
    final notes = string(row['notes']);
    final address = string(row['address']);
    final client = _nameIn(rows(data['clients']), row['client_id'], 'name');
    final related = _tasks
        ? const <Json>[]
        : rows(data['tasks'])
              .where((task) => task['object_id'] == row['id'])
              .toList();
    final done = related.where((task) => task['status'] == 'done').length;
    final start = _dayLabel(context, row['starts_on']);
    final end = _dayLabel(context, row['ends_on']);
    final due = _dueLabel(context, row['due_at']);
    final overdue =
        _tasks &&
        !{'done', 'cancelled'}.contains(status) &&
        (DateTime.tryParse(_value(row['due_at']))?.isBefore(DateTime.now()) ??
            false);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _WorkRecordHeader(
              title: title,
              status: _statuses[status] ?? status,
            ),
            if (_tasks) ...[
              if (objectTitle.isNotEmpty)
                _WorkRecordLine(Icons.location_city_outlined, objectTitle),
              if (due.isNotEmpty)
                _WorkRecordLine(
                  Icons.schedule_outlined,
                  overdue ? '$due · просрочена' : due,
                ),
            ] else ...[
              if (address.isNotEmpty)
                _WorkRecordLine(Icons.place_outlined, address),
              if (client.isNotEmpty)
                _WorkRecordLine(Icons.person_outline, client),
              if (start.isNotEmpty || end.isNotEmpty)
                _WorkRecordLine(
                  Icons.event_outlined,
                  [
                    if (start.isNotEmpty) 'с $start',
                    if (end.isNotEmpty) 'до $end',
                  ].join(' '),
                ),
              _WorkRecordLine(
                Icons.account_balance_wallet_outlined,
                'Бюджет ${_money(row['budget_rub'])} · расходы ${_money(row['actual_rub'])}',
              ),
              if (related.isNotEmpty) ...[
                const SizedBox(height: 10),
                Text('Выполнено задач: $done из ${related.length}'),
                const SizedBox(height: 5),
                LinearProgressIndicator(value: done / related.length),
              ],
            ],
            if (assignee.isNotEmpty)
              _WorkRecordLine(Icons.badge_outlined, assignee),
            if (notes.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(notes),
              ),
            if (editable) ...[
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 4,
                children: [
                  TextButton.icon(
                    onPressed: () => _edit(row),
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('Изменить'),
                  ),
                  if (_tasks && !{'done', 'cancelled'}.contains(status))
                    FilledButton.tonalIcon(
                      onPressed: _busy ? null : () => _completeTask(row),
                      icon: const Icon(Icons.check),
                      label: const Text('Готово'),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: _model,
    builder: (context, _) {
      final data = _model.data;
      final entries = rows(data[_collection]);
      final objects = rows(data['objects']);
      final clients = rows(data['clients']);
      final editable = _mayEdit(_model, manage: _estimates);
      final items = entries.where((row) {
        if (_status.isNotEmpty && row['status'] != _status) return false;
        if ((_tasks || _estimates) &&
            _objectFilter != 0 &&
            row['object_id'] != _objectFilter) {
          return false;
        }
        if (_query.isEmpty) return true;
        final text = [
          for (final key in [
            'title',
            'number',
            'address',
            'assignee_name',
            'object_title',
            'notes',
          ])
            _value(row[key]),
          _nameIn(objects, row['object_id'], 'title'),
          _nameIn(clients, row['client_id'], 'name'),
          for (final item in rows(row['items'])) string(item['title']),
        ].join(' ').toLowerCase();
        return text.contains(_query);
      }).toList();
      return Scaffold(
        appBar: AppBar(title: Text(_title)),
        floatingActionButton: editable
            ? FloatingActionButton.extended(
                onPressed: _edit,
                icon: const Icon(Icons.add),
                label: Text(_addLabel),
              )
            : null,
        body: SafeArea(
          child: RefreshIndicator(
            onRefresh: _model.reload,
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: EdgeInsets.fromLTRB(16, 12, 16, editable ? 96 : 20),
                  itemCount: items.isEmpty ? 2 : items.length + 1,
                  itemBuilder: (context, index) {
                    if (index == 0) {
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 14),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (_model.error case final error?) ...[
                              Text(
                                error,
                                style: TextStyle(
                                  color: Theme.of(context).colorScheme.error,
                                ),
                              ),
                              TextButton.icon(
                                onPressed: _model.loading
                                    ? null
                                    : _model.reload,
                                icon: const Icon(Icons.refresh),
                                label: const Text('Повторить'),
                              ),
                            ],
                            if (!editable &&
                                object(data['profile']).isNotEmpty) ...[
                              Text(
                                object(data['profile'])['active'] == true
                                    ? 'Изменения доступны руководителям кабинета.'
                                    : 'Для изменений продлите доступ к кабинету.',
                              ),
                              const SizedBox(height: 12),
                            ],
                            if (entries.isNotEmpty) ...[
                              TextField(
                                onChanged: (value) => setState(
                                  () => _query = value.trim().toLowerCase(),
                                ),
                                textInputAction: TextInputAction.search,
                                decoration: const InputDecoration(
                                  labelText: 'Поиск',
                                  prefixIcon: Icon(Icons.search),
                                ),
                              ),
                              const SizedBox(height: 10),
                              _WorkSelect<String>(
                                label: 'Статус',
                                value: _status,
                                choices: {'': 'Все статусы', ..._statuses},
                                onChanged: (value) =>
                                    setState(() => _status = value),
                              ),
                              if ((_tasks || _estimates) &&
                                  objects.isNotEmpty) ...[
                                const SizedBox(height: 10),
                                _WorkSelect<int>(
                                  label: 'Объект',
                                  value: _objectFilter,
                                  choices: _recordChoices(
                                    objects,
                                    label: 'title',
                                    empty: 'Все объекты',
                                    current: _objectFilter,
                                  ),
                                  onChanged: (value) =>
                                      setState(() => _objectFilter = value),
                                ),
                              ],
                            ],
                          ],
                        ),
                      );
                    }
                    if (items.isEmpty) {
                      if (_model.loading) {
                        return const Center(child: CircularProgressIndicator());
                      }
                      if (_model.error != null && entries.isEmpty) {
                        return const SizedBox.shrink();
                      }
                      return _WorkEmpty(
                        icon: _estimates
                            ? Icons.request_quote_outlined
                            : (_tasks
                                  ? Icons.task_alt_outlined
                                  : Icons.location_city_outlined),
                        title: entries.isNotEmpty
                            ? 'Ничего не найдено'
                            : (_estimates
                                  ? 'Смет пока нет'
                                  : (_tasks
                                        ? 'Задач пока нет'
                                        : 'Объектов пока нет')),
                        message: entries.isNotEmpty
                            ? 'Попробуйте другой запрос или фильтр.'
                            : '',
                      );
                    }
                    final item = items[index - 1];
                    return Padding(
                      key: ValueKey((_model.ownerId, item['id'])),
                      padding: const EdgeInsets.only(bottom: 10),
                      child: _card(item, editable),
                    );
                  },
                ),
              ),
            ),
          ),
        ),
      );
    },
  );
}

class _WorkRecordHeader extends StatelessWidget {
  const _WorkRecordHeader({required this.title, required this.status});

  final String title;
  final String status;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      if (status.isNotEmpty)
        Text(
          status,
          style: Theme.of(context).textTheme.labelLarge
              ?.copyWith(color: Theme.of(context).colorScheme.primary),
        ),
      Text(
        title,
        style: Theme.of(context).textTheme.titleMedium
            ?.copyWith(fontWeight: FontWeight.w700),
      ),
    ],
  );
}

class _WorkRecordLine extends StatelessWidget {
  const _WorkRecordLine(this.icon, this.text);

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 7),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(
          icon,
          size: 17,
          color: Theme.of(context).colorScheme.onSurfaceVariant,
        ),
        const SizedBox(width: 8),
        Expanded(child: Text(text)),
      ],
    ),
  );
}

class _WorkEmpty extends StatelessWidget {
  const _WorkEmpty({
    required this.icon,
    required this.title,
    required this.message,
  });

  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 16),
    child: Column(
      children: [
        Icon(icon, size: 40, color: Theme.of(context).colorScheme.primary),
        const SizedBox(height: 10),
        Text(
          title,
          style: Theme.of(context).textTheme.titleLarge,
          textAlign: TextAlign.center,
        ),
        if (message.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(message, textAlign: TextAlign.center),
        ],
      ],
    ),
  );
}
