import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hpoint/api.dart';
import 'package:hpoint/session.dart';
import 'package:hpoint/work.dart';

class _WorkApi extends HPointApi {
  static const userId = -7;
  static const ownerId = -12;
  final clients = <Json>[];
  final dashboardOwners = <String?>[];
  final clientWrites = <Json>[];

  @override
  Future<Json> get(String path, [Map<String, String>? query]) async {
    if (path != '/api/commercial') {
      throw StateError('Unexpected GET $path');
    }
    dashboardOwners.add(query?['owner_id']);
    return {
      'ok': true,
      'commercial': {
        'selected_owner_id': ownerId,
        'profile': {
          'title': 'Мастерская',
          'kind_title': 'Организация',
          'active': true,
        },
        'permissions': {'manage': true, 'write': true, 'owner': false},
        'clients': List<Json>.of(clients),
        'metrics': {'clients': clients.length},
      },
    };
  }

  @override
  Future<Json> post(String path, [Json body = const {}]) async {
    if (path != '/api/commercial/clients') {
      throw StateError('Unexpected POST $path');
    }
    clientWrites.add(Map.of(body));
    clients.add({
      'id': 1,
      'name': body['name'],
      'contact': body['contact'],
      'notes': body['notes'],
      'active': body['active'] == true ? 1 : 0,
    });
    return {'ok': true, 'id': 1};
  }
}

void main() {
  testWidgets('a workspace administrator adds a client on a narrow phone', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 690));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = _WorkApi();
    final session = HPointSession(api)
      ..data = {
        'current_user_id': _WorkApi.userId,
        'user': {'id': _WorkApi.userId, 'name': 'Администратор'},
      };
    addTearDown(session.dispose);

    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(splashFactory: NoSplash.splashFactory),
        home: WorkPage(
          session: session,
          onSignIn: () => fail('Signed-in administrator was sent to auth'),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final clientSection = find.text('Клиенты').hitTestable();
    await tester.scrollUntilVisible(clientSection, 150);
    await tester.pumpAndSettle();
    await tester.tap(clientSection);
    await tester.pumpAndSettle();
    expect(find.text('Клиентов пока нет'), findsOneWidget);

    await tester.tap(find.text('Добавить клиента'));
    await tester.pumpAndSettle();
    final submit = find.widgetWithText(FilledButton, 'Добавить клиента');
    await tester.ensureVisible(submit);
    await tester.pumpAndSettle();
    await tester.tap(submit);
    await tester.pumpAndSettle();
    expect(find.text('Не менее 2 символов'), findsOneWidget);
    expect(api.clientWrites, isEmpty);

    await tester.enterText(
      find.widgetWithText(TextFormField, 'Имя клиента'),
      '  Анна Соколова  ',
    );
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Контакт'),
      '+7 900 123-45-67',
    );
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Заметки'),
      'Первая консультация',
    );
    await tester.ensureVisible(submit);
    await tester.pumpAndSettle();
    await tester.tap(submit);
    await tester.pumpAndSettle();

    expect(api.clientWrites, [
      {
        'owner_id': _WorkApi.ownerId,
        'name': 'Анна Соколова',
        'contact': '+7 900 123-45-67',
        'notes': 'Первая консультация',
        'active': true,
      },
    ]);
    expect(api.dashboardOwners, [null, '${_WorkApi.ownerId}']);
    expect(find.text('Анна Соколова'), findsOneWidget);
    expect(find.text('Первая консультация'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
