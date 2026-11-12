import 'dart:convert';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import 'api.dart';
import 'session.dart';
import 'work_state.dart';

part 'work_team_calendar.dart';
part 'work_team_inquiries.dart';

class WorkTeamPage extends StatelessWidget {
  const WorkTeamPage({super.key, required this.model, required this.section});

  final WorkModel model;
  final String section;

  @override
  Widget build(BuildContext context) => switch (section) {
    'calendar' => _WorkCalendar(model: model),
    'publication' => _WorkOrganization(model: model, publication: true),
    'inquiries' => _WorkInquiries(model: model, incoming: true),
    'my-inquiries' => _WorkInquiries(model: model, incoming: false),
    _ => _WorkOrganization(model: model),
  };
}

bool _workActive(WorkModel model) =>
    object(model.data['profile'])['active'] == true;

bool _workFlag(Object? value) => value == true || value == 1;

bool _manage(WorkModel model) =>
    object(model.data['permissions'])['manage'] == true;

String _role(Object? value) => switch (value) {
  'owner' => 'Владелец',
  'admin' => 'Администратор',
  _ => 'Сотрудник',
};

int? _idOf(Object? value) {
  final id = integer(value);
  return id == 0 ? null : id;
}

String _shortDate(BuildContext context, DateTime value) =>
    MaterialLocalizations.of(context).formatMediumDate(value);

String _shortTime(BuildContext context, DateTime value) =>
    MaterialLocalizations.of(context).formatTimeOfDay(
      TimeOfDay.fromDateTime(value),
      alwaysUse24HourFormat: true,
    );

DateTime? _workDate(Object? value) =>
    DateTime.tryParse(string(value))?.toLocal();

String _dateTimeLabel(BuildContext context, DateTime? value) => value == null
    ? 'Не выбрано'
    : '${_shortDate(context, value)}, ${_shortTime(context, value)}';

String _dateKey(DateTime value) =>
    '${value.year.toString().padLeft(4, '0')}-${value.month.toString().padLeft(2, '0')}-${value.day.toString().padLeft(2, '0')}';

Future<DateTime?> _pickMoment(BuildContext context, DateTime? initial) async {
  final now = DateTime.now();
  final start = initial ?? now.add(const Duration(hours: 1));
  final min = DateTime(now.year - 5);
  final max = DateTime(now.year + 20, 12, 31);
  final date = await showDatePicker(
    context: context,
    firstDate: min,
    lastDate: max,
    initialDate: start.isBefore(min) || start.isAfter(max) ? now : start,
  );
  if (date == null || !context.mounted) return null;
  final time = await showTimePicker(
    context: context,
    initialTime: TimeOfDay.fromDateTime(start),
  );
  return time == null
      ? null
      : DateTime(date.year, date.month, date.day, time.hour, time.minute);
}

void _feedback(BuildContext context, String text) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
}

Future<bool> _confirm(
  BuildContext context,
  String title,
  String action, {
  String? message,
}) async =>
    await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: message == null ? null : Text(message),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: Text(action),
          ),
        ],
      ),
    ) ??
    false;

class _WorkContent extends StatelessWidget {
  const _WorkContent({required this.onRefresh, required this.children});

  final Future<void> Function() onRefresh;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) => SafeArea(
    child: RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
        children: children,
      ),
    ),
  );
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.label);
  final String label;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(top: 18, bottom: 8),
    child: Text(label, style: Theme.of(context).textTheme.titleMedium),
  );
}

class _WorkNotice extends StatelessWidget {
  const _WorkNotice(this.text, {this.icon = Icons.info_outline});
  final String text;
  final IconData icon;

  @override
  Widget build(BuildContext context) => Card(
    margin: const EdgeInsets.only(bottom: 8),
    child: ListTile(leading: Icon(icon), title: Text(text)),
  );
}

class _Editor extends StatefulWidget {
  const _Editor({
    required this.title,
    required this.fields,
    required this.submit,
    this.button = 'Сохранить',
  });

  final String title;
  final String button;
  final List<Widget> fields;
  final Future<void> Function() submit;

  @override
  State<_Editor> createState() => _EditorState();
}

class _EditorState extends State<_Editor> {
  final _form = GlobalKey<FormState>();
  bool _busy = false;
  String? _error;

