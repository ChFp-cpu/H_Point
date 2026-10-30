"""Telegram UI и пользовательские сценарии H-Point."""
import logging
import secrets
import time
from functools import wraps
from inspect import signature
from urllib.parse import urlencode, urlparse
from html import escape
from aiogram import Bot, F, Router, BaseMiddleware
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
from .chat_notifications import chat_notification_chunks
from .features import GAMES_ENABLED, GAMES_PAUSED_MESSAGE
from . import help_achievements
from . import bot_work_ui
from .email_access import has_verified_email, link_owner_has_verified_email

router = Router()

REQUEST_FORM_STATES = {item.state for item in HelpRequest.__all_states__}


def bot_pro_active(user_id):
    from . import personal
    return personal.is_pro(user_id, db_connection=db)


def pro_management_keyboard(route="#/help"):
    base = WEB_PUBLIC_URL.rstrip("/")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Продолжить бесплатно на сайте", url=base+"/"+route)],
        [InlineKeyboardButton(text="Условия H-Point PRO", url=base+"/#/profile/billing")],
    ])


async def require_pro_management(event, state=None):
    """Recheck expired subscriptions on messages, stale callbacks and form steps.

    Drafts are deliberately retained on denial. Chat, consent, reviews and paid
    professional workspace actions do not use this gate.
    """
    callback=isinstance(event,CallbackQuery) or (getattr(event,"message",None) is not None and isinstance(getattr(event,"data",None),str))
    message=event.message if callback else event
    if not message or getattr(getattr(message,"chat",None),"type",None)!="private":
        if callback:await event.answer("Управление заявками доступно только в личном чате с H-Point.",show_alert=True)
        elif message:await message.answer("Откройте личный диалог с H-Point или продолжите на сайте.",reply_markup=bot_website_keyboard("#/help"))
        return False
    actor=get_user(resolve_profile_id(event.from_user.id))
    if (has_verified_email(actor) and not actor["is_blocked"]
            and actor["tg_user_id"]==event.from_user.id and bot_pro_active(actor["user_id"])):
        return True
    if callback:
        await event.answer("Управление заявками в боте доступно с PRO. Сайт остаётся бесплатным.", show_alert=True)
    if message:
        await message.answer(
            "Управление заявками через Telegram доступно с H-Point PRO. "
            "Продолжить это действие можно бесплатно на сайте. "
            "Переписка, уведомления и отзывы в боте остаются доступными. "
            "Введённые данные не удалены; отменить действие — /cancel.",
            reply_markup=pro_management_keyboard(),
        )
    return False


def pro_request_action(function):
    """The handler guard also protects direct calls and delegated old callbacks."""
    parameters = signature(function)

    @wraps(function)
    async def guarded(event, *args, **kwargs):
        bound = parameters.bind_partial(event, *args, **kwargs)
        if not await require_pro_management(event, bound.arguments.get("state")):
            return
        return await function(event, *args, **kwargs)
    return guarded


def resolve_profile_id(telegram_user_id):
    row=db.execute("SELECT user_id FROM users WHERE tg_user_id=?",(telegram_user_id,)).fetchone()
    return row["user_id"] if row else telegram_user_id


def email_access_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Войти или зарегистрироваться по email",url=WEB_PUBLIC_URL.rstrip("/")+"/")]])


EMAIL_ACCESS_NOTICE = (
    "Регистрация и вход в H-Point доступны только по email на сайте. "
    "Подтвердите email, затем в профиле получите код привязки Telegram и отправьте сюда /link КОД. "
    "Бот используется для уведомлений и общения по уже созданному email-аккаунту."
)


class EmailOnlyBotMiddleware(BaseMiddleware):
    async def __call__(self,handler,event,data):
        sender=getattr(event,"from_user",None)
        if sender is None:return
        user=get_user(resolve_profile_id(sender.id))
        if has_verified_email(user) and not user["is_blocked"] and user["tg_user_id"]==sender.id:
            message=event.message if isinstance(event,CallbackQuery) else event
            private=message and getattr(getattr(message,"chat",None),"type",None)=="private"
            token=MENU_USER.set(user["user_id"] if private and user["tg_user_id"]==sender.id else None)
            try:return await self._verified(handler,event,data,user)
            finally:MENU_USER.reset(token)
        return await self._unverified(handler,event,data)

    async def _verified(self,handler,event,data,user):
        if await bot_work_ui.handle_event(event,data,user,db):return
        if isinstance(event,CallbackQuery) and (str(event.data or "").startswith(("setcat:","g:")) or event.data in {"profile:settings","profile:history","profile:achievements"}):
            state=data.get("state")
            if state:await state.clear()
            await event.answer("Откройте эту функцию на сайте")
            if event.message:await event.message.answer("Все настройки и возможности доступны на сайте.",reply_markup=bot_website_keyboard())
            return
        if await simplified_bot_message(event,data):return
        return await handler(event,data)

    async def _unverified(self,handler,event,data):
        text=str(getattr(event,"text","") or "")
        command=text.split(maxsplit=1)[0].split("@",1)[0] if text else ""
        if isinstance(event,Message) and (command in {"/start","/help","/website","/cancel","/link","/unlink"} or text==BTN_WEBSITE):
            return await handler(event,data)
        if isinstance(event,CallbackQuery):
            if event.data in {"telegram-link:confirm","telegram-link:cancel"}:
                return await handler(event,data)
            await event.answer("Войдите по email на сайте и привяжите этот бот в профиле.",show_alert=True)
        else:
            await event.answer(EMAIL_ACCESS_NOTICE,reply_markup=email_access_keyboard())


router.message.outer_middleware(EmailOnlyBotMiddleware())
router.callback_query.outer_middleware(EmailOnlyBotMiddleware())


# The website owns forms, settings and purchases. The bot delivers notifications
# and can relay a reply to an already selected conversation.
BOT_GUIDE = (
    "ℹ️ <b>H-Point в Telegram</b>\n\n"
    "Бесплатно: полные сообщения, важные уведомления и переписка по помощи. "
    "Открыть переписку — «Мои чаты»; ответить по текущей помощи — <b>/chat ТЕКСТ</b>.\n\n"
    "С PRO в меню появляются «Мне нужна помощь», «Хочу помочь» и «Мои заявки»: "
    "создание, подбор помощи, отклики, выбор помощника, отмена и завершение заявки. "
    "На сайте эти действия доступны бесплатно. Шаблоны и расписание находятся на сайте.\n\n"
    "Регистрация и вход — только по email на сайте. "
    "Для привязки получите код в профиле и отправьте <b>/link КОД</b>. "
    "Подтвердите привязку или нажмите «Отмена»; отвязать бот — <b>/unlink</b>. "
    "Незавершённое действие можно отменить командой <b>/cancel</b>."
)
BOT_START_OVERVIEW = (
    "Здесь приходят полные сообщения и важные уведомления по помощи. "
    "Переписка — «Мои чаты» или /chat ТЕКСТ. "
    "Управление заявками — на сайте или в меню PRO."
)
BASIC_BOT_COMMANDS = {"/start", "/help", "/menu", "/website", "/chats", "/chat", "/problem", "/cancel", "/link", "/unlink", "/ask", "/billing", "/terms", "/paysupport"}
PRO_BOT_ACTIONS = {BTN_NEED_HELP, BTN_WANT_HELP, BTN_FIND_CANDIDATES, BTN_MY_CANDIDATES, BOT_REQUESTS_BUTTON}
LEGACY_BOT_DESTINATIONS = {
    "/profile":"#/profile", "/history":"#/help", "/settings":"#/help",
    "/commercial":"#/profile", "/verifyme":"#/profile",
    "/games":"", "/achievements":"#/league",
    BTN_PROFILE:"#/profile", BTN_HISTORY:"#/help",
    BTN_SETTINGS:"#/help", BTN_GAMES:"", "💳 H-Point+":"#/profile/billing",
}


