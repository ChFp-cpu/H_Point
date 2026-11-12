# H-Point · Flutter

Мобильный клиент H-Point для Android и iOS. По умолчанию подключается к `https://gethpoint.ru`. У сайта и приложения общие аккаунты, заявки и чаты.

- Без аккаунта доступны публичные заявки, мероприятия и услуги.
- После входа по email доступны создание заявок, отклики, настройки помощника, Smart Match, чаты с фото, действия по заявкам, запись на мероприятия и профиль.
- В «Для работы» можно управлять клиентами, записями, расписанием, услугами, объектами, задачами, сметами и командой. Профильные разделы зависят от профессии и роли в организации. Сметы экспортируются в PDF и XLSX, а публичные услуги и обращения открываются в приложении.
- Поддержка открывается на сайте.

## Сборка Android

Используйте Flutter 3.47.9, Android SDK 36 и JDK 21. На Windows SDK и проект лучше размещать по пути без кириллицы.

```sh
flutter pub get
flutter analyze
flutter test
flutter build apk --release
```

Результат — `build/app/outputs/flutter-apk/app-release.apk`. Текущая конфигурация подписывает установочную сборку тестовым ключом. Для публикации потребуется ключ загрузки проекта и соответствующая настройка подписи.

Для проверки на отдельной базе можно передать `--dart-define=HPOINT_API_ORIGIN=http://10.0.2.2:8080` в `flutter run` на Android Emulator. HTTP разрешён только для локальных адресов в отладочной сборке.

## Сборка iOS

[Build H-Point for iOS](https://github.com/ChFp-cpu/H_Point/actions/workflows/mobile-ios.yml) собирает приложение на macOS. В артефактах успешного прогона доступны приложение для Simulator, снимок запуска и архив `.xcarchive` для iPhone без подписи.

Локальная сборка на Mac из папки `mobile`:

```sh
flutter pub get --enforce-lockfile
flutter build ios --simulator --debug
open ios/Runner.xcworkspace
```

Для запуска на своём iPhone выберите команду в **Runner → Signing & Capabilities** в Xcode, подключите iPhone и нажмите **Run**. Для распространения через TestFlight нужен [Apple Developer Program](https://developer.apple.com/programs/) и подпись для Bundle ID `ru.gethpoint.hpoint`. Архив без подписи нельзя установить на iPhone.

Если Mac и аккаунта разработчика нет, откройте [H-Point](https://gethpoint.ru) в Safari, нажмите **Поделиться → На экран «Домой»**, включите **Открывать как веб-приложение**, если этот переключатель доступен, и нажмите **Добавить**.
