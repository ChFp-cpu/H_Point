part of 'help.dart';

Future<bool?> openHelpSettings(BuildContext context, HPointSession session) =>
    Navigator.of(context).push<bool>(
      MaterialPageRoute(builder: (_) => _HelpSettings(session: session)),
    );

class _HelpSettings extends StatefulWidget {
  const _HelpSettings({required this.session});
  final HPointSession session;

  @override
  State<_HelpSettings> createState() => _HelpSettingsState();
}

class _HelpSettingsState extends State<_HelpSettings> {
  final _form = GlobalKey<FormState>();
  final _place = TextEditingController();
  final _radius = TextEditingController();
  final _availability = TextEditingController();
  final _categories = <String>{};
  late Json _user;
  DateTime? _from;
  DateTime? _until;
  bool _ready = false;
  bool _saving = false;
  String? _error;

  HPointSession get session => widget.session;

  @override
  void initState() {
    super.initState();
    _user = object(session.data?['user']);
    _ready = _user['helper_ready'] == true;
    _place.text = string(_user['saved_location']);
    _radius.text = '${integer(_user['helper_radius_km'])}';
    _availability.text = string(_user['helper_availability']);
    final saved = _user['helper_categories'];
    if (saved is List) _categories.addAll(saved.whereType<String>());
    _from = DateTime.tryParse(string(_user['helper_available_from']))
        ?.toLocal();
    _until = DateTime.tryParse(string(_user['helper_available_until']))
        ?.toLocal();
  }

  @override
  void dispose() {
    _place.dispose();
    _radius.dispose();
    _availability.dispose();
    super.dispose();
  }

  Future<void> _pickTime(bool beginning) async {
    final old = beginning ? _from : _until;
    final now = DateTime.now();
    final day = DateUtils.dateOnly(now);
    final lastDay = day.add(const Duration(days: 365));
    final initialDay = old == null || old.isBefore(day) || old.isAfter(lastDay)
        ? day
        : old;
    final date = await showDatePicker(
      context: context,
      firstDate: day,
      lastDate: lastDay,
      initialDate: initialDay,
    );
    if (!mounted || date == null) return;
    final time = await showTimePicker(
      context: context,
      initialTime: TimeOfDay.fromDateTime(old ?? now),
    );
    if (!mounted || time == null) return;
    final value = DateTime(
      date.year,
      date.month,
      date.day,
      time.hour,
      time.minute,
    );
    setState(() {
      if (beginning) {
        _from = value;
      } else {
        _until = value;
      }
    });
  }

