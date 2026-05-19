import asyncio
import csv
import html
import io
from collections import defaultdict
from datetime import datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS, moscow_now
from database.models import Match, Prediction, User
from handlers.predictions import get_prediction_keyboard
from scheduler import SEND_DELAY, broadcast, safe_send


def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить матч", callback_data="admin:add_match")],
        [InlineKeyboardButton(text="📋 Список матчей", callback_data="admin:list_matches")],
        [InlineKeyboardButton(text="👥 Пользователи и прогнозы", callback_data="admin:list_users")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="📊 Экспорт рейтинга", callback_data="admin:export_rating")],
    ])

router = Router()


def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS


class AddMatchFSM(StatesGroup):
    team_a = State()
    team_b = State()
    match_time = State()
    option = State()


class BroadcastFSM(StatesGroup):
    text = State()


class EditMatchFSM(StatesGroup):
    match_id = State()
    team_a = State()
    team_b = State()
    match_time = State()


class EditOptionsFSM(StatesGroup):
    match_id = State()
    option = State()


@router.message(CommandStart())
async def cmd_start_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer("Панель администратора:", reply_markup=get_admin_keyboard())


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    await message.answer("Панель администратора:", reply_markup=get_admin_keyboard())



@router.callback_query(F.data == "admin:add_match")
async def cb_add_match(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await callback.message.answer("Введи название команды A:")
    await state.set_state(AddMatchFSM.team_a)
    await callback.answer()


@router.message(AddMatchFSM.team_a)
async def fsm_team_a(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужно текстовое название.")
        return
    await state.update_data(team_a=message.text.strip())
    await message.answer("Введи название команды B:")
    await state.set_state(AddMatchFSM.team_b)


@router.message(AddMatchFSM.team_b)
async def fsm_team_b(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужно текстовое название.")
        return
    await state.update_data(team_b=message.text.strip())
    await message.answer("Дата и время матча (формат: 11.06.2026 21:00):")
    await state.set_state(AddMatchFSM.match_time)


@router.message(AddMatchFSM.match_time)
async def fsm_match_time(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужен текст с датой.")
        return
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
    except ValueError:
        await message.answer("Неверный формат. Попробуй ещё раз (пример: 11.06.2026 21:00):")
        return
    await state.update_data(match_time=dt, options=[])
    await message.answer("Вариант 1 (например: Победа Бразилии):")
    await state.set_state(AddMatchFSM.option)


def _substitute_teams(text: str, team_a: str, team_b: str) -> str:
    return text.replace("№1", team_a).replace("№2", team_b)


def _done_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Готово")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


@router.message(AddMatchFSM.option, F.text == "Готово")
async def fsm_option_done(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    if len(data["options"]) < 2:
        await message.answer("Нужно минимум 2 варианта. Введи ещё:")
        return
    await state.clear()

    match = Match(
        team_a=data["team_a"],
        team_b=data["team_b"],
        title=f"{data['team_a']} — {data['team_b']}",
        match_time=data["match_time"],
    )
    match.options = data["options"]
    session.add(match)
    await session.commit()
    await session.refresh(match)

    opts_text = "\n".join(f"{i+1}. {html.escape(o)}" for i, o in enumerate(match.options))
    await message.answer(
        f"Матч добавлен (ID: {match.id}):\n"
        f"<b>{html.escape(match.team_a)} — {html.escape(match.team_b)}</b>\n"
        f"Время: {match.match_time.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"Варианты:\n{opts_text}",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AddMatchFSM.option)
async def fsm_option(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужен текстовый вариант.")
        return
    data = await state.get_data()
    option = _substitute_teams(message.text.strip(), data["team_a"], data["team_b"])
    options = data["options"] + [option]
    await state.update_data(options=options)
    num = len(options) + 1
    kb = _done_keyboard() if len(options) >= 2 else None
    await message.answer(f"Вариант {num} (или нажми Готово):" if kb else f"Вариант {num}:", reply_markup=kb)


def _match_card(m: Match) -> tuple[str, InlineKeyboardMarkup]:
    now = moscow_now()

    reception_icon = "🔴" if m.is_closed else "🟢"

    if m.is_resolved:
        match_icon = "🔴"
    elif now >= m.match_time:
        match_icon = "🟢"
    else:
        match_icon = "🟡"

    opts_text = "\n".join(f"  {i+1}. {html.escape(o)}" for i, o in enumerate(m.options))
    text = (
        f"<b>[{m.id}] {html.escape(m.team_a)} — {html.escape(m.team_b)}</b>\n----------\n"
        f"{match_icon} {m.match_time.strftime('%d.%m.%Y %H:%M')}\n"
        f"{reception_icon} Приём прогнозов\n----------\n"
        f"Варианты:\n{opts_text}"
    )

    action_rows = []
    if not m.is_closed:
        action_rows.append([InlineKeyboardButton(text="🔒 Закрыть приём", callback_data=f"admin:close_match_id:{m.id}")])
    if not m.is_resolved:
        action_rows.append([InlineKeyboardButton(text="✅ Итоговый результат", callback_data=f"admin:resolve_match_id:{m.id}")])

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Изменить матч", callback_data=f"admin:edit_match:{m.id}"),
            InlineKeyboardButton(text="📝 Изменить варианты", callback_data=f"admin:edit_options:{m.id}"),
        ],
        *action_rows,
        [InlineKeyboardButton(text="🗑 Убрать матч", callback_data=f"admin:delete_match:{m.id}")],
    ])
    return text, kb


@router.callback_query(F.data == "admin:list_matches")
async def cb_list_matches(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    result = await session.execute(
        select(Match).order_by(Match.match_time.desc()).limit(20)
    )
    matches = result.scalars().all()
    if not matches:
        await callback.answer("Матчей нет.", show_alert=True)
        return

    for m in matches:
        text, kb = _match_card(m)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)

    await callback.answer()


@router.callback_query(F.data == "admin:list_users")
async def cb_list_users(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return

    users_result = await session.execute(select(User).order_by(User.points.desc()))
    users = users_result.scalars().all()

    if not users:
        await callback.answer("Пользователей нет.", show_alert=True)
        return

    all_preds_result = await session.execute(
        select(Prediction, Match)
        .join(Match, Prediction.match_id == Match.id)
        .order_by(Prediction.created_at.desc())
    )
    user_preds: dict[int, list] = defaultdict(list)
    for pred, match in all_preds_result.all():
        user_preds[pred.user_id].append((pred, match))

    for u in users:
        rows = user_preds.get(u.id, [])

        name = html.escape(u.full_name or u.username or str(u.tg_id))
        username_str = f" (@{html.escape(u.username)})" if u.username else ""

        if rows:
            pred_lines = "\n".join(
                f"  {html.escape(m.team_a)}—{html.escape(m.team_b)}: {html.escape(p.answer)}"
                + (" ✅" if p.is_correct else " ❌" if p.is_correct is False else "")
                for p, m in rows
            )
            spoiler = f"<tg-spoiler>Прогнозы ({len(rows)}):\n{pred_lines}</tg-spoiler>"
        else:
            spoiler = "<tg-spoiler>Прогнозов нет</tg-spoiler>"

        text = (
            f"<b>{name}</b>{username_str}\n"
            f"Баллы: {u.points} | ID: {u.tg_id}\n"
            f"{spoiler}"
        )
        await callback.message.answer(text, parse_mode="HTML")

    await callback.answer()


def _confirm_keyboard(yes_data: str, cancel_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да", callback_data=yes_data),
        InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_data),
    ]])


@router.callback_query(F.data.startswith("admin:close_match_id:"))
async def cb_close_match_direct(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    match_id = int(callback.data.split(":")[2])
    result = await session.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        await callback.answer("Матч не найден.", show_alert=True)
        return
    if match.is_closed:
        await callback.answer("Приём уже закрыт.", show_alert=True)
        return
    await callback.message.edit_text(
        f"⚠️ Закрыть приём прогнозов на матч\n<b>[{match.id}] {html.escape(match.team_a)} — {html.escape(match.team_b)}</b>?",
        parse_mode="HTML",
        reply_markup=_confirm_keyboard(
            yes_data=f"admin:confirm_close:{match_id}",
            cancel_data=f"admin:cancel_to_card:{match_id}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:confirm_close:"))
async def cb_confirm_close(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    match_id = int(callback.data.split(":")[2])
    result = await session.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        await callback.answer("Матч не найден.", show_alert=True)
        return
    match.is_closed = True
    await session.commit()
    text, kb = _match_card(match)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:delete_match:"))
async def cb_delete_match(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    match_id = int(callback.data.split(":")[2])
    result = await session.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        await callback.answer("Матч не найден.", show_alert=True)
        return
    await callback.message.edit_text(
        f"⚠️ Удалить матч <b>[{match.id}] {html.escape(match.team_a)} — {html.escape(match.team_b)}</b>?\n"
        f"Все прогнозы участников на этот матч будут удалены.",
        parse_mode="HTML",
        reply_markup=_confirm_keyboard(
            yes_data=f"admin:confirm_delete:{match_id}",
            cancel_data=f"admin:cancel_to_card:{match_id}",
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:confirm_delete:"))
async def cb_confirm_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    match_id = int(callback.data.split(":")[2])
    result = await session.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        await callback.answer("Матч не найден.", show_alert=True)
        return
    await session.execute(delete(Prediction).where(Prediction.match_id == match_id))
    await session.delete(match)
    await session.commit()
    await callback.message.edit_text(
        f"🗑 Матч <b>[{match_id}] {html.escape(match.team_a)} — {html.escape(match.team_b)}</b> удалён.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:cancel_to_card:"))
async def cb_cancel_to_card(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    match_id = int(callback.data.split(":")[2])
    result = await session.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        await callback.answer("Матч не найден.", show_alert=True)
        return
    text, kb = _match_card(match)
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:resolve_match_id:"))
async def cb_resolve_match_direct(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    match_id = int(callback.data.split(":")[2])
    result = await session.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        await callback.answer("Матч не найден.", show_alert=True)
        return

    buttons = [
        [InlineKeyboardButton(text=opt, callback_data=f"admin:pick_correct:{match_id}:{idx}")]
        for idx, opt in enumerate(match.options)
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin:cancel_to_card:{match_id}")])
    await callback.message.edit_text(
        f"Матч: <b>{html.escape(match.title)}</b>\n\nВыбери правильный вариант:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:pick_correct:"))
async def cb_pick_correct(callback: CallbackQuery, session: AsyncSession, user_bot: Bot) -> None:
    if not is_admin(callback.from_user.id):
        return
    try:
        _, _, match_id_str, idx_str = callback.data.split(":")
        match_id = int(match_id_str)
        idx = int(idx_str)
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    result = await session.execute(select(Match).where(Match.id == match_id))
    match = result.scalar_one_or_none()
    if not match:
        await callback.answer("Матч не найден.", show_alert=True)
        return

    options = match.options
    if idx < 0 or idx >= len(options):
        await callback.answer("Вариант не найден.", show_alert=True)
        return
    correct = options[idx]

    match.correct_answer = correct
    match.is_closed = True
    match.is_resolved = True

    preds_result = await session.execute(
        select(Prediction).where(Prediction.match_id == match_id)
    )
    predictions = preds_result.scalars().all()

    if predictions:
        users_result = await session.execute(
            select(User).where(User.id.in_([p.user_id for p in predictions]))
        )
        users_by_id = {u.id: u for u in users_result.scalars().all()}
    else:
        users_by_id = {}

    correct_count = 0
    for pred in predictions:
        pred.is_correct = pred.answer == correct
        user = users_by_id.get(pred.user_id)
        if pred.is_correct and user:
            user.points += 1
            correct_count += 1

    await session.commit()
    safe_correct = html.escape(correct)
    safe_title = html.escape(match.title)
    await callback.message.edit_text(
        f"Результат матча [{match_id}] сохранён.\n"
        f"Правильный ответ: <b>{safe_correct}</b>\n"
        f"Угадали: {correct_count} из {len(predictions)}",
        parse_mode="HTML",
    )
    await callback.answer()

    for pred in predictions:
        user = users_by_id.get(pred.user_id)
        if not user:
            continue
        if pred.is_correct:
            text = f"Матч <b>{safe_title}</b> завершён!\nТвой прогноз верный — <b>+1 балл</b>! Текущий счёт: {user.points}"
        else:
            text = f"Матч <b>{safe_title}</b> завершён.\nК сожалению, твой прогноз не совпал. Правильный ответ: <b>{safe_correct}</b>"
        await safe_send(user_bot, user.tg_id, text, parse_mode="HTML")
        await asyncio.sleep(SEND_DELAY)


@router.callback_query(F.data == "admin:broadcast")
async def cb_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    await callback.message.answer("Введи текст рассылки:")
    await state.set_state(BroadcastFSM.text)
    await callback.answer()


@router.message(BroadcastFSM.text)
async def fsm_broadcast(message: Message, state: FSMContext, session: AsyncSession, user_bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужен текст. Пришли текстовое сообщение.")
        return
    await state.clear()
    text = message.text.strip()
    users_result = await session.execute(select(User))
    users = users_result.scalars().all()

    sent, failed = await broadcast(user_bot, [u.tg_id for u in users], text)
    await message.answer(f"Рассылка завершена. Отправлено: {sent}, ошибок: {failed}.")


@router.callback_query(F.data == "admin:export_rating")
async def cb_export_rating(callback: CallbackQuery, session: AsyncSession) -> None:
    if not is_admin(callback.from_user.id):
        return
    result = await session.execute(select(User).order_by(User.points.desc()))
    users = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Место", "Имя", "Username", "TG ID", "Баллы"])
    for i, u in enumerate(users, start=1):
        writer.writerow([i, u.full_name, u.username or "", u.tg_id, u.points])

    file_bytes = buf.getvalue().encode("utf-8-sig")
    await callback.message.answer_document(
        BufferedInputFile(file_bytes, filename="rating.csv"),
        caption="Рейтинг участников",
    )
    await callback.answer()


# ── Редактирование матча ──────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:edit_match:"))
async def cb_edit_match(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    match_id = int(callback.data.split(":")[2])
    await state.update_data(match_id=match_id)
    await callback.message.answer("Новое название команды A (или — чтобы оставить прежнее):")
    await state.set_state(EditMatchFSM.team_a)
    await callback.answer()


@router.message(EditMatchFSM.team_a)
async def fsm_edit_team_a(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужен текст.")
        return
    await state.update_data(team_a=message.text.strip())
    await message.answer("Новое название команды B (или — чтобы оставить прежнее):")
    await state.set_state(EditMatchFSM.team_b)


@router.message(EditMatchFSM.team_b)
async def fsm_edit_team_b(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужен текст.")
        return
    await state.update_data(team_b=message.text.strip())
    await message.answer("Новая дата и время (формат: 11.06.2026 21:00) или — чтобы оставить прежнее:")
    await state.set_state(EditMatchFSM.match_time)


@router.message(EditMatchFSM.match_time)
async def fsm_edit_match_time(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужен текст.")
        return
    data = await state.get_data()
    await state.clear()

    result = await session.execute(select(Match).where(Match.id == data["match_id"]))
    match = result.scalar_one_or_none()
    if not match:
        await message.answer("Матч не найден.")
        return

    raw = message.text.strip()
    if raw != "—":
        try:
            match.match_time = datetime.strptime(raw, "%d.%m.%Y %H:%M")
        except ValueError:
            await message.answer(
                "Неверный формат даты. Изменения не применены. "
                "Запусти редактирование заново."
            )
            return

    if data["team_a"] != "—":
        match.team_a = data["team_a"]
    if data["team_b"] != "—":
        match.team_b = data["team_b"]
    match.title = f"{match.team_a} — {match.team_b}"

    await session.commit()
    await message.answer(
        f"Матч обновлён:\n<b>{html.escape(match.title)}</b>\n{match.match_time.strftime('%d.%m.%Y %H:%M')}",
        parse_mode="HTML",
    )


# ── Редактирование вариантов ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("admin:edit_options:"))
async def cb_edit_options(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        return
    match_id = int(callback.data.split(":")[2])
    await state.update_data(match_id=match_id, options=[])
    await callback.message.answer("Введи новые варианты по одному.\nВариант 1:")
    await state.set_state(EditOptionsFSM.option)
    await callback.answer()


@router.message(EditOptionsFSM.option, F.text == "Готово")
async def fsm_edit_options_done(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    if len(data["options"]) < 2:
        await message.answer("Нужно минимум 2 варианта. Введи ещё:")
        return
    await state.clear()

    result = await session.execute(select(Match).where(Match.id == data["match_id"]))
    match = result.scalar_one_or_none()
    if not match:
        await message.answer("Матч не найден.")
        return

    match.options = data["options"]
    await session.commit()

    opts_text = "\n".join(f"{i+1}. {o}" for i, o in enumerate(match.options))
    await message.answer(
        f"Варианты обновлены:\n{opts_text}",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(EditOptionsFSM.option)
async def fsm_edit_option(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    if not message.text:
        await message.answer("Нужен текстовый вариант.")
        return
    data = await state.get_data()
    option = message.text.strip()
    options = data["options"] + [option]
    await state.update_data(options=options)
    num = len(options) + 1
    kb = _done_keyboard() if len(options) >= 2 else None
    await message.answer(
        f"Вариант {num} (или нажми Готово):" if kb else f"Вариант {num}:",
        reply_markup=kb,
    )


# ─────────────────────────────────────────────────────────────────────────────

async def send_match_to_all(match: Match, session: AsyncSession, bot) -> None:
    users_result = await session.execute(select(User))
    users = users_result.scalars().all()

    text = (
        f"Новый прогноз!\n\n"
        f"Матч: <b>{html.escape(match.team_a)} — {html.escape(match.team_b)}</b>\n"
        f"Время: {match.match_time.strftime('%d.%m.%Y %H:%M')} МСК\n\n"
        f"Выбери свой вариант:"
    )
    kb = get_prediction_keyboard(match)
    await broadcast(bot, [u.tg_id for u in users], text, reply_markup=kb, parse_mode="HTML")