def bot_website_keyboard(route="", title="Открыть H-Point"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=title,url=WEB_PUBLIC_URL.rstrip("/")+"/"+route)]])


async def simplified_bot_message(event, data):
    """Keep a compact bot while letting authorised request forms reach handlers."""
    if not isinstance(event,Message):
        return False
    text=str(event.text or "")
    command=text.split(maxsplit=1)[0].split("@",1)[0] if text else ""
    state=data.get("state")
    if text=="💬 Мои чаты" or command=="/chats":
        if state:await state.clear()
        await event.answer("Ваши чаты по заявкам.",reply_markup=bot_website_keyboard("#/help/chats","Открыть чаты"))
        return True
    current_state=await state.get_state() if state else None
    if text in PRO_BOT_ACTIONS:
        if not await require_pro_management(event,state):return True
        if text==BTN_WANT_HELP:
            await want_help(event,state,data.get("bot"));return True
        action={BTN_NEED_HELP:need_help_start,BTN_FIND_CANDIDATES:find_candidates,BTN_MY_CANDIDATES:my_candidates,BOT_REQUESTS_BUTTON:request_management_menu}[text]
        await action(event,state)
        return True
    if command=="/ask":return not await require_pro_management(event,state)
    if current_state in REQUEST_FORM_STATES and command not in BASIC_BOT_COMMANDS and text not in {BTN_CANCEL,BTN_WEBSITE,BTN_NAVIGATOR}:
        return not await require_pro_management(event,state)
    destination=LEGACY_BOT_DESTINATIONS.get(command,LEGACY_BOT_DESTINATIONS.get(text))
    if destination is not None:
        if state:await state.clear()
        await event.answer("Это действие доступно на сайте.",reply_markup=bot_website_keyboard(destination))
        return True
    if command in BASIC_BOT_COMMANDS or text in {BTN_WEBSITE,BTN_NAVIGATOR,BTN_CANCEL}:
        return False
    if current_state in {Review.requester_review.state,Review.helper_review.state}:
        return False
    if state:await state.clear()
    await event.answer("Для ответа по текущей помощи отправьте /chat ТЕКСТ или откройте чат на сайте.",reply_markup=bot_website_keyboard("#/help/chats","Открыть чаты"))
    return True


def onboarding_text() -> str:
    return "👋 <b>H-Point — помощь рядом.</b>\n\n" + EMAIL_ACCESS_NOTICE


def request_title(request_id):
    request=get_request(request_id)
    return escape(str(request["what"])) if request else "Помощь"


def request_author_name(request):
    user=get_user(request["requester_id"])
    return escape(str(user["name"])) if user else "Участник"


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
        f"📋 <b>{escape(req['what'])}</b>\n"
        f"<b>Кому нужна помощь:</b> {request_author_name(req)}\n"
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
                "Свяжитесь с человеком на сайте или отправьте /chat ТЕКСТ. После оказания помощи заявку завершит её автор.",
                reply_markup=request_chat_kb(request_id),
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
                "Помощник свяжется с вами. Можно ответить на сайте или командой /chat ТЕКСТ. Когда помощь будет оказана, нажмите «Завершить помощь». После этого можно оставить оценку.",
                reply_markup=finish_kb(request_id),
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
    user_id = resolve_profile_id(message.from_user.id)
    unrated_request = get_unrated_request(user_id)
    if unrated_request:
        await message.answer(
            f"Сначала оцените помощь по задаче «{request_title(unrated_request['id'])}» (1–5):",
            reply_markup=rating_kb(unrated_request["id"], "rate"),
        )
        return False
    unrated_help = get_unrated_help(user_id)
    if unrated_help:
        await message.answer(
            f"Пожалуйста, оцените взаимодействие по задаче «{request_title(unrated_help['id'])}» (1–5):",
            reply_markup=rating_kb(unrated_help["id"], "ratehelp"),
        )
        return False
    helping = get_active_help(user_id)
    if helping:
        await message.answer(
            f"Вы сейчас помогаете по задаче «{request_title(helping['id'])}». После оказания помощи заявку завершит её автор.",
            reply_markup=request_chat_kb(helping["id"]),
        )
        return False
    return True


@router.message(Command("problem"))
async def report_request_problem(message: Message) -> None:
    description=(message.text or "").partition(" ")[2].strip()
    first,separator,rest=description.partition(" ")
    actor=resolve_profile_id(message.from_user.id)
    # Previously delivered commands still work; new messages use the task title.
    if first.startswith("#") and first[1:].isascii() and first[1:].isdigit():
        request=get_request(int(first[1:]));description=rest.strip()
    else:
        request=get_active_own_request(actor)
        if not request or request["status"]!=STATUS_IN_PROGRESS:request=get_active_help(actor)
    if not request or len(description)<5:
        await message.answer("Откройте текущую помощь на сайте и нажмите «Есть проблема» или отправьте /problem описание проблемы.")
        return
    try:create_request_dispute(request["id"],actor,description)
    except ValueError as error:
        await message.answer(escape(str(error)))
        return
    await message.answer(f"Обращение по задаче «{request_title(request['id'])}» создано. Завершение и выплата приостановлены до решения поддержки. Чат остаётся доступен.")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if (message.text or "").partition(" ")[2].strip().startswith("login_"):
        await message.answer(EMAIL_ACCESS_NOTICE,reply_markup=email_access_keyboard())
        return
    if not await ensure_registered(message,state):return
    user=get_user(resolve_profile_id(message.from_user.id))
    await show_main_menu(message,f"С возвращением, {escape(user['name'])}!\n\n"+BOT_START_OVERVIEW)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    if not has_verified_email(get_user(resolve_profile_id(message.from_user.id))):
        await message.answer(EMAIL_ACCESS_NOTICE,reply_markup=email_access_keyboard())
        return
    await message.answer(BOT_GUIDE, reply_markup=main_menu_kb())


