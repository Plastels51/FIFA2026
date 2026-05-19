import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import USER_BOT_TOKEN
from database.db import async_session_factory, init_db
from handlers import predictions, rating, referral, start
from scheduler import scheduler, start_scheduler

logging.basicConfig(level=logging.INFO)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logging.getLogger("aiogram.dispatcher").setLevel(logging.CRITICAL)


async def db_middleware(handler, event, data):
    async with async_session_factory() as session:
        data["session"] = session
        return await handler(event, data)


async def main() -> None:
    if not USER_BOT_TOKEN:
        raise RuntimeError("USER_BOT_TOKEN is not set in .env")

    await init_db()

    bot = Bot(token=USER_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(db_middleware)

    dp.include_router(start.router)
    dp.include_router(predictions.router)
    dp.include_router(rating.router)
    dp.include_router(referral.router)

    start_scheduler(bot)

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
