import logging, asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from .config import *
from .database import init_db, telegram_users_with_pending, pending_notifications, mark_notification_sent
from .handlers import router

async def notification_loop(bot):
    while True:
        try:
            for row in telegram_users_with_pending():
                for n in pending_notifications(row['user_id']):
                    try:
                        await bot.send_message(row['telegram_id'], n['text'])
                        mark_notification_sent(n['id'])
                    except Exception:
                        logging.exception('notification delivery failed')
        except Exception:
            logging.exception('notification loop failed')
        await asyncio.sleep(2)

async def main() -> None:
    token = __import__('os').getenv("BOT_TOKEN")
    if not token:
        print("Ошибка: не задана переменная окружения BOT_TOKEN.")
        print("PowerShell: $env:BOT_TOKEN='...' ")
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    init_db()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    asyncio.create_task(notification_loop(bot))
    logging.info("H-Point бот запущен")
    await dp.start_polling(bot)
