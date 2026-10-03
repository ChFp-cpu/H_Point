# H-Point — Web-first + Telegram

## Что теперь работает
- Сайт — главное пространство H-Point, а Telegram — второй полноценный клиент.
- После регистрации пользователь сразу попадает в рабочий кабинет, а не остаётся на приветственном экране.
- Заявки: создание, список, статусы, завершение и отзывы.
- Smart Match: подбор по категории, рейтингу, верификации и расстоянию.
- Карта: открытые заявки и кандидаты Smart Match.
- Чат: отдельный чат создаётся после назначения помощника.
- Умный поиск открытых заявок.
- Профиль, город, описание, рейтинг и история.
- Telegram: одноразовый код `/link КОД` связывает веб-аккаунт и Telegram-аккаунт.
- H·Point+: платные функции на сайте и в Telegram.
- Оплата только в RUB через внешний эквайринг YooKassa; Telegram Stars не используются.
- Один `run.py` запускает сайт и Telegram-бот одновременно.

## Первый запуск Windows

1. Открой:
```powershell
cd "C:\Главная\HPoint"
```

2. Один раз создай окружение и зависимости:
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

3. Создай `.env` из `.env.example` и заполни:
```env
BOT_TOKEN=токен_от_BotFather
WEB_HOST=127.0.0.1
WEB_PORT=8080
WEB_PUBLIC_URL=http://127.0.0.1:8080
DB_PATH=hpoint.db

# Для реального эквайринга после подключения YooKassa:
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
PAYMENT_RETURN_URL=http://127.0.0.1:8080/payment/result
```

4. После этого запускать всё можно одной командой:
```powershell
.\.venv\Scripts\python.exe run.py
```
или двойным кликом по `start.bat`.

`start.bat` сам создаёт `.venv`, ставит зависимости и создаёт `.env` из `.env.example`, если их ещё нет. Токен больше не нужно вводить в PowerShell при каждом запуске.

## Telegram-привязка

1. Зарегистрируйтесь на сайте.
2. Откройте **Профиль → Telegram**.
3. Нажмите «Получить новый код привязки».
4. Откройте H-Point в Telegram.
5. Отправьте:
```text
/link ВАШ_КОД
```
6. Обновите сайт. В профиле появится «Telegram привязан».

После этого сайт и бот работают с одной учётной записью и общей SQLite БД.

## YooKassa

Для реальных платежей нужны:
- `YOOKASSA_SHOP_ID`
- `YOOKASSA_SECRET_KEY`
- публичный HTTPS-домен
- `WEB_PUBLIC_URL=https://ваш-домен`
- `PAYMENT_RETURN_URL=https://ваш-домен/payment/result`
- webhook YooKassa:
  `https://ваш-домен/api/payments/webhook`

Без этих данных сайт и бот запускаются, но покупка не проходит — приложение не делает фиктивный успешный платёж.

## Проверка

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Все базовые тесты должны завершиться `OK`.

## Важно для production

Нужны HTTPS, домен, резервные копии `hpoint.db`, защита `.env` и политика обработки персональных данных. Не публикуйте точный домашний адрес в тексте заявки; геопозиция используется для Smart Match.
