import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import 'api.dart';
import 'session.dart';

part 'help_request.dart';
part 'help_match.dart';
part 'help_settings.dart';

class HelpPage extends StatefulWidget {
  const HelpPage({
    super.key,
    required this.session,
    required this.onSignIn,
    required this.onChat,
  });

  final HPointSession session;
  final VoidCallback onSignIn;
  final void Function(int requestId, {int? chatId}) onChat;

  @override
  State<HelpPage> createState() => _HelpPageState();
}

enum _HelpTab { open, mine, invites }

class _HelpPageState extends State<HelpPage> {
  _HelpTab _tab = _HelpTab.open;
  String _query = '';
  String? _category;
  List<Json>? _open;
  List<Json>? _offers;
  String? _error;
  int? _owner;
  int _generation = 0;

  HPointSession get session => widget.session;

  @override
  void initState() {
    super.initState();
    session.addListener(_sessionChanged);
    _owner = _currentOwner;
    if (_owner != null) Future.microtask(_loadRemote);
  }

  @override
  void didUpdateWidget(covariant HelpPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.session != session) {
      oldWidget.session.removeListener(_sessionChanged);
      session.addListener(_sessionChanged);
      _sessionChanged();
    }
  }

  @override
  void dispose() {
    session.removeListener(_sessionChanged);
    super.dispose();
  }

  int? get _currentOwner =>
      session.signedIn ? integer(object(session.data?['user'])['id']) : null;

  void _sessionChanged() {
    if (!mounted) return;
    final owner = _currentOwner;
    if (_owner == owner) {
      setState(() {});
      return;
    }
    _generation++;
    setState(() {
      _owner = owner;
      _tab = _HelpTab.open;
      _open = null;
      _offers = null;
      _error = null;
    });
    if (owner != null) _loadRemote();
  }

  Future<void> _loadRemote() async {
    if (!mounted || !session.signedIn) return;
    final generation = ++_generation;
    try {
      final results = await Future.wait([
        session.api.get('/api/requests', {'open': '1'}),
        session.api.get('/api/helper/offers'),
      ]);
      if (!mounted || generation != _generation) return;
      setState(() {
        _open = rows(results[0]['requests']);
        _offers = rows(results[1]['offers']);
        _error = null;
      });
    } catch (error) {
      if (mounted && generation == _generation) {
        setState(() => _error = error.toString());
      }
    }
  }

  Future<void> _refresh() async {
    try {
      await session.refresh();
      if (mounted && !session.signedIn) setState(() => _error = null);
      await _loadRemote();
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    }
  }

  Future<void> _create() async {
    if (!session.signedIn) {
      widget.onSignIn();
      return;
    }
    if (await openHelpRequestForm(context, session) == true && mounted) {
      setState(() => _tab = _HelpTab.mine);
      await _refresh();
    }
  }

  Future<void> _settings() async {
    if (!session.signedIn) {
      widget.onSignIn();
      return;
    }
    if (await openHelpSettings(context, session) == true && mounted) {
      await _refresh();
    }
  }

  Future<void> _detail(Json request, {bool invitation = false}) async {
    final requestId = integer(request[invitation ? 'request_id' : 'id']);
    if (requestId <= 0) return;
    final owner =
        session.signedIn &&
        integer(request['requester_id']) == _owner &&
        _tab == _HelpTab.mine;
    final participant = _tab == _HelpTab.mine && session.signedIn;
    final result = await Navigator.of(context).push<_HelpResult>(
      MaterialPageRoute(
        builder: (_) => _RequestDetail(
          session: session,
          request: request,
          requestId: requestId,
          owner: owner,
          participant: participant,
          invitation: invitation,
        ),
      ),
    );
    if (!mounted) return;
    if (result?.signIn == true) {
      widget.onSignIn();
      return;
    }
    if (result?.openChat == true) {
      widget.onChat(requestId, chatId: result?.chatId);
    }
    if (session.signedIn) await _refresh();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final mine = rows(session.data?['requests']);
    final user = object(session.data?['user']);
    final categories = _helpCategories(session);
    final raw = switch (_tab) {
      _HelpTab.mine => mine,
      _HelpTab.invites => _offers ?? <Json>[],
      _HelpTab.open =>
        session.signedIn ? _open ?? <Json>[] : rows(session.guest?['requests']),
    };
    final query = _query.toLowerCase().trim();
    final items = raw.where((request) {
      if (_tab != _HelpTab.open) return true;
      if (_category != null && request['category'] != _category) return false;
      final fields =
          '${string(request['what'])} ${_categoryTitle(categories, request)}';
      return query.isEmpty || fields.toLowerCase().contains(query);
    }).toList();
    final waiting =
        _error == null &&
        session.signedIn &&
        (_tab == _HelpTab.open && _open == null ||
            _tab == _HelpTab.invites && _offers == null);
    final empty = switch (_tab) {
      _HelpTab.mine =>
        'Здесь появятся ваши заявки и помощь, которую вы выполняете.',
      _HelpTab.invites =>
        'Когда вас пригласят обсудить заявку, она появится здесь.',
      _HelpTab.open =>
        query.isNotEmpty || _category != null
            ? 'По этим условиям заявок нет. Попробуйте изменить фильтры.'
            : 'Сейчас нет подходящих открытых заявок. Попробуйте обновить список позже.',
    };

    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        key: const PageStorageKey('hpoint-help'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
        children: [
          Text(
            'Помощь',
            style: theme.textTheme.headlineMedium?.copyWith(
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 6),
          const Text('Найдите помощника или откликнитесь на задачу.'),
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              FilledButton.icon(
                onPressed: _create,
                icon: const Icon(Icons.add_rounded),
                label: const Text('Создать заявку'),
              ),
              OutlinedButton.icon(
                onPressed: _settings,
                icon: Icon(
                  user['helper_ready'] == true
                      ? Icons.check_circle_outline
                      : Icons.tune_rounded,
                ),
                label: const Text('Настроить помощь'),
              ),
            ],
          ),
          if (user['helper_ready'] == true) ...[
            const SizedBox(height: 8),
            Text(
              user['helper_busy'] == true
                  ? 'Вы выполняете помощь'
                  : 'Готовность помогать включена',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.primary,
              ),
            ),
          ],
          const SizedBox(height: 14),
          if (session.signedIn)
            Wrap(
              spacing: 7,
              runSpacing: 3,
              children: [
                _tabChip(_HelpTab.open, 'Открытые'),
                _tabChip(_HelpTab.mine, 'Мои заявки'),
                _tabChip(
                  _HelpTab.invites,
                  'Приглашения${_offers?.isNotEmpty == true ? ' · ${_offers!.length}' : ''}',
                ),
              ],
            ),
          if (_tab == _HelpTab.open) ...[
            const SizedBox(height: 10),
            TextField(
              onChanged: (value) => setState(() => _query = value),
              textInputAction: TextInputAction.search,
              decoration: const InputDecoration(
                labelText: 'Поиск по названию',
                prefixIcon: Icon(Icons.search_rounded),
              ),
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              initialValue: _category ?? '',
              decoration: const InputDecoration(
                labelText: 'Сфера помощи',
                prefixIcon: Icon(Icons.category_outlined),
              ),
              isExpanded: true,
              items: [
                const DropdownMenuItem(value: '', child: Text('Все сферы')),
                for (final entry in categories.entries)
                  DropdownMenuItem(
                    value: entry.key,
                    child: Text(entry.value, overflow: TextOverflow.ellipsis),
                  ),
              ],
              onChanged: (value) =>
                  setState(() => _category = value == '' ? null : value),
            ),
          ],
          const SizedBox(height: 14),
          if (_error != null)
            _HelpNotice(
              message: _error!,
              button: 'Обновить',
              onPressed: _refresh,
              icon: Icons.sync_problem_rounded,
            ),
          if (waiting)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            ),
          if (!waiting && items.isEmpty && _error == null)
            _HelpNotice(message: empty),
          for (final request in items)
            _RequestCard(
              request: request,
              categories: categories,
              onOpen: () =>
                  _detail(request, invitation: _tab == _HelpTab.invites),
            ),
        ],
      ),
    );
  }

  Widget _tabChip(_HelpTab tab, String title) => ChoiceChip(
    label: Text(title),
    selected: _tab == tab,
    onSelected: (_) {
      setState(() => _tab = tab);
      if (tab == _HelpTab.invites) _loadRemote();
    },
  );
}

