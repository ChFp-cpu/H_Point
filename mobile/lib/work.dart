import 'package:flutter/material.dart';

import 'api.dart';
import 'session.dart';
import 'work_operations.dart';
import 'work_professional.dart';
import 'work_projects.dart';
import 'work_state.dart';
import 'work_team.dart';

String workDate(BuildContext context, dynamic value) {
  final date = DateTime.tryParse(string(value))?.toLocal();
  if (date == null) return '';
  final locale = MaterialLocalizations.of(context);
  return '${locale.formatMediumDate(date)}, ${locale.formatTimeOfDay(TimeOfDay.fromDateTime(date), alwaysUse24HourFormat: true)}';
}

class WorkPage extends StatefulWidget {
  const WorkPage({super.key, required this.session, required this.onSignIn});
  final HPointSession session;
  final VoidCallback onSignIn;

  @override
  State<WorkPage> createState() => _WorkPageState();
}

class _WorkPageState extends State<WorkPage> {
  late final _model = WorkModel(widget.session);
  late bool _catalog = !widget.session.signedIn;

  @override
  void initState() {
    super.initState();
    _model.reload();
  }

  @override
  void dispose() {
    _model.dispose();
    super.dispose();
  }

  void _open(String section) {
    final page = switch (section) {
      'projects' ||
      'tasks' ||
      'estimates' => WorkProjectsPage(model: _model, section: section),
      'team' ||
      'publication' ||
      'calendar' ||
      'inquiries' ||
      'my-inquiries' => WorkTeamPage(model: _model, section: section),
      'profession' => WorkProfessionalPage(model: _model),
      'performance' => _PerformancePage(model: _model),
      _ => WorkOperationsPage(model: _model, section: section),
    };
    Navigator.of(context).push(MaterialPageRoute<void>(builder: (_) => page));
  }

