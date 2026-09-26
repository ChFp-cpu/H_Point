# H Point

Единый MVP: сайт + Telegram-бот на одной SQLite-базе.

## Запуск

```powershell
py -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
notepad .env
.\venv\Scripts\python.exe run.py
```

`.env`:

```env
BOT_TOKEN=ваш_токен_бота
SECRET_KEY=случайная_длинная_строка
```

Сайт: `http://127.0.0.1:5000`

## Интеграция

- сайт и Telegram используют одну БД и один `user_id` после привязки;
- веб-аккаунт имеет постоянный вход по никнейму + паролю;
- сессия сайта сохраняется 30 дней;
- Telegram привязывается через шестизначный код;
- заявки, отклики, выбор помощника, статусы, HP и оценки общие;
- действия сайта создают уведомления в Telegram;
- действия Telegram сразу меняют данные, которые видны на сайте;
- открытая заявка не считается активной задачей;
- только `in_progress` блокирует параллельную активную помощь;
- Telegram-уведомления не дублируются.

## Проверка

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```
