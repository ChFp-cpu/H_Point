import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hpoint/api.dart';
import 'package:hpoint/help.dart';
import 'package:hpoint/session.dart';

const _request = <String, dynamic>{
  'id': 17,
  'requester_id': -7,
  'requester_name': 'Автор заявки',
  'what': 'Собрать шкаф',
  'category': 'furniture',
  'status': 'open',
};

class _FixtureApi extends HPointApi {
  _FixtureApi({required this.signed});

  final bool signed;
  final posts = <(String, Json)>[];

  @override
  bool get hasSession => signed;

  Json get sync => {
    'ok': true,
    'user': {'id': -7, 'name': 'Автор заявки'},
    'requests': [_request],
  };

  @override
  Future<Json> get(String path, [Map<String, String>? query]) async =>
      switch (path) {
        '/api/sync' => sync,
        '/api/requests' => {'ok': true, 'requests': []},
        '/api/helper/offers' => {'ok': true, 'offers': []},
        _ => throw StateError('Unexpected GET $path'),
      };

  @override
  Future<Json> post(String path, [Json body = const {}]) async {
    posts.add((path, Map.of(body)));
    return switch (path) {
      '/api/assistant/candidates' => {
        'ok': true,
        'matches': [
          {
            'user_id': -8,
            'name': 'Помощник',
            'match_percent': 87,
            'match_factors': [
              {
                'label': 'Навыки по задаче',
                'detail': 'В профиле указана сборка шкафов',
                'status': 'matched',
              },
            ],
            'applied': true,
            'can_select': true,
            'application_token': 'current-consent',
          },
        ],
      },
      '/api/requests/response/accept' => {'ok': true, 'chat_id': 31},
      _ => throw StateError('Unexpected POST $path'),
    };
  }
}

void main() {
  testWidgets('guest can browse a request and is asked to sign in to apply', (
    tester,
  ) async {
    final api = _FixtureApi(signed: false);
    final session = HPointSession(api)
      ..guest = {
        'requests': [_request],
      };
    var signInCalls = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(splashFactory: NoSplash.splashFactory),
        home: Scaffold(
          body: HelpPage(
            session: session,
            onSignIn: () => signInCalls++,
            onChat: (_, {chatId}) => fail('Guest opened a chat'),
          ),
        ),
      ),
    );

    await tester.ensureVisible(find.text('Собрать шкаф'));
    await tester.tap(find.text('Собрать шкаф'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Войти, чтобы откликнуться'));
    await tester.pumpAndSettle();

    expect(signInCalls, 1);
    expect(api.posts, isEmpty);
    await tester.pumpWidget(const SizedBox());
    session.dispose();
  });

  testWidgets('Smart Match displays criteria and forwards exact consent', (
    tester,
  ) async {
    final api = _FixtureApi(signed: true);
    final session = HPointSession(api)..data = api.sync;
    (int, int?)? opened;
    await tester.binding.setSurfaceSize(const Size(420, 960));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(splashFactory: NoSplash.splashFactory),
        home: Scaffold(
          body: HelpPage(
            session: session,
            onSignIn: () => fail('Signed-in author was sent to auth'),
            onChat: (requestId, {chatId}) => opened = (requestId, chatId),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Мои заявки'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Собрать шкаф'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Подобрать помощника'));
    await tester.pumpAndSettle();

    expect(find.text('87%'), findsOneWidget);
    expect(
      find.textContaining(
        'В профиле указана сборка шкафов',
        findRichText: true,
      ),
      findsOneWidget,
    );
    await tester.enterText(find.byType(TextField), 'autofilled@example.test');
    await tester.tap(find.text('Посмотреть вручную'));
    await tester.pumpAndSettle();
    expect(api.posts.last.$2, {
      'request_id': 17,
      'mode': 'manual',
      'question': '',
    });
    await tester.ensureVisible(find.text('Выбрать исполнителя'));
    await tester.tap(find.text('Выбрать исполнителя'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Выбрать'));
    await tester.pumpAndSettle();

    expect(api.posts.last.$1, '/api/requests/response/accept');
    expect(api.posts.last.$2, {
      'request_id': 17,
      'helper_id': -8,
      'application_token': 'current-consent',
    });
    expect(opened, (17, 31));
    await tester.pumpWidget(const SizedBox());
    session.dispose();
  });
}
