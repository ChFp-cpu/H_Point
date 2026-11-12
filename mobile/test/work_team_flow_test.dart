import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hpoint/api.dart';
import 'package:hpoint/session.dart';
import 'package:hpoint/work_team.dart';

class _InquiryApi extends HPointApi {
  Json? lastWrite;
  Json? inquiry;

  @override
  Future<Json> get(String path, [Map<String, String>? query]) async =>
      switch (path) {
        '/api/work-inquiries/service' => {
          'ok': true,
          'service': {
            'id': 42,
            'title': 'Сборка шкафа',
            'organization_title': 'Мастерская',
            'price_rub': 1200,
            'duration_minutes': 60,
          },
        },
        '/api/work-inquiries/mine' => {
          'ok': true,
          'inquiries': [?inquiry],
        },
        '/api/work-inquiries' => {'ok': true, 'inquiry': inquiry},
        _ => throw StateError('Unexpected GET $path'),
      };

  @override
  Future<Json> post(String path, [Json body = const {}]) async {
    if (path == '/api/work-inquiries') {
      lastWrite = Map.of(body);
      inquiry = {
        'id': 55,
        'service_title': 'Сборка шкафа',
        'organization_title': 'Мастерская',
        'price_rub': 1200,
        'duration_minutes': 60,
        'status': 'new',
        'can_cancel': true,
        'message': body['message'],
        'contact': body['contact'],
      };
    } else if (path == '/api/work-inquiries/cancel') {
      expect(body, {'id': 55});
      inquiry = {...inquiry!, 'status': 'cancelled', 'can_cancel': false};
    } else {
      throw StateError('Unexpected POST $path');
    }
    return {
      'ok': true,
      'result': {'id': 55, 'inquiry': inquiry},
    };
  }
}

void main() {
  testWidgets('a customer sends and cancels a service inquiry in the app', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 690));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = _InquiryApi();
    final session = HPointSession(api)
      ..data = {
        'current_user_id': -7,
        'user': {'id': -7, 'name': 'Заказчик'},
      };
    addTearDown(session.dispose);
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(splashFactory: NoSplash.splashFactory),
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => openWorkService(
                context,
                session,
                42,
                onSignIn: () => fail('Signed-in customer was sent to auth'),
              ),
              child: const Text('Открыть услугу'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Открыть услугу'));
    await tester.pumpAndSettle();
    expect(find.text('Мастерская'), findsOneWidget);
    await tester.tap(find.text('Отправить обращение'));
    await tester.pumpAndSettle();

    await tester.enterText(
      find.widgetWithText(TextFormField, 'Что нужно сделать'),
      '  Собрать шкаф в прихожей  ',
    );
    await tester.enterText(
      find.widgetWithText(TextFormField, 'Как с вами связаться'),
      '+7 900 123-45-67',
    );
    final submit = find.text('Отправить обращение');
    await tester.ensureVisible(submit);
    await tester.pumpAndSettle();
    await tester.tap(submit);
    await tester.pumpAndSettle();
    expect(api.lastWrite, {
      'service_id': 42,
      'request_key': matches(RegExp(r'^[a-f0-9]{48}$')),
      'message': 'Собрать шкаф в прихожей',
      'contact': '+7 900 123-45-67',
      'preferred_time': '',
      'photos': <String>[],
    });
    expect(find.text('Мои обращения'), findsOneWidget);
    await tester.tap(find.text('Сборка шкафа'));
    await tester.pumpAndSettle();

    expect(find.text('Собрать шкаф в прихожей'), findsOneWidget);
    final cancel = find.text('Отменить обращение');
    await tester.ensureVisible(cancel);
    await tester.pumpAndSettle();
    await tester.tap(cancel);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Отменить обращение'));
    await tester.pumpAndSettle();
    expect(find.text('Отменено'), findsOneWidget);
    expect(cancel, findsNothing);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
  });
}
