import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'api.dart';
import 'auth.dart';
import 'chat.dart';
import 'community.dart';
import 'help.dart';
import 'profile.dart';
import 'session.dart';
import 'work.dart';

void main() => runApp(const HPointApp());

class HPointApp extends StatefulWidget {
  const HPointApp({super.key, this.session});

  final HPointSession? session;

  @override
  State<HPointApp> createState() => _HPointAppState();
}

class _HPointAppState extends State<HPointApp> {
  late final HPointSession _session =
      widget.session ?? HPointSession(HPointApi());

  @override
  void initState() {
    super.initState();
    unawaited(_session.start());
  }

  @override
  void dispose() {
    if (widget.session == null) _session.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'H-Point',
    debugShowCheckedModeBanner: false,
    locale: const Locale('ru'),
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    supportedLocales: const [Locale('ru')],
    theme: _theme(Brightness.light),
    darkTheme: _theme(Brightness.dark),
    home: _Shell(session: _session),
  );
}

ThemeData _theme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  final colors = ColorScheme.fromSeed(
    seedColor: const Color(0xff297456),
    brightness: brightness,
    surface: dark ? const Color(0xff111b19) : const Color(0xfff6f8f5),
  );
  final theme = ThemeData(
    useMaterial3: true,
    splashFactory: InkRipple.splashFactory,
    colorScheme: colors,
    scaffoldBackgroundColor: colors.surface,
    appBarTheme: AppBarTheme(backgroundColor: colors.surface, elevation: 0),
    cardTheme: CardThemeData(
      elevation: 0,
      margin: EdgeInsets.zero,
      color: dark ? const Color(0xff1a2824) : Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(22),
        side: BorderSide(color: colors.outlineVariant.withValues(alpha: .55)),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: colors.surfaceContainerLowest,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: BorderSide(color: colors.outlineVariant),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: colors.surfaceContainerLow,
      elevation: 0,
      height: 68,
      labelBehavior: NavigationDestinationLabelBehavior.onlyShowSelected,
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(minimumSize: const Size(48, 48)),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
    ),
  );
  return theme.copyWith(
    textTheme: theme.textTheme.copyWith(
      headlineMedium: theme.textTheme.headlineMedium?.copyWith(
        fontWeight: FontWeight.w800,
        letterSpacing: -.6,
      ),
      titleLarge: theme.textTheme.titleLarge?.copyWith(
        fontWeight: FontWeight.w700,
        letterSpacing: -.25,
      ),
      titleMedium: theme.textTheme.titleMedium?.copyWith(
        fontWeight: FontWeight.w700,
      ),
    ),
  );
}

class _Shell extends StatefulWidget {
  const _Shell({required this.session});
  final HPointSession session;
  @override
  State<_Shell> createState() => _ShellState();
}

class _ShellState extends State<_Shell> {
  int _tab = 0;
  HPointSession get _session => widget.session;

  void _signIn({bool register = false}) {
    Navigator.of(context).push(
      MaterialPageRoute<bool>(
        builder: (_) => AuthPage(session: _session, register: register),
      ),
    );
  }

