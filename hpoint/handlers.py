"""Telegram UI и пользовательские сценарии H-Point."""
import logging
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

router = Router()


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
    )


async def notify_match(bot: Bot, request_id: int) -> None:
    req = get_request(request_id)
    if req is None or req["helper_id"] is None:
        logging.error("Нельзя отправить уведомление: заявка %s не найдена или без помощника", request_id)
        return
    requester = get_user(req["requester_id"])
    helper = get_user(req["helper_id"])
    if requester is None or helper is None:
        logging.error("Не найдены участники заявки %s", request_id)
        return

    try:
        await bot.send_message(
            helper["user_id"],
            "🤝 <b>Вы нашли, кому помочь!</b>\n\n"
            f"{request_text(req)}\n\n"
            f"<b>Кому помогаете:</b> {user_link(requester)}\n\n"
            "Свяжитесь с человеком. Когда помощь будет оказана — нажмите «Завершить помощь».",
            reply_markup=finish_kb(request_id),
        )
    except Exception:
        logging.exception("Не удалось уведомить помощника %s по заявке %s", helper["user_id"], request_id)

    try:
        await bot.send_message(
            requester["user_id"],
            "🎉 <b>Для вашей заявки нашёлся помощник!</b>\n\n"
            f"{request_text(req)}\n\n"
            f"<b>Ваш помощник:</b> {user_link(helper)}\n\n"
            "Помощник свяжется с вами. После выполнения он нажмёт «Завершить помощь», "
            "а вас попросят оценить взаимодействие.",
            reply_markup=main_menu_kb(),
        )
    except Exception:
        logging.exception("Не удалось уведомить автора %s по заявке %s", requester["user_id"], request_id)


async def safe_notify_match(bot: Bot, request_id: int) -> None:
    try:
        await notify_match(bot, request_id)
    except Exception:
        logging.exception("Не удалось отправить уведомление о паре для заявки %s", request_id)


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
    user = get_user(message.from_user.id)
    if user is None:
        await state.set_state(Registration.name)
        await message.answer(
            "👋 Добро пожаловать в <b>H-Point</b> — сервис взаимопомощи!\n\n"
            "Как вас зовут? Напишите своё имя."
        )
        return
    await show_main_menu(message, f"С возвращением, {escape(user['name'])}! Выберите действие:")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>H-Point — помощь рядом</b>\n\n"
        "Создайте заявку, чтобы попросить о помощи, или встаньте в очередь, "
        "чтобы помочь кому-то. После подбора вы получите уведомление; "
        "завершение заявки и оценки доступны в боте.\n\n"
        "Основные действия находятся в меню. Команды: /start, /profile, "
        "/history, /settings, /billing, /cancel. Для привязки аккаунта: /link КОД.\n\n"
        "Подбор использует правила и данные профиля; AI-функций в текущей версии нет."
    )


@router.message(Registration.name, F.text)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if name.startswith("/") or name in (BTN_NEED_HELP, BTN_WANT_HELP, BTN_FIND_CANDIDATES, BTN_MY_CANDIDATES, BTN_PROFILE, BTN_HISTORY, BTN_SETTINGS, BTN_CANCEL):
        await message.answer("Пожалуйста, напишите своё имя обычным текстом.")
        return
    if not name or len(name) > MAX_NAME_LEN:
        await message.answer(f"Имя должно быть от 1 до {MAX_NAME_LEN} символов.")
        return
    create_user(message.from_user.id, name, message.from_user.username)
    await state.clear()
    await show_main_menu(message, f"✅ Регистрация завершена, {escape(name)}! Вам начислено <b>{START_BALANCE} HP</b>.")


@router.message(Registration.name)
async def reg_name_invalid(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте имя текстовым сообщением.")


async def ensure_registered(message: Message, state: FSMContext) -> bool:
    if get_user(message.from_user.id) is None:
        await state.set_state(Registration.name)
        await message.answer("Сначала давайте познакомимся. Как вас зовут?")
        return False
    return True


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
    categories = get_helper_categories(user["user_id"])
    text = (
        f"👤 <b>{escape(user['name'])}</b>\n\n"
        f"💰 Баланс: <b>{user['balance']} HP</b>\n"
        f"🤝 Помощей оказано: <b>{stats['helped']}</b>\n"
        f"📥 Помощей получено: <b>{stats['received']}</b>\n"
        f"⭐ Оценка как помощника: <b>{stars(stats['helped_avg'])}</b>\n"
        f"⭐ Оценка как получателя: <b>{stars(stats['received_avg'])}</b>\n\n"
        f"🛠 Категории помощи: {', '.join(CATEGORIES[c] for c in categories) if categories else 'не настроены'}"
    )
    await message.answer(text, reply_markup=profile_kb())


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
        f"👤 <b>{escape(candidate.get('name') or 'Пользователь')}</b>{verified}{username}\n"
        f"⭐ {rating:.1f}/5 · {reviews} отзывов\n"
        f"📍 {distance_text}\n"
        f"🎯 Совпадение: <b>{score}%</b>"
    )


