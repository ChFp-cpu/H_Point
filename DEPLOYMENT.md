# Запуск H-Point на VPS

Проект уже настроен для Docker Compose: сайт, PostgreSQL, Telegram-бот и Caddy с автоматическим HTTPS. Отдельно устанавливать Nginx и Python-зависимости на VPS не нужно.

## 1. Подготовьте сервер и DNS

На Ubuntu установите Docker Engine с Compose plugin по официальной инструкции Docker. В DNS создайте A-запись `gethpoint.ru` на публичный IPv4 VPS. Разрешите входящие TCP-порты **22, 80 и 443** в firewall VPS и провайдера. PostgreSQL и порт 8080 наружу не открывайте.

## 2. Загрузите проект и настройте `.env`

На VPS перейдите в папку `HPoint` (там лежит `compose.yaml`) и выполните:

```bash
cp .env.example .env
nano .env
```

Заполните в `.env`:

```dotenv
APP_ENV=production
CADDY_DOMAIN=gethpoint.ru
WEB_PUBLIC_URL=https://gethpoint.ru
SESSION_COOKIE_SECURE=1
TRUST_PROXY_HEADERS=1
BOT_TOKEN=токен_от_BotFather
BOT_USERNAME=имя_бота_без_собаки
POSTGRES_PASSWORD=длинный_случайный_пароль_из_букв_и_цифр
DATABASE_URL=postgresql://hpoint:ТОТ_ЖЕ_ПАРОЛЬ@db:5432/hpoint
```

В `DATABASE_URL` подставьте тот же пароль, что в `POSTGRES_PASSWORD`. Используйте пароль только из латинских букв и цифр, чтобы не кодировать специальные символы. Не публикуйте `.env` и не отправляйте токен бота в чат.

`BOT_TOKEN` и `BOT_USERNAME` нужны для запуска контейнера бота и входа через Telegram. Остальные необязательные интеграции (карта и Robokassa) можно оставить пустыми.

## 3. Запустите сайт

Из папки `HPoint`:

```bash
chmod 600 .env
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app bot caddy
```

Откройте **https://gethpoint.ru**. Первый выпуск HTTPS-сертификата Caddy может занять минуту. Если сайт не открылся, проверьте DNS, доступность портов 80/443 и вывод команды `docker compose logs`.

После обновления файлов проекта повторите `docker compose up -d --build`. Для остановки: `docker compose down` (данные PostgreSQL сохраняются в Docker volume). Не используйте `docker compose down -v`: это удалит базу.
