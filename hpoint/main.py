import logging
import asyncio
from contextlib import suppress
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
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
    validate_production_config()
    init_db()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    from . import web
    bot_profile = await bot.me()
    web.configure_telegram_notifications(bot, bot_profile.username)
    # Replace the old Telegram command list as well as the reply keyboard.
    await bot.set_my_commands([BotCommand(command=command,description=description) for command,description in (
        ("start","Открыть H-Point"),("website","Перейти на сайт"),("chats","Открыть чаты"),
        ("chat","Ответить по текущей помощи"),("help","Как пользоваться"),("cancel","Отменить действие"),
        ("link","Привязать профиль по коду"),("unlink","Отвязать Telegram"),
    )])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    logging.info("H-Point бот запущен")
    from . import database,work_bot
    reminders=asyncio.create_task(work_bot.reminder_loop(bot,database.db))
    try:await dp.start_polling(bot)
    finally:
        reminders.cancel()
        with suppress(asyncio.CancelledError):await reminders
