part of 'help.dart';

class _HelpMatchPage extends StatefulWidget {
  const _HelpMatchPage({required this.session, required this.request});
  final HPointSession session;
  final Json request;

  @override
  State<_HelpMatchPage> createState() => _HelpMatchPageState();
}

class _HelpMatchPageState extends State<_HelpMatchPage> {
  final _requirements = TextEditingController();
  List<Json> _candidates = [];
  bool _manual = false;
  bool _loading = true;
  int? _pending;
  String? _error;
  bool _changed = false;
  int _generation = 0;

  HPointApi get api => widget.session.api;
  int get requestId => integer(widget.request['id']);

  @override
  void initState() {
    super.initState();
    Future.microtask(() => _load(false));
  }

  @override
  void dispose() {
    _requirements.dispose();
    super.dispose();
  }

  Future<void> _load(bool manual) async {
    if (!mounted) return;
    final generation = ++_generation;
    final question = _requirements.text.trim();
    final isEmail = RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$').hasMatch(question);
    if (isEmail) _requirements.clear();
    setState(() {
      if (_manual != manual) _candidates = [];
      _loading = true;
      _error = null;
      _manual = manual;
    });
    try {
      final data = await api.post('/api/assistant/candidates', {
        'request_id': requestId,
        'mode': manual ? 'manual' : 'recommended',
        'question': isEmail ? '' : question,
      });
      if (mounted && generation == _generation) {
        setState(() => _candidates = rows(data['matches']));
      }
    } catch (error) {
      if (mounted && generation == _generation) {
        setState(() => _error = error.toString());
      }
    } finally {
      if (mounted && generation == _generation) {
        setState(() => _loading = false);
      }
    }
  }

  Future<void> _invite(Json candidate) => _candidateAction(
    candidate,
    '/api/smart-match/assign',
    {},
    'Приглашение отправлено',
  );

  Future<void> _withdraw(Json candidate) async {
    if (!await _confirmHelp(
          context,
          'Отозвать приглашение?',
          'Заявка останется открытой. При необходимости можно пригласить другого помощника.',
          'Отозвать',
        ) ||
        !mounted) {
      return;
    }
    await _candidateAction(candidate, '/api/helper/offers/withdraw', {
      'offer_token': string(candidate['offer_token']),
    }, 'Приглашение отозвано');
  }

  Future<void> _select(Json candidate) async {
    final name = string(candidate['name'], 'этого помощника');
    if (!await _confirmHelp(
          context,
          'Выбрать исполнителя?',
          '$name станет исполнителем. Другие обсуждения останутся в истории.',
          'Выбрать',
        ) ||
        !mounted) {
      return;
    }
    await _candidateAction(
      candidate,
      '/api/requests/response/accept',
      {'application_token': string(candidate['application_token'])},
      'Исполнитель выбран',
      openChat: true,
    );
  }