async def _show_candidates(message: Message, request_id: int, *, edit: bool = False) -> None:
    req = get_request(request_id)
    if not req:
        await message.answer("Заявка не найдена.")
        return
    if req["requester_id"] != message.from_user.id:
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
    if not matches:
        text = (
            "⚡ <b>Подбор кандидатов</b>\n\n"
            "Пока нет доступных кандидатов. Попробуйте обновить подбор позже.\n\n"
            f"{request_text(req)}"
        )
        markup = candidates_navigation_kb(request_id)
        if edit:
            await message.edit_text(text, reply_markup=markup)
        else:
            await message.answer(text, reply_markup=markup)
        return

    header = (
        f"⚡ <b>Кандидаты для заявки №{request_id}</b>\n\n"
        f"{escape(req['what'])}\n\n"
        f"Найдено: <b>{len(matches)}</b>. Выберите подходящего помощника."
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
    await message.answer("Подбор можно обновить после изменения профилей или доступности.", reply_markup=candidates_navigation_kb(request_id))


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

    if not try_assign_helper(request_id, candidate_id):
        await callback.answer("Кандидат уже занят. Обновляю список.", show_alert=True)
        await _show_candidates(callback.message, request_id)
        return

    db.execute(
        "UPDATE request_candidates SET status='accepted', updated_at=CURRENT_TIMESTAMP WHERE request_id=? AND candidate_id=?",
        (request_id, candidate_id),
    )
    db.execute(
        "UPDATE request_candidates SET status='rejected', updated_at=CURRENT_TIMESTAMP WHERE request_id=? AND candidate_id!=? AND status='pending'",
        (request_id, candidate_id),
    )

    await callback.answer("Помощник назначен!")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "🎉 <b>Помощник назначен</b>\n\n"
        f"{request_text(req)}\n\n"
        f"<b>Ваш помощник:</b> {user_link(candidate)}\n\n"
        "Чат создаётся автоматически. После выполнения помощи вы получите запрос на оценку.",
        reply_markup=main_menu_kb(),
    )
    await safe_notify_match(bot, request_id)


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
    await _show_candidates(callback.message, request_id, edit=True)


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
    active = get_active_own_request(user_id)
    if active:
        markup = cancel_request_kb(active["id"]) if active["status"] == STATUS_OPEN else None
        await message.answer(f"У вас уже есть активная заявка.\n\n{request_text(active)}", reply_markup=markup)
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
    if get_active_own_request(user_id):
        await show_main_menu(message, "У вас уже есть активная заявка. Новая не создана.")
        return
    request_id = create_request(user_id, data)
    req = get_request(request_id)
    helper_id = find_best_queued_helper(req)
    if helper_id is not None and try_assign_helper(request_id, helper_id):
        await message.answer("✅ Заявка создана и помощник найден!", reply_markup=main_menu_kb())
        await safe_notify_match(bot, request_id)
        return
    await message.answer(
        f"✅ Заявка создана!\n\n{request_text(req)}\n\n"
        "Свободного помощника пока нет. Как только кто-то откликнется, мы вас соединим.",
        reply_markup=main_menu_kb(),
    )
    await message.answer("Если помощь больше не нужна:", reply_markup=cancel_request_kb(request_id))


@router.message(StateFilter(None), F.text == BTN_WANT_HELP)
async def want_help(message: Message, state: FSMContext, bot: Bot) -> None:
    if not await ensure_registered(message, state) or not await check_not_busy(message):
        return
    user_id = message.from_user.id
    own = get_active_own_request(user_id)
    if own:
        await message.answer(f"У вас есть активная заявка №{own['id']}. Нельзя одновременно просить помощь и помогать.")
        return
    while True:
        req = find_best_open_request_for(user_id)
        if req is None:
            break
        if try_assign_helper(req["id"], user_id):
            await safe_notify_match(bot, req["id"])
            return
    if is_in_queue(user_id):
        await message.answer("Вы уже в очереди помощников.", reply_markup=leave_queue_kb())
        return
    add_to_queue(user_id)
    await message.answer("Вы добавлены в очередь помощников. Мы сообщим, когда появится подходящая заявка.", reply_markup=leave_queue_kb())


@router.callback_query(F.data == "leave_queue")
async def cb_leave_queue(callback: CallbackQuery) -> None:
    if is_in_queue(callback.from_user.id):
        remove_from_queue(callback.from_user.id)
        await callback.answer("Вы вышли из очереди")
        await callback.message.edit_text("Вы вышли из очереди помощников.")
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
    if not complete_request(request_id, callback.from_user.id):
        await callback.answer("Не удалось завершить: заявка уже закрыта или недостаточно HP у автора.", show_alert=True); return
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
            await callback.bot.send_message(req["helper_id"], f"Ваша помощь по заявке №{request_id} получила оценку {'⭐' * rating} ({rating}/5).")
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
        "Платные возможности оплачиваются в рублях через внешний эквайринг.\n"
        "Telegram Stars не используются.\n\n"
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
        await callback.answer("Неизвестный товар",show_alert=True);return
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
            [InlineKeyboardButton(text=f"🚀 Продвижение — {PRICE_BOOST_RUB} ₽",callback_data=f"payreq:boost:{request_id}")],
            [InlineKeyboardButton(text=f"🔥 Больше откликов — {PRICE_MORE_RESPONSES_RUB} ₽",callback_data=f"payreq:more_responses:{request_id}")]
        ])
    )

@router.callback_query(F.data.startswith("payreq:"))
async def cb_pay_request(callback: CallbackQuery):
    try:_,item_type,rid=callback.data.split(":");rid=int(rid)
    except:
        await callback.answer("Некорректные данные",show_alert=True);return
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
    text=message.text.strip()
    if not text or len(text)>MAX_TEXT_LEN:
        await message.answer(f"Текст должен быть от 1 до {MAX_TEXT_LEN} символов.");return
    await state.clear()
    await message.answer(
        f"📢 Объявление подготовлено.\nЦена: <b>{PRICE_AD_RUB} ₽</b>",
        reply_markup=payment_button("ad")
    )

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

