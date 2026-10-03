"""H-Point — точка запуска Telegram-бота.

Бизнес-логика, БД, клавиатуры и handlers вынесены в пакет hpoint.
Публичные константы и функции бизнес-логики реэкспортируются для совместимости.
"""
import asyncio
from hpoint.api import *
from hpoint.handlers import router
from hpoint.main import main

if __name__ == "__main__":
    asyncio.run(main())
