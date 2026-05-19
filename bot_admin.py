import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import ADMIN_BOT_TOKEN, USER_BOT_TOKEN
from database.db import async_session_factory, init_db
from handlers import admin

logging.basicConfig(level=logging.INFO)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("aiogram.dispatcher").setLevel(logging.CRITICAL)


async def db_middleware(handler, event, data):
    async with async_session_factory() as session:
        data["session"] = session
        return await handler(event, data)


async def main() -> None:
    if not ADMIN_BOT_TOKEN:
        raise RuntimeError("ADMIN_BOT_TOKEN is not set in .env")
    if not USER_BOT_TOKEN:
        raise RuntimeError("USER_BOT_TOKEN is not set in .env")

    await init_db()

    bot = Bot(token=ADMIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    user_bot = Bot(token=USER_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    dp = Dispatcher(storage=MemoryStorage())
    dp["user_bot"] = user_bot
    dp.update.middleware(db_middleware)

    dp.include_router(admin.router)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await user_bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