@router.message(Command("menu"))
@router.message(StateFilter(None), F.text == BTN_NAVIGATOR)
async def cmd_menu_guide(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    await state.clear()
    await message.answer(BOT_GUIDE, reply_markup=main_menu_kb())


@router.message(Command("ask"))
@pro_request_action
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
    request = get_active_own_request(resolve_profile_id(message.from_user.id))
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
    if len(text)>1000:
        await message.answer("Сообщение не отправлено: максимум 1000 символов. Разделите его на несколько сообщений; текст не был обрезан.")
        return
    if not text:
        await message.answer("Отправьте сообщение так: <b>/chat ТЕКСТ</b>")
        return
    user_id = resolve_profile_id(message.from_user.id)
    request = get_request(target_id) if target_id is not None else None
    if target_id is None:
        conversations=db.execute("SELECT * FROM requests WHERE status=? AND helper_id IS NOT NULL AND (requester_id=? OR helper_id=?) ORDER BY id DESC",(STATUS_IN_PROGRESS,user_id,user_id)).fetchall()
        if len(conversations)>1:
            choices="\n".join(f"• {escape(row['what'])} — <code>/chat #{row['id']} ТЕКСТ</code>" for row in conversations)
            await message.answer("У вас несколько активных переписок. Укажите нужную помощь, чтобы сообщение не попало в другой чат:\n\n"+choices,reply_markup=bot_website_keyboard("#/help/chats","Открыть чаты"))
            return
        request=conversations[0] if conversations else None
    if not request or not request["helper_id"] or user_id not in (request["requester_id"], request["helper_id"]) or (target_id is None and request["status"] != STATUS_IN_PROGRESS):
        await message.answer("Чат доступен после назначения помощника по активной заявке.")
        return
    from . import chat_threads
    try:
        # Older direct assignments may predate the first website/chat visit.
        chat_threads.ensure_chat(db,request["id"],request["helper_id"])
        conversation=chat_threads.send_message(db,user_id,text,request_id=request["id"])
    except (PermissionError,LookupError,ValueError):
        await message.answer("Не удалось отправить сообщение. Откройте нужный чат на сайте.",reply_markup=bot_website_keyboard("#/help/chats","Открыть чаты"))
        return
    chat_id=conversation["chat_id"]
    other_id = request["helper_id"] if request["requester_id"] == user_id else request["requester_id"]
    other = get_user(other_id)
    if other and other["tg_user_id"]:
        try:
            for part in chat_notification_chunks(request["id"],get_user(user_id)["name"],text,request["what"],chat_id=chat_id):
                await bot.send_message(other["tg_user_id"],part)
        except Exception:
            logging.exception("Не удалось отправить уведомление о сообщении в Telegram")
    await message.answer(f"💬 Сообщение отправлено в общий чат помощи «{request_title(request['id'])}».")


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    admin = get_user(resolve_profile_id(message.from_user.id))
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
    admin = get_user(resolve_profile_id(message.from_user.id))
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
    if target_id == resolve_profile_id(message.from_user.id):
        await message.answer("Нельзя изменить собственный доступ.")
        return
    if not set_user_blocked(resolve_profile_id(message.from_user.id), target_id, blocked, reason):
        await message.answer("Пользователь не найден.")
        return
    await message.answer("Пользователь заблокирован." if blocked else "Доступ пользователя восстановлен.")


@router.message(Command("verifications"))
async def cmd_verifications(message: Message) -> None:
    admin = get_user(resolve_profile_id(message.from_user.id))
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
    admin = get_user(resolve_profile_id(message.from_user.id))
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
    ok, status = review_identity_verification(resolve_profile_id(message.from_user.id), target_id, approved, note)
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
    ok, status = request_identity_verification(resolve_profile_id(message.from_user.id))
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
    await state.clear()
    await message.answer("Откройте H-Point и войдите по email.",reply_markup=email_access_keyboard())


@router.message(Registration.name, F.text)
async def reg_name(message: Message, state: FSMContext) -> None:
    # Old conversations may still hold this state after the release.
    await state.clear()
    await message.answer(EMAIL_ACCESS_NOTICE,reply_markup=email_access_keyboard())


@router.message(Registration.name)
async def reg_name_invalid(message: Message) -> None:
    await message.answer(EMAIL_ACCESS_NOTICE,reply_markup=email_access_keyboard())


async def ensure_registered(message: Message, state: FSMContext) -> bool:
    user=get_user(resolve_profile_id(message.from_user.id))
    if not has_verified_email(user):
        await state.clear()
        await message.answer(EMAIL_ACCESS_NOTICE,reply_markup=email_access_keyboard())
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
    return WEB_PUBLIC_URL.rstrip("/") + target



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
    await message.answer("🎮 <b>Игры H-Point — на сайте</b>\n\nВыберите игру: откроется её полный интерфейс в вашем профиле. HP, рекорды и достижения общие с ботом.\n\nВход на сайт выполняется по email.", reply_markup=_games_menu_kb(resolve_profile_id(message.from_user.id)))


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
    user = get_user(resolve_profile_id(callback.from_user.id))
    if not user or user["is_blocked"]:
        await callback.answer("Сначала откройте личный диалог с H-Point.", show_alert=True)
        return
    await state.clear()
    parts = (callback.data or "").split(":")
    game = parts[2] if len(parts) > 2 and parts[1] == "start" and parts[2] in game_service.GAME_CATALOG else None
    if game is None and len(parts) > 2 and parts[1] in {"restart", "view", "move", "vol", "assign", "pick", "swap", "hint", "answer", "choose"}:
        try:
            game = game_service.game_session(resolve_profile_id(callback.from_user.id), parts[2])["game"]
        except ValueError:
            pass
    await callback.answer("Полная версия игры — на сайте")
    await callback.message.edit_text(
        "🎮 Игры теперь открываются на сайте: с игровым полем, анимацией и удобным управлением. Ваш прогресс сохранён.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Играть на сайте ↗", url=_game_website_url(resolve_profile_id(callback.from_user.id), game, "store" if len(parts) > 1 and parts[1] in {"shop", "item", "buy", "use"} else None))
        ]]),
    )


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cancel_action(message: Message, state: FSMContext) -> None:
    await state.clear()
    if has_verified_email(get_user(resolve_profile_id(message.from_user.id))):
        await show_main_menu(message,"Действие отменено.")
    else:
        await message.answer("Действие отменено. Вход на сайт — по email.",reply_markup=email_access_keyboard())


@router.message(Command("profile"))
@router.message(StateFilter(None), F.text == BTN_PROFILE)
async def profile(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    user = get_user(resolve_profile_id(message.from_user.id))
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
    if await ensure_registered(message,state):await _show_help_achievements(message,resolve_profile_id(message.from_user.id))


@router.callback_query(F.data == "profile:achievements")
async def help_achievements_callback(callback: CallbackQuery) -> None:
    user=get_user(resolve_profile_id(callback.from_user.id))
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
        line = f"\n<b>{escape(req['what'])}</b> · {request_author_name(req)}\n{role} · {status}"
        if rating is not None:
            line += f" · {'⭐' * rating}"
        chunks.append(line)
    await message.answer("\n".join(chunks), reply_markup=main_menu_kb())
    active_own = [req for req in rows if req["requester_id"] == user_id and req["status"] == STATUS_IN_PROGRESS]
    if active_own:
        await message.answer(
            "Когда помощь оказана, завершите свою заявку:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"✅ {req['what'][:36]}", callback_data=f"finish:{req['id']}")]
                for req in active_own
            ]),
        )