  Future<void> _candidateAction(
    Json candidate,
    String path,
    Json extra,
    String message, {
    bool openChat = false,
  }) async {
    if (_pending != null || _loading) return;
    final helperId = integer(candidate['user_id']);
    setState(() {
      _pending = helperId;
      _error = null;
    });
    try {
      final result = await api.post(path, {
        'request_id': requestId,
        'helper_id': helperId,
        ...extra,
      });
      if (!mounted) return;
      _changed = true;
      _helpToast(context, message);
      if (openChat) {
        final id = integer(result['chat_id']);
        Navigator.of(context)
            .pop(_HelpResult(openChat: true, chatId: id > 0 ? id : null));
      } else {
        await _load(_manual);
      }
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _pending = null);
    }
  }

  Future<void> _openDiscussion(Json candidate) async {
    if (_pending != null || _loading) return;
    final helperId = integer(candidate['user_id']);
    setState(() {
      _pending = helperId;
      _error = null;
    });
    try {
      final payload = await api.get('/api/chats', {'archived': '1'});
      if (!mounted) return;
      final chats = rows(payload['chats']).where(
        (chat) =>
            integer(chat['request_id']) == requestId &&
            integer(chat['candidate_id']) == helperId,
      );
      if (chats.isEmpty) {
        throw const FormatException(
          'Обсуждение не найдено. Обновите список кандидатов.',
        );
      }
      Navigator.of(context)
          .pop(_HelpResult(openChat: true, chatId: integer(chats.first['id'])));
    } catch (error) {
      if (mounted) {
        setState(
          () => _error = error is FormatException
              ? error.message
              : error.toString(),
        );
      }
    } finally {
      if (mounted) setState(() => _pending = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final busy = _loading || _pending != null;
    final tracked = _candidates
        .where(
          (candidate) =>
              candidate['applied'] == true || candidate['offered'] == true,
        )
        .toList();
    final recommended = _candidates
        .where(
          (candidate) =>
              candidate['applied'] != true && candidate['offered'] != true,
        )
        .toList();
    return PopScope(
      canPop: _pending == null,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Smart Match'),
          leading: IconButton(
            icon: const Icon(Icons.arrow_back),
            tooltip: 'Назад',
            onPressed: _pending == null
                ? () => Navigator.pop(
                    context,
                    _changed ? const _HelpResult() : null,
                  )
                : null,
          ),
        ),
        body: SafeArea(
          top: false,
          child: RefreshIndicator(
            onRefresh: () => _load(_manual),
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(20),
              children: [
                Text(
                  string(widget.request['what'], 'Подбор помощника'),
                  style: theme.textTheme.headlineSmall?.copyWith(
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 6),
                const Text(
                  'Подбор учитывает сферу, навыки, расстояние и время. Исполнителя выбираете вы.',
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: _requirements,
                  enabled: !busy,
                  maxLength: 500,
                  textCapitalization: TextCapitalization.sentences,
                  autofillHints: null,
                  textInputAction: TextInputAction.search,
                  onSubmitted: (_) => _load(false),
                  decoration: const InputDecoration(
                    labelText: 'Требования к помощнику',
                    hintText: 'Например, сборка мебели',
                    counterText: '',
                  ),
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    FilledButton.icon(
                      onPressed: busy ? null : () => _load(false),
                      icon: const Icon(Icons.auto_awesome_outlined),
                      label: const Text('Подобрать'),
                    ),
                    OutlinedButton(
                      onPressed: busy ? null : () => _load(true),
                      child: const Text('Посмотреть вручную'),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                if (_loading) const LinearProgressIndicator(),
                if (_error != null)
                  _HelpNotice(
                    message: _error!,
                    icon: Icons.error_outline_rounded,
                    button: 'Обновить подбор',
                    onPressed: busy ? null : () => _load(_manual),
                  ),
                if (tracked.isNotEmpty) ...[
                  Text(
                    'Отклики и приглашения',
                    style: theme.textTheme.titleLarge,
                  ),
                  const SizedBox(height: 8),
                  for (final candidate in tracked) _candidate(candidate, busy),
                  const SizedBox(height: 16),
                ],
                Text(
                  _manual ? 'Ручной просмотр' : 'Рекомендации',
                  style: theme.textTheme.titleLarge,
                ),
                const SizedBox(height: 8),
                if (!_loading && recommended.isEmpty && _error == null)
                  _HelpNotice(
                    message: _manual ? 'Сейчас нет доступных кандидатов.' : 'Подходящих кандидатов пока нет. Попробуйте ручной просмотр или дождитесь откликов.',
                  ),
                for (final candidate in recommended)
                  _candidate(candidate, busy),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _candidate(Json candidate, bool busy) {
    final theme = Theme.of(context);
    final applied = candidate['applied'] == true;
    final offered = candidate['offered'] == true;
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    string(candidate['name'], 'Участник'),
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w800,
                    ),
                  ),
                ),
                if (candidate['match_percent'] is num) ...[
                  const SizedBox(width: 8),
                  Tooltip(
                    message: 'Совпадение с критериями заявки',
                    child: Chip(
                      label: Text('${integer(candidate['match_percent'])}%'),
                      backgroundColor: theme.colorScheme.secondaryContainer,
                    ),
                  ),
                ],
              ],
            ),
            if (applied || offered)
              Text(
                applied ? 'Откликнулся' : 'Приглашение отправлено',
                style: theme.textTheme.labelMedium?.copyWith(
                  color: theme.colorScheme.primary,
                ),
              ),
            for (final factor in rows(candidate['match_factors']))
              Padding(
                padding: const EdgeInsets.only(top: 9),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      switch (factor['status']) {
                        'matched' => Icons.check_circle_outline,
                        'mismatch' => Icons.cancel_outlined,
                        'partial' => Icons.timelapse_outlined,
                        _ => Icons.info_outline,
                      },
                      size: 17,
                      color: theme.colorScheme.primary,
                    ),
                    const SizedBox(width: 7),
                    Expanded(
                      child: Text.rich(
                        TextSpan(
                          children: [
                            TextSpan(
                              text: '${string(factor['label'])} · ',
                              style: const TextStyle(
                                fontWeight: FontWeight.w700,
                              ),
                            ),
                            TextSpan(text: string(factor['detail'])),
                          ],
                        ),
                        style: theme.textTheme.bodySmall,
                      ),
                    ),
                  ],
                ),
              ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                if (applied) ...[
                  FilledButton(
                    onPressed: busy || candidate['can_select'] != true
                        ? null
                        : () => _select(candidate),
                    child: Text(
                      candidate['can_select'] == true
                          ? 'Выбрать исполнителя'
                          : 'Сейчас занят',
                    ),
                  ),
                  OutlinedButton(
                    onPressed: busy ? null : () => _openDiscussion(candidate),
                    child: const Text('Открыть чат'),
                  ),
                ] else if (offered)
                  OutlinedButton(
                    onPressed: busy ? null : () => _withdraw(candidate),
                    child: const Text('Отозвать приглашение'),
                  )
                else
                  FilledButton(
                    onPressed: busy || candidate['can_invite'] != true
                        ? null
                        : () => _invite(candidate),
                    child: const Text('Пригласить'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
