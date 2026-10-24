from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from .config import *

def main_menu_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_NEED_HELP), KeyboardButton(text=BTN_WANT_HELP)],
        [KeyboardButton(text=BTN_FIND_CANDIDATES), KeyboardButton(text=BTN_MY_CANDIDATES)],
        [KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_HISTORY)],
        [KeyboardButton(text=BTN_SETTINGS)],
        [KeyboardButton(text=BTN_GAMES)],
        [KeyboardButton(text="💳 H-Point+"), KeyboardButton(text=BTN_NAVIGATOR)],
        [KeyboardButton(text=BTN_WEBSITE)],
    ], resize_keyboard=True)


def cancel_kb(*extra_rows):
    rows = [[KeyboardButton(text=t) for t in row] for row in extra_rows]
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def finish_kb(request_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Завершить помощь", callback_data=f"finish:{request_id}")]])

def confirm_paid_completion_kb(request_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Подтвердить помощь и выплатить из резерва", callback_data=f"paid_done:{request_id}")]])

def rating_kb(request_id, prefix="rate"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{n} ⭐", callback_data=f"{prefix}:{request_id}:{n}") for n in range(1, 6)]])

def leave_queue_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚪 Выйти из очереди", callback_data="leave_queue")]])

def cancel_request_kb(request_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 Отменить заявку", callback_data=f"cancel_req:{request_id}")]])

def category_kb(prefix="cat"):
    keys = list(CATEGORIES)
    rows = []
    for i in range(0, len(keys), 2):
        rows.append([InlineKeyboardButton(text=CATEGORIES[k], callback_data=f"{prefix}:{k}") for k in keys[i:i+2]])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def profile_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
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
        [InlineKeyboardButton(text=f"{item['title']} — {item['rub']} ₽" + (" / 30 дней" if key == "pro" else ""), callback_data=f"buy:{key}")]
        for key, item in MONETIZATION_ITEMS.items()
    ])

def choose_request_kb(requests):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"№{r['id']} — {r['what'][:28]}", callback_data=f"buyreq:{r['id']}")] for r in requests])


def choose_match_request_kb(requests, prefix="matchreq"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"№{r['id']} — {r['what'][:32]}", callback_data=f"{prefix}:{r['id']}")]
        for r in requests
    ])

def candidate_kb(request_id, candidate_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Выбрать помощника", callback_data=f"candidate:assign:{request_id}:{candidate_id}")]
    ])

def application_kb(request_id, helper_id, token, for_author=True):
    rows = [[InlineKeyboardButton(text="🤝 Выбрать помощника", callback_data=f"candidate:assign:{request_id}:{helper_id}")]] if for_author else []
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
