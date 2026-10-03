from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from .config import *

def main_menu_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=BTN_NEED_HELP), KeyboardButton(text=BTN_WANT_HELP)],
        [KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_HISTORY)],
        [KeyboardButton(text=BTN_SETTINGS)],
        [KeyboardButton(text="💳 H-Point+" )],
    ], resize_keyboard=True)

def cancel_kb(*extra_rows):
    rows = [[KeyboardButton(text=t) for t in row] for row in extra_rows]
    rows.append([KeyboardButton(text=BTN_CANCEL)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

def finish_kb(request_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Завершить помощь", callback_data=f"finish:{request_id}")]])

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
        [InlineKeyboardButton(text=f"🚀 Продвижение — {PRICE_BOOST_RUB} ₽", callback_data="buy:boost")],
        [InlineKeyboardButton(text=f"🔥 Больше откликов — {PRICE_MORE_RESPONSES_RUB} ₽", callback_data="buy:more_responses")],
        [InlineKeyboardButton(text=f"⭐ PRO — {PRICE_PRO_RUB} ₽/мес", callback_data="buy:pro")],
        [InlineKeyboardButton(text=f"✓ Верификация — {PRICE_VERIFICATION_RUB} ₽", callback_data="buy:verification")],
        [InlineKeyboardButton(text=f"📌 Избранное+ — {PRICE_FAVORITES_RUB} ₽", callback_data="buy:favorites")],
        [InlineKeyboardButton(text=f"💼 Business — {PRICE_BUSINESS_RUB} ₽/мес", callback_data="buy:business")],
        [InlineKeyboardButton(text=f"🏢 Business Pro — {PRICE_BUSINESS_PRO_RUB} ₽/мес", callback_data="buy:business_pro")],
        [InlineKeyboardButton(text=f"📢 Реклама — {PRICE_AD_RUB} ₽", callback_data="buy:ad")],
    ])

def choose_request_kb(requests):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"№{r['id']} — {r['what'][:28]}", callback_data=f"buyreq:{r['id']}")] for r in requests])
