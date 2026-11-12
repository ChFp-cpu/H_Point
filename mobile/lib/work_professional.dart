import 'package:flutter/material.dart';

import 'api.dart';
import 'work_state.dart';

class WorkProfessionalPage extends StatelessWidget {
  const WorkProfessionalPage({super.key, required this.model});
  final WorkModel model;

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: model,
    builder: (context, _) {
      final work = object(model.data['professional']);
      final modules = rows(work['modules']);
      final history = rows(work['history']);
      final progress = object(work['progress']);
      return Scaffold(
        appBar: AppBar(title: Text(string(work['title'], 'По профессии'))),
        body: SafeArea(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              if (string(work['description']).isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(string(work['description'])),
                ),
              if (progress.containsKey('athletes'))
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      Chip(
                        label: Text(
                          'Подопечные: ${integer(progress['athletes'])}',
                        ),
                      ),
                      Chip(
                        label: Text(
                          'Тренировки: ${integer(progress['training_completed'])}',
                        ),
                      ),
                      Chip(
                        label: Text(
                          'Соревнования: ${integer(progress['competitions_upcoming'])}',
                        ),
                      ),
                    ],
                  ),
                ),
              for (final spec in modules) _module(context, spec, false),
              if (rows(progress['weight_series']).isNotEmpty)
                Card(
                  child: ListTile(
                    leading: const Icon(Icons.monitor_weight_outlined),
                    title: const Text('Динамика веса'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => _WeightPage(
                          series: rows(progress['weight_series']),
                        ),
                      ),
                    ),
                  ),
                ),
              if (history.isNotEmpty) ...[
                const SizedBox(height: 18),
                Text(
                  'История прежних форматов работы',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: 8),
                for (final spec in history) _module(context, spec, true),
              ],
            ],
          ),
        ),
      );
    },
  );

  Widget _module(BuildContext context, Json spec, bool archived) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Card(
      child: ListTile(
        leading: Icon(archived ? Icons.history : Icons.folder_outlined),
        title: Text(string(spec['title'], 'Рабочие записи')),
        subtitle: Text('Записей: ${integer(spec['count'])}'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => _ProfessionalModule(
              model: model,
              module: string(spec['key']),
              historical: archived,
            ),
          ),
        ),
      ),
    ),
  );
}

class _ProfessionalModule extends StatefulWidget {
  const _ProfessionalModule({
    required this.model,
    required this.module,
    required this.historical,
  });
  final WorkModel model;
  final String module;
  final bool historical;
  @override
  State<_ProfessionalModule> createState() => _ProfessionalModuleState();
}

class _ProfessionalModuleState extends State<_ProfessionalModule> {
  bool _showArchive = false;
  String _query = '';

  Future<void> _open(Json spec, [Json? record]) =>
      Navigator.of(context).push<void>(
        MaterialPageRoute(
          builder: (_) => _ProfessionalForm(
            model: widget.model,
            spec: spec,
            record: record,
            writable:
                spec['can_write'] == true &&
                (record == null || record['can_write'] == true),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: widget.model,
    builder: (context, _) {
      final work = object(widget.model.data['professional']);
      final specs = rows(work[widget.historical ? 'history' : 'modules']);
      final spec =
          specs.where((row) => row['key'] == widget.module).firstOrNull ??
          const <String, dynamic>{};
      final statuses = object(spec['statuses']);
      final records = rows(spec['records']).where(
        (row) =>
            (_showArchive || row['archived'] != true) &&
            string(row['title']).toLowerCase().contains(_query),
      );
      return Scaffold(
        appBar: AppBar(title: Text(string(spec['title'], 'Рабочие записи'))),
        floatingActionButton: spec['can_write'] == true
            ? FloatingActionButton.extended(
                onPressed: () => _open(spec),
                icon: const Icon(Icons.add),
                label: const Text('Добавить'),
              )
            : null,
        body: SafeArea(
          child: RefreshIndicator(
            onRefresh: widget.model.reload,
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 90),
              children: [
                if (spec.isEmpty)
                  const ListTile(title: Text('Раздел недоступен')),
                if (string(spec['description']).isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(string(spec['description'])),
                  ),
                if (spec.isNotEmpty) ...[
                  TextField(
                    onChanged: (value) =>
                        setState(() => _query = value.trim().toLowerCase()),
                    decoration: const InputDecoration(
                      labelText: 'Поиск',
                      prefixIcon: Icon(Icons.search),
                    ),
                  ),
                  SwitchListTile(
                    value: _showArchive,
                    onChanged: (value) => setState(() => _showArchive = value),
                    title: const Text('Показать архив'),
                  ),
                  if (records.isEmpty)
                    const ListTile(title: Text('Нет записей')),
                  for (final row in records)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Card(
                        child: ListTile(
                          title: Text(string(row['title'], 'Запись')),
                          subtitle: Text(
                            string(statuses[row['status']], 'Запись'),
                          ),
                          trailing: const Icon(Icons.chevron_right),
                          onTap: () => _open(spec, row),
                        ),
                      ),
                    ),
                ],
              ],
            ),
          ),
        ),
      );
    },
  );
}