@router.message(Command("history"))
@router.message(StateFilter(None), F.text == BTN_HISTORY)
async def history(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    await show_history(message, resolve_profile_id(message.from_user.id))


@router.callback_query(F.data == "profile:history")
async def cb_profile_history(callback: CallbackQuery) -> None:
    await callback.answer()
    await show_history(callback.message, resolve_profile_id(callback.from_user.id))


@router.message(Command("settings"))
@router.message(StateFilter(None), F.text == BTN_SETTINGS)
async def settings(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    selected = set(get_helper_categories(resolve_profile_id(message.from_user.id)))
    await message.answer(
        "⚙️ <b>Настройки помощи</b>\n\nВыберите категории, в которых готовы помогать. "
        "Если ничего не выбрать, вы сможете помочь с любой заявкой.",
        reply_markup=settings_categories_kb(selected),
    )


@router.callback_query(F.data == "profile:settings")
async def cb_profile_settings(callback: CallbackQuery) -> None:
    selected = set(get_helper_categories(resolve_profile_id(callback.from_user.id)))
    await callback.answer()
    await callback.message.answer(
        "⚙️ <b>Настройки помощи</b>\n\nВыберите категории, в которых готовы помогать.",
        reply_markup=settings_categories_kb(selected),
    )


@router.callback_query(F.data.startswith("setcat:"))
async def cb_set_category(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]
    selected = set(get_helper_categories(resolve_profile_id(callback.from_user.id)))
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
    set_helper_categories(resolve_profile_id(callback.from_user.id), list(selected))
    await callback.answer("Изменено")
    await callback.message.edit_reply_markup(reply_markup=settings_categories_kb(selected))


async def _candidate_card(candidate: dict) -> str:
    verified = (" ✓" if candidate.get("verified") else "")+(" · PRO" if candidate.get("pro_active") else "")
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
    if req["requester_id"] != (actor_id if actor_id is not None else resolve_profile_id(message.from_user.id)):
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
        f"⚡ <b>Кандидаты для помощи «{request_title(request_id)}»</b>\n\n"
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


def own_open_requests(user_id):
    return db.execute("SELECT * FROM requests WHERE requester_id=? AND status=? ORDER BY id DESC LIMIT 5",(user_id,STATUS_OPEN)).fetchall()


async def _choose_candidate_request(message: Message, state: FSMContext) -> bool:
    if not await ensure_registered(message,state):return False
    requests=own_open_requests(resolve_profile_id(message.from_user.id))
    if not requests:
        await message.answer("Сначала создайте открытую заявку. Текущую помощь и чаты можно открыть на сайте.",reply_markup=bot_website_keyboard("#/help"))
        return False
    if len(requests)>1:
        await message.answer("Для какой заявки подобрать помощника?",reply_markup=choose_match_request_kb(requests))
        return False
    return True


@router.message(StateFilter(None), F.text == BTN_FIND_CANDIDATES)
@pro_request_action
async def find_candidates(message: Message, state: FSMContext) -> None:
    if await _choose_candidate_request(message,state):
        await _show_candidates(message,own_open_requests(resolve_profile_id(message.from_user.id))[0]["id"])


@router.message(StateFilter(None), F.text == BTN_MY_CANDIDATES)
@pro_request_action
async def my_candidates(message: Message, state: FSMContext) -> None:
    await find_candidates(message,state)


@router.callback_query(F.data.startswith("matchreq:"))
@pro_request_action
async def cb_match_request(callback: CallbackQuery):
    try:request_id=int(callback.data.split(":",1)[1])
    except (ValueError,IndexError):
        await callback.answer("Некорректная заявка.",show_alert=True);return
    await callback.answer()
    if callback.message:await _show_candidates(callback.message,request_id,actor_id=resolve_profile_id(callback.from_user.id))


async def show_request_management(message,user_id,request_id=None):
    if request_id is None:
        requests=db.execute("SELECT id,what,status FROM requests WHERE requester_id=? AND status IN (?,?) ORDER BY id DESC LIMIT 10",(user_id,STATUS_OPEN,STATUS_IN_PROGRESS)).fetchall()
        if not requests:
            await message.answer("Активных заявок пока нет. Создать заявку можно кнопкой «Мне нужна помощь» или на сайте.",reply_markup=bot_website_keyboard("#/help"));return
        await message.answer("Выберите свою заявку:",reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=str(row["what"])[:48],callback_data="request:view:"+str(row["id"]))] for row in requests
        ]))
        return
    request=get_request(request_id)
    if not request or request["requester_id"]!=user_id:
        await message.answer("Заявка недоступна.");return
    rows=[]
    if request["status"]==STATUS_OPEN:
        rows.append([InlineKeyboardButton(text="Подобрать помощника",callback_data="matchreq:"+str(request_id))])
        rows.append([InlineKeyboardButton(text="Отменить заявку",callback_data="cancel_req:"+str(request_id))])
    if request["status"]==STATUS_IN_PROGRESS:
        rows.append([InlineKeyboardButton(text="Подтвердить завершение",callback_data="finish:"+str(request_id))])
        rows.append([InlineKeyboardButton(text="Отменить помощь",callback_data="cancel_req:"+str(request_id))])
    rows.extend(request_chat_kb(request_id).inline_keyboard)
    rows.append([InlineKeyboardButton(text="Все мои заявки",callback_data="bot:requests")])
    await message.answer(request_text(request),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(StateFilter(None),F.text == BOT_REQUESTS_BUTTON)
@pro_request_action
async def request_management_menu(message: Message,state: FSMContext):
    if await ensure_registered(message,state):await show_request_management(message,resolve_profile_id(message.from_user.id))


@router.callback_query(F.data == "bot:requests")
@pro_request_action
async def cb_request_management_menu(callback: CallbackQuery):
    await callback.answer()
    if callback.message:await show_request_management(callback.message,resolve_profile_id(callback.from_user.id))


@router.callback_query(F.data.startswith("request:view:"))
@pro_request_action
async def cb_request_management_view(callback: CallbackQuery):
    try:request_id=int(callback.data.split(":")[-1])
    except (ValueError,IndexError):
        await callback.answer("Некорректная заявка.",show_alert=True);return
    await callback.answer()
    if callback.message:await show_request_management(callback.message,resolve_profile_id(callback.from_user.id),request_id)


@router.callback_query(F.data.startswith("candidate:assign:"))
@pro_request_action
async def cb_candidate_assign(callback: CallbackQuery, bot: Bot) -> None:
    try:
        _, _, request_id_s, candidate_id_s = callback.data.split(":")
        request_id, candidate_id = int(request_id_s), int(candidate_id_s)
    except (ValueError, TypeError):
        await callback.answer("Некорректные данные.", show_alert=True)
        return

    req = get_request(request_id)
    if not req or req["requester_id"] != resolve_profile_id(callback.from_user.id):
        await callback.answer("Заявка недоступна.", show_alert=True)
        return
    if req["status"] != STATUS_OPEN:
        await callback.answer("Эта заявка уже получила помощника или закрыта.", show_alert=True)
        return
    if candidate_id == resolve_profile_id(callback.from_user.id):
        await callback.answer("Нельзя выбрать себя.", show_alert=True)
        return

    candidate = get_user(candidate_id)
    if not candidate:
        await callback.answer("Кандидат больше недоступен.", show_alert=True)
        return

    if get_current_helper_offer(request_id):
        await callback.answer("Сначала отмените текущее приглашение, затем выберите другого помощника.", show_alert=True)
        await _show_candidates(callback.message, request_id, actor_id=resolve_profile_id(callback.from_user.id))
        return

    application=db.execute("SELECT offer_token FROM request_candidates WHERE request_id=? AND candidate_id=? AND status='applied'",(request_id,candidate_id)).fetchone()
    if application:
        result=accept_open_request(request_id,candidate_id,author_id=resolve_profile_id(callback.from_user.id),application_token=application["offer_token"])
        if result!="created":
            await callback.answer("Для платной помощи сначала нужен резерв в кошельке; либо отклик уже изменился.",show_alert=True)
            return
        await callback.answer("Помощь подтверждена, чат создан")
        await callback.message.answer("Отклик принят. Повторное согласие помощника не требуется.",reply_markup=request_chat_kb(request_id))
        await safe_notify_match(bot,request_id)
        return

    if not offer_helper(request_id, candidate_id):
        await callback.answer("Кандидат уже занят, вышел из очереди или заявка изменилась. Обновляю список.", show_alert=True)
        await _show_candidates(callback.message, request_id, actor_id=resolve_profile_id(callback.from_user.id))
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
    actor_id=resolve_profile_id(callback.from_user.id)
    if actor_id!=helper_id and not await require_pro_management(callback):return
    if not cancel_request_application(request_id, helper_id, actor_id, token):
        await callback.answer("Отклик уже изменился или помощник выбран.", show_alert=True)
        return
    await callback.answer("Отклик отменён")
    await callback.message.edit_text("↩️ Отклик отменён. Сама заявка остаётся открытой.")
    request = get_request(request_id)
    other = get_user(request["requester_id"] if resolve_profile_id(callback.from_user.id) == helper_id else helper_id)
    if other and other["tg_user_id"]:
        try:
            await bot.send_message(other["tg_user_id"], f"↩️ Отклик на помощь «{request_title(request_id)}» отозван помощником." if resolve_profile_id(callback.from_user.id) == helper_id else f"ℹ️ Автор отклонил ваш отклик на помощь «{request_title(request_id)}».")
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
        if not await require_pro_management(callback):return
        offer = get_current_helper_offer(request_id)
        if not offer or not withdraw_helper_offer(request_id, resolve_profile_id(callback.from_user.id), offer["candidate_id"], token):
            await callback.answer("Приглашение уже изменилось или помощь подтверждена.", show_alert=True)
            return
        await callback.answer("Приглашение отменено, заявка остаётся открытой")
        if offer["tg_user_id"]:
            try:
                await bot.send_message(offer["tg_user_id"], f"↩️ Автор отменил приглашение по задаче «{request_title(request_id)}». Подтверждать его больше не нужно; вы можете помогать другим.")
            except Exception:
                logging.exception("Не удалось уведомить об отмене приглашения %s", request_id)
        await _show_candidates(callback.message, request_id, edit=True, actor_id=resolve_profile_id(callback.from_user.id))
        return
    if action not in ("accept", "decline"):
        await callback.answer("Некорректное действие.", show_alert=True)
        return
    accepted = action == "accept"
    request = get_request(request_id)
    offer = get_current_helper_offer(request_id)
    if accepted and offer and offer["candidate_id"] == resolve_profile_id(callback.from_user.id) and (offer["offer_token"] or "") == token and int(request["reward_rub"] or 0) > 0 and request["reward_payment_status"] != "paid":
        await callback.answer("Автор ещё не создал резерв в кошельке H-Point. До резерва не начинайте помощь.", show_alert=True)
        return
    if not respond_to_helper_offer(request_id, resolve_profile_id(callback.from_user.id), accepted, token):
        await callback.answer("Предложение уже неактуально.", show_alert=True)
        return
    request = get_request(request_id)
    if accepted:
        await callback.answer("Помощь подтверждена")
        await callback.message.edit_text(
            "✅ <b>Вы подтвердили помощь.</b> Чат создан — можно связаться с человеком на сайте или командой /chat ТЕКСТ.",
            reply_markup=request_chat_kb(request_id),
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
                f"ℹ️ Помощник отклонил предложение по задаче «{request_title(request_id)}». Можно выбрать другого помощника на сайте.",
                reply_markup=main_menu_kb(),
            )
        except Exception:
            logging.exception("Не удалось уведомить автора заявки %s об отказе", request_id)


@router.callback_query(F.data.startswith("candidate:refresh:"))
@pro_request_action
async def cb_candidate_refresh(callback: CallbackQuery) -> None:
    try:
        request_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return
    req = get_request(request_id)
    if not req or req["requester_id"] != resolve_profile_id(callback.from_user.id):
        await callback.answer("Заявка недоступна.", show_alert=True)
        return
    await callback.answer("Подбор обновлён")
    await _show_candidates(callback.message, request_id, edit=True, actor_id=resolve_profile_id(callback.from_user.id))


@router.callback_query(F.data.startswith("candidate:back:"))
@pro_request_action
async def cb_candidate_back(callback: CallbackQuery) -> None:
    try:
        request_id = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer("Некорректная заявка.", show_alert=True)
        return
    req = get_request(request_id)
    if not req or req["requester_id"] != resolve_profile_id(callback.from_user.id):
        await callback.answer("Заявка недоступна.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(request_text(req), reply_markup=cancel_request_kb(request_id) if req["status"] == STATUS_OPEN else main_menu_kb())


@router.message(StateFilter(None), F.text == BTN_NEED_HELP)
@pro_request_action
async def need_help_start(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message, state):
        return
    from . import personal
    user_id = resolve_profile_id(message.from_user.id)
    usage=personal.usage(user_id,db_connection=db)
    if usage["requests"]["remaining"]<=0:
        await message.answer("Достигнут лимит собственных активных заявок: "+str(usage["requests"]["limit"])+". Завершите или отмените одну из текущих. Черновик сохранён.",reply_markup=bot_website_keyboard("#/help"))
        return
    await state.set_state(HelpRequest.what)
    await message.answer("1/5. <b>Какая помощь нужна?</b> Эта форма создаёт бесплатную заявку. Фото, вознаграждение и расписание доступны на сайте.", reply_markup=cancel_kb())


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


@router.message(HelpRequest.what, ~F.text.startswith("/"))
@pro_request_action
async def q_what(message: Message, state: FSMContext) -> None:
    text = await read_answer(message)
    if text is None: return
    await state.update_data(what=text)
    await state.set_state(HelpRequest.place)
    await message.answer("2/5. <b>Где нужна помощь?</b>", reply_markup=cancel_kb())


@router.message(HelpRequest.place, ~F.text.startswith("/"))
@pro_request_action
async def q_place(message: Message, state: FSMContext) -> None:
    text = await read_answer(message)
    if text is None: return
    await state.update_data(place=text)
    await state.set_state(HelpRequest.time_needed)
    await message.answer("3/5. <b>Когда нужна помощь?</b>", reply_markup=cancel_kb())


@router.message(HelpRequest.time_needed, ~F.text.startswith("/"))
@pro_request_action
async def q_time(message: Message, state: FSMContext) -> None:
    text = await read_answer(message)
    if text is None: return
    await state.update_data(time_needed=text)
    await state.set_state(HelpRequest.urgency)
    await message.answer("4/5. <b>Насколько срочно?</b> Выберите вариант или напишите свой.", reply_markup=cancel_kb(URGENCY_OPTIONS))


@router.message(HelpRequest.urgency, ~F.text.startswith("/"))
@pro_request_action
async def q_urgency(message: Message, state: FSMContext) -> None:
    text = await read_answer(message)
    if text is None: return
    await state.update_data(urgency=text)
    await state.set_state(HelpRequest.details)
    await message.answer("5/5. <b>Дополнительные детали?</b> Если деталей нет — нажмите «Нет».", reply_markup=cancel_kb([BTN_NO_DETAILS]))


@router.message(HelpRequest.details, ~F.text.startswith("/"))
@pro_request_action
async def q_details(message: Message, state: FSMContext, bot: Bot) -> None:
    text = await read_answer(message)
    if text is None: return
    if text == BTN_NO_DETAILS:text = "Нет дополнительных деталей"
    await state.update_data(details=text)
    data = await state.get_data()
    user_id = resolve_profile_id(message.from_user.id)
    try:
        request_id = create_request(user_id, data)
    except (ValueError,PermissionError) as error:
        await message.answer(escape(str(error))+"\nВведённые данные сохранены. Можно повторить отправку после освобождения лимита или продолжить на сайте.",reply_markup=pro_management_keyboard())
        return
    await state.clear()
    req = get_request(request_id)
    await message.answer(
        f"✅ Заявка создана!\n\n{request_text(req)}\n\n"
        "Откройте кандидатов и выберите помощника. Он сам подтвердит согласие.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Подобрать помощника",callback_data="matchreq:"+str(request_id))],
            [InlineKeyboardButton(text="Мои заявки",callback_data="bot:requests")],
        ]),
    )
    await message.answer("Если помощь больше не нужна:", reply_markup=cancel_request_kb(request_id))


