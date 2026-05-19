import asyncio
import html
import logging
from datetime import timedelta

from aiogram.exceptions import TelegramRetryAfter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from config import MOSCOW_TZ, moscow_now
from database.db import async_session_factory
from database.models import Match, Prediction, User
from handlers.predictions import get_prediction_keyboard

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)

SEND_DELAY = 0.05  # 20 msg/sec — c запасом под лимит Telegram (~30/sec)


async def safe_send(bot, chat_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(chat_id, text, **kwargs)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(chat_id, text, **kwargs)
            return True
        except Exception as exc:
            logger.warning("send_message failed after retry to %s: %s", chat_id, exc)
            return False
    except Exception as exc:
        logger.debug("send_message failed to %s: %s", chat_id, exc)
        return False


async def broadcast(bot, chat_ids, text: str, **kwargs) -> tuple[int, int]:
    sent = failed = 0
    for chat_id in chat_ids:
        ok = await safe_send(bot, chat_id, text, **kwargs)
        sent += int(ok)
        failed += int(not ok)
        await asyncio.sleep(SEND_DELAY)
    return sent, failed


async def _send_match_notification(match_id: int, bot) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(Match).where(Match.id == match_id))
        match = result.scalar_one_or_none()
        if not match or match.is_closed:
            return

        users_result = await session.execute(select(User))
        users = users_result.scalars().all()

        text = (
            f"Новый прогноз!\n\n"
            f"Матч: <b>{html.escape(match.team_a)} — {html.escape(match.team_b)}</b>\n"
            f"Время: {match.match_time.strftime('%d.%m.%Y %H:%M')} МСК\n\n"
            f"Выбери свой вариант:"
        )
        kb = get_prediction_keyboard(match)
        await broadcast(bot, (u.tg_id for u in users), text, reply_markup=kb, parse_mode="HTML")


async def _send_reminder(match_id: int, bot) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(Match).where(Match.id == match_id))
        match = result.scalar_one_or_none()
        if not match or match.is_closed:
            return

        users_result = await session.execute(select(User))
        users = users_result.scalars().all()

        voted_result = await session.execute(
            select(Prediction.user_id).where(Prediction.match_id == match_id)
        )
        voted_ids = {row[0] for row in voted_result.all()}

        kb = get_prediction_keyboard(match)
        text = (
            f"Напоминание! До конца приёма прогнозов на матч "
            f"<b>{html.escape(match.team_a)} — {html.escape(match.team_b)}</b> осталось 30 минут!"
        )
        targets = [u.tg_id for u in users if u.id not in voted_ids]
        await broadcast(bot, targets, text, reply_markup=kb, parse_mode="HTML")


async def _auto_close_match(match_id: int) -> None:
    async with async_session_factory() as session:
        result = await session.execute(select(Match).where(Match.id == match_id))
        match = result.scalar_one_or_none()
        if match and not match.is_closed:
            match.is_closed = True
            await session.commit()


def schedule_match_notifications(match: Match, bot) -> None:
    notify_time = match.match_time - timedelta(hours=1)
    reminder_time = match.match_time - timedelta(minutes=30)
    now = moscow_now()

    if notify_time > now:
        scheduler.add_job(
            _send_match_notification,
            "date",
            run_date=notify_time,
            args=[match.id, bot],
            id=f"match_notify_{match.id}",
            replace_existing=True,
        )

    if reminder_time > now:
        scheduler.add_job(
            _send_reminder,
            "date",
            run_date=reminder_time,
            args=[match.id, bot],
            id=f"match_reminder_{match.id}",
            replace_existing=True,
        )

    if match.match_time > now:
        scheduler.add_job(
            _auto_close_match,
            "date",
            run_date=match.match_time,
            args=[match.id],
            id=f"match_close_{match.id}",
            replace_existing=True,
        )


async def _scan_matches(bot) -> None:
    async with async_session_factory() as session:
        now = moscow_now()
        result = await session.execute(
            select(Match).where(Match.is_closed == False, Match.match_time > now)
        )
        for match in result.scalars().all():
            schedule_match_notifications(match, bot)


def start_scheduler(bot) -> None:
    scheduler.add_job(
        _scan_matches,
        "interval",
        seconds=60,
        args=[bot],
        id="match_scanner",
        replace_existing=True,
        next_run_time=moscow_now(),
    )
    scheduler.start()