class _ProfessionalForm extends StatefulWidget {
  const _ProfessionalForm({
    required this.model,
    required this.spec,
    required this.record,
    required this.writable,
  });
  final WorkModel model;
  final Json spec;
  final Json? record;
  final bool writable;
  @override
  State<_ProfessionalForm> createState() => _ProfessionalFormState();
}

class _ProfessionalFormState extends State<_ProfessionalForm> {
  final _form = GlobalKey<FormState>();
  final Map<String, TextEditingController> _controllers = {};
  final Map<String, String?> _choices = {};
  late final List<Json> _fields = rows(widget.spec['fields']);
  late final Json _statuses = object(widget.spec['statuses']);
  late String? _status =
      widget.record?['status'] as String? ?? _statuses.keys.firstOrNull;
  bool _saving = false;
  String? _error;
  static const _selectTypes = {
    'select',
    'client',
    'member',
    'object',
    'record',
  };

  @override
  void initState() {
    super.initState();
    for (final field in _fields) {
      final key = string(field['key']);
      final value = widget.record == null
          ? field['default']
          : widget.record?[key];
      if (_selectTypes.contains(field['type'])) {
        _choices[key] = value?.toString();
      } else {
        _controllers[key] = TextEditingController(
          text: value?.toString() ?? '',
        );
      }
    }
  }

