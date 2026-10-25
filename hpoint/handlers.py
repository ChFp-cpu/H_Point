"""Telegram UI и пользовательские сценарии H-Point."""
import logging
import secrets
from urllib.parse import urlencode, urlparse
from html import escape
from aiogram import Bot, F, Router
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from .config import *
from .database import *
from .services import *
from .states import Registration, HelpRequest, Review, Billing
from .keyboards import *
from .billing import create_pending_invoice
from . import games as game_service
from .chat_notifications import chat_notification
from .features import GAMES_ENABLED, GAMES_PAUSED_MESSAGE
from . import help_achievements

router = Router()


# The bot deliberately stays focused on the help flow.  This guide makes every
# available control discoverable without turning the reply keyboard into a
# second, crowded version of the website.
BOT_GUIDE = (
    "ℹ️ <b>Как пользоваться H-Point</b>\n\n"
    "<b>Основное меню</b>\n"
    "🆘 <b>Мне нужна помощь</b> — ответьте на 5 коротких вопросов, чтобы создать заявку.\n"
    "🤝 <b>Хочу помочь</b> — встать в общую очередь помощников сайта и бота.\n"
    "⚡ <b>Подобрать кандидатов</b> / 👥 <b>Мои кандидаты</b> — выбрать человека для своей открытой заявки; он подтвердит участие сам.\n"
    "📨 На сайте «Хочу помочь» в карточке заявки сразу назначает помощника и открывает чат. Уведомление с кнопкой чата придёт обоим в Telegram.\n"
    "👤 <b>Мой профиль</b> — баланс HP, рейтинг, статистика и статус проверки.\n"
    "📜 <b>История</b> — завершённые и текущие заявки.\n"
    "⚙️ <b>Настройки помощи</b> — указать категории, в которых вы готовы помогать.\n" +
    ("🎮 <b>Игры H-Point</b> — игры на сайте.\n" if GAMES_ENABLED else "🏅 <b>Достижения за помощь</b> — в профиле: условия, награды HP и ваш прогресс.\n") +
    "💳 <b>H-Point+</b> — платные возможности и безопасный переход к оплате.\n"
    "🌐 <b>Перейти на сайт</b> — одноразовый вход в тот же профиль без пароля.\n\n"
    "<b>Как проходит помощь</b>\n"
    "1. Создайте заявку или встаньте в очередь.\n"
    "2. Автор выбирает кандидата; помощник подтверждает согласие.\n"
    "3. Сообщения с сайта приходят сюда целиком. Ответьте командой /chat #НОМЕР ТЕКСТ из уведомления, завершите помощь и поставьте оценки.\n\n"
    "<b>Синхронизация и безопасность</b>\n"
    "Бот и сайт используют общие профиль, заявки, историю, HP и достижения за реальную помощь. "
    "Чтобы подключить существующий сайт: сайт → «Профиль» → «Получить код Telegram», затем в боте <b>/link КОД</b>. "
    "Код вводите только в этом боте. Для отмены незавершённого действия используйте /cancel. "
    "Уточнить подбор можно командой <b>/ask НУЖНЫЙ ОПЫТ</b>; вернуть меню — /menu.\n\n"
    "Сайт остаётся основным местом для карты, активностей, Лиги H-Point, профиля, подтверждения email и платежей — бот открывает его одноразовой ссылкой."
)

# The first reply for a returning participant remains short enough for a
# messenger, but names every visible main-menu group.  The separate guide
# keeps the explanations discoverable without adding secondary controls to the
# reply keyboard.
BOT_START_OVERVIEW = (
    "<b>Что открывает меню</b>\n"
    "🆘 Нужна помощь — новая заявка; 🤝 хочу помочь — очередь помощников.\n"
    "⚡ Подобрать кандидатов и 👥 Мои кандидаты — выбор и статус помощника.\n"
    "👤 профиль, 📜 история и ⚙️ настройки — ваш аккаунт и готовность помогать.\n"
    "🏅 Достижения за помощь — в профиле; 💳 H-Point+ и 🌐 сайт — доступы и полный веб-интерфейс.\n"
    "ℹ️ «Как пользоваться» показывает подробный порядок действий и команды чата."
)


def onboarding_text() -> str:
    return (
        "👋 <b>H-Point — помощь рядом.</b>\n\n"
        "Сначала создадим ваш профиль, а затем откроется понятное главное меню.\n\n"
        + BOT_GUIDE
        + "\n\n<b>Как вас зовут?</b>"
    )


def user_link(user) -> str:
    name = escape(user["name"])
    if user["username"]:
        return f'{name} (@{escape(user["username"])})'
    return f'<a href="tg://user?id={user["user_id"]}">{name}</a>'


def stars(value) -> str:
    if value is None:
        return "—"
    return "⭐" * int(round(value)) + f" ({value:.1f}/5)"


def request_text(req) -> str:
    category = CATEGORIES.get(req["category"], CATEGORIES["other"])
    return (
        f"📋 <b>Заявка №{req['id']}</b>\n"
        f"<b>Категория:</b> {escape(category)}\n"
        f"<b>Какая помощь нужна:</b> {escape(req['what'])}\n"
        f"<b>Где:</b> {escape(req['place'])}\n"
        f"<b>Когда:</b> {escape(req['time_needed'])}\n"
        f"<b>Срочность:</b> {escape(req['urgency'])}\n"
        f"<b>Детали:</b> {escape(req['details'])}"
        + (f"\n💳 {escape(request_reward_note(req))}" if int(req["reward_rub"] or 0) else "")
    )


async def notify_match(bot: Bot, request_id: int) -> None:
    req = get_request(request_id)
    if req is None or req["helper_id"] is None:
        logging.error("Нельзя отправить уведомление: заявка %s не найдена или без помощника", request_id)
        return
    get_or_create_chat_for_request(request_id)
    requester = get_user(req["requester_id"])
    helper = get_user(req["helper_id"])
    if requester is None or helper is None:
        logging.error("Не найдены участники заявки %s", request_id)
        return

    if helper["tg_user_id"]:
        try:
            await bot.send_message(
                helper["tg_user_id"],
                "🤝 <b>Вы нашли, кому помочь!</b>\n\n"
                f"{request_text(req)}\n\n"
                f"<b>Кому помогаете:</b> {user_link(requester)}\n\n"
                "Свяжитесь с человеком на сайте или отправьте /chat ТЕКСТ. Когда помощь будет оказана — нажмите «Завершить помощь».",
                reply_markup=finish_kb(request_id),
            )
        except Exception:
            logging.exception("Не удалось уведомить помощника %s по заявке %s", helper["user_id"], request_id)

    if requester["tg_user_id"]:
        try:
            await bot.send_message(
                requester["tg_user_id"],
                "🎉 <b>Для вашей заявки нашёлся помощник!</b>\n\n"
                f"{request_text(req)}\n\n"
                f"<b>Ваш помощник:</b> {user_link(helper)}\n\n"
                "Помощник свяжется с вами. Можно ответить на сайте или командой /chat ТЕКСТ. После выполнения он нажмёт «Завершить помощь», "
                "а вас попросят оценить взаимодействие.",
                reply_markup=request_chat_kb(request_id),
            )
        except Exception:
            logging.exception("Не удалось уведомить автора %s по заявке %s", requester["user_id"], request_id)


async def safe_notify_match(bot: Bot, request_id: int) -> None:
    try:
        await notify_match(bot, request_id)
    except Exception:
        logging.exception("Не удалось отправить уведомление о паре для заявки %s", request_id)


async def notify_helper_offer(bot: Bot, request_id: int, helper_id: int) -> None:
    """Ask a selected volunteer for consent before creating a chat or assignment."""
    request = get_request(request_id)
    helper = get_user(helper_id)
    requester = get_user(request["requester_id"]) if request else None
    offer = get_current_helper_offer(request_id)
    if not request or not helper or not requester or not helper["tg_user_id"] or not offer or offer["candidate_id"] != helper_id:
        return
    try:
        await bot.send_message(
            helper["tg_user_id"],
            "🤝 <b>Вас выбрали как помощника</b>\n\n"
            f"{request_text(request)}\n\n"
            f"<b>Кому нужна помощь:</b> {user_link(requester)}\n\n"
            "Подтвердите, что готовы помочь. До вашего согласия заявка никому не назначена.",
            reply_markup=helper_offer_kb(request_id, offer["offer_token"] or ""),
        )
    except Exception:
        logging.exception("Не удалось отправить предложение помощнику %s по заявке %s", helper_id, request_id)


async def show_main_menu(message: Message, text: str = "Главное меню. Выберите действие:") -> None:
    await message.answer(text, reply_markup=main_menu_kb())


