"""Единый запуск H-Point: Flask-сайт + Telegram-бот в одном процессе."""
import asyncio, os, threading
from dotenv import load_dotenv

load_dotenv()
from hpoint.database import init_db
from hpoint.main import main as bot_main
from webapp.app import app


def run_bot():
    asyncio.run(bot_main())

if __name__ == '__main__':
    init_db()
    if not os.getenv('BOT_TOKEN'):
        print('ОШИБКА: не задан BOT_TOKEN')
        raise SystemExit(1)
    threading.Thread(target=run_bot, name='telegram-bot', daemon=True).start()
    port=int(os.getenv('PORT','5000'))
    host=os.getenv('HOST','0.0.0.0')
    print(f'H-Point: web http://{host}:{port} | Telegram bot: ON')
    app.run(host=host, port=port, threaded=True, use_reloader=False)