def _helper_card(request, distance=None):
    """Public matching summary; exact address and private details stay in chat."""
    text=(f"🤝 <b>{escape(str(request['what']))}</b>\n"
          f"Кому нужна помощь: {request_author_name(request)}\n"
          f"{escape(CATEGORIES.get(request['category'],CATEGORIES['other']))} · {escape(str(request['time_needed']))}")
    if distance is not None:text+=f"\nОколо {distance:g} км от сохранённой точки"
    text+="\n"+escape(request_reward_note(request))
    return text


async def show_helper_status(message,user_id):
    active=get_active_help(user_id)
    applications=get_helper_applications(user_id)
    offers=get_helper_offers(user_id,limit=5)
    ready=is_in_queue(user_id)
    rows=[]
    lines=["🤝 <b>Хочу помочь</b>","Готовность к новым приглашениям: "+("включена" if ready else "на паузе")]
    if active:
        lines.extend(["", "Сейчас вы помогаете: <b>"+escape(str(active["what"]))+"</b>",
                      "Завершение подтверждает автор. Новую помощь можно взять после текущей."])
        rows.extend(request_chat_kb(active["id"]).inline_keyboard)
        rows.append([InlineKeyboardButton(text="Помощь не состоялась · отменить",callback_data="cancel_req:"+str(active["id"]))])
    else:
        rows.append([InlineKeyboardButton(text="Подобрать помощь",callback_data="helper:find")])
        if not ready:rows.append([InlineKeyboardButton(text="Готов получать приглашения",callback_data="helper:ready")])
    if ready:rows.append([InlineKeyboardButton(text="Приостановить новые приглашения",callback_data="leave_queue")])
    if offers:
        lines.append("\nПриглашений от авторов: "+str(len(offers)))
        for offer in offers:rows.append([InlineKeyboardButton(text="Приглашение · "+str(offer["what"])[:40],callback_data="helper:view:"+str(offer["request_id"]))])
    if applications:
        lines.append("Ожидают выбора автора: "+str(len(applications)))
        for application in applications[:5]:rows.append([InlineKeyboardButton(text=str(application["what"])[:45],callback_data="helper:view:"+str(application["request_id"]))])
    closed=db.execute("SELECT r.what,r.status FROM requests r WHERE (r.helper_id=? OR EXISTS(SELECT 1 FROM request_candidates rc WHERE rc.request_id=r.id AND rc.candidate_id=?)) AND r.status IN ('done','cancelled') ORDER BY r.id DESC LIMIT 3",(user_id,user_id)).fetchall()
    if closed:
        lines.append("\nПоследняя помощь:")
        lines.extend(("✅ " if row["status"]=="done" else "↩️ ")+escape(str(row["what"])) for row in closed)
    lines.append("\nИзменения, сообщения и важные уведомления приходят бесплатно, в том числе после окончания PRO.")
    rows.append([InlineKeyboardButton(text="Обновить статус",callback_data="helper:status")])
    rows.append([InlineKeyboardButton(text="Навыки и место на сайте",url=WEB_PUBLIC_URL.rstrip("/")+"/#/help")])
    await message.answer("\n".join(lines),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.message(StateFilter(None), F.text == BTN_WANT_HELP)
@pro_request_action
async def want_help(message: Message, state: FSMContext, bot: Bot=None) -> None:
    if await ensure_registered(message,state):await show_helper_status(message,resolve_profile_id(message.from_user.id))


@router.callback_query(F.data.startswith("helper:"))
@pro_request_action
async def cb_helper_management(callback: CallbackQuery,bot: Bot) -> None:
    user_id=resolve_profile_id(callback.from_user.id)
    parts=str(callback.data or "").split(":")
    action=parts[1] if len(parts)>1 else ""
    if not callback.message:return
    if action in ("status","menu"):
        await callback.answer();await show_helper_status(callback.message,user_id);return
    if action in ("find","ready"):
        await callback.answer()
        if not await check_not_busy(_helper_actor_message(callback)):
            return
        if action=="ready":
            add_to_queue(user_id)
            await callback.message.answer("Готовность включена. Навыки и сохранённая точка синхронизированы с сайтом. Когда автор пригласит вас, придёт уведомление.")
            await show_helper_status(callback.message,user_id);return
        matches=smart_requests_for_helper(user_id,limit=5)
        if not matches:
            await callback.message.answer("По вашим навыкам, доступности и сохранённому месту подходящей помощи пока нет. Можно включить готовность и получать приглашения.")
        for match in matches:
            request=match["request"]
            await callback.message.answer(_helper_card(request,match["distance_km"]),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Откликнуться",callback_data="helper:apply:"+str(request["id"]))]]))
        await callback.message.answer("Отклик открывает обсуждение. Автор сам выберет помощника; деньги не списываются.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Моя помощь и отклики",callback_data="helper:status")],[InlineKeyboardButton(text="Все заявки на сайте",url=WEB_PUBLIC_URL.rstrip("/")+"/#/help")]]))
        return
    try:
        if len(parts)!=3 or action not in ("apply","view"):raise ValueError()
        request_id=int(parts[2])
        if request_id<1:raise ValueError()
    except ValueError:
        await callback.answer("Действие недоступно.",show_alert=True);return
    request=get_request(request_id)
    if action=="apply":
        if not await check_not_busy(_helper_actor_message(callback)):
            await callback.answer("Сначала откройте текущую помощь или оценку в сообщении бота.");return
        eligible={item["request"]["id"] for item in smart_requests_for_helper(user_id,limit=100)}
        if request_id not in eligible:
            await callback.answer("Заявка уже недоступна или не подходит текущим настройкам. Обновите подбор.",show_alert=True);return
        result=apply_to_request(request_id,user_id)
        if result not in ("created","applied","offered"):
            await callback.answer("Заявка уже изменилась. Обновите подбор.",show_alert=True);return
        await callback.answer("Отклик отправлен" if result=="created" else "Отклик уже сохранён")
        candidate=db.execute("SELECT status,offer_token FROM request_candidates WHERE request_id=? AND candidate_id=?",(request_id,user_id)).fetchone()
        author=get_user(request["requester_id"])
        if result=="created" and candidate and candidate["status"]=="applied" and author and author["tg_user_id"]:
            try:await bot.send_message(author["tg_user_id"],f"🤝 <b>{escape(str(get_user(user_id)['name']))}</b> откликнулся на помощь «{request_title(request_id)}». Обсудите детали и выберите помощника.",reply_markup=application_kb(request_id,user_id,candidate["offer_token"],True))
            except Exception:logging.exception("Не удалось уведомить автора об отклике %s",request_id)
        await callback.message.answer("Отклик сохранён. Обсудите детали в чате; автор увидит вас среди откликнувшихся. Когда вас выберут, придёт уведомление.",reply_markup=request_chat_kb(request_id))
        return
    candidate=db.execute("SELECT status,offer_token FROM request_candidates WHERE request_id=? AND candidate_id=?",(request_id,user_id)).fetchone()
    if not request or not (request["helper_id"]==user_id or candidate and candidate["status"] in ("applied","offered","accepted")):
        await callback.answer("Эта помощь вам недоступна.",show_alert=True);return
    await callback.answer()
    status={"open":"Ожидает выбора автора","in_progress":"В работе","done":"Завершена","cancelled":"Отменена"}.get(request["status"],request["status"])
    rows=request_chat_kb(request_id).inline_keyboard
    if candidate and candidate["status"]=="offered" and request["status"]==STATUS_OPEN:
        rows+=helper_offer_kb(request_id,candidate["offer_token"] or "").inline_keyboard
    elif candidate and candidate["status"]=="applied" and request["status"]==STATUS_OPEN:
        rows+=application_kb(request_id,user_id,candidate["offer_token"],False).inline_keyboard
    rows.append([InlineKeyboardButton(text="Моя помощь и отклики",callback_data="helper:status")])
    await callback.message.answer(_helper_card(request)+"\nСтатус: "+escape(status),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


def _helper_actor_message(callback):
    # A callback's message is authored by the bot; permission/business checks
    # must use the person who pressed the button, never message.from_user.
    from types import SimpleNamespace
    return SimpleNamespace(from_user=callback.from_user,answer=callback.message.answer)


@router.callback_query(F.data == "leave_queue")
async def cb_leave_queue(callback: CallbackQuery) -> None:
    if is_in_queue(resolve_profile_id(callback.from_user.id)):
        remove_from_queue(resolve_profile_id(callback.from_user.id))
        await callback.answer("Вы вышли из очереди")
        await callback.message.edit_text("Новые приглашения приостановлены. Сохранённые отклики и уже принятая помощь продолжают действовать.")
    else:
        await callback.answer("Вы не в очереди", show_alert=True)


@router.callback_query(F.data.startswith("cancel_req:"))
@pro_request_action
async def cb_cancel_request(callback: CallbackQuery,bot: Bot=None) -> None:
    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError,IndexError):
        await callback.answer("Некорректная заявка", show_alert=True)
        return
    actor=resolve_profile_id(callback.from_user.id)
    request=get_request(request_id)
    recipients=set()
    if request:
        recipients={request["requester_id"],request["helper_id"]}
        recipients.update(row["candidate_id"] for row in db.execute("SELECT candidate_id FROM request_candidates WHERE request_id=? AND status IN ('applied','offered')",(request_id,)).fetchall())
    reason="Помощник сообщил, что помощь не состоялась" if request and request["helper_id"]==actor else "Отменено автором заявки"
    if cancel_request(request_id,actor,reason):
        await callback.answer("Заявка отменена")
        await callback.message.edit_text(f"🗑 Помощь «{request_title(request_id)}» отменена.")
        if bot:
            for uid in recipients-{None,actor}:
                user=get_user(uid)
                if user and user["tg_user_id"]:
                    try:await bot.send_message(user["tg_user_id"],f"↩️ Помощь «{request_title(request_id)}» отменена. "+escape(reason)+". Переписка и история сохранены.",reply_markup=request_chat_kb(request_id))
                    except Exception:logging.exception("Не удалось уведомить об отмене помощи %s",request_id)
    else:
        await callback.answer("Заявку уже нельзя отменить.", show_alert=True)