  Future<void> _chooseOrganization() async {
    final organizations = rows(_model.data['organizations']);
    final userId = widget.session.data?['current_user_id'];
    final choice = await showModalBottomSheet<int>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            for (final org in organizations)
              ListTile(
                leading: Icon(
                  org['owner_id'] == _model.ownerId
                      ? Icons.check_circle
                      : Icons.business_outlined,
                ),
                title: Text(string(org['title'], 'Организация')),
                subtitle: Text(switch (org['role']) {
                  'owner' => 'Владелец',
                  'admin' => 'Администратор',
                  _ => 'Участник',
                }),
                onTap: () => Navigator.pop(context, integer(org['owner_id'])),
              ),
            if (userId is int &&
                !organizations.any((org) => org['owner_id'] == userId))
              ListTile(
                leading: const Icon(Icons.add_business_outlined),
                title: const Text('Создать свой кабинет'),
                onTap: () => Navigator.pop(context, userId),
              ),
          ],
        ),
      ),
    );
    if (choice == null || !mounted) return;
    await _model.selectOrganization(choice);
    if (mounted && _model.error == null && _model.data['profile'] == null) {
      _open('profile');
    }
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: Listenable.merge([widget.session, _model]),
    builder: (context, _) => Scaffold(
      appBar: AppBar(title: const Text('Для работы')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 700),
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 6, 16, 10),
                  child: SizedBox(
                    width: double.infinity,
                    child: SegmentedButton<bool>(
                      segments: const [
                        ButtonSegment(
                          value: false,
                          label: Text('Кабинет'),
                          icon: Icon(Icons.work_outline_rounded),
                        ),
                        ButtonSegment(
                          value: true,
                          label: Text('Услуги'),
                          icon: Icon(Icons.storefront_outlined),
                        ),
                      ],
                      selected: {_catalog},
                      showSelectedIcon: false,
                      onSelectionChanged: (selected) =>
                          setState(() => _catalog = selected.single),
                    ),
                  ),
                ),
                Expanded(
                  child: _catalog
                      ? _ServiceCatalog(
                          session: widget.session,
                          onSignIn: widget.onSignIn,
                          onMyInquiries: () => _open('my-inquiries'),
                        )
                      : _workspace(context),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );

  Widget _workspace(BuildContext context) {
    if (!widget.session.signedIn) {
      return ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Кабинет для работы',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    'Клиенты, расписание, проекты и сметы специалистов и команд.',
                  ),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed: widget.onSignIn,
                    child: const Text('Войти по email'),
                  ),
                ],
              ),
            ),
          ),
        ],
      );
    }
    final data = _model.data;
    if (_model.loading && data.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_model.error != null && data.isEmpty) {
      return _WorkError(message: _model.error!, onRetry: _model.reload);
    }
    final profile = object(data['profile']);
    final metrics = object(data['metrics']);
    final profession = object(data['professional']);
    final invites = rows(data['incoming_invitations']).length;
    final inquiries = integer(data['incoming_count']);
    final upcoming = rows(data['bookings'])
        .where(
          (row) =>
              row['status'] == 'planned' &&
              (DateTime.tryParse(string(row['starts_at']))
                      ?.isAfter(DateTime.now()) ??
                  false),
        )
        .take(2);
    return RefreshIndicator(
      onRefresh: _model.reload,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
        children: [
          if (_model.error != null)
            ListTile(
              leading: const Icon(Icons.cloud_off_outlined),
              title: Text(_model.error!),
            ),
          if (profile.isEmpty) ...[
            Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Кабинет для работы',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      'Выберите профессию. Кабинет добавит нужные вам рабочие разделы.',
                    ),
                    if (data['trial_available'] == true)
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Text(
                          'Пробный период — ${integer(data['trial_days'])} дней',
                        ),
                      ),
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      onPressed: () => _open('profile'),
                      icon: const Icon(Icons.add),
                      label: const Text('Создать кабинет'),
                    ),
                    if (rows(data['organizations']).isNotEmpty)
                      TextButton(
                        onPressed: _chooseOrganization,
                        child: const Text('Открыть другой кабинет'),
                      ),
                  ],
                ),
              ),
            ),
          ] else ...[
            _WorkspaceHeader(
              profile: profile,
              metrics: metrics,
              onSwitch: _chooseOrganization,
              onAccess: () => _open('subscription'),
            ),
            if (upcoming.isNotEmpty) ...[
              const SizedBox(height: 14),
              _WorkSection(
                title: 'Ближайшие записи',
                entries: [
                  for (final row in upcoming)
                    _WorkEntry(
                      'bookings',
                      string(row['title'], 'Запись'),
                      Icons.schedule,
                      workDate(context, row['starts_at']),
                    ),
                ],
                onOpen: _open,
              ),
            ],
            const SizedBox(height: 14),
            _WorkSection(
              title: 'Клиенты и расписание',
              onOpen: _open,
              entries: [
                const _WorkEntry(
                  'calendar',
                  'Календарь',
                  Icons.calendar_month_outlined,
                  'Записи и смены',
                ),
                const _WorkEntry(
                  'bookings',
                  'Записи',
                  Icons.event_available_outlined,
                  'Приёмы и статусы',
                ),
                const _WorkEntry(
                  'clients',
                  'Клиенты',
                  Icons.people_outline,
                  'Карточки и контакты',
                ),
                const _WorkEntry(
                  'services',
                  'Мои услуги',
                  Icons.storefront_outlined,
                  'Цены и публикация',
                ),
                _WorkEntry(
                  'inquiries',
                  'Входящие обращения',
                  Icons.inbox_outlined,
                  inquiries == 0 ? '' : 'Новых: $inquiries',
                ),
              ],
            ),
            if (rows(profession['modules']).isNotEmpty ||
                rows(profession['history']).isNotEmpty) ...[
              const SizedBox(height: 14),
              _WorkSection(
                title: 'По профессии',
                onOpen: _open,
                entries: [
                  _WorkEntry(
                    'profession',
                    string(profile['kind_title'], 'Профильные записи'),
                    Icons.badge_outlined,
                    string(profession['description']),
                  ),
                ],
              ),
            ],
            const SizedBox(height: 14),
            _WorkSection(
              title: 'Проекты и команда',
              onOpen: _open,
              entries: [
                const _WorkEntry(
                  'projects',
                  'Объекты',
                  Icons.domain_outlined,
                  'Проекты, адреса и ответственные',
                ),
                const _WorkEntry(
                  'tasks',
                  'Задачи',
                  Icons.task_alt,
                  'Сроки и статусы',
                ),
                const _WorkEntry(
                  'estimates',
                  'Сметы',
                  Icons.request_quote_outlined,
                  'Расчёт, PDF и Excel',
                ),
                const _WorkEntry(
                  'performance',
                  'Результаты',
                  Icons.insights_outlined,
                  'Динамика и итоги за месяц',
                ),
                _WorkEntry(
                  'team',
                  'Команда',
                  Icons.groups_outlined,
                  invites == 0 ? 'Участники и роли' : 'Приглашений: $invites',
                ),
                const _WorkEntry(
                  'publication',
                  'Страница организации',
                  Icons.public,
                  'Описание и видимость',
                ),
                const _WorkEntry(
                  'profile',
                  'Настройки кабинета',
                  Icons.settings_outlined,
                ),
              ],
            ),
          ],
          if (profile.isEmpty && invites > 0) ...[
            const SizedBox(height: 14),
            _WorkSection(
              title: 'Команда',
              entries: [
                _WorkEntry(
                  'team',
                  'Приглашения',
                  Icons.mail_outline,
                  'Новых: $invites',
                ),
              ],
              onOpen: _open,
            ),
          ],
        ],
      ),
    );
  }
}