  Future<void> _save() async {
    if (_busy || !_form.currentState!.validate()) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.submit();
      if (mounted) Navigator.of(context).pop(true);
    } catch (error) {
      if (mounted) setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !_busy,
    child: Scaffold(
      appBar: AppBar(title: Text(widget.title)),
      body: SafeArea(
        child: Form(
          key: _form,
          child: ListView(
            keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 28),
            children: [
              for (final field in widget.fields)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: IgnorePointer(ignoring: _busy, child: field),
                ),
              if (_error case final error?) ...[
                Semantics(
                  liveRegion: true,
                  child: Text(
                    error,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
                const SizedBox(height: 12),
              ],
              FilledButton(
                onPressed: _busy ? null : _save,
                child: Text(_busy ? 'Сохраняем…' : widget.button),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

Widget _editText(
  String label,
  String value,
  ValueChanged<String> changed, {
  int limit = 240,
  int minLength = 0,
  int lines = 1,
  TextInputType? keyboard,
  FormFieldValidator<String>? validate,
}) => TextFormField(
  initialValue: value,
  decoration: InputDecoration(labelText: label),
  maxLength: limit,
  minLines: lines,
  maxLines: lines,
  keyboardType:
      keyboard ?? (lines == 1 ? TextInputType.text : TextInputType.multiline),
  onChanged: changed,
  validator: (value) {
    if ((value ?? '').trim().length < minLength) return 'Заполните поле';
    return validate?.call(value);
  },
);

Widget _choosePerson({
  required List<Json> people,
  required int? value,
  required ValueChanged<int?> changed,
  bool required = false,
  String label = 'Ответственный',
}) {
  final choices = <int, String>{
    for (final row in people)
      ?_idOf(row['user_id']): string(row['name'], 'Участник'),
  };
  return DropdownButtonFormField<int>(
    initialValue: choices.containsKey(value) ? value : null,
    decoration: InputDecoration(labelText: label),
    isExpanded: true,
    items: [
      if (!required)
        const DropdownMenuItem<int>(value: null, child: Text('Не назначен')),
      for (final entry in choices.entries)
        DropdownMenuItem(
          value: entry.key,
          child: Text(entry.value, overflow: TextOverflow.ellipsis),
        ),
    ],
    onChanged: changed,
    validator: required
        ? (value) => value == null ? 'Выберите участника' : null
        : null,
  );
}

Widget _chooseRecord(
  String label,
  String emptyLabel,
  List<Json> entries,
  int? value,
  ValueChanged<int?> changed, {
  String labelKey = 'title',
}) {
  final choices = <int, String>{
    for (final row in entries)
      ?_idOf(row['id']): string(row[labelKey], 'Без названия'),
  };
  return DropdownButtonFormField<int>(
    initialValue: choices.containsKey(value) ? value : null,
    decoration: InputDecoration(labelText: label),
    isExpanded: true,
    items: [
      DropdownMenuItem<int>(value: null, child: Text(emptyLabel)),
      for (final entry in choices.entries)
        DropdownMenuItem(
          value: entry.key,
          child: Text(entry.value, overflow: TextOverflow.ellipsis),
        ),
    ],
    onChanged: changed,
  );
}

class _WorkOrganization extends StatefulWidget {
  const _WorkOrganization({required this.model, this.publication = false});

  final WorkModel model;
  final bool publication;

  @override
  State<_WorkOrganization> createState() => _WorkOrganizationState();
}

class _WorkOrganizationState extends State<_WorkOrganization> {
  WorkModel get _model => widget.model;
  bool _busy = false;

  Future<void> _reload() async {
    try {
      await _model.reload();
    } catch (error) {
      if (mounted) _feedback(context, error.toString());
    }
  }

  Future<void> _apply(
    String action,
    Json fields, {
    String? notice,
    bool closePage = false,
  }) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      await _model.update(action, fields);
      if (!mounted) return;
      if (notice != null) _feedback(context, notice);
      if (closePage) Navigator.of(context).pop();
    } catch (error) {
      if (mounted) _feedback(context, error.toString());
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _invite() async {
    var email = '';
    var role = 'member';
    final owner = _model.data['role'] == 'owner';
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (context) => _Editor(
          title: 'Пригласить в команду',
          button: 'Пригласить',
          submit: () async {
            await _model.update('/api/commercial/team/invite', {
              'email': email.trim(),
              'role': role,
            });
          },
          fields: [
            _editText(
              'Email участника',
              email,
              (value) => email = value,
              minLength: 3,
              keyboard: TextInputType.emailAddress,
              validate: (value) =>
                  RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
                      .hasMatch((value ?? '').trim())
                  ? null
                  : 'Укажите действительный email',
            ),
            if (owner)
              DropdownButtonFormField<String>(
                initialValue: role,
                decoration: const InputDecoration(labelText: 'Роль'),
                items: const [
                  DropdownMenuItem(value: 'member', child: Text('Сотрудник')),
                  DropdownMenuItem(
                    value: 'admin',
                    child: Text('Администратор'),
                  ),
                ],
                onChanged: (value) => role = value ?? 'member',
              ),
            const Text(
              'Приглашение появится в H-Point у аккаунта с этим email.',
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _memberAction(Json member, String action) async {
    if (action == 'remove' &&
        !await _confirm(
          context,
          'Исключить участника?',
          'Исключить',
          message:
              '${string(member['name'], 'Участник')} потеряет доступ к кабинету. Назначения и смены этого участника будут сняты.',
        )) {
      return;
    }
    if (!mounted) return;
    await _apply(
      action == 'remove'
          ? '/api/commercial/team/remove'
          : '/api/commercial/team/role',
      {'user_id': member['user_id'], if (action != 'remove') 'role': action},
      notice: action == 'remove' ? 'Участник исключён' : 'Роль обновлена',
    );
  }

  Future<void> _leave() async {
    if (!await _confirm(
      context,
      'Выйти из организации?',
      'Выйти',
      message: 'Вы потеряете доступ к кабинету, а ваши назначения и смены в нём будут сняты.',
    )) {
      return;
    }
    if (!mounted) return;
    await _apply('/api/commercial/team/leave', const {}, closePage: true);
  }

  Future<void> _editPublication(Json page) async {
    var slug = string(page['slug']);
    var description = string(page['description']);
    var contact = string(page['contact']);
    var address = string(page['address']);
    var published = page['published'] == true;
    final active = _workActive(_model);
    await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (context) => _Editor(
          title: 'Публичная страница',
          submit: () async {
            await _model.update('/api/commercial/public-profile', {
              'slug': slug.trim().toLowerCase(),
              'description': description.trim(),
              'contact': contact.trim(),
              'address': address.trim(),
              'published': published,
            });
          },
          fields: [
            StatefulBuilder(
              builder: (context, setField) => SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Показывать страницу клиентам'),
                subtitle: active
                    ? null
                    : const Text('Для публикации продлите доступ'),
                value: published,
                onChanged: active || published
                    ? (value) => setField(() => published = value)
                    : null,
              ),
            ),
            _editText(
              'Короткий адрес страницы',
              slug,
              (value) => slug = value,
              minLength: 3,
              limit: 64,
              validate: (value) =>
                  RegExp(r'^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$')
                      .hasMatch((value ?? '').trim().toLowerCase())
                  ? null
                  : 'От 3 до 64 латинских букв, цифр или дефисов',
            ),
            _editText(
              'Описание для клиентов',
              description,
              (value) => description = value,
              limit: 2000,
              lines: 4,
            ),
            _editText('Публичный контакт', contact, (value) => contact = value),
            _editText(
              'Адрес для клиентов',
              address,
              (value) => address = value,
              limit: 400,
            ),
            const Text('Эти сведения и выбранные услуги будут видны всем.'),
          ],
        ),
      ),
    );
  }

  Future<void> _copyPublicLink(String slug) async {
    await Clipboard.setData(
      ClipboardData(
        text: 'https://gethpoint.ru/organizations/${Uri.encodeComponent(slug)}',
      ),
    );
    if (mounted) _feedback(context, 'Ссылка скопирована');
  }

  List<Widget> _team() {
    final data = _model.data;
    final role = data['role'];
    final owner = role == 'owner';
    final actor =
        _model.session.data?['current_user_id'] ?? _model.session.user['id'];
    final managers = _manage(_model);
    final active = _workActive(_model);
    final members = rows(data['members']);
    final incoming = rows(data['incoming_invitations']);
    final sent = rows(data['invitations']).where(
      (row) =>
          row['status'] == 'pending' &&
          (_workDate(row['expires_at'])?.isAfter(DateTime.now()) ?? true),
    );
    return [
      if (incoming.isNotEmpty) const _SectionTitle('Приглашения вам'),
      for (final invite in incoming)
        Card(
          margin: const EdgeInsets.only(bottom: 8),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  string(invite['organization_title'], 'Организация'),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Text(_role(invite['role'])),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: [
                    FilledButton.tonal(
                      onPressed: _busy
                          ? null
                          : () => _apply('/api/commercial/team/accept', {
                              'invitation_id': invite['id'],
                            }, notice: 'Приглашение принято'),
                      child: const Text('Принять'),
                    ),
                    TextButton(
                      onPressed: _busy
                          ? null
                          : () => _apply('/api/commercial/team/decline', {
                              'invitation_id': invite['id'],
                            }, notice: 'Приглашение отклонено'),
                      child: const Text('Отклонить'),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      if (members.isNotEmpty) _SectionTitle('Команда · ${members.length}'),
      if (managers && active)
        FilledButton.tonalIcon(
          onPressed: _busy ? null : _invite,
          icon: const Icon(Icons.person_add_alt_1_outlined),
          label: const Text('Пригласить участника'),
        ),
      for (final member in members)
        Card(
          margin: const EdgeInsets.only(top: 8),
          child: ListTile(
            leading: const Icon(Icons.person_outline),
            title: Text(string(member['name'], 'Участник')),
            subtitle: Text(
              [
                _role(member['role']),
                if (managers && string(member['email']).isNotEmpty)
                  string(member['email']),
              ].join('\n'),
            ),
            trailing:
                managers &&
                    !_busy &&
                    member['user_id'] != actor &&
                    member['role'] != 'owner' &&
                    (owner || member['role'] != 'admin')
                ? PopupMenuButton<String>(
                    tooltip: 'Действия с участником',
                    onSelected: (action) => _memberAction(member, action),
                    itemBuilder: (context) => [
                      if (owner && member['role'] != 'admin')
                        const PopupMenuItem(
                          value: 'admin',
                          child: Text('Сделать администратором'),
                        ),
                      if (owner && member['role'] == 'admin')
                        const PopupMenuItem(
                          value: 'member',
                          child: Text('Сделать сотрудником'),
                        ),
                      const PopupMenuItem(
                        value: 'remove',
                        child: Text('Исключить'),
                      ),
                    ],
                  )
                : null,
          ),
        ),
      if (managers && sent.isNotEmpty) const _SectionTitle('Ожидают ответа'),
      if (managers)
        for (final invite in sent)
          Card(
            margin: const EdgeInsets.only(bottom: 8),
            child: ListTile(
              title: Text(string(invite['email'])),
              subtitle: Text(
                '${_role(invite['role'])} · до ${_dateTimeLabel(context, _workDate(invite['expires_at']))}',
              ),
              trailing: _busy || !owner && invite['role'] == 'admin'
                  ? null
                  : IconButton(
                      tooltip: 'Отозвать приглашение',
                      icon: const Icon(Icons.close),
                      onPressed: () => _apply('/api/commercial/team/revoke', {
                        'invitation_id': invite['id'],
                      }, notice: 'Приглашение отозвано'),
                    ),
            ),
          ),
      if (role != null && !owner) ...[
        const SizedBox(height: 18),
        OutlinedButton(
          onPressed: _busy ? null : _leave,
          child: const Text('Выйти из организации'),
        ),
      ],
      if (members.isEmpty && incoming.isEmpty)
        const _WorkNotice('У вас пока нет команды или приглашений.'),
    ];
  }

  List<Widget> _publication() {
    final profile = object(_model.data['profile']);
    if (profile.isEmpty) {
      return const [_WorkNotice('Сначала создайте кабинет для работы.')];
    }
    final page = object(_model.data['public_profile']);
    final services = rows(_model.data['services']);
    final canManage = _manage(_model) && !_busy;
    final active = _workActive(_model);
    final published = page['published'] == true;
    final slug = string(page['slug']);
    return [
      _WorkNotice(
        published && active
            ? 'Страница опубликована'
            : 'Страница скрыта от клиентов',
        icon: published && active
            ? Icons.public
            : Icons.visibility_off_outlined,
      ),
      if (published && active && slug.isNotEmpty)
        OutlinedButton.icon(
          onPressed: () => _copyPublicLink(slug),
          icon: const Icon(Icons.copy_outlined),
          label: const Text('Скопировать публичную ссылку'),
        ),
      if (_manage(_model))
        FilledButton.tonalIcon(
          onPressed: canManage ? () => _editPublication(page) : null,
          icon: const Icon(Icons.edit_outlined),
          label: const Text('Редактировать страницу'),
        ),
      const _SectionTitle('Услуги на публичной странице'),
      if (services.isEmpty)
        const _WorkNotice('Добавьте услуги в кабинете, чтобы их опубликовать.'),
      for (final service in services)
        Card(
          margin: const EdgeInsets.only(bottom: 8),
          child: SwitchListTile(
            title: Text(string(service['title'], 'Услуга')),
            subtitle: Text(
              '${integer(service['price_rub'])} тест. ₽ · ${integer(service['duration_minutes'])} мин.',
            ),
            value: _workFlag(service['published']),
            onChanged:
                canManage &&
                    (_workFlag(service['published']) ||
                        active && published && _workFlag(service['active']))
                ? (value) => _apply(
                    '/api/commercial/services/publish',
                    {'id': service['id'], 'published': value},
                    notice: value
                        ? 'Услуга опубликована'
                        : 'Услуга снята с публикации',
                  )
                : null,
          ),
        ),
    ];
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(widget.publication ? 'Публикация' : 'Команда')),
    body: AnimatedBuilder(
      animation: _model,
      builder: (context, _) => _WorkContent(
        onRefresh: _reload,
        children: [
          if (_busy) const LinearProgressIndicator(),
          ...widget.publication ? _publication() : _team(),
        ],
      ),
    ),
  );
}
