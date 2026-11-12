import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'api.dart';
import 'work_state.dart';

part 'work_operations_form.dart';

const _bookingStatuses = {
  'planned': 'Запланировано',
  'completed': 'Выполнено',
  'cancelled': 'Отменено',
};

final _pendingRenewals = Expando<Map<int, String>>();

enum _WorkRecord {
  profile('Настройки кабинета', 'Создать кабинет'),
  clients('Клиенты', 'Добавить клиента'),
  services('Услуги', 'Добавить услугу'),
  bookings('Записи', 'Новая запись'),
  subscription('Доступ к кабинету', '');

  const _WorkRecord(this.title, this.createLabel);

  final String title;
  final String createLabel;

  String get path => '/api/commercial/$name';
}

/// Native editors and lists for the core workspace records.
class WorkOperationsPage extends StatefulWidget {
  const WorkOperationsPage({
    super.key,
    required this.model,
    required this.section,
  });

  final WorkModel model;
  final String section;

  @override
  State<WorkOperationsPage> createState() => _WorkOperationsPageState();
}

class _WorkOperationsPageState extends State<WorkOperationsPage> {
  late final _WorkRecord _section = _WorkRecord.values.byName(widget.section);
  final _search = TextEditingController();
  String _filter = 'active';
  bool _busy = false;
  String? _error;

  WorkModel get _model => widget.model;
  Json get _data => _model.data;
  Json get _profile => object(_data['profile']);
  Json get _permissions => object(_data['permissions']);
  bool get _active => _profile['active'] == true;
  bool get _manage => _permissions['manage'] == true;
  bool get _owner => _permissions['owner'] == true;
  bool get _canEdit =>
      _model.error == null &&
      !_model.loading &&
      _active &&
      (_section == _WorkRecord.bookings
          ? _permissions['write'] == true
          : _manage);