@router.callback_query(F.data.startswith("finish:"))
@pro_request_action
async def cb_finish(callback: CallbackQuery, bot: Bot) -> None:
    try:
        request_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректная заявка.", show_alert=True)
        return
    request = get_request(request_id)
    if request is None:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    if request["requester_id"] != resolve_profile_id(callback.from_user.id):
        await callback.answer("Завершить помощь может только автор заявки.", show_alert=True)
        return
    if not complete_request(request_id, request["helper_id"], confirmed_by=resolve_profile_id(callback.from_user.id)):
        await callback.answer("Не удалось завершить: заявка уже закрыта, открыто обращение, нет резерва или недостаточно HP у автора.", show_alert=True)
        return
    await callback.answer("Помощь завершена!")
    request = get_request(request_id)
    paid = int(request["reward_rub"] or 0) > 0
    requester = get_user(request["requester_id"])
    from . import workflow
    quote=workflow.reward_quote(request)
    fee,net,total=quote["commission_rub"],quote["helper_reward_rub"],quote["total_rub"]
    currency="тестовых ₽" if quote["test_only"] else "₽"
    settlement = (f"Помощнику зачислено {net} {currency}; комиссия H-Point — {fee} {currency}; всего из резерва — {total} {currency}. HP за платную помощь не списывались и не начислялись."
                  if paid else (f"Списано {REQUEST_COST} HP. Баланс: {requester['balance']} HP." if request["hp_settled"] else "Повторная помощь за 24 часа: HP не списывались и не начислялись."))
    await callback.message.edit_text(
        f"✅ Вы подтвердили выполнение помощи по задаче «{request_title(request_id)}». {settlement}\n\nОцените помощь:",
        reply_markup=rating_kb(request_id),
    )
    helper = get_user(request["helper_id"])
    if helper and helper["tg_user_id"]:
        settlement = (f"В ваш кошелёк H-Point поступило {net} {currency}. Условия вознаграждения выполнены; комиссия H-Point — {fee} {currency}."
                      if paid else (f"Вам начислено +{HELPER_REWARD} HP. Баланс: {helper['balance']} HP." if request["hp_settled"] else "Повторная помощь за 24 часа: HP не списывались и не начислялись."))
        try:
            await bot.send_message(
                helper["tg_user_id"],
                f"✅ Автор подтвердил помощь по задаче «{request_title(request_id)}». {settlement}\n\nОцените взаимодействие:",
                reply_markup=rating_kb(request_id, "ratehelp"),
            )
        except Exception:
            logging.exception("Не удалось сообщить о завершении заявки %s", request_id)