async def check_not_busy(message: Message) -> bool:
    user_id = message.from_user.id
    unrated_request = get_unrated_request(user_id)
    if unrated_request:
        await message.answer(
            f"Сначала оцените помощь по заявке №{unrated_request['id']} (1–5):",
            reply_markup=rating_kb(unrated_request["id"], "rate"),
        )
        return False
    unrated_help = get_unrated_help(user_id)
    if unrated_help:
        await message.answer(
            f"Пожалуйста, оцените взаимодействие по заявке №{unrated_help['id']} (1–5):",
            reply_markup=rating_kb(unrated_help["id"], "ratehelp"),
        )
        return False
    helping = get_active_help(user_id)
    if helping:
        await message.answer(
            f"Вы сейчас помогаете по заявке №{helping['id']}. Завершите её.",
            reply_markup=finish_kb(helping["id"]),
        )
        return False
    return True


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    payload = (message.text or "").partition(" ")[2].strip()
    if payload.startswith("login_"):
        ticket = payload.removeprefix("login_")
        if complete_telegram_auth_ticket(ticket, message.from_user.id, message.from_user.full_name, message.from_user.username):
            await message.answer(
                "✅ <b>Telegram подтверждён.</b> Вернитесь в браузер: сайт автоматически откроет ваш общий профиль.",
                reply_markup=main_menu_kb(),
            )
        else:
            await message.answer("Эта ссылка уже использована или истекла. Вернитесь на сайт и начните вход заново.")
        return
    user = get_user(message.from_user.id)
    if user is None:
        await state.set_state(Registration.name)
        await message.answer(onboarding_text())
        return
    await show_main_menu(
        message,
        f"С возвращением, {escape(user['name'])}!\n\n" + BOT_START_OVERVIEW,
    )
    if payload == "profile":
        await profile(message, state)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(BOT_GUIDE, reply_markup=main_menu_kb())


@router.message(Command("menu"))
@router.message(StateFilter(None), F.text == BTN_NAVIGATOR)
async def cmd_menu_guide(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    await state.clear()
    await message.answer(BOT_GUIDE, reply_markup=main_menu_kb())


@router.message(Command("ask"))
async def cmd_ask(message: Message, state: FSMContext) -> None:
    """Explainable local assistant: it ranks candidates without exporting user data."""
    question = (message.text or "").partition(" ")[2].strip()
    if message.chat.type != "private":
        await message.answer(
            "Я работаю в группе по командам. Для подбора людей и просмотра заявок откройте личный чат со мной — там данные доступны только участнику заявки."
        )
        return
    if not await ensure_registered(message, state):
        return
    request = get_active_own_request(message.from_user.id)
    if not request or request["status"] != STATUS_OPEN:
        await message.answer("Сначала создайте открытую заявку через «🆘 Мне нужна помощь». Затем напишите, например: /ask нужен человек с опытом техники.")
        return
    matches = smart_match(request["id"], limit=3, query=question)
    if not matches:
        await message.answer("Пока подходящих свободных помощников нет. Попробуйте позже или расширьте описание заявки.")
        return
    text = "⚡ <b>Подбор кандидатов</b>\n\n"
    for index, candidate in enumerate(matches, start=1):
        reasons = ", ".join(candidate.get("reasons") or ["по параметрам заявки"])
        distance = f" · {candidate['distance_km']} км" if candidate.get("distance_km") is not None else ""
        text += f"{index}. <b>{escape(candidate['name'])}</b> — {escape(reasons)}{distance}\n"
    text += "\nОткройте «⚡ Подобрать кандидатов», чтобы назначить помощника."
    await message.answer(text, reply_markup=main_menu_kb())


@router.message(Command("chat"))
async def cmd_chat(message: Message, state: FSMContext, bot: Bot) -> None:
    """Relay a private Telegram reply into the shared website chat."""
    if message.chat.type != "private":
        await message.answer("Для чата по заявке откройте личный диалог с H-Point.")
        return
    if not await ensure_registered(message, state):
        return
    text = (message.text or "").partition(" ")[2].strip()
    first, _, rest = text.partition(" ")
    target_id = int(first[1:]) if first.startswith("#") and first[1:].isascii() and first[1:].isdigit() and len(first) <= 12 else None
    if target_id is not None:
        text = rest.strip()
    text = text[:1000]
    if not text:
        await message.answer("Отправьте сообщение так: <b>/chat ТЕКСТ</b>")
        return
    user_id = message.from_user.id
    request = get_request(target_id) if target_id is not None else get_active_own_request(user_id)
    if target_id is None and (not request or request["status"] != STATUS_IN_PROGRESS):
        request = get_active_help(user_id)
    if not request or not request["helper_id"] or user_id not in (request["requester_id"], request["helper_id"]) or (target_id is None and request["status"] != STATUS_IN_PROGRESS):
        await message.answer("Чат доступен после назначения помощника по активной заявке.")
        return
    chat_id = get_or_create_chat_for_request(request["id"])
    if not chat_id:
        await message.answer("Не удалось открыть чат по этой заявке.")
        return
    db.execute("INSERT INTO chat_messages(chat_id,user_id,text) VALUES(?,?,?)", (chat_id, user_id, text))
    other_id = request["helper_id"] if request["requester_id"] == user_id else request["requester_id"]
    other = get_user(other_id)
    if other and other["tg_user_id"]:
        try:
            await bot.send_message(
                other["tg_user_id"],
                chat_notification(request["id"], get_user(user_id)["name"], text),
            )
        except Exception:
            logging.exception("Не удалось отправить уведомление о сообщении в Telegram")
    await message.answer(f"💬 Сообщение отправлено в общий чат заявки №{request['id']}.")


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    admin = get_user(message.from_user.id)
    if not admin or admin["role"] != "admin":
        await message.answer("Команда доступна только администратору.")
        return
    summary = admin_summary()
    reqs = ", ".join(f"{status}: {count}" for status, count in summary["requests"].items()) or "нет"
    await message.answer(
        "<b>Администрирование H-Point</b>\n"
        f"Пользователей: {summary['users']} · заблокировано: {summary['blocked_users']}\n"
        f"Заявки: {escape(reqs)}\n\n"
        "Блокировка: /block USER_ID причина\n"
        "Разблокировка: /unblock USER_ID\n"
        "Проверки личности: /verifications, /verify USER_ID, /rejectverify USER_ID причина"
    )


@router.message(Command("block"))
@router.message(Command("unblock"))
async def cmd_user_block(message: Message) -> None:
    admin = get_user(message.from_user.id)
    if not admin or admin["role"] != "admin":
        await message.answer("Команда доступна только администратору.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Укажите ID пользователя.")
        return
    try: target_id = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    blocked = parts[0].split("@", 1)[0] == "/block"
    reason = parts[2] if len(parts) > 2 and blocked else ""
    if target_id == message.from_user.id:
        await message.answer("Нельзя изменить собственный доступ.")
        return
    if not set_user_blocked(message.from_user.id, target_id, blocked, reason):
        await message.answer("Пользователь не найден.")
        return
    await message.answer("Пользователь заблокирован." if blocked else "Доступ пользователя восстановлен.")


@router.message(Command("verifications"))
async def cmd_verifications(message: Message) -> None:
    admin = get_user(message.from_user.id)
    if not admin or admin["role"] != "admin":
        await message.answer("Команда доступна только администратору.")
        return
    rows = pending_identity_verifications()
    if not rows:
        await message.answer("Заявок на проверку личности нет.")
        return
    items = []
    for row in rows:
        username = f" @{escape(row['username'])}" if row["username"] else ""
        items.append(f"• <b>{escape(row['name'])}</b>{username} · ID <code>{row['user_id']}</code>")
    await message.answer(
        "<b>Ожидают ручной проверки</b>\n\n" + "\n".join(items) +
        "\n\nОдобрить: /verify USER_ID\nОтклонить: /rejectverify USER_ID причина"
    )


@router.message(Command("verify"))
@router.message(Command("rejectverify"))
async def cmd_review_identity(message: Message, bot: Bot) -> None:
    admin = get_user(message.from_user.id)
    if not admin or admin["role"] != "admin":
        await message.answer("Команда доступна только администратору.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Укажите ID пользователя.")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("ID должен быть числом.")
        return
    approved = parts[0].split("@", 1)[0] == "/verify"
    note = parts[2] if len(parts) > 2 and not approved else ""
    ok, status = review_identity_verification(message.from_user.id, target_id, approved, note)
    if not ok:
        await message.answer("Заявка не найдена, уже обработана или доступ запрещён.")
        return
    target = get_user(target_id)
    if target and target["tg_user_id"]:
        try:
            text = "✅ Ваша личность подтверждена на 365 дней." if approved else "ℹ️ Заявка на подтверждение личности отклонена."
            if note:
                text += f"\nПричина: {escape(note[:500])}"
            await bot.send_message(target["tg_user_id"], text)
        except Exception:
            logging.exception("Не удалось сообщить пользователю результат проверки")
    await message.answer("Личность подтверждена." if status == "approved" else "Заявка отклонена.")


@router.message(Command("verifyme"))
async def cmd_request_identity_verification(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    ok, status = request_identity_verification(message.from_user.id)
    if not ok:
        await message.answer("Сначала откройте бот в личном чате и завершите привязку Telegram.")
        return
    if status == "approved":
        await message.answer("Ваша личность уже подтверждена.")
        return
    await message.answer(
        "🔐 Заявка на ручную проверку отправлена. Telegram подтверждает владение аккаунтом; "
        "решение по личности принимает администратор. Не присылайте документы в обычный чат."
    )


@router.message(Command("website"))
@router.message(StateFilter(None), F.text == BTN_WEBSITE)
async def website(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    public_url = urlparse(WEB_PUBLIC_URL)
    if public_url.scheme not in {"http", "https"} or public_url.hostname in {None, "0.0.0.0", "::"}:
        await message.answer(
            "Ссылка на сайт ещё не настроена. Укажите публичный адрес в WEB_PUBLIC_URL и перезапустите бота."
        )
        return
    token = secrets.token_urlsafe(32)
    create_web_login_ticket(message.from_user.id, token)
    url = WEB_PUBLIC_URL.rstrip("/") + "/auth/telegram?" + urlencode({"ticket": token})
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть мой профиль на сайте", url=url)
    ]])
    await message.answer(
        "Войти на сайт в ваш профиль H-Point можно по одноразовой ссылке. "
        "Она действует 5 минут.",
        reply_markup=keyboard,
    )


