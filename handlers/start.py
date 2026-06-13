import html
import secrets

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import CHANNEL_ID, CHANNEL_URL
from database.models import User


async def _check_subscription(bot, tg_id: int) -> bool | None:
    """True — подписан, False — точно не подписан, None — проверить нельзя."""
    if CHANNEL_ID is None:
        return None
    try:
        member = await bot.get_chat_member(CHANNEL_ID, tg_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return None


def get_join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚽️ Участвую!", callback_data="join")]
    ])


def get_accept_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принимаю", callback_data="accept_rules")]
    ])


def get_check_subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="accept_rules")],
    ])


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Сделать прогноз", callback_data="predict_menu")],
        [InlineKeyboardButton(text="🏆 Мой рейтинг", callback_data="rating")],
        [InlineKeyboardButton(text="🔗 Реферальная ссылка", callback_data="referral")],
        [InlineKeyboardButton(text="📜 Правила", callback_data="rules")],
    ])

router = Router()

WELCOME_TEXT = (
    "<b>Прогнозист ЧМ 2026</b>\n\n"
   "• Каждый день ты получаешь 2 задания — прогнозы на матчи\n"
    "• За правильный прогноз — <b>+1 балл</b>\n"
    "• За приглашённого друга — <b>+1 балл</b>\n"
    "• По итогам турнира лучшие участники получат <b>приз</b>\n\n"
    "Нажми кнопку, чтобы начать!"
)

RULES_TEXT = (
    "🏆 <b>Правила викторины ЧМ 2026</b>\n\n"
    "1️⃣ Принять участие может любой, соблюдающий правила.\n\n"
    "2️⃣ Необходимо быть подписчиком ТГ канала\n"
    "👉 <a href=\"https://t.me/+NT6WIW-KEcwyNTU6\">Подписаться</a>\n\n"
    "3️⃣ Необходим счёт в одной из БК:\n"
    "- <a href=\"https://clck.ru/3MTUvS\">БК Мелбет</a>\n"
    "- <a href=\"https://clck.ru/3MdHXU\">БК Pari</a>\n"
    "- <a href=\"https://clck.ru/33pxSW\">БК Зенит</a>\n"
    "- <a href=\"https://clck.ru/3U4GjU\">Не из РФ</a>\n\n"
    "4️⃣ Вы можете получить дополнительно 1 балл к рейтингу за приглашение нового игрока, при условии выполнения "
    "им всех правил. Для приглашение игроков Используйте свою реферальную ссылку!\n\n"
    "5️⃣ Дополнительные баллы аннулируются при выявлении ботов и мультиаккаунтов.\n\n"
    "6️⃣ Итоги подводятся в течение 3 рабочих дней после окончания ЧМ.\n\n"
    "7️⃣ Невыполнение правил — аннулирование рейтинга.\n\n"
    "8️⃣ Призовые места по рейтингу:\n"
    "🥇 1 место — 25 000 ₽\n"
    "🥈 2 место — 10 000 ₽\n"
    "🥉 3 место —   5 000 ₽\n"
    "4–10 место —   2 000 ₽"
)


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext) -> None:
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

    ref_token = None
    if args and args.startswith("ref_"):
        ref_token = args[4:]
    await state.update_data(ref_token=ref_token)

    await message.answer(WELCOME_TEXT, reply_markup=get_join_keyboard(), parse_mode="HTML")


@router.callback_query(F.data == "join")
async def cb_join(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        RULES_TEXT + "\n\nНажимая «Принимаю», ты соглашаешься с правилами.",
        reply_markup=get_accept_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data == "accept_rules")
async def cb_accept_rules(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    tg_id = callback.from_user.id

    result = await session.execute(select(User).where(User.tg_id == tg_id))
    if result.scalar_one_or_none():
        await callback.message.edit_text(
            "Ты уже участвуешь!\n\nИспользуй меню ниже:",
            reply_markup=get_main_menu_keyboard(),
        )
        await callback.answer()
        return

    data = await state.get_data()
    ref_token = data.get("ref_token")

    referrer: User | None = None
    if ref_token:
        ref_result = await session.execute(select(User).where(User.ref_code == ref_token))
        candidate = ref_result.scalar_one_or_none()
        if candidate and candidate.tg_id != tg_id:
            referrer = candidate

    # Пришёл по реферальной ссылке — не принимаем до подписки на канал.
    if referrer is not None:
        sub = await _check_subscription(callback.bot, tg_id)
        if sub is False:
            await callback.message.edit_text(
                "Ты перешёл по приглашению. Чтобы участвовать, "
                "сначала подпишись на канал, затем нажми «Проверить подписку».",
                reply_markup=get_check_subscription_keyboard(),
            )
            await callback.answer("Сначала подпишись на канал", show_alert=True)
            return

    await state.clear()

    new_user = User(
        tg_id=tg_id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
        ref_code=secrets.token_hex(6),
        referred_by=referrer.id if referrer else None,
    )
    session.add(new_user)
    if referrer:
        referrer.points += 1
    await session.commit()

    await callback.message.edit_text(
        "Отлично! Ты в игре. Сделай первый прогноз!\n\n"
        "Используй меню ниже:",
        reply_markup=get_main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "rules")
async def cb_rules(callback: CallbackQuery) -> None:
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Назад", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(
        RULES_TEXT,
        reply_markup=back_kb,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Главное меню:",
        reply_markup=get_main_menu_keyboard(),
    )
    await callback.answer()