@router.callback_query(F.data.startswith("paid_done:"))
async def cb_paid_completion(callback: CallbackQuery, bot: Bot) -> None:
    # Keep confirmation buttons in previously sent Telegram messages usable.
    await cb_finish(callback, bot)


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
    if not set_rating(request_id, resolve_profile_id(callback.from_user.id), rating):
        await callback.answer("Оценка уже поставлена или недоступна.", show_alert=True); return
    await callback.answer("Спасибо за оценку!")
    await callback.message.edit_reply_markup(reply_markup=None)
    await start_review(callback, state, request_id, "requester", rating)
    req = get_request(request_id)
    if req and req["helper_id"]:
        try:
            helper=get_user(req["helper_id"])
            if helper and helper["tg_user_id"]:
                await callback.bot.send_message(helper["tg_user_id"], f"Ваша помощь по задаче «{request_title(request_id)}» получила оценку {'⭐' * rating} ({rating}/5)."+help_achievements.reward_notice(req["helper_id"],request_id))
        except Exception:
            logging.exception("Не удалось сообщить помощнику оценку")


@router.callback_query(F.data.startswith("ratehelp:"))
async def cb_rate_help(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        _, request_id_str, rating_str = callback.data.split(":")
        request_id, rating = int(request_id_str), int(rating_str)
    except ValueError:
        await callback.answer("Некорректные данные.", show_alert=True); return
    if not set_helper_rating(request_id, resolve_profile_id(callback.from_user.id), rating):
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
    set_review(request_id, resolve_profile_id(message.from_user.id), review, side)
    await state.clear()
    await show_main_menu(message, "Спасибо за отзыв! Диалог завершён. Главное меню:")


@router.message(Review.requester_review)
async def requester_review(message: Message, state: FSMContext) -> None:
    await finish_review(message, state, "requester")


@router.message(Review.helper_review)
async def helper_review(message: Message, state: FSMContext) -> None:
    await finish_review(message, state, "helper")





async def show_billing(message: Message, state: FSMContext) -> None:
    if not await ensure_registered(message,state):return
    from . import personal
    user=get_user(resolve_profile_id(message.from_user.id))
    usage=personal.usage(user["user_id"],db_connection=db)
    active=usage["pro_active"]
    status=("PRO активен до "+escape(str(usage["pro_until"])) if active else "Сейчас бесплатный тариф")
    await message.answer(
        "⭐ <b>H-Point PRO</b>\n\n"+status+"\n"
        "Собственные активные заявки: "+str(usage["requests"]["active"])+" из "+str(usage["requests"]["limit"])+".\n\n"
        "149 тестовых ₽ или 90 HP на 30 дней, без автопродления. Досрочное продление добавляет 30 дней к текущему сроку.\n"
        "PRO: до 5 активных собственных заявок, активности без месячного тарифного лимита, личные шаблоны, повтор по расписанию, управление заявками в Telegram и мягкий приоритет среди подходящих кандидатов.\n\n"
        "Бесплатно: 1 собственная активная заявка и 2 публикации активностей за календарный месяц. Переписка, уведомления, отклики и управление помощью на сайте доступны без PRO.\n"
        "«Для работы» — отдельный профессиональный кабинет; его права и подписка сохраняются. Рейтинг и Лига не продаются, результат подбора не гарантирован.",
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
        "Сейчас используются только тестовые средства. Оплата и вывод реальных денег отключены. "
        "В новой платной заявке сумма — вознаграждение помощнику; комиссия H-Point 15% добавляется сверху и оплачивается автором. Старые договорённости сохраняют свои условия. "
        "Тестовые средства нельзя вывести.\n\n"
        "Поддержка платежей: /paysupport"
    )

@router.message(Command("paysupport"))
async def paysupport(message: Message):
    await message.answer(
        "💬 <b>Поддержка платежей H-Point</b>\n\n"
        "Если тестовые средства списались, но функция не включилась, откройте поддержку на сайте и опишите действие. "
        "Не отправляйте пароль от аккаунта."
    )

@router.message(Command("link"))
async def link_account(message: Message,state: FSMContext):
    await state.clear()
    if message.chat.type!="private":
        await message.answer("Привязка выполняется только в личном чате с H-Point.")
        return
    parts=(message.text or "").split(maxsplit=1)
    if len(parts)!=2:
        await message.answer("Получите код в профиле сайта и отправьте <b>/link КОД</b>.",reply_markup=email_access_keyboard())
        return
    code=parts[1].strip().upper()
    if not link_owner_has_verified_email(db,code):
        await message.answer("Подтвердите email на сайте и получите новый код привязки.",reply_markup=email_access_keyboard())
        return
    await state.set_state("TelegramLink:confirmation")
    await state.update_data(telegram_link_code=code,telegram_link_created_at=time.time())
    await message.answer("Привязать этот Telegram к вашему профилю H-Point? Подтверждайте только свою привязку.",reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Привязать",callback_data="telegram-link:confirm"),InlineKeyboardButton(text="Отмена",callback_data="telegram-link:cancel")]
    ]))