@router.message(Registration.name, F.text)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if name.startswith("/") or name in (BTN_NEED_HELP, BTN_WANT_HELP, BTN_FIND_CANDIDATES, BTN_MY_CANDIDATES, BTN_PROFILE, BTN_HISTORY, BTN_SETTINGS, BTN_WEBSITE, BTN_GAMES, BTN_NAVIGATOR, BTN_CANCEL, "💳 H-Point+"):
        await message.answer("Пожалуйста, напишите своё имя обычным текстом.")
        return
    if not name or len(name) > MAX_NAME_LEN:
        await message.answer(f"Имя должно быть от 1 до {MAX_NAME_LEN} символов.")
        return
    create_user(message.from_user.id, name, message.from_user.username)
    await state.clear()
    await show_main_menu(
        message,
        f"✅ Регистрация завершена, {escape(name)}! Вам начислено <b>{START_BALANCE} HP</b>.\n\n"
        "Нажмите «🌐 Перейти на сайт», чтобы открыть этот же профиль в браузере, "
        "или «ℹ️ Как пользоваться», чтобы увидеть назначение всех кнопок.",
    )


@router.message(Registration.name)
async def reg_name_invalid(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте имя текстовым сообщением.")


async def ensure_registered(message: Message, state: FSMContext) -> bool:
    user = get_user(message.from_user.id)
    if user is None:
        await state.set_state(Registration.name)
        await message.answer("Сначала давайте познакомимся. Как вас зовут?")
        return False
    if user["is_blocked"]:
        await message.answer("Доступ к аккаунту ограничен. Обратитесь в поддержку.")
        return False
    return True


# ---------------------------------------------------------------------------
# H-Point Games.  Telegram is a second client of the exact same game service
# as the website: it sends actions to server-owned sessions and never carries a
# score or a reward in callback data.

_GAME_TILE_LABELS = {
    "food": "●", "book": "▰", "tool": "◆", "cloth": "✦", "kit": "✚", "box": "■",
}


def _game_website_url(user_id=None, game=None, section=None):
    target = "/games"
    if game in game_service.GAME_CATALOG:
        target += "?" + urlencode({"game": game})
    elif section in {"store", "achievements"}:
        target += "#" + section
    if user_id is None:
        return WEB_PUBLIC_URL.rstrip("/") + target
    token = secrets.token_urlsafe(32)
    create_web_login_ticket(user_id, token)
    return WEB_PUBLIC_URL.rstrip("/") + "/auth/telegram?" + urlencode({"ticket": token, "next": target})


def _games_menu_kb(user_id=None) -> InlineKeyboardMarkup:
    if not GAMES_ENABLED:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏅 Достижения за помощь",callback_data="profile:achievements")]])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚶 H-Crossing ↗", url=_game_website_url(user_id, "crossing")), InlineKeyboardButton(text="📍 H-Dispatch ↗", url=_game_website_url(user_id, "dispatch"))],
        [InlineKeyboardButton(text="🧩 H-Match ↗", url=_game_website_url(user_id, "match")), InlineKeyboardButton(text="🛡 H-Safety ↗", url=_game_website_url(user_id, "safety"))],
        [InlineKeyboardButton(text="💚 H-Mission ↗", url=_game_website_url(user_id, "mission"))],
        [InlineKeyboardButton(text="🏆 Прогресс и достижения ↗", url=_game_website_url(user_id, section="achievements")), InlineKeyboardButton(text="🛍 Магазин ↗", url=_game_website_url(user_id, section="store"))],
    ])


def _game_nav_kb(session: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↻ Начать заново", callback_data=f"g:restart:{session['id']}"),
        InlineKeyboardButton(text="🎮 К играм", callback_data="g:menu"),
    ]])


def _game_text(session: dict) -> str:
    code = session["game"]
    state = session["game_state"]
    title = game_service.GAME_CATALOG[code]["title"]
    score = session.get("score", 0)
    if code == "crossing":
        score = state["distance"] * 10 + state["coins"] * 5 + state["deliveries"] * 20
        body = (
            f"📍 Расстояние: <b>{state['distance']}</b> · ресурсы: <b>{state['coins']}</b> · доставки: <b>{state['deliveries']}</b>\n"
            f"🛡 Щит: <b>{'активен' if state['shield'] else 'нет'}</b>\n\n{escape(state['notice'])}"
        )
    elif code == "dispatch":
        body = (
            f"✅ Выполнено: <b>{state['completed']}</b> · назначено: <b>{state['assigned']}/8</b>\n"
            f"📈 Эффективность: <b>{state['efficiency']}%</b>\n\n{escape(state['notice'])}"
        )
    elif code == "match":
        body = (
            f"📚 Книги: <b>{state['target_count']}/{state['target_goal']}</b> · ходы: <b>{state['moves']}</b>\n"
            f"✨ Лучший каскад: <b>×{state['max_combo']}</b>\n\n{escape(state['notice'])}"
        )
    elif code == "safety":
        body = f"🧠 Верных ответов: <b>{state['correct']}</b> · ситуация {min(state['index'] + 1, state['total'])}/{state['total']}"
    else:
        body = f"💚 Репутация помощника: <b>{state['reputation']}</b> · история {min(state['index'] + 1, state['total'])}/{state['total']}"
    return f"🎮 <b>{escape(title)}</b>\n\n🏅 Счёт: <b>{score}</b>\n{body}"


def _game_result_text(session: dict) -> str:
    result = session.get("result") or {}
    rewards = result.get("reward_events") or []
    achievements = result.get("achievements") or []
    reward_text = "\n".join(f"• {escape(item['label'])}: <b>+{item['hp']} HP</b>" for item in rewards)
    achievement_text = "\n".join(f"• 🏆 {escape(item['title'])}" for item in achievements)
    return (
        f"🏁 <b>{escape(result.get('outcome', 'Игра завершена'))}</b>\n\n"
        f"Результат: <b>{result.get('score', session.get('score', 0))}</b>\n"
        f"Получено сейчас: <b>+{result.get('reward_hp', 0)} HP</b>"
        + (f"\n\n<b>Награды</b>\n{reward_text}" if reward_text else "\n\nСегодняшняя награда за этот результат уже учтена или достигнут дневной лимит.")
        + (f"\n\n<b>Новые достижения</b>\n{achievement_text}" if achievement_text else "")
    )


def _crossing_kb(session: dict) -> InlineKeyboardMarkup:
    sid = session["id"]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️", callback_data=f"g:move:{sid}:up")],
        [InlineKeyboardButton(text="⬅️", callback_data=f"g:move:{sid}:left"), InlineKeyboardButton(text="⬇️", callback_data=f"g:move:{sid}:down"), InlineKeyboardButton(text="➡️", callback_data=f"g:move:{sid}:right")],
        _game_nav_kb(session).inline_keyboard[0],
    ])


