from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from .config import *
from .features import GAMES_ENABLED
from contextvars import ContextVar

MENU_USER = ContextVar("hpoint_bot_menu_user",default=None)
BOT_REQUESTS_BUTTON = "📋 Мои заявки"

def main_menu_kb(user_id=None):
    from . import database,work_bot
    user_id=MENU_USER.get() if user_id is None else user_id
    rows=[
        [KeyboardButton(text=BTN_WEBSITE), KeyboardButton(text="💬 Мои чаты")],
        [KeyboardButton(text=BTN_NAVIGATOR), KeyboardButton(text=BTN_CANCEL)],
    ]
    if user_id is not None:
        from . import personal
        if personal.is_pro(user_id,db_connection=database.db):
            rows.insert(1,[KeyboardButton(text=BTN_NEED_HELP),KeyboardButton(text=BOT_REQUESTS_BUTTON)])
    if work_bot.has_paid_access(database.db,user_id):rows.insert(1,[KeyboardButton(text=work_bot.WORK_BUTTON)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_kb(*extra_rows):
    rows = [[KeyboardButton(text=t) for t in row] for row in extra_rows]
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def _request_owner_pro(request_id):
    from . import database,personal
    request=database.get_request(request_id)
    return bool(request and personal.is_pro(request["requester_id"],db_connection=database.db))


def finish_kb(request_id):
    action=(InlineKeyboardButton(text="✅ Завершить помощь",callback_data=f"finish:{request_id}")
            if _request_owner_pro(request_id) else InlineKeyboardButton(text="✅ Завершить помощь на сайте",url=WEB_PUBLIC_URL.rstrip("/")+"/#/help"))
    return InlineKeyboardMarkup(inline_keyboard=request_chat_kb(request_id).inline_keyboard+[[action]])


def request_chat_kb(request_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💬 Открыть чат заявки",url=WEB_PUBLIC_URL.rstrip("/")+"/#/help/chat/"+str(int(request_id)))]])


def confirm_paid_completion_kb(request_id):
    if not _request_owner_pro(request_id):return finish_kb(request_id)
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить помощь и выплатить из резерва", callback_data=f"paid_done:{request_id}")]])


def rating_kb(request_id, prefix="rate"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{n} ⭐", callback_data=f"{prefix}:{request_id}:{n}") for n in range(1, 6)]])

def leave_queue_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚪 Выйти из очереди", callback_data="leave_queue")]])

def cancel_request_kb(request_id):
    button=(InlineKeyboardButton(text="🗑 Отменить заявку",callback_data=f"cancel_req:{request_id}")
            if _request_owner_pro(request_id) else InlineKeyboardButton(text="Отменить заявку на сайте",url=WEB_PUBLIC_URL.rstrip("/")+"/#/help"))
    return InlineKeyboardMarkup(inline_keyboard=[[button]])

def category_kb(prefix="cat"):
    keys = list(CATEGORIES)
    rows = []
    for i in range(0, len(keys), 2):
        rows.append([InlineKeyboardButton(text=CATEGORIES[k], callback_data=f"{prefix}:{k}") for k in keys[i:i+2]])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏅 Достижения за помощь", callback_data="profile:achievements")],
        [InlineKeyboardButton(text=BTN_HISTORY, callback_data="profile:history")],
        [InlineKeyboardButton(text=BTN_SETTINGS, callback_data="profile:settings")],
    ])

def settings_categories_kb(selected: set[str]):
    rows = []
    keys = list(CATEGORIES)
    for i in range(0, len(keys), 2):
        row = []
        for k in keys[i:i+2]:
            mark = "✅ " if k in selected else ""
            row.append(InlineKeyboardButton(text=mark + CATEGORIES[k], callback_data=f"setcat:{k}"))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="💾 Сохранить", callback_data="setcat:save")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def billing_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="H-Point PRO · 149 тестовых ₽ / 90 HP · 30 дней",callback_data="buy:pro")],
        [InlineKeyboardButton(text="Для работы · профессиональный кабинет",url=WEB_PUBLIC_URL.rstrip("/")+"/#/profile")],
    ])


def choose_request_kb(requests):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=r["what"][:48], callback_data=f"buyreq:{r['id']}")] for r in requests])


def choose_match_request_kb(requests, prefix="matchreq"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r["what"][:48], callback_data=f"{prefix}:{r['id']}")]
        for r in requests
    ])

def candidate_kb(request_id, candidate_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Выбрать помощника", callback_data=f"candidate:assign:{request_id}:{candidate_id}")]
    ])

def application_kb(request_id, helper_id, token, for_author=True):
    action=(InlineKeyboardButton(text="🤝 Выбрать помощника",callback_data=f"candidate:assign:{request_id}:{helper_id}")
            if _request_owner_pro(request_id) else InlineKeyboardButton(text="Выбрать помощника на сайте",url=WEB_PUBLIC_URL.rstrip("/")+"/#/help"))
    rows = [[action]] if for_author else []
    rows.append([InlineKeyboardButton(text="Отклонить отклик" if for_author else "Отозвать отклик", callback_data=f"ac:{request_id}:{helper_id}:{token}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def helper_offer_kb(request_id, offer_token=""):
    suffix = f":{offer_token}" if offer_token else ""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Помогу", callback_data=f"offer:accept:{request_id}{suffix}"),
         InlineKeyboardButton(text="↩️ Отклонить", callback_data=f"offer:decline:{request_id}{suffix}")]
    ])

def candidates_navigation_kb(request_id, offer=None):
    rows = []
    if offer:
        rows.append([InlineKeyboardButton(text="↩️ Отменить приглашение", callback_data=f"offer:cancel:{request_id}:{offer['offer_token'] or ''}")])
    rows.extend([
        [InlineKeyboardButton(text="🔄 Обновить кандидатов", callback_data=f"candidate:refresh:{request_id}")],
        [InlineKeyboardButton(text="⬅️ К заявке", callback_data=f"candidate:back:{request_id}")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
