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


def _back_to_matches_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« К списку матчей", callback_data="predict_menu")],
    ])


@router.callback_query(F.data == "predict_menu")
async def cb_predict_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    user_result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
    user = user_result.scalar_one_or_none()
    if not user:
        await callback.answer("Сначала зарегистрируйся через /start", show_alert=True)
        return

    now = moscow_now()
    matches_result = await session.execute(
        select(Match)
        .where(Match.is_closed == False, Match.match_time > now)
        .order_by(Match.match_time)
    )
    matches = matches_result.scalars().all()

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад", callback_data="back_to_menu")]
    ])

    if not matches:
        await callback.message.edit_text(
            "Сейчас нет открытых матчей для прогнозов.\nДождись следующего!",
            reply_markup=back_kb,
        )
        await callback.answer()
        return

    preds_result = await session.execute(
        select(Prediction.match_id).where(Prediction.user_id == user.id)
    )
    voted_match_ids = {row[0] for row in preds_result.all()}

    lines = [
        "<b>Как сделать прогноз:</b>",
        "1. Выбери игру из списка ниже",
        "2. Выбери свой вариант исхода",
        "",
        "Прогноз можно сделать на каждую открытую игру. ✅ — ты уже проголосовал.",
        "",
        "<b>Доступные матчи:</b>",
    ]
    buttons = []
    for m in matches:
        voted = m.id in voted_match_ids
        lines.append(
            f"\n⚽️ <b>{html.escape(m.team_a)} — {html.escape(m.team_b)}</b>"
            f"\n   🕒 {m.match_time.strftime('%d.%m.%Y %H:%M')} МСК"
            + (" ✅" if voted else "")
        )
        btn_text = f"{m.team_a} — {m.team_b}" + (" ✅" if voted else "")
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"predict_pick:{m.id}")])

    buttons.append([InlineKeyboardButton(text="« Назад", callback_data="back_to_menu")])

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("predict_pick:"))
async def cb_pick_match(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        _, match_id_str = callback.data.split(":", 1)
        match_id = int(match_id_str)
    except (ValueError, AttributeError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    user_result = await session.execute(select(User).where(User.tg_id == callback.from_user.id))
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

    existing_result = await session.execute(
        select(Prediction).where(
            Prediction.user_id == user.id,
            Prediction.match_id == match_id,
        )
    )
    existing_pred = existing_result.scalar_one_or_none()

    text = (
        f"<b>{html.escape(match.team_a)} — {html.escape(match.team_b)}</b>\n"
        f"🕒 {match.match_time.strftime('%d.%m.%Y %H:%M')} МСК\n\n"
    )

    if existing_pred:
        text += (
            f"Ты уже сделал прогноз: <b>{html.escape(existing_pred.answer)}</b>\n"
            f"Изменить нельзя."
        )
        await callback.message.edit_text(
            text, parse_mode="HTML", reply_markup=_back_to_matches_kb()
        )
        await callback.answer()
        return

    text += "Выбери свой вариант:"
    buttons = [
        [InlineKeyboardButton(text=opt, callback_data=f"predict:{match.id}:{idx}")]
        for idx, opt in enumerate(match.options)
    ]
    buttons.append([InlineKeyboardButton(text="« К списку матчей", callback_data="predict_menu")])

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


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
        reply_markup=_back_to_matches_kb(),
    )
    await callback.answer()