def _dispatch_kb(session: dict, volunteer_id: str | None = None) -> InlineKeyboardMarkup:
    sid, state = session["id"], session["game_state"]
    if volunteer_id:
        buttons = []
        for job in state["jobs"]:
            if job.get("assigned"):
                continue
            buttons.append([InlineKeyboardButton(text=f"{job['title']} · {job['distance']} км", callback_data=f"g:assign:{sid}:{volunteer_id}:{job['id']}")])
        buttons.append([InlineKeyboardButton(text="← К команде", callback_data=f"g:view:{sid}")])
        buttons.append(_game_nav_kb(session).inline_keyboard[0])
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    rows = []
    for person in state["volunteers"]:
        rows.append([InlineKeyboardButton(text=f"{person['name']} · {'/'.join(person['skills'])} · скорость {person['speed']}", callback_data=f"g:vol:{sid}:{person['id']}")])
    rows.append(_game_nav_kb(session).inline_keyboard[0])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _match_kb(session: dict) -> InlineKeyboardMarkup:
    sid, board = session["id"], session["game_state"]["board"]
    rows = []
    for row_index, row in enumerate(board):
        rows.append([InlineKeyboardButton(text=_GAME_TILE_LABELS.get(tile, "●"), callback_data=f"g:pick:{sid}:{row_index}:{col_index}") for col_index, tile in enumerate(row)])
    hint = session["game_state"].get("hints", 0)
    rows.append([InlineKeyboardButton(text=f"💡 Подсказка ({hint})" if hint else "Подсказок нет", callback_data=f"g:hint:{sid}")])
    rows.append(_game_nav_kb(session).inline_keyboard[0])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _scenario_kb(session: dict) -> InlineKeyboardMarkup:
    sid, code, scenario = session["id"], session["game"], session["game_state"].get("scenario", {})
    action = "answer" if code == "safety" else "choose"
    rows = [[InlineKeyboardButton(text=choice[:60], callback_data=f"g:{action}:{sid}:{index}")] for index, choice in enumerate(scenario.get("choices", []))]
    rows.append(_game_nav_kb(session).inline_keyboard[0])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _game_keyboard(session: dict) -> InlineKeyboardMarkup:
    if session.get("status") != "active":
        code = session["game"]
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="↻ Играть ещё", callback_data=f"g:start:{code}"), InlineKeyboardButton(text="🎮 К играм", callback_data="g:menu")]
        ])
    if session["game"] == "crossing":
        return _crossing_kb(session)
    if session["game"] == "dispatch":
        return _dispatch_kb(session)
    if session["game"] == "match":
        return _match_kb(session)
    return _scenario_kb(session)


def _games_summary(user_id: int) -> str:
    payload = game_service.game_state(user_id)
    profile, economy = payload["profile"], payload["economy"]
    return (
        "🎮 <b>H-Point Games</b>\n\n"
        "Пять мини-игр, общий H-Points-баланс, достижения и безопасные обучающие сценарии.\n\n"
        f"💰 Баланс: <b>{payload['balance']} HP</b>\n"
        f"📈 Сыграно: <b>{profile['games_played']}</b> · завершено: <b>{profile['games_completed']}</b>\n"
        f"✨ Получено сегодня: <b>{economy['earned_today']}/{economy['daily_cap']} HP</b>\n\n"
        "Выберите игру. Лучший подтверждённый сервером результат увеличивает награду только до дневного лимита."
    )


async def _send_or_edit_game(message: Message, session: dict, *, edit: bool = False, feedback: dict | None = None) -> None:
    if session.get("status") == "completed":
        text = _game_result_text(session)
    else:
        text = _game_text(session)
        if feedback:
            if session["game"] == "safety":
                title = "✅ Безопасный выбор" if feedback.get("correct") else "ℹ️ Разберём ситуацию"
                detail = feedback.get("principle") or feedback.get("explanation")
            elif session["game"] == "mission":
                title = "💚 Репутация выросла" if int(feedback.get("reputation", 0)) > 0 else "ℹ️ Другой вариант был бы бережнее"
                detail = feedback.get("explanation")
            else:
                title, detail = "💡 Подсказка", "Ход подсвечен в веб-версии."
            text += f"\n\n<b>{title}</b>\n{escape(detail or '')}"
    markup = _game_keyboard(session)
    if edit:
        try:
            await message.edit_text(text, reply_markup=markup)
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=markup)


@router.message(Command("games"))
@router.message(StateFilter(None), F.text == BTN_GAMES)
async def games_menu(message: Message, state: FSMContext) -> None:
    if message.chat.type != "private":
        await message.answer("Игры и личный прогресс доступны в личном диалоге с H-Point.")
        return
    if not GAMES_ENABLED:
        await message.answer(GAMES_PAUSED_MESSAGE,reply_markup=main_menu_kb())
        return
    if not await ensure_registered(message, state):
        return
    # Entering the games intentionally leaves any unfinished text form, so a
    # later answer cannot be misinterpreted as a request or review field.
    await state.clear()
    await message.answer("🎮 <b>Игры H-Point — на сайте</b>\n\nВыберите игру: откроется её полный интерфейс в вашем профиле. HP, рекорды и достижения общие с ботом.\n\nЛичная ссылка действует 5 минут. Чтобы получить новую, снова нажмите «Игры H-Point».", reply_markup=_games_menu_kb(message.from_user.id))


@router.callback_query(F.data.startswith("g:"))
async def game_callbacks(callback: CallbackQuery, state: FSMContext) -> None:
    """Old game messages now lead to the same full website UI."""
    if callback.message.chat.type != "private":
        await callback.answer("Игры доступны только в личном чате.", show_alert=True)
        return
    if not GAMES_ENABLED:
        await callback.answer(GAMES_PAUSED_MESSAGE,show_alert=True)
        await callback.message.answer("Продолжить помощь и посмотреть достижения можно в профиле.",reply_markup=main_menu_kb())
        return
    user = get_user(callback.from_user.id)
    if not user or user["is_blocked"]:
        await callback.answer("Сначала откройте личный диалог с H-Point.", show_alert=True)
        return
    await state.clear()
    parts = (callback.data or "").split(":")
    game = parts[2] if len(parts) > 2 and parts[1] == "start" and parts[2] in game_service.GAME_CATALOG else None
    if game is None and len(parts) > 2 and parts[1] in {"restart", "view", "move", "vol", "assign", "pick", "swap", "hint", "answer", "choose"}:
        try:
            game = game_service.game_session(callback.from_user.id, parts[2])["game"]
        except ValueError:
            pass
    await callback.answer("Полная версия игры — на сайте")
    await callback.message.edit_text(
        "🎮 Игры теперь открываются на сайте: с игровым полем, анимацией и удобным управлением. Ваш прогресс сохранён.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Играть на сайте ↗", url=_game_website_url(callback.from_user.id, game, "store" if len(parts) > 1 and parts[1] in {"shop", "item", "buy", "use"} else None))
        ]]),
    )


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cancel_action(message: Message, state: FSMContext) -> None:
    await state.clear()
    await show_main_menu(message, "Действие отменено.")