@router.callback_query(F.data.in_({"telegram-link:confirm","telegram-link:cancel"}))
async def confirm_telegram_link(callback: CallbackQuery,state: FSMContext):
    pending=await state.get_data()
    await state.clear()
    if callback.data=="telegram-link:cancel":
        await callback.answer("Привязка отменена")
        await callback.message.answer("Привязка отменена. Вход на сайт — по email.",reply_markup=email_access_keyboard())
        return
    code=pending.get("telegram_link_code")
    created=pending.get("telegram_link_created_at",0)
    if not code or not isinstance(created,(int,float)) or not 0<=time.time()-created<=300 or not link_owner_has_verified_email(db,code):
        await callback.answer("Подтверждение устарело. Получите новый код на сайте.",show_alert=True)
        return
    ok,result=link_by_code(code,callback.from_user.id,callback.from_user.username)
    if not ok:
        await callback.answer(str(result),show_alert=True)
        return
    await callback.answer("Telegram привязан")
    await callback.message.answer("Telegram привязан. Здесь будут приходить уведомления и сообщения.",reply_markup=main_menu_kb(resolve_profile_id(callback.from_user.id)))

@router.message(Command("unlink"))
async def unlink_account(message: Message):
    """Detach the current Telegram identity so it can be linked to another site profile."""
    source=get_user(resolve_profile_id(message.from_user.id))
    if not source or not source["tg_user_id"]:
        await message.answer("Telegram не привязан. Войдите по email на сайте, получите код в профиле и отправьте /link КОД.")
        return
    detached=detach_telegram_to_web_profile(resolve_profile_id(message.from_user.id))
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
        [InlineKeyboardButton(text="Открыть тестовую оплату на сайте", url=web_payment_url(item_type,request_id))]
    ])

@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(callback: CallbackQuery,state: FSMContext):
    item_type=str(callback.data or "").partition(":")[2]
    if item_type!="pro":
        await callback.answer("Эта отдельная функция снята с новых продаж. История и оплаченные права сохранены.",show_alert=True)
        return
    await callback.answer()
    if callback.message:
        await callback.message.answer("H-Point PRO: 149 тестовых ₽ или 90 HP на 30 дней, без автопродления. Покупка и продление — на сайте.",reply_markup=payment_button("pro"))


@router.callback_query(F.data.startswith("buyreq:"))
async def cb_buy_request(callback: CallbackQuery):
    await callback.answer("Отдельное продвижение заявки снято с новых продаж. Ранее оплаченные права сохранены.",show_alert=True)


@router.callback_query(F.data.startswith("payreq:"))
async def cb_pay_request(callback: CallbackQuery):
    await callback.answer("Эта отдельная функция снята с новых продаж. Ранее оплаченные права сохранены.",show_alert=True)


@router.message(Billing.ad_text,F.text)
async def billing_ad_text(message: Message,state: FSMContext):
    await state.clear()
    await message.answer("Локальные объявления сняты с новых продаж. Уже оплаченные права сохранены. Актуальные возможности:",reply_markup=billing_kb())

@router.message(Command("commercial"))
async def commercial_start(message: Message,state: FSMContext):
    if not await ensure_registered(message,state):return
    await state.clear()
    await message.answer(
        "💼 Коммерческий кабинет для тренеров, организаций, прорабов и специалистов: услуги, клиенты и расписание. "
        "7 дней бесплатно, затем 490 тестовых ₽ за 30 дней, без автоматических списаний. "
        "Войдите по email и откройте «Коммерческий кабинет» в профиле сайта.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть профиль на сайте",url=WEB_PUBLIC_URL.rstrip("/")+"/#/profile")]]),
    )


@router.message(Billing.commercial_title,F.text)
async def commercial_title(message: Message,state: FSMContext):
    await commercial_start(message,state)


@router.message(Billing.commercial_amount,F.text)
async def commercial_amount(message: Message,state: FSMContext):
    await commercial_start(message,state)
