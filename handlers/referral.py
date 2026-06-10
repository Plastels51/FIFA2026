from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import User

router = Router()


async def build_referral_text(tg_id: int, session: AsyncSession, bot_username: str) -> str:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one_or_none()
    if not user:
        return "Сначала зарегистрируйся через /start"

    count_result = await session.execute(
        select(func.count()).where(User.referred_by == user.id)
    )
    invited_count = count_result.scalar_one()

    link = f"https://t.me/{bot_username}?start=ref_{user.ref_code}"
    return (
        f"Твоя реферальная ссылка:\n<code>{link}</code>\n\n"
        f"Приглашено друзей: <b>{invited_count}</b>\n"
        f"За каждого приглашённого ты получаешь <b>+1 балл</b>!"
    )


@router.message(Command("referral"))
async def cmd_referral(message: Message, session: AsyncSession) -> None:
    bot = await message.bot.get_me()
    text = await build_referral_text(message.from_user.id, session, bot.username)
    await message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "referral")
async def cb_referral(callback: CallbackQuery, session: AsyncSession) -> None:
    bot = await callback.bot.get_me()
    text = await build_referral_text(callback.from_user.id, session, bot.username)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()