  @override
  void initState() {
    super.initState();
    if (_section == _WorkRecord.bookings) _filter = 'planned';
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  Future<void> _edit(_WorkRecord section, [Json row = const {}]) async {
    final account = integer(_model.session.data?['current_user_id']);
    final ownerId = section == _WorkRecord.profile && row.isEmpty
        ? account
        : _model.ownerId;
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => _OperationsForm(
          model: _model,
          account: account,
          ownerId: ownerId,
          section: section,
          row: row,
        ),
      ),
    );
  }

  Future<void> _run(Future<void> Function() action) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await action();
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _confirm(String title, String body, String action) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text(title),
          content: Text(body),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Назад'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: Text(action),
            ),
          ],
        ),
      ) ??
      false;

  Future<void> _changeBookingStatus(Json row, String status) async {
    final ownerId = _model.ownerId;
    if (status == 'cancelled' &&
        !await _confirm(
          'Отменить запись?',
          string(row['title'], 'Запись останется в истории.'),
          'Отменить запись',
        )) {
      return;
    }
    if (!mounted) return;
    await _run(() async {
      await _model.update('/api/commercial/bookings/status', {
        'id': row['id'],
        'status': status,
        'owner_id': ownerId,
      });
    });
  }

  Future<void> _renew(int price) async {
    final ownerId = _model.ownerId;
    if (ownerId == null) return;
    if (!await _confirm(
          'Продлить доступ на 30 дней?',
          'Из тестового кошелька спишется ${_workMoney(price)}.',
          'Продлить',
        ) ||
        !mounted) {
      return;
    }
    final renewalKeys = _pendingRenewals[_model] ??= {};
    final key = renewalKeys.putIfAbsent(ownerId, () {
      final random = Random.secure();
      return 'mobile:${List.generate(16, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join()}';
    });
    await _run(() async {
      await _model.update('/api/commercial/renew', {
        'owner_id': ownerId,
        'purchase_key': key,
      });
      renewalKeys.remove(ownerId);
      try {
        await _model.session.refresh();
      } on ApiException {
        // Access has already been updated. A wallet refresh can be retried.
      }
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('Доступ продлён')));
      }
    });
  }

  Future<void> _deleteProfile() async {
    final ownerId = _model.ownerId;
    if (!await _confirm(
          'Удалить рабочий кабинет?',
          'Клиенты, записи, услуги, задачи и другие данные кабинета будут удалены.',
          'Удалить кабинет',
        ) ||
        !mounted) {
      return;
    }
    await _run(() async {
      await _model.update('/api/commercial/delete', {
        'owner_id': ownerId,
        'confirm': true,
      });
      if (mounted) Navigator.of(context).pop();
    });
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _model,
      builder: (context, _) {
        final settings =
            _section == _WorkRecord.profile ||
            _section == _WorkRecord.subscription;
        final loading = _data.isEmpty && _model.loading;
        final failed = _data.isEmpty && _model.error != null;
        return Scaffold(
          appBar: AppBar(title: Text(_section.title)),
          body: SafeArea(
            child: loading
                ? const Center(child: CircularProgressIndicator())
                : failed
                ? _loadFailure(context)
                : RefreshIndicator(
                    onRefresh: () => _run(_model.reload),
                    child: settings ? _settings(context) : _records(context),
                  ),
          ),
        );
      },
    );
  }

  Widget _loadFailure(BuildContext context) => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      _WorkPanel(
        title: 'Кабинет не загрузился',
        details: [_model.error!],
        actions: [
          OutlinedButton(
            onPressed: _model.reload,
            child: const Text('Повторить'),
          ),
        ],
      ),
    ],
  );

  List<Widget> _feedback(BuildContext context) => [
    if (_busy) const LinearProgressIndicator(),
    if ((_error ?? _model.error) case final message?)
      Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Text(
          message,
          style: TextStyle(color: Theme.of(context).colorScheme.error),
        ),
      ),
  ];

  Widget _settings(BuildContext context) {
    final price = integer(_data['price_rub']);
    final trialDays = integer(_data['trial_days']);
    final wallet = object(_model.session.data?['wallet']);
    final renewals = rows(_data['renewals']);
    final showProfile = _section == _WorkRecord.profile;
    final profile = _profile;
    final active = _active;
    final pending = _busy || _model.loading || _model.error != null;
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        ..._feedback(context),
        if (profile.isEmpty) ...[
          _WorkPanel(
            title: 'Ваш рабочий кабинет',
            details: [
              if (_data['trial_available'] == true && trialDays > 0)
                '$trialDays дней пробного доступа.',
              if (_data['trial_available'] == false)
                'При повторном создании сохранится прежний срок доступа.',
            ],
            actions: [
              FilledButton.icon(
                onPressed: pending ? null : () => _edit(_WorkRecord.profile),
                icon: const Icon(Icons.add_rounded),
                label: const Text('Создать кабинет'),
              ),
            ],
          ),
        ] else ...[
          if (showProfile)
            _WorkPanel(
              title: string(profile['title'], 'Организация'),
              details: [
                string(profile['kind_title']),
                string(profile['description']),
                string(profile['contact']),
              ],
              actions: [
                if (_manage && active)
                  OutlinedButton.icon(
                    onPressed: pending
                        ? null
                        : () => _edit(_WorkRecord.profile, profile),
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('Изменить профиль'),
                  ),
              ],
            ),
          const SizedBox(height: 12),
          _WorkPanel(
            title: active
                ? profile['trial_active'] == true
                      ? 'Пробный доступ'
                      : 'Доступ активен'
                : 'Доступ закончился',
            details: [
              if (profile['access_until'] != null)
                'Доступ до ${_workDate(context, profile['access_until'], withTime: false)}',
              if (price > 0) '${_workMoney(price)} за 30 дней.',
              if (_owner && wallet['test_balance_rub'] != null)
                'В кошельке ${_workMoney(wallet['test_balance_rub'])}.',
              if (!_owner && !active) 'Продлить доступ может владелец.',
            ],
            actions: [
              if (_owner && price > 0)
                FilledButton.icon(
                  onPressed: pending ? null : () => _renew(price),
                  icon: const Icon(Icons.refresh_rounded),
                  label: const Text('Продлить доступ'),
                ),
            ],
          ),
          if (renewals.isNotEmpty) ...[
            const SizedBox(height: 16),
            Text('Продления', style: Theme.of(context).textTheme.titleMedium),
            for (final row in renewals)
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.history),
                title: Text(_workMoney(row['price_rub'])),
                subtitle: Text(
                  'До ${_workDate(context, row['ends_at'], withTime: false)}',
                ),
              ),
          ],
          if (showProfile && _owner) ...[
            const SizedBox(height: 20),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: TextButton(
                style: TextButton.styleFrom(
                  foregroundColor: Theme.of(context).colorScheme.error,
                ),
                onPressed: pending ? null : _deleteProfile,
                child: const Text('Удалить кабинет'),
              ),
            ),
          ],
        ],
      ],
    );
  }

  Widget _records(BuildContext context) {
    final bookings = _section == _WorkRecord.bookings;
    final clients = _section == _WorkRecord.clients;
    final allRows = rows(_data[_section.name]);
    final query = _search.text.trim().toLowerCase();
    final records = allRows.where((row) {
      final status = bookings
          ? row['status']
          : _enabled(row['active'])
          ? 'active'
          : 'archived';
      if (_filter.isNotEmpty && status != _filter) return false;
      if (query.isEmpty) return true;
      return [
        'title',
        'name',
        'client_name',
        'contact',
        'notes',
        'description',
      ].any((key) => string(row[key]).toLowerCase().contains(query));
    }).toList();
    final hasClients = rows(_data['clients'])
        .any((row) => _enabled(row['active']));
    final total = integer(object(_data['record_counts'])[_section.name]);
    final filters = bookings
        ? const {
            '': 'Все',
            'planned': 'В плане',
            'completed': 'Готово',
            'cancelled': 'Отменено',
          }
        : const {'': 'Все', 'active': 'Активные', 'archived': 'В архиве'};
    return ListView.builder(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      itemCount: records.length + 1,
      itemBuilder: (context, index) {
        if (index != 0) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: _recordCard(context, records[index - 1]),
          );
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ..._feedback(context),
            if (_profile.isNotEmpty && !_active)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: OutlinedButton.icon(
                  onPressed: () => Navigator.of(context).push(
                    MaterialPageRoute<void>(
                      builder: (_) => WorkOperationsPage(
                        model: _model,
                        section: 'subscription',
                      ),
                    ),
                  ),
                  icon: const Icon(Icons.lock_clock_outlined),
                  label: const Text('Доступ закончился'),
                ),
              ),
            if (_canEdit)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: FilledButton.icon(
                  onPressed: _busy || (bookings && !hasClients && !_manage)
                      ? null
                      : () => _edit(
                          bookings && !hasClients
                              ? _WorkRecord.clients
                              : _section,
                        ),
                  icon: const Icon(Icons.add_rounded),
                  label: Text(
                    bookings && !hasClients
                        ? 'Сначала добавьте клиента'
                        : _section.createLabel,
                  ),
                ),
              ),
            if (allRows.isNotEmpty) ...[
              if (total > allRows.length)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text('Загружено ${allRows.length} из $total записей'),
                ),
              TextField(
                controller: _search,
                decoration: InputDecoration(
                  labelText: clients
                      ? 'Поиск клиента'
                      : bookings
                      ? 'Поиск записи'
                      : 'Поиск услуги',
                  prefixIcon: const Icon(Icons.search),
                ),
                textInputAction: TextInputAction.search,
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                children: [
                  for (final option in filters.entries)
                    ChoiceChip(
                      label: Text(option.value),
                      selected: _filter == option.key,
                      onSelected: (_) => setState(() => _filter = option.key),
                    ),
                ],
              ),
              const SizedBox(height: 12),
            ],
            if (records.isEmpty)
              _WorkPanel(
                title: allRows.isNotEmpty
                    ? 'Ничего не найдено'
                    : clients
                    ? 'Клиентов пока нет'
                    : bookings
                    ? 'Записей пока нет'
                    : 'Услуг пока нет',
                details: [
                  if (allRows.isNotEmpty) 'Измените поиск или фильтр.',
                  if (bookings && !hasClients)
                    'Для записи нужен активный клиент.',
                ],
              ),
          ],
        );
      },
    );
  }

  Widget _recordCard(BuildContext context, Json row) {
    final bookings = _section == _WorkRecord.bookings;
    final services = _section == _WorkRecord.services;
    final archived = !bookings && !_enabled(row['active']);
    final published = _enabled(row['published']);
    final canPublish =
        services &&
        _manage &&
        _model.error == null &&
        !_model.loading &&
        (published ||
            (_active &&
                !archived &&
                object(_data['public_profile'])['published'] == true));
    return _WorkPanel(
      title: string(row['title'] ?? row['name'], 'Без названия'),
      badge: bookings
          ? _bookingStatuses[row['status']]
          : archived
          ? 'В архиве'
          : published
          ? 'Опубликовано'
          : null,
      details: [
        if (bookings) ...[
          _workDate(context, row['starts_at']),
          [
            string(row['client_name']),
            string(row['assignee_name']),
            string(row['object_title']),
          ].where((value) => value.isNotEmpty).join(' · '),
        ],
        if (bookings || services)
          '${_workMoney(row['price_rub'])} · ${integer(row['duration_minutes'])} мин',
        string(row['contact']),
        string(row['description']),
        string(row['notes']),
      ],
      actions: [
        if (_canEdit)
          OutlinedButton(
            onPressed: _busy ? null : () => _edit(_section, row),
            child: const Text('Изменить'),
          ),
        if (_canEdit && bookings && row['status'] == 'planned') ...[
          FilledButton.tonal(
            onPressed: _busy
                ? null
                : () => _changeBookingStatus(row, 'completed'),
            child: const Text('Выполнено'),
          ),
          TextButton(
            onPressed: _busy
                ? null
                : () => _changeBookingStatus(row, 'cancelled'),
            child: const Text('Отменить'),
          ),
        ],
        if (canPublish)
          TextButton(
            onPressed: _busy
                ? null
                : () => _run(() async {
                    await _model.update('/api/commercial/services/publish', {
                      'id': row['id'],
                      'published': !published,
                    });
                  }),
            child: Text(published ? 'Снять с публикации' : 'Опубликовать'),
          ),
      ],
    );
  }
}