  @override
  void dispose() {
    for (final controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  Map<String, String> _options(Json field) {
    final data = widget.model.data;
    switch (field['type']) {
      case 'select':
        return object(field['options'])
            .map((key, value) => MapEntry(key, string(value, key)));
      case 'client':
        return {
          for (final row in rows(data['clients']))
            '${row['id']}': string(row['name'], 'Клиент'),
        };
      case 'member':
        return {
          for (final row in rows(data['members']))
            '${row['user_id']}': string(row['name'], 'Участник'),
        };
      case 'object':
        return {
          for (final row in rows(data['objects']))
            '${row['id']}': string(row['title'], 'Объект'),
        };
      case 'record':
        final professional = object(data['professional']);
        final specs = [
          ...rows(professional['modules']),
          ...rows(professional['history']),
        ];
        final spec = specs
            .where((row) => row['key'] == field['ref'])
            .firstOrNull;
        return {
          for (final row in rows(spec?['records']))
            '${row['id']}': string(row['title'], 'Запись'),
        };
      default:
        return const {};
    }
  }

  Future<void> _pickDate(TextEditingController controller) async {
    final now = DateTime.now();
    final first = DateTime(1900);
    final last = DateTime(2100, 12, 31);
    final current = DateTime.tryParse(controller.text);
    final value = await showDatePicker(
      context: context,
      firstDate: first,
      lastDate: last,
      initialDate:
          current != null && !current.isBefore(first) && !current.isAfter(last)
          ? current
          : now,
    );
    if (value != null && mounted) {
      controller.text = value.toIso8601String().split('T').first;
    }
  }

  Future<void> _save() async {
    if (_saving || !_form.currentState!.validate()) return;
    final fields = <String, dynamic>{
      if (widget.record != null) 'id': widget.record!['id'],
      'status': _status,
    };
    for (final field in _fields) {
      final key = string(field['key']);
      final type = string(field['type']);
      final input = _controllers[key]?.text.trim();
      fields[key] = switch (type) {
        'integer' => int.tryParse(input ?? ''),
        'client' ||
        'member' ||
        'object' ||
        'record' => int.tryParse(_choices[key] ?? ''),
        'select' => _choices[key],
        _ => input,
      };
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.model.update(
        '/api/commercial/professional/${widget.spec['key']}',
        fields,
      );
      if (mounted) Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Widget _field(Json field) {
    final key = string(field['key']);
    final type = string(field['type']);
    final required = field['required'] == true;
    final label = string(field['label'], key);
    if (_selectTypes.contains(type)) {
      final options = _options(field);
      final selected = options.containsKey(_choices[key])
          ? _choices[key]
          : null;
      return DropdownButtonFormField<String>(
        initialValue: selected,
        isExpanded: true,
        decoration: InputDecoration(
          labelText: label,
          helperText: options.isEmpty && required
              ? 'Сначала добавьте связанную запись'
              : null,
        ),
        items: [
          if (!required)
            const DropdownMenuItem(value: '', child: Text('Не выбрано')),
          for (final option in options.entries)
            DropdownMenuItem(
              value: option.key,
              child: Text(option.value, overflow: TextOverflow.ellipsis),
            ),
        ],
        onChanged: _saving ? null : (value) => _choices[key] = value,
        validator: (value) => required && (value == null || value.isEmpty)
            ? 'Выберите значение'
            : null,
      );
    }
    final controller = _controllers[key]!;
    return TextFormField(
      controller: controller,
      enabled: !_saving,
      readOnly: type == 'date',
      onTap: type == 'date' ? () => _pickDate(controller) : null,
      minLines: type == 'textarea' ? 2 : 1,
      maxLines: type == 'textarea' ? 5 : 1,
      maxLength: field['max_length'] as int?,
      keyboardType: type == 'integer' || type == 'decimal'
          ? TextInputType.numberWithOptions(decimal: type == 'decimal')
          : null,
      textCapitalization: type == 'text' || type == 'textarea'
          ? TextCapitalization.sentences
          : TextCapitalization.none,
      decoration: InputDecoration(
        labelText: label,
        suffixIcon: type == 'date'
            ? IconButton(
                onPressed: _saving ? null : () => _pickDate(controller),
                tooltip: 'Выбрать дату',
                icon: const Icon(Icons.calendar_today_outlined),
              )
            : null,
      ),
      validator: (input) {
        final value = (input ?? '').trim();
        if (value.isEmpty) return required ? 'Заполните поле' : null;
        if (type == 'integer' || type == 'decimal') {
          final number = type == 'integer'
              ? int.tryParse(value)
              : double.tryParse(value.replaceAll(',', '.'));
          if (number == null || !number.isFinite) return 'Введите число';
          if (number < (field['min'] as num? ?? 0) ||
              number > (field['max'] as num? ?? 1000000000)) {
            return 'Значение вне диапазона';
          }
        }
        return null;
      },
    );
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: Text(
        widget.record == null
            ? 'Новая запись'
            : string(widget.record?['title'], 'Запись'),
      ),
    ),
    body: SafeArea(
      child: Form(
        key: _form,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            if (!widget.writable) ...[
              for (final field in _fields)
                if (widget.record?[field['key']] != null &&
                    widget.record![field['key']].toString().isNotEmpty)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(string(field['label'])),
                    subtitle: Text(
                      _selectTypes.contains(field['type'])
                          ? (_options(field)[widget.record![field['key']]
                                    .toString()] ??
                                'Недоступно')
                          : widget.record![field['key']].toString(),
                    ),
                  ),
              if (_status != null)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Статус'),
                  subtitle: Text(string(_statuses[_status])),
                ),
            ] else ...[
              for (final field in _fields)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: _field(field),
                ),
              DropdownButtonFormField<String>(
                initialValue: _status,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Статус'),
                items: [
                  for (final entry in _statuses.entries)
                    DropdownMenuItem(
                      value: entry.key,
                      child: Text(string(entry.value)),
                    ),
                ],
                onChanged: _saving ? null : (value) => _status = value,
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(
                    _error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              const SizedBox(height: 14),
              FilledButton(
                onPressed: _saving ? null : _save,
                child: Text(_saving ? 'Сохраняем…' : 'Сохранить'),
              ),
            ],
          ],
        ),
      ),
    ),
  );
}

class _WeightPage extends StatelessWidget {
  const _WeightPage({required this.series});
  final List<Json> series;

  @override
  Widget build(BuildContext context) {
    final byAthlete = <Object?, List<Json>>{};
    for (final row in series) {
      byAthlete.putIfAbsent(row['athlete_id'], () => []).add(row);
    }
    return Scaffold(
      appBar: AppBar(title: const Text('Динамика веса')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            for (final group in byAthlete.values) ...[
              Text(
                string(group.first['athlete_title'], 'Подопечный'),
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 6),
              Card(
                child: Column(
                  children: [
                    for (final row in group.reversed.take(10))
                      ListTile(
                        title: Text(string(row['date'])),
                        trailing: Text('${row['weight_kg']} кг'),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
            ],
          ],
        ),
      ),
    );
  }
}
