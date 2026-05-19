import asyncio
import logging

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL
from database.models import Base

logger = logging.getLogger(__name__)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_wal(dbapi_connection, _) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


async def init_db(retries: int = 5, delay: float = 0.5) -> None:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.run_sync(Base.metadata.create_all)
            return
        except OperationalError as e:
            last_err = e
            logger.warning("init_db attempt %d failed: %s", attempt + 1, e)
            await asyncio.sleep(delay * (attempt + 1))
    raise RuntimeError(f"init_db failed after {retries} attempts: {last_err}")
