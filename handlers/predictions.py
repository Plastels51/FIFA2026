import html

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import moscow_now
from database.models import Match, Prediction, User


def get_prediction_keyboard(match: Match) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=opt,
            callback_data=f"predict:{match.id}:{idx}"
        )]
        for idx, opt in enumerate(match.options)
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

router = Router()


@router.callback_query(F.data.startswith("predict:"))
async def cb_predict(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        _, match_id_str, idx_str = callback.data.split(":", 2)
        match_id = int(match_id_str)
        idx = int(idx_str)
    except (ValueError, AttributeError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return
    tg_id = callback.from_user.id

    user_result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = user_result.scalar_one_or_none()
    if not user:
        await callback.answer("Сначала зарегистрируйся через /start", show_alert=True)
        return

    match_result = await session.execute(select(Match).where(Match.id == match_id))
    match = match_result.scalar_one_or_none()
    if not match:
        await callback.answer("Матч не найден.", show_alert=True)
        return

    if match.is_closed or moscow_now() >= match.match_time:
        await callback.answer("Приём прогнозов на этот матч закрыт.", show_alert=True)
        return

    options = match.options
    if idx < 0 or idx >= len(options):
        await callback.answer("Недопустимый вариант ответа.", show_alert=True)
        return
    answer = options[idx]

    existing = await session.execute(
        select(Prediction).where(
            Prediction.user_id == user.id,
            Prediction.match_id == match_id,
        )
    )
    if existing.scalar_one_or_none():
        await callback.answer("Ты уже сделал прогноз на этот матч.", show_alert=True)
        return

    prediction = Prediction(user_id=user.id, match_id=match_id, answer=answer)
    session.add(prediction)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        await callback.answer("Ты уже сделал прогноз на этот матч.", show_alert=True)
        return

    await callback.message.edit_text(
        f"Прогноз принят!\n\n"
        f"Матч: <b>{html.escape(match.team_a)} — {html.escape(match.team_b)}</b>\n"
        f"Твой выбор: <b>{html.escape(answer)}</b>\n\n"
        f"Удачи! Результат узнаешь после матча.",
        parse_mode="HTML",
    )
    await callback.answer()
