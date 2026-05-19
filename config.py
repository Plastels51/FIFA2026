import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

USER_BOT_TOKEN: str = os.getenv("USER_BOT_TOKEN", "")
ADMIN_BOT_TOKEN: str = os.getenv("ADMIN_BOT_TOKEN", "")
ADMIN_IDS: list[int] = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DATABASE_URL: str = "sqlite+aiosqlite:///football_bot.db"

MOSCOW_TZ = timezone(timedelta(hours=3))


def moscow_now() -> datetime:
    return datetime.now(tz=MOSCOW_TZ).replace(tzinfo=None)
