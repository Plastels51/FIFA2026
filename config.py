import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

USER_BOT_TOKEN: str = os.getenv("USER_BOT_TOKEN", "")
ADMIN_BOT_TOKEN: str = os.getenv("ADMIN_BOT_TOKEN", "")
ADMIN_IDS: list[int] = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# Числовой ID канала для проверки подписки (вида -1001234567890).
# Бот USER_BOT должен быть администратором этого канала.
_channel_raw = os.getenv("CHANNEL_ID", "").strip()
CHANNEL_ID: int | None = int(_channel_raw) if _channel_raw.lstrip("-").isdigit() else None

# Ссылка-приглашение на канал для кнопки «Подписаться».
CHANNEL_URL: str = os.getenv("CHANNEL_URL", "https://t.me/+NT6WIW-KEcwyNTU6")

DATABASE_URL: str = "sqlite+aiosqlite:///football_bot.db"

MOSCOW_TZ = timezone(timedelta(hours=3))


def moscow_now() -> datetime:
    return datetime.now(tz=MOSCOW_TZ).replace(tzinfo=None)