  void _chat(int requestId, {int? chatId}) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ChatPage(
          session: _session,
          onSignIn: _signIn,
          requestId: requestId,
          chatId: chatId,
        ),
      ),
    );
  }

  Future<void> _requestHelp() async {
    if (!_session.signedIn) {
      _signIn();
      return;
    }
    if (await openHelpRequestForm(context, _session) == true) {
      await _refreshAfterAction();
    }
  }

  Future<void> _helpOthers() async {
    if (!_session.signedIn) {
      setState(() => _tab = 1);
      return;
    }
    if (await openHelpSettings(context, _session) == true) {
      await _refreshAfterAction();
    }
  }

  Future<void> _refreshAfterAction() async {
    try {
      await _session.refresh();
    } on ApiException catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(error.message)));
      }
    }
  }

  void _work() => Navigator.of(context).push(
    MaterialPageRoute<void>(
      builder: (_) => WorkPage(session: _session, onSignIn: _signIn),
    ),
  );

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
    animation: _session,
    builder: (context, _) {
      final dark = Theme.of(context).brightness == Brightness.dark;
      void register() => _signIn(register: true);
      return Scaffold(
        appBar: AppBar(
          titleSpacing: 18,
          title: Image.asset(
            'assets/${dark ? 'logo-dark' : 'logo'}.webp',
            height: 33,
            semanticLabel: 'H-Point',
          ),
          actions: [
            if (_session.signedIn)
              IconButton(
                tooltip: 'Профиль',
                onPressed: () => setState(() => _tab = 4),
                icon: const Icon(Icons.account_circle_outlined),
              )
            else
              Padding(
                padding: const EdgeInsets.only(right: 12),
                child: TextButton(
                  onPressed: _signIn,
                  child: const Text('Войти'),
                ),
              ),
          ],
        ),
        body: _session.starting
            ? const Center(child: CircularProgressIndicator())
            : SafeArea(
                top: false,
                bottom: false,
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 760),
                    child: IndexedStack(
                      key: ValueKey(_session.data?['current_user_id']),
                      index: _tab,
                      children: [
                        _Home(
                          session: _session,
                          onRequest: _requestHelp,
                          onHelp: _helpOthers,
                          onWork: _work,
                          onRegister: register,
                        ),
                        HelpPage(
                          session: _session,
                          onSignIn: _signIn,
                          onChat: _chat,
                        ),
                        ChatPage(
                          session: _session,
                          onSignIn: _signIn,
                          active: _tab == 2,
                        ),
                        ActivitiesPage(
                          session: _session,
                          active: _tab == 3,
                          onSignIn: _signIn,
                          onWork: _work,
                        ),
                        ProfilePage(
                          session: _session,
                          onSignIn: _signIn,
                          onRegister: register,
                          onWork: _work,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
        bottomNavigationBar: NavigationBar(
          selectedIndex: _tab,
          onDestinationSelected: (value) => setState(() => _tab = value),
          destinations: const [
            NavigationDestination(
              icon: Icon(Icons.home_outlined),
              selectedIcon: Icon(Icons.home_rounded),
              label: 'Главная',
            ),
            NavigationDestination(
              icon: Icon(Icons.volunteer_activism_outlined),
              selectedIcon: Icon(Icons.volunteer_activism),
              label: 'Помощь',
            ),
            NavigationDestination(
              icon: Icon(Icons.chat_bubble_outline_rounded),
              selectedIcon: Icon(Icons.chat_bubble_rounded),
              label: 'Чаты',
            ),
            NavigationDestination(
              icon: Icon(Icons.event_outlined),
              selectedIcon: Icon(Icons.event),
              label: 'Активности',
            ),
            NavigationDestination(
              icon: Icon(Icons.person_outline_rounded),
              selectedIcon: Icon(Icons.person_rounded),
              label: 'Профиль',
            ),
          ],
        ),
      );
    },
  );
}

class _Home extends StatelessWidget {
  const _Home({
    required this.session,
    required this.onRequest,
    required this.onHelp,
    required this.onWork,
    required this.onRegister,
  });
  final HPointSession session;
  final VoidCallback onRequest, onHelp, onWork, onRegister;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = theme.colorScheme;
    final name = string(session.user['name']);
    return RefreshIndicator(
      onRefresh: () async {
        try {
          await session.refresh();
        } on ApiException {
          /* Error visible above the hero. */
        }
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 22),
        children: [
          if (session.error != null &&
              session.data == null &&
              session.guest == null)
            ListTile(
              leading: const Icon(Icons.cloud_off_outlined),
              title: Text(session.error!),
              trailing: IconButton(
                tooltip: 'Повторить',
                onPressed: session.start,
                icon: const Icon(Icons.refresh),
              ),
            ),
          ClipRRect(
            borderRadius: BorderRadius.circular(26),
            child: DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  colors: [colors.primaryContainer, colors.tertiaryContainer],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  AspectRatio(
                    aspectRatio: 2.3,
                    child: Image.asset(
                      'assets/neighbors.webp',
                      fit: BoxFit.cover,
                      excludeFromSemantics: true,
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          name.isEmpty ? 'Помощь рядом' : 'Привет, $name!',
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.headlineMedium?.copyWith(
                            color: colors.onPrimaryContainer,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Найдите помощника для своего дела или предложите помощь рядом с вами.',
                          style: theme.textTheme.bodyLarge?.copyWith(
                            color: colors.onPrimaryContainer,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: onRequest,
            icon: const Icon(Icons.add_circle_outline),
            label: const Text('Нужна помощь'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: onHelp,
            icon: const Icon(Icons.volunteer_activism_outlined),
            label: Text(
              session.user['helper_ready'] == true
                  ? 'Настроить помощь'
                  : 'Хочу помочь',
            ),
          ),
          const SizedBox(height: 18),
          Card(
            child: ListTile(
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 16,
                vertical: 8,
              ),
              leading: Icon(Icons.work_outline_rounded, color: colors.primary),
              title: const Text('Для работы'),
              subtitle: const Text('Услуги специалистов и кабинеты для команд'),
              trailing: const Icon(Icons.chevron_right_rounded),
              onTap: onWork,
            ),
          ),
          if (!session.signedIn)
            TextButton(
              onPressed: onRegister,
              child: const Text('Создать аккаунт'),
            ),
        ],
      ),
    );
  }
}
