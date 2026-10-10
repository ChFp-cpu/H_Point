import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from .config import *
from .database import init_db
from .handlers import router

async def main() -> None:
    token = __import__('os').getenv("BOT_TOKEN")
    if not token:
        print("Ошибка: не задана переменная окружения BOT_TOKEN.")
        print("PowerShell: $env:BOT_TOKEN='...' ")
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    init_db()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    from . import web
    web.configure_telegram_notifications(bot)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    logging.info("H-Point бот запущен")
    await dp.start_polling(bot)