Map<String, String> _helpCategories(HPointSession session) {
  final fromServer = {
    for (final row in rows(session.guest?['categories']))
      if (string(row['key']).isNotEmpty)
        string(row['key']): string(row['title']),
  };
  return fromServer.isEmpty ? _defaultHelpCategories : fromServer;
}

// These choices mirror the site for offline startup. The live catalog wins.
const _defaultHelpCategories = <String, String>{
  'carry': '📦 Перенос / переезд',
  'cleaning': '🧹 Уборка дома',
  'snow': '❄️ Снег и уборка территории',
  'repairs': '🛠️ Мелкий ремонт',
  'plumbing': '🚰 Сантехника',
  'electric': '💡 Электрика',
  'furniture': '🪑 Сборка мебели',
  'garden': '🌱 Сад и растения',
  'tools': '🔧 Инструменты / вещи',
  'shopping': '🛒 Покупки',
  'delivery': '📬 Доставка и поручения',
  'transport': '🚗 Транспорт',
  'pets': '🐾 Забота о животных',
  'elderly': '🤲 Помощь пожилым',
  'children': '🧸 Помощь с детьми',
  'accompany': '🚶 Сопровождение',
  'tech': '💻 Техника',
  'study': '📚 Учёба',
  'languages': '🌍 Языки и перевод',
  'documents': '📄 Документы и тексты',
  'design': '🎨 Дизайн и творчество',
  'sport': '🏃 Спорт и тренировки',
  'cooking': '🍳 Готовка',
  'sewing': '🧵 Шитьё и одежда',
  'photo': '📷 Фото и видео',
  'events': '🎈 Помощь на мероприятиях',
  'volunteering': '💚 Волонтёрство',
  'other': '🧩 Другое',
};

