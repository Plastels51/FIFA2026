import html
import secrets

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import User


def get_join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚽️ Участвую!", callback_data="join")]
    ])


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Мой рейтинг", callback_data="rating")],
        [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="referral")],
    ])

router = Router()

WELCOME_TEXT = (
    "<b>Прогнозист ЧМ 2026</b>!\n\n"
   "• Каждый день ты получаешь 2 задания — прогнозы на матчи\n"
    "• За правильный прогноз — <b>+1 балл</b>\n"
    "• За приглашённого друга — <b>+2 балла</b>\n"
    "• По итогам турнира лучшие участники получат <b>приз</b>\n\n"
    "Нажми кнопку, чтобы начать!"
)


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    tg_id = message.from_user.id
    parts = message.text.split(maxsplit=1)
    args = parts[1] if len(parts) > 1 else None

    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one_or_none()

    if user:
        await message.answer(
            f"Ты уже участвуешь! Удачи, {html.escape(message.from_user.first_name or '')}!",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    ref_code = secrets.token_hex(6)
    referrer: User | None = None

    if args and args.startswith("ref_"):
        ref_token = args[4:]
        ref_result = await session.execute(select(User).where(User.ref_code == ref_token))
        candidate = ref_result.scalar_one_or_none()
        if candidate and candidate.tg_id != tg_id:
            referrer = candidate

    new_user = User(
        tg_id=tg_id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
        ref_code=ref_code,
        referred_by=referrer.id if referrer else None,
    )
    session.add(new_user)
    if referrer:
        referrer.points += 2
    await session.commit()

    await message.answer(WELCOME_TEXT, reply_markup=get_join_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "join")
async def cb_join(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Отлично! Ты в игре. Ожидай первое задание!\n\n"
        "Используй меню ниже:",
        reply_markup=get_main_menu_keyboard(),
    )
    await callback.answer()
