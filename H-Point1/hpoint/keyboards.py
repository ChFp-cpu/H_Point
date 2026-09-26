from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from .config import *
def main_menu_kb(): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=BTN_NEED_HELP),KeyboardButton(text=BTN_WANT_HELP)],[KeyboardButton(text=BTN_CANDIDATES),KeyboardButton(text=BTN_MY_OFFERS)],[KeyboardButton(text=BTN_PROFILE),KeyboardButton(text=BTN_HISTORY)],[KeyboardButton(text=BTN_SETTINGS)]],resize_keyboard=True)
def cancel_kb(*extra_rows): return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=t) for t in row] for row in extra_rows]+[[KeyboardButton(text=BTN_CANCEL)]],resize_keyboard=True)
def finish_kb(rid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Завершить помощь',callback_data=f'finish:{rid}')]])
def rating_kb(rid,prefix='rate'): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f'{n} ⭐',callback_data=f'{prefix}:{rid}:{n}') for n in range(1,6)]])
def cancel_request_kb(rid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🗑 Отменить заявку',callback_data=f'cancel_req:{rid}')],[InlineKeyboardButton(text=f'🚀 Поднять на 24ч ({BOOST_COST} HP)',callback_data=f'boost:{rid}')]])
def profile_kb(): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✏️ Изменить навыки и портфолио',callback_data='profile:edit')],[InlineKeyboardButton(text=BTN_SETTINGS,callback_data='profile:settings')]])
def settings_categories_kb(selected):
    keys=list(CATEGORIES); rows=[]
    for i in range(0,len(keys),2): rows.append([InlineKeyboardButton(text=('✅ ' if k in selected else '')+CATEGORIES[k],callback_data=f'setcat:{k}') for k in keys[i:i+2]])
    rows.append([InlineKeyboardButton(text='💾 Сохранить',callback_data='setcat:save')]); return InlineKeyboardMarkup(inline_keyboard=rows)
def request_card_kb(rid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🤝 Откликнуться',callback_data=f'apply:{rid}')]])
def candidate_kb(aid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Выбрать',callback_data=f'cand_accept:{aid}'),InlineKeyboardButton(text='❌ Отсеять',callback_data=f'cand_reject:{aid}')]])
def offer_kb(aid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🚫 Отозвать отклик',callback_data=f'offer_reject:{aid}')]])