class _WorkspaceHeader extends StatelessWidget {
  const _WorkspaceHeader({
    required this.profile,
    required this.metrics,
    required this.onSwitch,
    required this.onAccess,
  });
  final Json profile, metrics;
  final VoidCallback onSwitch, onAccess;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final active = profile['active'] == true;
    final remaining = integer(profile['days_remaining']);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.primaryContainer,
        borderRadius: BorderRadius.circular(24),
      ),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              string(profile['kind_title'], 'Рабочий кабинет'),
              style: TextStyle(color: colors.onPrimaryContainer),
            ),
            const SizedBox(height: 4),
            Text(
              string(profile['title'], 'Мой кабинет'),
              style: theme.textTheme.headlineSmall?.copyWith(
                color: colors.onPrimaryContainer,
              ),
            ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                Chip(label: Text('${integer(metrics['clients'])} · Клиенты')),
                Chip(label: Text('${integer(metrics['planned'])} · В плане')),
                Chip(label: Text('${integer(metrics['completed'])} · Готово')),
              ],
            ),
            Wrap(
              spacing: 6,
              runSpacing: 4,
              children: [
                FilledButton.tonalIcon(
                  onPressed: onSwitch,
                  icon: const Icon(Icons.swap_horiz),
                  label: const Text('Кабинеты'),
                ),
                TextButton(
                  onPressed: onAccess,
                  child: Text(
                    active ? 'Доступ ещё $remaining дн.' : 'Продлить доступ',
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _WorkEntry {
  const _WorkEntry(this.key, this.title, this.icon, [this.subtitle = '']);
  final String key, title, subtitle;
  final IconData icon;
}

class _WorkSection extends StatelessWidget {
  const _WorkSection({
    required this.title,
    required this.entries,
    required this.onOpen,
  });
  final String title;
  final List<_WorkEntry> entries;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(4, 0, 4, 7),
        child: Text(title, style: Theme.of(context).textTheme.titleMedium),
      ),
      Card(
        child: Column(
          children: [
            for (final entry in entries)
              ListTile(
                leading: Icon(
                  entry.icon,
                  color: Theme.of(context).colorScheme.primary,
                ),
                title: Text(entry.title),
                subtitle: entry.subtitle.isEmpty ? null : Text(entry.subtitle),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => onOpen(entry.key),
              ),
          ],
        ),
      ),
    ],
  );
}

class _WorkError extends StatelessWidget {
  const _WorkError({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => ListView(
    padding: const EdgeInsets.all(16),
    children: [
      ListTile(
        leading: const Icon(Icons.cloud_off_outlined),
        title: Text(message),
      ),
      OutlinedButton.icon(
        onPressed: onRetry,
        icon: const Icon(Icons.refresh),
        label: const Text('Повторить'),
      ),
    ],
  );
}

class _ServiceCatalog extends StatefulWidget {
  const _ServiceCatalog({
    required this.session,
    required this.onSignIn,
    required this.onMyInquiries,
  });
  final HPointSession session;
  final VoidCallback onSignIn, onMyInquiries;

  @override
  State<_ServiceCatalog> createState() => _ServiceCatalogState();
}

class _ServiceCatalogState extends State<_ServiceCatalog> {
  List<Json>? _services;
  String? _error;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final data = await widget.session.api.get('/api/guest');
      if (mounted) {
        setState(() {
          _services = rows(data['services']);
          _error = null;
        });
      }
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final rowsToShow = (_services ?? rows(widget.session.guest?['services']))
        .where(
          (row) => [
            row['title'],
            row['organization_title'],
            row['description'],
          ].any((value) => string(value).toLowerCase().contains(_query)),
        );
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
        children: [
          if (!widget.session.signedIn)
            Card(
              child: ListTile(
                leading: const Icon(Icons.work_outline),
                title: const Text('Кабинет для работы'),
                subtitle: const Text('Войдите, чтобы открыть свой кабинет.'),
                onTap: widget.onSignIn,
              ),
            )
          else
            OutlinedButton.icon(
              onPressed: widget.onMyInquiries,
              icon: const Icon(Icons.outbox_outlined),
              label: const Text('Мои обращения'),
            ),
          const SizedBox(height: 12),
          TextField(
            onChanged: (value) =>
                setState(() => _query = value.trim().toLowerCase()),
            decoration: const InputDecoration(
              prefixIcon: Icon(Icons.search),
              labelText: 'Поиск услуг',
            ),
          ),
          const SizedBox(height: 12),
          if (_error != null)
            ListTile(
              title: Text(_error!),
              trailing: IconButton(
                tooltip: 'Повторить',
                onPressed: _load,
                icon: const Icon(Icons.refresh),
              ),
            )
          else if (_services == null)
            const LinearProgressIndicator()
          else if (rowsToShow.isEmpty)
            ListTile(
              title: Text(
                _query.isEmpty
                    ? 'Пока нет опубликованных услуг'
                    : 'По вашему запросу ничего не найдено',
              ),
            ),
          for (final service in rowsToShow)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Card(
                child: ListTile(
                  leading: const Icon(Icons.storefront_outlined),
                  title: Text(string(service['title'], 'Услуга')),
                  subtitle: Text(
                    '${string(service['organization_title'])}\n${integer(service['price_rub'])} тест. ₽ · ${integer(service['duration_minutes'])} мин',
                  ),
                  isThreeLine: true,
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => openWorkService(
                    context,
                    widget.session,
                    integer(service['id']),
                    onSignIn: widget.onSignIn,
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _PerformancePage extends StatelessWidget {
  const _PerformancePage({required this.model});
  final WorkModel model;

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: model,
    builder: (context, _) {
      final stats = object(model.data['performance']);
      final recent = rows(stats['series']).reversed
          .take(14)
          .toList()
          .reversed
          .toList();
      final maxCount = recent.fold<int>(
        1,
        (max, row) =>
            integer(row['completed']) > max ? integer(row['completed']) : max,
      );
      final theme = Theme.of(context);
      return Scaffold(
        appBar: AppBar(title: const Text('Результаты')),
        body: SafeArea(
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Text('Записи за 30 дней', style: theme.textTheme.titleLarge),
              const SizedBox(height: 8),
              Card(
                child: Column(
                  children: [
                    _result('Записей выполнено', stats['completed']),
                    _result(
                      'Доля выполненных записей',
                      '${integer(stats['completion_percent'])}%',
                    ),
                    _result('Выручка, тест. ₽', stats['revenue_test_rub']),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              Text('Задачи и сметы', style: theme.textTheme.titleMedium),
              const SizedBox(height: 8),
              Card(
                child: Column(
                  children: [
                    _result('Задач выполнено', stats['tasks_done']),
                    _result('Задач просрочено', stats['tasks_overdue']),
                    if (stats.containsKey('profit_total_rub'))
                      _result(
                        'Прибыль по сметам, тест. ₽',
                        stats['profit_total_rub'],
                      ),
                  ],
                ),
              ),
              if (recent.isNotEmpty) ...[
                const SizedBox(height: 16),
                Text(
                  'Выполненные записи за 14 дней',
                  style: theme.textTheme.titleMedium,
                ),
                const SizedBox(height: 10),
                SizedBox(
                  height: 105,
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      for (final row in recent)
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 2),
                            child: Tooltip(
                              message:
                                  '${row['date']}: ${integer(row['completed'])}',
                              child: Semantics(
                                label:
                                    '${row['date']}, записей ${integer(row['completed'])}',
                                child: Container(
                                  height:
                                      4 +
                                      100 *
                                          integer(row['completed']) /
                                          maxCount,
                                  decoration: BoxDecoration(
                                    color: integer(row['completed']) == 0
                                        ? theme.colorScheme.outlineVariant
                                        : theme.colorScheme.primary,
                                    borderRadius: const BorderRadius.vertical(
                                      top: Radius.circular(4),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
              if (rows(stats['by_member']).isNotEmpty) ...[
                const SizedBox(height: 18),
                Text('По участникам', style: theme.textTheme.titleMedium),
                for (final row in rows(stats['by_member']))
                  ListTile(
                    title: Text(string(row['name'], 'Участник')),
                    subtitle: Text(
                      'Записи: ${integer(row['bookings_completed'])} · Задачи: ${integer(row['tasks_done'])}',
                    ),
                  ),
              ],
            ],
          ),
        ),
      );
    },
  );

  Widget _result(String name, dynamic value) =>
      ListTile(title: Text(name), trailing: Text('${value ?? 0}'));
}