  Future<void> _save() async {
    if (_saving || _form.currentState?.validate() != true) return;
    final from = _from;
    final until = _until;
    if (from != null && until != null && !until.isAfter(from)) {
      setState(() => _error = 'Конец периода должен быть позже начала.');
      return;
    }
    FocusScope.of(context).unfocus();
    final place = _place.text.trim();
    final radius = int.tryParse(_radius.text.trim()) ?? 0;
    final needsPoint = _ready && radius > 0;
    if (needsPoint && place.isEmpty) {
      setState(
        () => _error =
            'Для ограничения по радиусу укажите город, район или адрес.',
      );
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final missing = _user['lat'] is! num || _user['lon'] is! num;
      if (place.isNotEmpty &&
          (place != string(_user['saved_location']).trim() ||
              needsPoint && missing)) {
        final result = await session.api.post('/api/profile/location', {
          'location': place,
        });
        _user = object(result['user']);
      }
      if (needsPoint && (_user['lat'] is! num || _user['lon'] is! num)) {
        if (mounted) {
          setState(
            () => _error =
                'Точка не найдена. Уточните адрес или поставьте радиус 0 км.',
          );
        }
        return;
      }
      await session.api.post('/api/helper/preferences', {
        'ready': _ready,
        'categories': _categories.toList(),
        'radius_km': radius,
        'availability': _availability.text.trim(),
        'available_from': from?.toUtc().toIso8601String(),
        'available_until': until?.toUtc().toIso8601String(),
      });
      if (!mounted) return;
      _helpToast(context, 'Настройки помощи сохранены');
      Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  String _formatTime(BuildContext context, DateTime time) {
    final locale = MaterialLocalizations.of(context);
    return '${locale.formatShortDate(time)} · ${locale.formatTimeOfDay(TimeOfDay.fromDateTime(time), alwaysUse24HourFormat: true)}';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final categories = _helpCategories(session);
    return PopScope(
      canPop: !_saving,
      child: Scaffold(
        appBar: AppBar(title: const Text('Настроить помощь')),
        body: SafeArea(
          top: false,
          child: Form(
            key: _form,
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                Card.filled(
                  child: SwitchListTile(
                    value: _ready,
                    title: const Text('Готов помогать сейчас'),
                    subtitle: const Text(
                      'Авторы подходящих заявок смогут отправить приглашение.',
                    ),
                    onChanged: _saving
                        ? null
                        : (value) => setState(() => _ready = value),
                  ),
                ),
                const SizedBox(height: 12),
                Text(
                  'Сферы, в которых вы помогаете',
                  style: theme.textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(height: 5),
                const Text(
                  'Отметьте подходящие направления, чтобы появляться в рекомендациях по ним.',
                ),
                const SizedBox(height: 7),
                Wrap(
                  spacing: 7,
                  runSpacing: 3,
                  children: [
                    for (final category in categories.entries)
                      FilterChip(
                        label: Text(category.value),
                        selected: _categories.contains(category.key),
                        onSelected: _saving
                            ? null
                            : (value) => setState(() {
                                if (value) {
                                  _categories.add(category.key);
                                } else {
                                  _categories.remove(category.key);
                                }
                              }),
                      ),
                  ],
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _place,
                  enabled: !_saving,
                  maxLength: 180,
                  decoration: const InputDecoration(
                    labelText: 'Город, район или адрес',
                    counterText: '',
                  ),
                  validator: (value) {
                    final length = value?.trim().length ?? 0;
                    return length == 1 ? 'Уточните место' : null;
                  },
                ),
                const SizedBox(height: 10),
                TextFormField(
                  controller: _radius,
                  enabled: !_saving,
                  keyboardType: TextInputType.number,
                  inputFormatters: [
                    FilteringTextInputFormatter.digitsOnly,
                    LengthLimitingTextInputFormatter(4),
                  ],
                  decoration: const InputDecoration(
                    labelText: 'Радиус, км',
                    helperText: '0 — без ограничения по радиусу',
                  ),
                  validator: (value) {
                    final radius = int.tryParse(value ?? '') ?? 0;
                    return radius > 1000 ? 'Не более 1000 км' : null;
                  },
                ),
                const SizedBox(height: 10),
                TextFormField(
                  controller: _availability,
                  enabled: !_saving,
                  maxLength: 240,
                  decoration: const InputDecoration(
                    labelText: 'Когда вам удобно',
                    hintText: 'Например, в будни после 18:00',
                    counterText: '',
                  ),
                ),
                const SizedBox(height: 10),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Доступен с'),
                  subtitle: Text(
                    _from == null
                        ? 'Любое время'
                        : _formatTime(context, _from!),
                  ),
                  onTap: _saving ? null : () => _pickTime(true),
                  trailing: _from == null
                      ? const Icon(Icons.event_outlined)
                      : IconButton(
                          tooltip: 'Очистить начало',
                          onPressed: _saving
                              ? null
                              : () => setState(() => _from = null),
                          icon: const Icon(Icons.close),
                        ),
                ),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('Доступен до'),
                  subtitle: Text(
                    _until == null
                        ? 'Без ограничения'
                        : _formatTime(context, _until!),
                  ),
                  onTap: _saving ? null : () => _pickTime(false),
                  trailing: _until == null
                      ? const Icon(Icons.event_outlined)
                      : IconButton(
                          tooltip: 'Очистить конец',
                          onPressed: _saving
                              ? null
                              : () => setState(() => _until = null),
                          icon: const Icon(Icons.close),
                        ),
                ),
                if (_error != null)
                  _HelpNotice(
                    message: _error!,
                    icon: Icons.error_outline_rounded,
                  ),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: _saving ? null : _save,
                  child: Text(_saving ? 'Сохраняем…' : 'Сохранить настройки'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