@router.message(Command("profile"))
@router.message(StateFilter(None), F.text == BTN_PROFILE)
async def profile(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    user = get_user(message.from_user.id)
    stats = get_user_stats(user["user_id"])
    achievements = help_achievements.achievement_state(user["user_id"])
    categories = get_helper_categories(user["user_id"])
    identity = get_identity_verification(user["user_id"])
    identity_text = "не запрошено — /verifyme" if not identity else {
        "pending": "заявка на ручной проверке",
        "approved": "подтверждена",
        "rejected": "отклонена — /verifyme для новой заявки",
    }.get(identity["status"], identity["status"])
    text = (
        f"👤 <b>{escape(user['name'])}</b>\n\n"
        f"💰 Баланс: <b>{user['balance']} HP</b>\n"
        f"🏅 Достижения за помощь: <b>{achievements['unlocked_count']}/5</b> · награды <b>{achievements['awarded_hp']} HP</b>\n"
        f"🤝 Помощей оказано: <b>{stats['helped']}</b>\n"
        f"📥 Помощей получено: <b>{stats['received']}</b>\n"
        f"⭐ Оценка как помощника: <b>{stars(stats['helped_avg'])}</b>\n"
        f"⭐ Оценка как получателя: <b>{stars(stats['received_avg'])}</b>\n\n"
        f"🔐 Личность: <b>{identity_text}</b>\n"
        f"🛠 Категории помощи: {', '.join(CATEGORIES[c] for c in categories) if categories else 'не настроены'}"
    )
    await message.answer(text, reply_markup=profile_kb())


async def _show_help_achievements(message: Message, user_id: int) -> None:
    earned=help_achievements.claim_earned(user_id)
    data=help_achievements.achievement_state(user_id)
    lines=["🏅 <b>Достижения за помощь</b>",data["rule"]]
    if earned:lines.append("Начислено за заслуженные достижения: <b>+"+str(sum(item["reward_hp"] for item in earned))+" HP</b>.")
    for item in data["items"]:
        lines.append(("✅ " if item["unlocked"] else "○ ")+"<b>"+escape(item["title"])+" · +"+str(item["reward_hp"])+" HP</b>\n"+escape(item["description"])+"\n"+("Награда уже начислена" if item["unlocked"] else escape(item["progress_text"])))
    lines.append("Баланс: <b>"+str(get_user(user_id)["balance"])+" HP</b>. Награды общие с сайтом.")
    await message.answer("\n\n".join(lines),reply_markup=profile_kb())


@router.message(Command("achievements"))
async def help_achievements_menu(message: Message, state: FSMContext) -> None:
    if await ensure_registered(message,state):await _show_help_achievements(message,message.from_user.id)


@router.callback_query(F.data == "profile:achievements")
async def help_achievements_callback(callback: CallbackQuery) -> None:
    user=get_user(callback.from_user.id)
    if not user or user["is_blocked"]:
        await callback.answer("Сначала откройте свой профиль.",show_alert=True)
        return
    await callback.answer()
    await _show_help_achievements(callback.message,user["user_id"])


async def show_history(message: Message, user_id: int) -> None:
    rows = get_history(user_id, HISTORY_LIMIT)
    if not rows:
        await message.answer("📜 История пока пуста.", reply_markup=main_menu_kb())
        return
    chunks = ["📜 <b>Последние заявки</b>"]
    for req in rows:
        role = "🙋 Вы просили помощь" if req["requester_id"] == user_id else "🤝 Вы помогали"
        status = STATUS_TITLES.get(req["status"], req["status"])
        rating = req["requester_rating"] if req["requester_id"] == user_id else req["helper_rating"]
        line = f"\n<b>№{req['id']}</b> — {escape(req['what'])}\n{role} · {status}"
        if rating is not None:
            line += f" · {'⭐' * rating}"
        chunks.append(line)
    await message.answer("\n".join(chunks), reply_markup=main_menu_kb())


@router.message(Command("history"))
@router.message(StateFilter(None), F.text == BTN_HISTORY)
async def history(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    await show_history(message, message.from_user.id)


@router.callback_query(F.data == "profile:history")
async def cb_profile_history(callback: CallbackQuery) -> None:
    await callback.answer()
    await show_history(callback.message, callback.from_user.id)


@router.message(Command("settings"))
@router.message(StateFilter(None), F.text == BTN_SETTINGS)
async def settings(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    selected = set(get_helper_categories(message.from_user.id))
    await message.answer(
        "⚙️ <b>Настройки помощи</b>\n\nВыберите категории, в которых готовы помогать. "
        "Если ничего не выбрать, вы сможете помочь с любой заявкой.",
        reply_markup=settings_categories_kb(selected),
    )


@router.callback_query(F.data == "profile:settings")
async def cb_profile_settings(callback: CallbackQuery) -> None:
    selected = set(get_helper_categories(callback.from_user.id))
    await callback.answer()
    await callback.message.answer(
        "⚙️ <b>Настройки помощи</b>\n\nВыберите категории, в которых готовы помогать.",
        reply_markup=settings_categories_kb(selected),
    )


@router.callback_query(F.data.startswith("setcat:"))
async def cb_set_category(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    selected = set(get_helper_categories(callback.from_user.id))
    if action == "save":
        await callback.answer("Настройки сохранены")
        await callback.message.edit_text("✅ Настройки помощи сохранены. Чем больше совпадение категорий, тем выше приоритет при подборе.")
        return
    if action not in CATEGORIES:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    if action in selected:
        selected.remove(action)
    else:
        selected.add(action)
    set_helper_categories(callback.from_user.id, list(selected))
    await callback.answer("Изменено")
    await callback.message.edit_reply_markup(reply_markup=settings_categories_kb(selected))


async def _candidate_card(candidate: dict) -> str:
    verified = " ✓" if candidate.get("verified") else ""
    rating = candidate.get("rating") or 0
    reviews = int(candidate.get("reviews") or 0)
    distance = candidate.get("distance_km")
    distance_text = f"{distance} км" if distance is not None else "расстояние неизвестно"
    score = min(100, round(float(candidate.get("score") or 0)))
    username = f" (@{escape(candidate['username'])})" if candidate.get("username") else ""
    return (
        ("📨 <b>Откликнулся на вашу заявку</b>\n" if candidate.get("applied") else "")
        + f"👤 <b>{escape(candidate.get('name') or 'Пользователь')}</b>{verified}{username}\n"
        f"⭐ {rating:.1f}/5 · {reviews} отзывов\n"
        f"📍 {distance_text}\n"
        f"🎯 Совпадение: <b>{score}%</b>"
    )


async def _show_candidates(message: Message, request_id: int, *, edit: bool = False, actor_id: int | None = None) -> None:
    req = get_request(request_id)
    if not req:
        await message.answer("Заявка не найдена.")
        return
    if req["requester_id"] != (actor_id if actor_id is not None else message.from_user.id):
        await message.answer("Эта заявка принадлежит другому пользователю.")
        return
    if req["status"] != STATUS_OPEN:
        text = "Кандидатов можно подбирать только для открытой заявки.\n\n" + request_text(req)
        if edit:
            await message.edit_text(text, reply_markup=main_menu_kb())
        else:
            await message.answer(text, reply_markup=main_menu_kb())
        return

    matches = get_candidates_for_request(request_id, limit=20)
    offer = get_current_helper_offer(request_id)
    waiting = (f"\n\n⏳ Ждём ответ: {escape(offer['name'])}. Можно отменить приглашение и выбрать другого помощника." if offer else "")
    if not matches:
        text = (
            "⚡ <b>Подбор кандидатов</b>\n\n"
            "Пока нет доступных кандидатов. Попробуйте обновить подбор позже.\n\n"
            f"{request_text(req)}{waiting}"
        )
        markup = candidates_navigation_kb(request_id, offer)
        if edit:
            await message.edit_text(text, reply_markup=markup)
        else:
            await message.answer(text, reply_markup=markup)
        return

    header = (
        f"⚡ <b>Кандидаты для заявки №{request_id}</b>\n\n"
        f"{escape(req['what'])}\n\n"
        f"Найдено: <b>{len(matches)}</b>. Это люди, которые сейчас готовы помочь. Выберите одного — он подтвердит согласие сам.{waiting}"
    )
    if edit:
        await message.edit_text(header)
    else:
        await message.answer(header)

    for candidate in matches:
        await message.answer(
            await _candidate_card(candidate),
            reply_markup=candidate_kb(request_id, candidate["user_id"]),
        )
    await message.answer("Подбор можно обновить после изменения профилей или доступности.", reply_markup=candidates_navigation_kb(request_id, offer))


async def _choose_candidate_request(message: Message, state: FSMContext) -> bool:
    if not await ensure_registered(message, state) or not await check_not_busy(message):
        return False
    active = get_active_own_request(message.from_user.id)
    if not active:
        await message.answer(
            "У вас нет активной заявки. Сначала создайте её через «🆘 Мне нужна помощь».\n\n"
            "После создания здесь появится Smart Match с кандидатами."
        )
        return False
    if active["status"] != STATUS_OPEN:
        await message.answer("По вашей заявке уже назначен помощник. Новых кандидатов подбирать не нужно.", reply_markup=main_menu_kb())
        return False
    return True


@router.message(StateFilter(None), F.text == BTN_FIND_CANDIDATES)
async def find_candidates(message: Message, state: FSMContext) -> None:
    if not await _choose_candidate_request(message, state):
        return
    active = get_active_own_request(message.from_user.id)
    await _show_candidates(message, active["id"])


@router.message(StateFilter(None), F.text == BTN_MY_CANDIDATES)
async def my_candidates(message: Message, state: FSMContext) -> None:
    if not await _choose_candidate_request(message, state):
        return
    active = get_active_own_request(message.from_user.id)
    await _show_candidates(message, active["id"])


@router.callback_query(F.data.startswith("candidate:assign:"))
async def cb_candidate_assign(callback: CallbackQuery, bot: Bot) -> None:
    try:
        _, _, request_id_s, candidate_id_s = callback.data.split(":")
        request_id, candidate_id = int(request_id_s), int(candidate_id_s)
    except (ValueError, TypeError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    req = get_request(request_id)
    if not req or req["requester_id"] != callback.from_user.id:
        await callback.answer("Заявка недоступна.", show_alert=True)
        return
    if req["status"] != STATUS_OPEN:
        await callback.answer("Эта заявка уже получила помощника или закрыта.", show_alert=True)
        return
    if candidate_id == callback.from_user.id:
        await callback.answer("Нельзя выбрать себя.", show_alert=True)
        return

    candidate = get_user(candidate_id)
    if not candidate:
        await callback.answer("Кандидат больше недоступен.", show_alert=True)
        return

    if get_current_helper_offer(request_id):
        await callback.answer("Сначала отмените текущее приглашение, затем выберите другого помощника.", show_alert=True)
        await _show_candidates(callback.message, request_id, actor_id=callback.from_user.id)
        return

    application=db.execute("SELECT offer_token FROM request_candidates WHERE request_id=? AND candidate_id=? AND status='applied'",(request_id,candidate_id)).fetchone()
    if application:
        result=accept_open_request(request_id,candidate_id,author_id=callback.from_user.id,application_token=application["offer_token"])
        if result!="created":
            await callback.answer("Для платной помощи сначала нужен резерв в кошельке; либо отклик уже изменился.",show_alert=True)
            return
        await callback.answer("Помощь подтверждена, чат создан")
        await callback.message.answer("Отклик принят. Повторное согласие помощника не требуется.",reply_markup=request_chat_kb(request_id))
        await safe_notify_match(bot,request_id)
        return

    if not offer_helper(request_id, candidate_id):
        await callback.answer("Кандидат уже занят, вышел из очереди или заявка изменилась. Обновляю список.", show_alert=True)
        await _show_candidates(callback.message, request_id, actor_id=callback.from_user.id)
        return

    await callback.answer("Предложение отправлено")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "⏳ <b>Ждём подтверждение помощника</b>\n\n"
        f"{request_text(req)}\n\n"
        f"<b>Вы выбрали:</b> {user_link(candidate)}\n\n"
        "Помощник сам подтвердит или отклонит предложение. Чат появится только после его согласия.",
        reply_markup=candidates_navigation_kb(request_id, get_current_helper_offer(request_id)),
    )
    await notify_helper_offer(bot, request_id, candidate_id)


@router.callback_query(F.data.startswith("ac:"))
async def cb_application_cancel(callback: CallbackQuery, bot: Bot) -> None:
    try:
        _, rid, hid, token = callback.data.split(":")
        request_id, helper_id = int(rid), int(hid)
    except (ValueError, TypeError):
        await callback.answer("Некорректный отклик.", show_alert=True)
        return
    if not cancel_request_application(request_id, helper_id, callback.from_user.id, token):
        await callback.answer("Отклик уже изменился или помощник выбран.", show_alert=True)
        return
    await callback.answer("Отклик отменён")
    await callback.message.edit_text("↩️ Отклик отменён. Сама заявка остаётся открытой.")
    request = get_request(request_id)
    other = get_user(request["requester_id"] if callback.from_user.id == helper_id else helper_id)
    if other and other["tg_user_id"]:
        try:
            await bot.send_message(other["tg_user_id"], f"↩️ Отклик на заявку №{request_id} отозван помощником." if callback.from_user.id == helper_id else f"ℹ️ Автор отклонил ваш отклик на заявку №{request_id}.")
        except Exception:
            logging.exception("Не удалось уведомить об отмене отклика %s", request_id)


@router.callback_query(F.data.startswith("offer:"))
async def cb_helper_offer_response(callback: CallbackQuery, bot: Bot) -> None:
    try:
        parts = callback.data.split(":")
        if len(parts) not in (3, 4):
            raise ValueError("offer")
        _, action, request_id_s = parts[:3]
        token = parts[3] if len(parts) == 4 else ""
        request_id = int(request_id_s)
    except (ValueError, TypeError):
        await callback.answer("Некорректное предложение.", show_alert=True)
        return
    if action == "cancel":
        offer = get_current_helper_offer(request_id)
        if not offer or not withdraw_helper_offer(request_id, callback.from_user.id, offer["candidate_id"], token):
            await callback.answer("Приглашение уже изменилось или помощь подтверждена.", show_alert=True)
            return
        await callback.answer("Приглашение отменено, заявка остаётся открытой")
        if offer["tg_user_id"]:
            try:
                await bot.send_message(offer["tg_user_id"], f"↩️ Автор отменил приглашение по заявке №{request_id}. Подтверждать его больше не нужно; вы можете помогать другим.")
            except Exception:
                logging.exception("Не удалось уведомить об отмене приглашения %s", request_id)
        await _show_candidates(callback.message, request_id, edit=True, actor_id=callback.from_user.id)
        return
    if action not in ("accept", "decline"):
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    accepted = action == "accept"
    request = get_request(request_id)
    offer = get_current_helper_offer(request_id)
    if accepted and offer and offer["candidate_id"] == callback.from_user.id and (offer["offer_token"] or "") == token and int(request["reward_rub"] or 0) > 0 and request["reward_payment_status"] != "paid":
        await callback.answer("Автор ещё не создал резерв в кошельке H-Point. До резерва не начинайте помощь.", show_alert=True)
        return
    if not respond_to_helper_offer(request_id, callback.from_user.id, accepted, token):
        await callback.answer("Предложение уже неактуально.", show_alert=True)
        return
    request = get_request(request_id)
    if accepted:
        await callback.answer("Помощь подтверждена")
        await callback.message.edit_text(
            "✅ <b>Вы подтвердили помощь.</b> Чат создан — можно связаться с человеком на сайте или командой /chat ТЕКСТ.",
            reply_markup=finish_kb(request_id),
        )
        await safe_notify_match(bot, request_id)
        return
    await callback.answer("Предложение отклонено")
    await callback.message.edit_text("↩️ <b>Вы отказались от помощи.</b> Вы остались в очереди и можете получить другое предложение.")
    requester = get_user(request["requester_id"]) if request else None
    if requester and requester["tg_user_id"]:
        try:
            await bot.send_message(
                requester["tg_user_id"],
                f"ℹ️ Помощник отклонил предложение по заявке №{request_id}. Откройте «⚡ Подобрать кандидатов» и выберите другого.",
                reply_markup=main_menu_kb(),
            )
        except Exception:
            logging.exception("Не удалось уведомить автора заявки %s об отказе", request_id)


@router.callback_query(F.data.startswith("candidate:refresh:"))
async def cb_candidate_refresh(callback: CallbackQuery) -> None:
    try:
        request_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return
    req = get_request(request_id)
    if not req or req["requester_id"] != callback.from_user.id:
        await callback.answer("Заявка недоступна.", show_alert=True)
        return
    await callback.answer("Подбор обновлён")
    await _show_candidates(callback.message, request_id, edit=True, actor_id=callback.from_user.id)


@router.callback_query(F.data.startswith("candidate:back:"))
async def cb_candidate_back(callback: CallbackQuery) -> None:
    try:
        request_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return
    req = get_request(request_id)
    if not req or req["requester_id"] != callback.from_user.id:
        await callback.answer("Заявка недоступна.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(request_text(req), reply_markup=cancel_request_kb(request_id) if req["status"] == STATUS_OPEN else main_menu_kb())


@router.message(StateFilter(None), F.text == BTN_NEED_HELP)
async def need_help_start(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state) or not await check_not_busy(message):
        return
    user_id = message.from_user.id
    open_count = db.execute("SELECT COUNT(*) n FROM requests WHERE requester_id=? AND status=?", (user_id, STATUS_OPEN)).fetchone()["n"]
    if int(open_count or 0) >= 10:
        await message.answer("Одновременно можно опубликовать до 10 открытых заявок. Закройте или отмените одну из текущих.")
        return
    if is_in_queue(user_id):
        await message.answer("Вы сейчас в очереди помощников. Выйдите из очереди, чтобы создать заявку.", reply_markup=leave_queue_kb())
        return
    user = get_user(user_id)
    if user["balance"] < REQUEST_COST:
        await message.answer(f"Для заявки нужно минимум {REQUEST_COST} HP. У вас {user['balance']} HP.")
        return
    await state.set_state(HelpRequest.what)
    await message.answer("1/5. <b>Какая помощь нужна?</b>", reply_markup=cancel_kb())


async def read_answer(message: Message) -> str | None:
    if not message.text:
        await message.answer("Пожалуйста, ответьте текстом.")
        return None
    text = message.text.strip()
    if not text:
        await message.answer("Ответ не может быть пустым.")
        return None
    if len(text) > MAX_TEXT_LEN:
        await message.answer(f"Слишком длинный ответ (максимум {MAX_TEXT_LEN} символов).")
        return None
    return text


@router.message(HelpRequest.what)
async def q_what(message: Message, state: FSMContext) -> None:
    text = await read_answer(message)
    if text is None: return
    await state.update_data(what=text)
    await state.set_state(HelpRequest.place)
    await message.answer("2/5. <b>Где нужна помощь?</b>", reply_markup=cancel_kb())


@router.message(HelpRequest.place)
async def q_place(message: Message, state: FSMContext) -> None:
    text = await read_answer(message)
    if text is None: return
    await state.update_data(place=text)
    await state.set_state(HelpRequest.time_needed)
    await message.answer("3/5. <b>Когда нужна помощь?</b>", reply_markup=cancel_kb())


@router.message(HelpRequest.time_needed)
async def q_time(message: Message, state: FSMContext) -> None:
    text = await read_answer(message)
    if text is None: return
    await state.update_data(time_needed=text)
    await state.set_state(HelpRequest.urgency)
    await message.answer("4/5. <b>Насколько срочно?</b> Выберите вариант или напишите свой.", reply_markup=cancel_kb(URGENCY_OPTIONS))


@router.message(HelpRequest.urgency)
async def q_urgency(message: Message, state: FSMContext) -> None:
    text = await read_answer(message)
    if text is None: return
    await state.update_data(urgency=text)
    await state.set_state(HelpRequest.details)
    await message.answer("5/5. <b>Дополнительные детали?</b> Если деталей нет — нажмите «Нет».", reply_markup=cancel_kb([BTN_NO_DETAILS]))


@router.message(HelpRequest.details)
async def q_details(message: Message, state: FSMContext, bot: Bot) -> None:
    text = await read_answer(message)
    if text is None: return
    if text == BTN_NO_DETAILS:
        text = "Нет дополнительных деталей"
    data = await state.update_data(details=text)
    await state.clear()
    user_id = message.from_user.id
    open_count = db.execute("SELECT COUNT(*) n FROM requests WHERE requester_id=? AND status=?", (user_id, STATUS_OPEN)).fetchone()["n"]
    if int(open_count or 0) >= 10:
        await show_main_menu(message, "Одновременно можно опубликовать до 10 открытых заявок. Новая не создана.")
        return
    request_id = create_request(user_id, data)
    req = get_request(request_id)
    await message.answer(
        f"✅ Заявка создана!\n\n{request_text(req)}\n\n"
        "Теперь откройте «⚡ Подобрать кандидатов» и выберите человека из тех, кто готов помочь. Он сам подтвердит согласие.",
        reply_markup=main_menu_kb(),
    )
    await message.answer("Если помощь больше не нужна:", reply_markup=cancel_request_kb(request_id))


@router.message(StateFilter(None), F.text == BTN_WANT_HELP)
async def want_help(message: Message, state: FSMContext, bot: Bot) -> None:
    if not await ensure_registered(message, state) or not await check_not_busy(message):
        return
    user_id = message.from_user.id
    if is_in_queue(user_id):
        await message.answer("Вы уже в очереди помощников.", reply_markup=leave_queue_kb())
        return
    add_to_queue(user_id)
    await message.answer(
        "Вы добавлены в общую очередь помощников сайта и бота. Когда вас выберут, вы сами подтвердите или отклоните предложение.",
        reply_markup=leave_queue_kb(),
    )


@router.callback_query(F.data == "leave_queue")
async def cb_leave_queue(callback: CallbackQuery) -> None:
    if is_in_queue(callback.from_user.id):
        remove_from_queue(callback.from_user.id)
        await callback.answer("Вы вышли из очереди")
        await callback.message.edit_text("Вы вышли из очереди помощников. Ожидающие отклики отозваны; уже принятая помощь не отменяется.")
    else:
        await callback.answer("Вы не в очереди", show_alert=True)


@router.callback_query(F.data.startswith("cancel_req:"))
async def cb_cancel_request(callback: CallbackQuery) -> None:
    try:
        request_id = int(callback.data.split(":")[1])
    except ValueError:
        await callback.answer("Некорректная заявка", show_alert=True)
        return
    if cancel_request(request_id, callback.from_user.id):
        await callback.answer("Заявка отменена")
        await callback.message.edit_text(f"🗑 Заявка №{request_id} отменена.")
    else:
        await callback.answer("Заявку уже нельзя отменить.", show_alert=True)


@router.callback_query(F.data.startswith("finish:"))
async def cb_finish(callback: CallbackQuery, bot: Bot) -> None:
    try:
        request_id = int(callback.data.split(":")[1])
    except ValueError:
        await callback.answer("Некорректная заявка", show_alert=True)
        return
    req = get_request(request_id)
    if req is None:
        await callback.answer("Заявка не найдена.", show_alert=True); return
    if req["helper_id"] != callback.from_user.id:
        await callback.answer("Завершить помощь может только её помощник.", show_alert=True); return
    result = request_help_completion(request_id, callback.from_user.id)
    if result == "unavailable":
        await callback.answer("Не удалось завершить: заявка уже закрыта или недостаточно HP у автора.", show_alert=True); return
    if result in ("created", "pending"):
        await callback.answer("Ожидается подтверждение автора")
        await callback.message.answer("✅ Вы сообщили о выполнении. Деньги остаются в резерве до подтверждения автора; после этого поступят в ваш кошелёк H-Point.")
        requester = get_user(req["requester_id"])
        if result == "created" and requester and requester["tg_user_id"]:
            try:
                await bot.send_message(requester["tg_user_id"], f"✅ Помощник сообщил о выполнении заявки №{request_id}. Проверьте результат и подтвердите выплату {req['reward_rub']} ₽ из резерва.", reply_markup=confirm_paid_completion_kb(request_id))
            except Exception:
                logging.exception("Не удалось запросить подтверждение платной помощи %s", request_id)
        return
    await callback.answer("Помощь завершена!")
    await callback.message.edit_reply_markup(reply_markup=None)
    helper = get_user(callback.from_user.id)
    await callback.message.answer(
        f"✅ Заявка №{request_id} завершена. Вам начислено <b>+{HELPER_REWARD} HP</b>. Баланс: <b>{helper['balance']} HP</b>.\n\n"
        "Поставьте оценку взаимодействию:",
        reply_markup=rating_kb(request_id, "ratehelp"),
    )
    requester = get_user(req["requester_id"])
    try:
        await bot.send_message(
            requester["user_id"],
            f"✅ Помощь по заявке №{request_id} выполнена!\n"
            f"С вашего баланса списано <b>{REQUEST_COST} HP</b>. Баланс: <b>{requester['balance']} HP</b>.\n\n"
            "Пожалуйста, оцените помощь:",
            reply_markup=rating_kb(request_id, "rate"),
        )
    except Exception:
        logging.exception("Не удалось запросить оценку у пользователя %s", requester["user_id"])


@router.callback_query(F.data.startswith("paid_done:"))
async def cb_paid_completion(callback: CallbackQuery, bot: Bot) -> None:
    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError,IndexError):
        await callback.answer("Некорректная заявка.", show_alert=True)
        return
    request = get_request(request_id)
    if not request or not int(request["reward_rub"] or 0) or not complete_request(request_id, request["helper_id"], confirmed_by=callback.from_user.id):
        await callback.answer("Выплата уже выполнена или подтверждение недоступно.", show_alert=True)
        return
    await callback.answer("Выплата из резерва выполнена")
    await callback.message.edit_text(f"✅ Помощь по заявке №{request_id} подтверждена. {request['reward_rub']} ₽ зачислено в кошелёк помощника. H-Points не списывались.",reply_markup=rating_kb(request_id))
    helper = get_user(request["helper_id"])
    if helper and helper["tg_user_id"]:
        try:
            await bot.send_message(helper["tg_user_id"],f"💳 Автор подтвердил помощь по заявке №{request_id}. {request['reward_rub']} ₽ поступило в ваш кошелёк H-Point.",reply_markup=rating_kb(request_id,"ratehelp"))
        except Exception:
            logging.exception("Не удалось сообщить о выплате по заявке %s",request_id)


async def start_review(callback: CallbackQuery, state: FSMContext, request_id: int, side: str, rating: int) -> None:
    await state.update_data(review_request_id=request_id, review_side=side, review_rating=rating)
    await state.set_state(Review.requester_review if side == "requester" else Review.helper_review)
    await callback.message.answer(
        f"Спасибо! Ваша оценка: {'⭐' * rating}.\n\n"
        "Хотите оставить короткий отзыв? Напишите его или нажмите «Пропустить».",
        reply_markup=cancel_kb(["Пропустить"]),
    )


@router.callback_query(F.data.startswith("rate:"))
async def cb_rate(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        _, request_id_str, rating_str = callback.data.split(":")
        request_id, rating = int(request_id_str), int(rating_str)
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True); return
    if not set_rating(request_id, callback.from_user.id, rating):
        await callback.answer("Оценка уже поставлена или недоступна.", show_alert=True); return
    await callback.answer("Спасибо за оценку!")
    await callback.message.edit_reply_markup(reply_markup=None)
    await start_review(callback, state, request_id, "requester", rating)
    req = get_request(request_id)
    if req and req["helper_id"]:
        try:
            helper=get_user(req["helper_id"])
            if helper and helper["tg_user_id"]:
                await callback.bot.send_message(helper["tg_user_id"], f"Ваша помощь по заявке №{request_id} получила оценку {'⭐' * rating} ({rating}/5)."+help_achievements.reward_notice(req["helper_id"],request_id))
        except Exception:
            logging.exception("Не удалось сообщить помощнику оценку")


@router.callback_query(F.data.startswith("ratehelp:"))
async def cb_rate_help(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        _, request_id_str, rating_str = callback.data.split(":")
        request_id, rating = int(request_id_str), int(rating_str)
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True); return
    if not set_helper_rating(request_id, callback.from_user.id, rating):
        await callback.answer("Оценка уже поставлена или недоступна.", show_alert=True); return
    await callback.answer("Спасибо за оценку!")
    await callback.message.edit_reply_markup(reply_markup=None)
    await start_review(callback, state, request_id, "helper", rating)


async def finish_review(message: Message, state: FSMContext, side: str) -> None:
    data = await state.get_data()
    request_id = data.get("review_request_id")
    if not request_id:
        await state.clear(); await show_main_menu(message); return
    review = message.text.strip()
    if review == "Пропустить":
        await state.clear()
        await show_main_menu(message, "Диалог завершён. Главное меню:")
        return
    if not review or len(review) > MAX_TEXT_LEN:
        await message.answer(f"Отзыв должен быть от 1 до {MAX_TEXT_LEN} символов.")
        return
    set_review(request_id, message.from_user.id, review, side)
    await state.clear()
    await show_main_menu(message, "Спасибо за отзыв! Диалог завершён. Главное меню:")


@router.message(Review.requester_review)
async def requester_review(message: Message, state: FSMContext) -> None:
    await finish_review(message, state, "requester")


@router.message(Review.helper_review)
async def helper_review(message: Message, state: FSMContext) -> None:
    await finish_review(message, state, "helper")





async def show_billing(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    user=get_user(message.from_user.id)
    status=[]
    if is_pro(user["user_id"]): status.append("⭐ PRO активен")
    if is_verified(user["user_id"]): status.append("✓ Верификация активна")
    if is_business(user["user_id"]): status.append("💼 Business активен")
    await message.answer(
        "💳 <b>H-Point+</b>\n\n"
        "Продвижение — приоритет одной открытой заявки до её закрытия.\n"
        "PRO — приоритет профиля и заявок в автоматическом подборе на 30 дней, без автопродления.\n"
        "Рейтинг и Лига не продаются; отклики не гарантированы. Проверка личности бесплатна в профиле сайта.\n\n"
        + ("\n".join(status)+"\n\n" if status else "") +
        "Выберите функцию:",
        reply_markup=billing_kb(),
    )

@router.message(Command("billing"))
@router.message(StateFilter(None), F.text == "💳 H-Point+")
async def billing_menu(message: Message, state: FSMContext):
    await show_billing(message,state)

@router.message(Command("terms"))
async def terms(message: Message):
    await message.answer(
        "<b>Условия покупок H-Point</b>\n\n"
        "Оплата цифровых функций производится в рублях через внешний эквайринг. "
        "После подтверждения платежа функция активируется автоматически.\n\n"
        "Поддержка платежей: /paysupport"
    )

@router.message(Command("paysupport"))
async def paysupport(message: Message):
    await message.answer(
        "💬 <b>Поддержка платежей H-Point</b>\n\n"
        "Если платёж прошёл, но функция не активировалась, укажите номер счёта H-Point. "
        "Не отправляйте пароль или данные банковской карты."
    )

@router.message(Command("link"))
async def link_account(message: Message):
    parts=(message.text or "").split(maxsplit=1)
    if len(parts)!=2:
        await message.answer("🔐 Чтобы привязать Telegram к сайту, отправьте:\n\n<b>/link КОД</b>\n\nКод находится в разделе «Профиль» на сайте.")
        return
    ok,msg=link_by_code(parts[1].strip().upper(),message.from_user.id,message.from_user.username)
    if not ok:
        await message.answer("❌ "+msg); return
    user=get_user(message.from_user.id)
    await message.answer(
        "✅ <b>Telegram успешно привязан!</b>\n\n"
        f"Профиль: <b>{escape(user['name'])}</b>\n"
        f"Баланс: <b>{user['balance']} HP</b>\n\n"
        "Теперь сайт и бот работают с одним аккаунтом и общей историей.",
        reply_markup=main_menu_kb(),
    )

@router.message(Command("unlink"))
async def unlink_account(message: Message):
    """Detach the current Telegram identity so it can be linked to another site profile."""
    source=get_user(message.from_user.id)
    if not source or not source["tg_user_id"]:
        await message.answer("Telegram уже используется как отдельный профиль. Для привязки к сайту получите код в разделе «Профиль» и отправьте /link КОД.")
        return
    detached=detach_telegram_to_web_profile(message.from_user.id)
    if detached is None:
        await message.answer("Не удалось отвязать профиль. Попробуйте позже.")
        return
    await message.answer("✅ Telegram отвязан от сайта. Теперь получите код в нужном профиле сайта и отправьте сюда /link КОД.", reply_markup=main_menu_kb())

def web_payment_url(item_type, request_id=None):
    from urllib.parse import urlencode
    q={"item":item_type}
    if request_id:q["request_id"]=request_id
    return WEB_PUBLIC_URL.rstrip("/")+"/?"+urlencode(q)

def payment_button(item_type, request_id=None):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Перейти к оплате в рублях", url=web_payment_url(item_type,request_id))]
    ])

@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery, state: FSMContext):
    item_type=callback.data.split(":",1)[1]
    if item_type not in MONETIZATION_ITEMS:
        await callback.answer("Эта функция снята с продажи. Откройте обновлённое меню H-Point+.",show_alert=True);return
    if item_type in ("boost","more_responses"):
        requests=db.execute("SELECT id,what FROM requests WHERE requester_id=? AND status=? ORDER BY id DESC LIMIT 10",(callback.from_user.id,STATUS_OPEN)).fetchall()
        if not requests:
            await callback.answer("Нет открытых заявок для продвижения.",show_alert=True);return
        await callback.answer()
        await callback.message.answer("Выберите заявку:",reply_markup=choose_request_kb(requests));return
    if item_type=="ad":
        await callback.answer();await state.set_state(Billing.ad_text)
        await callback.message.answer("Напишите текст объявления до 500 символов. После этого получите ссылку на оплату.")
        return
    await callback.answer()
    await callback.message.answer(
        f"<b>{MONETIZATION_ITEMS[item_type]['title']}</b>\n"
        f"{MONETIZATION_ITEMS[item_type]['description']}\n\n"
        f"Цена: <b>{MONETIZATION_ITEMS[item_type]['rub']} ₽</b>",
        reply_markup=payment_button(item_type)
    )

@router.callback_query(F.data.startswith("buyreq:"))
async def cb_buy_request(callback: CallbackQuery):
    try:request_id=int(callback.data.split(":",1)[1])
    except:
        await callback.answer("Некорректная заявка",show_alert=True);return
    await callback.answer()
    await callback.message.answer(
        f"Заявка №{request_id}. Выберите функцию:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🚀 Продвижение — {PRICE_BOOST_RUB} ₽",callback_data=f"payreq:boost:{request_id}")]
        ])
    )