bool _enabled(dynamic value) => value == true || value == 1;

String _workMoney(dynamic value) => '${integer(value)} тест. ₽';

String _workDate(BuildContext context, dynamic value, {bool withTime = true}) {
  final parsed = value is DateTime ? value : DateTime.tryParse(string(value));
  if (parsed == null) return 'Дата не указана';
  final local = parsed.toLocal();
  final locale = MaterialLocalizations.of(context);
  final date = locale.formatMediumDate(local);
  if (!withTime) return date;
  final time = locale.formatTimeOfDay(
    TimeOfDay.fromDateTime(local),
    alwaysUse24HourFormat: true,
  );
  return '$date, $time';
}

class _WorkPanel extends StatelessWidget {
  const _WorkPanel({
    required this.title,
    this.badge,
    this.details = const [],
    this.actions = const [],
  });

  final String title;
  final String? badge;
  final List<String> details;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: theme.textTheme.titleMedium),
            if (badge case final value?)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  value,
                  style: theme.textTheme.labelLarge?.copyWith(
                    color: theme.colorScheme.primary,
                  ),
                ),
              ),
            for (final detail in details.where((value) => value.isNotEmpty))
              Padding(
                padding: const EdgeInsets.only(top: 5),
                child: Text(
                  detail,
                  style: TextStyle(color: theme.colorScheme.onSurfaceVariant),
                ),
              ),
            if (actions.isNotEmpty) ...[
              const SizedBox(height: 12),
              Wrap(spacing: 8, runSpacing: 4, children: actions),
            ],
          ],
        ),
      ),
    );
  }
}
