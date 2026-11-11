import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hpoint/api.dart';
import 'package:hpoint/main.dart';
import 'package:hpoint/session.dart';

class _GuestApi extends HPointApi {
  @override
  Future<void> restore() async {}

  @override
  Future<Json> get(String path, [Map<String, String>? query]) async {
    if (path != '/api/guest') throw StateError('Unexpected request: $path');
    return {
      'ok': true,
      'guest': true,
      'requests': <Json>[],
      'services': <Json>[],
      'events': <Json>[],
      'categories': <Json>[],
    };
  }
}

class _UnavailableStorageApi extends _GuestApi {
  @override
  Future<void> restore() async {
    throw PlatformException(
      code: 'Unexpected security result code',
      details: -34018,
    );
  }
}

void main() {
  test('Guest data loads when secure storage cannot read a session', () async {
    final session = HPointSession(_UnavailableStorageApi());
    addTearDown(session.dispose);
    await session.start();
    expect(session.guest?['guest'], isTrue);
    expect(session.error, isNull);
    expect(session.signedIn, isFalse);
  });

  testWidgets(
    'Guest can browse native screens and open email login on a narrow display',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(320, 740));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final session = HPointSession(_GuestApi());
      addTearDown(session.dispose);
      await tester.pumpWidget(HPointApp(session: session));
      await tester.pumpAndSettle();
      expect(find.text('Помощь рядом'), findsOneWidget);
      expect(find.text('Нужна помощь'), findsOneWidget);

      await tester.tap(find.text('Нужна помощь'));
      await tester.pumpAndSettle();
      expect(find.text('Email'), findsOneWidget);
      expect(find.text('Пароль'), findsOneWidget);
      await tester.tap(find.text('Создать аккаунт'));
      await tester.pumpAndSettle();
      expect(find.text('Имя'), findsOneWidget);
      expect(find.text('Получить код'), findsOneWidget);

      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Для работы'));
      await tester.pumpAndSettle();
      expect(find.text('Кабинет для работы'), findsOneWidget);
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();
      await tester.tap(find.byIcon(Icons.event_outlined));
      await tester.pumpAndSettle();
      expect(find.text('Пока нет предстоящих мероприятий'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
