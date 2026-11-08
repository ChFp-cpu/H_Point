import 'package:flutter/material.dart';

import 'api.dart';
import 'profile.dart';
import 'session.dart';

String _date(BuildContext context, dynamic value) {
  final date = DateTime.tryParse(string(value))?.toLocal();
  if (date == null) return '';
  final locale = MaterialLocalizations.of(context);
  return '${locale.formatMediumDate(date)}, ${locale.formatTimeOfDay(TimeOfDay.fromDateTime(date), alwaysUse24HourFormat: true)}';
}

class ActivitiesPage extends StatefulWidget {
  const ActivitiesPage({
    super.key,
    required this.session,
    required this.active,
    required this.onSignIn,
    required this.onWork,
  });
  final HPointSession session;
  final bool active;
  final VoidCallback onSignIn, onWork;

  @override
  State<ActivitiesPage> createState() => _ActivitiesPageState();
}

class _ActivitiesPageState extends State<ActivitiesPage> {
  List<Json>? _events;
  String? _error;
  int? _busyEvent;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    if (widget.active) _load();
  }

  @override
  void didUpdateWidget(covariant ActivitiesPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.active && !oldWidget.active) _load();
  }

  Future<void> _load() async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final api = widget.session.api;
      final result = await api.get(
        widget.session.signedIn ? '/api/events' : '/api/guest',
      );
      if (mounted) setState(() => _events = rows(result['events']));
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _join(Json event) async {
    if (!widget.session.signedIn) {
      widget.onSignIn();
      return;
    }
    final id = integer(event['id']);
    final leaving = event['joined'] == true;
    setState(() => _busyEvent = id);
    try {
      await widget.session.api.post(
        '/api/events/${leaving ? 'leave' : 'join'}',
        {'event_id': id},
      );
      await _load();
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    } finally {
      if (mounted) setState(() => _busyEvent = null);
    }
  }

  Future<void> _participants(Json event) async {
    if (!widget.session.signedIn) {
      widget.onSignIn();
      return;
    }
    final future = widget.session.api.get('/api/events/participants', {
      'id': '${integer(event['id'])}',
    });
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: FutureBuilder<Json>(
          future: future,
          builder: (context, snapshot) {
            final participants = rows(snapshot.data?['participants']);
            return ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.fromLTRB(16, 4, 16, 20),
              children: [
                Text(
                  'Участники',
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                if (snapshot.connectionState != ConnectionState.done)
                  const LinearProgressIndicator()
                else if (snapshot.hasError)
                  ListTile(title: Text('${snapshot.error}'))
                else if (participants.isEmpty)
                  const ListTile(title: Text('Пока никто не записался'))
                else
                  for (final participant in participants)
                    ListTile(
                      leading: const Icon(Icons.person_outline),
                      title: Text(string(participant['name'], 'Участник')),
                    ),
              ],
            );
          },
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final events = _events ?? rows(widget.session.guest?['events']);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
        children: [
          Text('Активности', style: theme.textTheme.headlineMedium),
          const SizedBox(height: 12),
          Card(
            child: ListTile(
              leading: const Icon(Icons.storefront_outlined),
              title: const Text('Услуги специалистов'),
              trailing: const Icon(Icons.chevron_right),
              onTap: widget.onWork,
            ),
          ),
          const SizedBox(height: 18),
          Text('Мероприятия', style: theme.textTheme.titleLarge),
          const SizedBox(height: 8),
          if (_loading) const LinearProgressIndicator(),
          if (_error != null)
            ListTile(
              title: Text(_error!),
              trailing: IconButton(
                tooltip: 'Повторить',
                onPressed: _load,
                icon: const Icon(Icons.refresh),
              ),
            ),
          if (!_loading && _error == null && events.isEmpty)
            const ListTile(title: Text('Пока нет предстоящих мероприятий')),
          for (final event in events)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        string(event['title'], 'Мероприятие'),
                        style: theme.textTheme.titleMedium,
                      ),
                      Text(_date(context, event['starts_at'])),
                      if (string(event['place']).isNotEmpty)
                        Text(string(event['place'])),
                      if (string(event['description']).isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 6),
                          child: Text(string(event['description'])),
                        ),
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        runSpacing: 4,
                        children: [
                          if (event['is_creator'] != true &&
                              (event['status'] == null ||
                                  event['status'] == 'published'))
                            FilledButton.tonal(
                              onPressed: _busyEvent == null && !_loading
                                  ? () => _join(event)
                                  : null,
                              child: Text(
                                event['joined'] == true
                                    ? 'Отменить запись'
                                    : 'Записаться',
                              ),
                            ),
                          TextButton.icon(
                            onPressed: () => _participants(event),
                            icon: const Icon(Icons.people_outline),
                            label: Text(
                              'Участники · ${integer(event['participant_count'])}',
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class WorkPage extends StatefulWidget {
  const WorkPage({super.key, required this.session, required this.onSignIn});
  final HPointSession session;
  final VoidCallback onSignIn;

  @override
  State<WorkPage> createState() => _WorkPageState();
}

class _WorkPageState extends State<WorkPage> {
  Json? _summary;
  List<Json>? _services;
  String? _error;
  bool _loading = false;
  int? _owner;

  @override
  void initState() {
    super.initState();
    widget.session.addListener(_accountChanged);
    _load();
  }

  @override
  void dispose() {
    widget.session.removeListener(_accountChanged);
    super.dispose();
  }

  void _accountChanged() {
    if (widget.session.data?['current_user_id'] != _owner) {
      setState(() => _summary = null);
      if (!_loading) _load();
    }
  }

  Future<void> _load() async {
    if (_loading) return;
    _owner = widget.session.data?['current_user_id'] as int?;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final public = await widget.session.api.get('/api/guest');
      if (mounted) setState(() => _services = rows(public['services']));
      if (_owner != null && _owner == widget.session.data?['current_user_id']) {
        final result = await widget.session.api.get('/api/commercial/summary');
        if (mounted && _owner == widget.session.data?['current_user_id']) {
          setState(() => _summary = object(result['summary']));
        }
      }
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) {
        setState(() => _loading = false);
        _accountChanged();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final metrics = object(_summary?['metrics']);
    final services = _services ?? rows(widget.session.guest?['services']);
    return Scaffold(
      appBar: AppBar(title: const Text('Для работы')),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.all(16),
            children: [
              if (_loading) const LinearProgressIndicator(),
              if (_error != null)
                ListTile(
                  title: Text(_error!),
                  trailing: IconButton(
                    tooltip: 'Повторить',
                    onPressed: _load,
                    icon: const Icon(Icons.refresh),
                  ),
                ),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        string(_summary?['title'], 'Кабинет для работы'),
                        style: theme.textTheme.titleLarge,
                      ),
                      const SizedBox(height: 8),
                      if (_summary?['exists'] == true) ...[
                        Text(string(_summary?['kind_title'])),
                        if (_summary?['active'] == true)
                          Text(
                            'Доступ ещё ${integer(_summary?['days_remaining'])} дн.',
                          ),
                        const SizedBox(height: 8),
                        Text(
                          'Клиенты: ${integer(metrics['clients'])} · Услуги: ${integer(metrics['services'])} · Записи: ${integer(metrics['planned'])}',
                        ),
                        for (final next in rows(_summary?['next_appointments']))
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text(string(next['title'])),
                            subtitle: Text(_date(context, next['starts_at'])),
                          ),
                      ] else
                        const Text(
                          'Кабинеты для тренеров, мастеров и организаций: клиенты, записи и услуги.',
                        ),
                      const SizedBox(height: 10),
                      FilledButton.tonalIcon(
                        onPressed: widget.session.signedIn
                            ? () => openHPointSite(context, '/#/work')
                            : widget.onSignIn,
                        icon: Icon(
                          widget.session.signedIn
                              ? Icons.open_in_new
                              : Icons.login,
                        ),
                        label: Text(
                          widget.session.signedIn
                              ? 'Открыть кабинет на сайте'
                              : 'Войти по email',
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 18),
              Text('Услуги специалистов', style: theme.textTheme.titleLarge),
              const SizedBox(height: 8),
              if (!_loading && services.isEmpty)
                const ListTile(title: Text('Пока нет опубликованных услуг')),
              for (final service in services)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Card(
                    child: ListTile(
                      title: Text(string(service['title'], 'Услуга')),
                      subtitle: Text(
                        [
                          string(service['organization_title']),
                          string(service['description']),
                        ].where((text) => text.isNotEmpty).join('\n'),
                      ),
                      trailing: const Icon(Icons.open_in_new),
                      onTap: () => openHPointSite(
                        context,
                        string(service['organization_url'], '/#/work'),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
