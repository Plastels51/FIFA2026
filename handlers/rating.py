import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User

router = Router()

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


async def build_rating_text(tg_id: int, session: AsyncSession) -> str:
    top_result = await session.execute(
        select(User).order_by(User.points.desc()).limit(10)
    )
    top_users = top_result.scalars().all()

    lines = ["<b>Топ-10 участников:</b>\n"]
    for i, u in enumerate(top_users, start=1):
        medal = MEDALS.get(i, f"{i}.")
        name = html.escape(u.full_name or u.username or str(u.tg_id))
        lines.append(f"{medal} {name} — <b>{u.points} очков</b>")

    user_result = await session.execute(select(User).where(User.tg_id == tg_id))
    current = user_result.scalar_one_or_none()

    if current:
        count_result = await session.execute(
            select(func.count(User.id)).where(User.points > current.points)
        )
        ahead = count_result.scalar()
        my_rank = ahead + 1
        lines.append(f"\nТвоё место: <b>{my_rank}</b> ({current.points} очков)")

    return "\n".join(lines)


@router.message(Command("rating"))
async def cmd_rating(message: Message, session: AsyncSession) -> None:
    text = await build_rating_text(message.from_user.id, session)
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "rating")
async def cb_rating(callback: CallbackQuery, session: AsyncSession) -> None:
    text = await build_rating_text(callback.from_user.id, session)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()