@router.callback_query(F.data.startswith("payreq:"))
async def cb_pay_request(callback: CallbackQuery):
    try:_,item_type,rid=callback.data.split(":");rid=int(rid)
    except:
        await callback.answer("Некорректные данные",show_alert=True);return
    if item_type != "boost":
        await callback.answer("Эта функция больше не продаётся. Откройте H-Point+.",show_alert=True);return
    req=get_request(rid)
    if not req or req["requester_id"]!=callback.from_user.id or req["status"]!=STATUS_OPEN:
        await callback.answer("Заявка уже недоступна.",show_alert=True);return
    await callback.answer()
    await callback.message.answer(
        f"<b>{MONETIZATION_ITEMS[item_type]['title']}</b> · {MONETIZATION_ITEMS[item_type]['rub']} ₽",
        reply_markup=payment_button(item_type,rid)
    )

@router.message(Billing.ad_text,F.text)
async def billing_ad_text(message: Message,state: FSMContext):
    await state.clear()
    await message.answer("Локальные объявления сняты с новых продаж. Уже оплаченные права сохранены. Актуальные возможности:",reply_markup=billing_kb())

@router.message(Command("commercial"))
async def commercial_start(message: Message,state: FSMContext):
    if not await ensure_registered(message,state):return
    await state.set_state(Billing.commercial_title)
    await message.answer("💼 Коммерческий заказ. Напишите название/описание заказа.")

@router.message(Billing.commercial_title,F.text)
async def commercial_title(message: Message,state: FSMContext):
    title=message.text.strip()
    if not title or len(title)>MAX_TEXT_LEN:
        await message.answer(f"Название должно быть от 1 до {MAX_TEXT_LEN} символов.");return
    await state.update_data(commercial_title=title);await state.set_state(Billing.commercial_amount)
    await message.answer("Укажите сумму заказа в рублях.")

@router.message(Billing.commercial_amount,F.text)
async def commercial_amount(message: Message,state: FSMContext):
    try:amount=int(message.text.strip())
    except:
        await message.answer("Введите целое число рублей.");return
    if amount<=0:
        await message.answer("Сумма должна быть положительной.");return
    data=await state.get_data();state_id=create_commercial_order(message.from_user.id,data["commercial_title"],amount)
    await state.clear()
    order=get_commercial_order(state_id)
    await message.answer(f"💼 Заказ №{state_id} создан.\nСумма: <b>{amount} ₽</b>\nКомиссия H-Point: <b>{order['commission_amount']} ₽</b>.")