String _categoryTitle(Map<String, String> categories, Json request) => string(
  request['category_name'],
  categories[string(request['category'])] ?? 'Другое',
);

String _statusTitle(Json request) =>
    string(request['status_title'], switch (request['status']) {
      'in_progress' => 'В работе',
      'done' => 'Завершена',
      'cancelled' => 'Отменена',
      _ => 'Ожидает помощника',
    });

String _requestReward(Json request) => integer(request['reward_rub']) > 0
    ? '${integer(request['reward_rub'])} тестовых ₽'
    : 'Без оплаты';

String _requestTime(BuildContext context, Json request) {
  final scheduled = DateTime.tryParse(string(request['scheduled_at']))
      ?.toLocal();
  if (scheduled == null) return string(request['time_needed']);
  final material = MaterialLocalizations.of(context);
  return '${material.formatShortDate(scheduled)} · ${material.formatTimeOfDay(TimeOfDay.fromDateTime(scheduled), alwaysUse24HourFormat: true)}';
}

void _helpToast(BuildContext context, String message) =>
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));

class _HelpNotice extends StatelessWidget {
  const _HelpNotice({
    required this.message,
    this.button,
    this.onPressed,
    this.icon = Icons.info_outline_rounded,
  });
  final String message;
  final String? button;
  final VoidCallback? onPressed;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Card.filled(
      color: colors.surfaceContainerHigh,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: colors.primary, size: 20),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(message),
                  if (button != null)
                    TextButton(onPressed: onPressed, child: Text(button!)),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _RequestCard extends StatelessWidget {
  const _RequestCard({
    required this.request,
    required this.categories,
    required this.onOpen,
  });
  final Json request;
  final Map<String, String> categories;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final author = string(request['requester_name']);
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        onTap: onOpen,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _categoryTitle(categories, request),
                      style: theme.textTheme.labelMedium?.copyWith(
                        color: theme.colorScheme.primary,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      string(request['what'], 'Заявка о помощи'),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      [
                        if (author.isNotEmpty) author,
                        _requestReward(request),
                        if (request['status'] != null &&
                            request['status'] != 'open')
                          _statusTitle(request),
                      ].join(' · '),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Icon(Icons.chevron_right_rounded),
            ],
          ),
        ),
      ),
    );
  }
}

class _HelpResult {
  const _HelpResult({this.openChat = false, this.chatId, this.signIn = false});
  final bool openChat;
  final int? chatId;
  final bool signIn;
}

Future<bool> _confirmHelp(
  BuildContext context,
  String title,
  String description,
  String action,
) async =>
    await showDialog<bool>(
      context: context,
      builder: (dialog) => AlertDialog(
        title: Text(title),
        content: Text(description),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialog, false),
            child: const Text('Назад'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialog, true),
            child: Text(action),
          ),
        ],
      ),
    ) ==
    true;
