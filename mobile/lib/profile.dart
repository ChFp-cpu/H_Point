import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api.dart';
import 'session.dart';

Future<void> openHPointSite(BuildContext context, [String path = '/']) async {
  final address = Uri.https('gethpoint.ru').resolve(path);
  if (address.origin != 'https://gethpoint.ru') return;
  try {
    if (await launchUrl(address, mode: LaunchMode.externalApplication)) return;
  } catch (_) {
    // Show the same retry prompt if the operating system cannot open a browser.
  }
  if (context.mounted) {
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('Не удалось открыть сайт.')));
  }
}

class ProfilePage extends StatelessWidget {
  const ProfilePage({
    super.key,
    required this.session,
    required this.onSignIn,
    required this.onRegister,
    required this.onWork,
  });
  final HPointSession session;
  final VoidCallback onSignIn, onRegister, onWork;

  Future<void> _signOut(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Выйти из аккаунта?'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Остаться'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Выйти'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await session.signOut();
    } on ApiException catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final user = session.user;
    final wallet = object(session.data?['wallet']);
    final name = string(user['name'], 'Участник');
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        Text('Профиль', style: theme.textTheme.headlineMedium),
        const SizedBox(height: 14),
        if (session.signedIn) ...[
          Card(
            child: Padding(
              padding: const EdgeInsets.all(18),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  CircleAvatar(
                    radius: 26,
                    child: Text(name.characters.first.toUpperCase()),
                  ),
                  const SizedBox(height: 10),
                  Wrap(
                    spacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      Text(name, style: theme.textTheme.titleLarge),
                      if (user['pro_active'] == true)
                        const Chip(label: Text('PRO')),
                    ],
                  ),
                  Text(
                    string(user['email']),
                    style: theme.textTheme.bodyMedium,
                  ),
                  if (string(user['city']).isNotEmpty)
                    Text(string(user['city'])),
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (_) => _EditProfile(session: session),
                      ),
                    ),
                    icon: const Icon(Icons.edit_outlined),
                    label: const Text('Редактировать'),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 10),
          Card(
            child: ListTile(
              leading: const Icon(Icons.account_balance_wallet_outlined),
              title: const Text('Тестовый кошелёк'),
              subtitle: Text(
                '${integer(wallet['test_balance_rub'])} тест. ₽ · ${integer(user['balance'])} HP',
              ),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => _wallet(context, wallet),
            ),
          ),
          const SizedBox(height: 10),
        ] else ...[
          Text(
            'Войдите, чтобы видеть свои заявки, чаты и баланс.',
            style: theme.textTheme.bodyLarge,
          ),
          const SizedBox(height: 14),
          FilledButton(
            onPressed: onSignIn,
            child: const Text('Войти по email'),
          ),
          TextButton(
            onPressed: onRegister,
            child: const Text('Создать аккаунт'),
          ),
          const SizedBox(height: 12),
        ],
        Card(
          child: Column(
            children: [
              ListTile(
                leading: const Icon(Icons.work_outline),
                title: const Text('Для работы'),
                trailing: const Icon(Icons.chevron_right),
                onTap: onWork,
              ),
              ListTile(
                leading: const Icon(Icons.support_agent_outlined),
                title: const Text('Поддержка на сайте'),
                trailing: const Icon(Icons.open_in_new),
                onTap: () => openHPointSite(context, '/?action=support'),
              ),
              ListTile(
                leading: const Icon(Icons.language),
                title: const Text('Сайт H-Point'),
                trailing: const Icon(Icons.open_in_new),
                onTap: () => openHPointSite(context),
              ),
            ],
          ),
        ),
        if (session.signedIn) ...[
          const SizedBox(height: 12),
          TextButton.icon(
            onPressed: () => _signOut(context),
            icon: const Icon(Icons.logout),
            label: const Text('Выйти из аккаунта'),
          ),
        ],
      ],
    );
  }

  void _wallet(BuildContext context, Json wallet) {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 20),
          children: [
            Text(
              'Тестовый кошелёк',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            ListTile(
              title: const Text('Доступно'),
              trailing: Text('${integer(wallet['test_balance_rub'])} ₽'),
            ),
            ListTile(
              title: const Text('В резерве'),
              trailing: Text('${integer(wallet['test_reserved_rub'])} ₽'),
            ),
            for (final row in rows(wallet['transactions']))
              ListTile(
                title: Text(string(row['description'], 'Операция')),
                trailing: Text('${integer(row['amount_rub'])} ₽'),
              ),
          ],
        ),
      ),
    );
  }
}

class _EditProfile extends StatefulWidget {
  const _EditProfile({required this.session});
  final HPointSession session;
  @override
  State<_EditProfile> createState() => _EditProfileState();
}

class _EditProfileState extends State<_EditProfile> {
  late final _name = TextEditingController(
    text: string(widget.session.user['name']),
  );
  late final _city = TextEditingController(
    text: string(widget.session.user['city']),
  );
  late final _bio = TextEditingController(
    text: string(widget.session.user['bio']),
  );
  String? _error;
  bool _saving = false;

  @override
  void dispose() {
    _name.dispose();
    _city.dispose();
    _bio.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.session.api.post('/api/profile', {
        'name': _name.text.trim(),
        'city': _city.text.trim(),
        'bio': _bio.text.trim(),
      });
      await widget.session.refresh();
      if (mounted) Navigator.pop(context);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Редактировать профиль')),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _name,
            maxLength: 50,
            enabled: !_saving,
            textCapitalization: TextCapitalization.words,
            decoration: const InputDecoration(labelText: 'Имя'),
          ),
          TextField(
            controller: _city,
            maxLength: 80,
            enabled: !_saving,
            textCapitalization: TextCapitalization.words,
            decoration: const InputDecoration(labelText: 'Город'),
          ),
          TextField(
            controller: _bio,
            maxLength: 500,
            minLines: 3,
            maxLines: 5,
            enabled: !_saving,
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(
              labelText: 'О себе',
              helperText: 'Добавьте навыки, которые пригодятся в подборе.',
            ),
          ),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          FilledButton(
            onPressed: _saving ? null : _save,
            child: Text(_saving ? 'Сохраняем…' : 'Сохранить'),
          ),
        ],
      ),
    ),
  );
}
