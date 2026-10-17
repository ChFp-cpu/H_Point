"""Run only the Telegram long-polling worker for H-Point."""
import asyncio

from dotenv import load_dotenv

from run import SingleInstance


load_dotenv()


def main():
    from hpoint.config import BOT_TOKEN, validate_production_config

    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is not set. Set it in .env before starting the bot.")
        return 1

    instance = SingleInstance()
    if not instance.acquire():
        print("Telegram polling is already running in this project folder. Close the other run.py or run_bot.py window first.")
        return 2

    try:
        validate_production_config()
        from hpoint.main import main as bot_main

        print("H-Point Telegram bot started")
        asyncio.run(bot_main())
    except KeyboardInterrupt:
        pass
    finally:
        instance.release()
        print("H-Point Telegram bot stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
