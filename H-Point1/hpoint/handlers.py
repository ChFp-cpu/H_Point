import logging
from html import escape
from aiogram import Bot, F, Router
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from .config import *
from .database import *
from datetime import datetime
from .services import *
from .states import Registration, HelpRequest, ProfileEdit
from .keyboards import *
router=Router()

def tg_uid(telegram_id):
    uid = resolve_user_id(telegram_id)
    return uid if uid is not None else telegram_id
def stars(v): return '—' if v is None else '⭐'*int(round(v))+f' ({v:.1f}/5)'
def profile_text(u):
    s=get_user_stats(u['user_id']); cats=get_helper_categories(u['user_id'])
    return f"👤 <b>{escape(u['name'])}</b>\n💰 <b>{u['balance']} HP</b>\n\n🧠 <b>Навыки:</b> {escape(u['skills'] or 'не указаны')}\n🖼 <b>Портфолио:</b> {escape(u['portfolio'] or 'не указано')}\n\n🤝 Помощей оказано: {s['helped']} · ⭐ {stars(s['helped_avg'])}\n📥 Получено: {s['received']} · ⭐ {stars(s['received_avg'])}\n🛠 Категории: {', '.join(CATEGORIES[c] for c in cats) if cats else 'любые'}"
def request_text(r): return f"📋 <b>Заявка №{r['id']}</b>\n<b>{escape(r['what'])}</b>\n📍 {escape(r['place'])}\n🕒 {escape(r['time_needed'])}\n{escape(r['urgency'])}\n🛠 Требуются навыки: {escape(r['required_skills'] or 'не указаны')}\n📝 {escape(r['details'])}"
def user_card(u): return f"👤 <b>{escape(u['name'])}</b>\n🧠 Навыки: {escape(u['skills'] or 'не указаны')}\n🖼 Портфолио: {escape(u['portfolio'] or 'не указано')}"
async def ensure(message,state):
    if get_user_by_telegram(message.from_user.id) is None and get_user(message.from_user.id) is None: await state.set_state(Registration.name); await message.answer('Сначала зарегистрируемся. Как вас зовут?'); return False
    return True
async def notify_user(bot,uid,text,markup=None):
    u=get_user(uid)
    if u and u['telegram_id']:
        try: await bot.send_message(u['telegram_id'],text,reply_markup=markup)
        except Exception: logging.exception('notify failed')
@router.message(Command('link'))
async def link_account(m,state):
    parts=(m.text or '').split()
    if len(parts)!=2 or not parts[1].isdigit() or len(parts[1])!=6:
        return await m.answer('Формат: /link 123456')
    if get_user_by_telegram(m.from_user.id) is None and get_user(m.from_user.id) is None:
        return await m.answer('Сначала отправьте /start и создайте Telegram-профиль.')
    token=get_link_token(parts[1])
    if not token:
        return await m.answer('Код не найден или уже истёк. Получите новый код на сайте.')
    ok=link_accounts(token['web_user_id'],m.from_user.id,m.from_user.username)
    consume_link_token(parts[1])
    await state.clear()
    if ok:
        u=get_user(tg_uid(m.from_user.id))
        await m.answer(f'✅ Сайт и Telegram связаны. Теперь это один профиль.\n\n{profile_text(u)}',reply_markup=main_menu_kb())
    else:
        await m.answer('Не удалось связать профили. Получите новый код на сайте.')

@router.message(CommandStart())
async def start(m,state):
    await state.clear(); u=get_user(tg_uid(m.from_user.id))
    if u is None: await state.set_state(Registration.name); await m.answer('👋 Добро пожаловать в <b>H Point</b>!\n\nКак вас зовут?'); return
    await m.answer(f'С возвращением, {escape(u["name"])}!\n\n{profile_text(u)}',reply_markup=main_menu_kb())
@router.message(Registration.name,F.text)
async def reg_name(m,state):
    name=m.text.strip()
    if not name or len(name)>MAX_NAME_LEN: return await m.answer(f'Имя: 1–{MAX_NAME_LEN} символов.')
    await state.update_data(name=name); await state.set_state(Registration.skills); await m.answer('🧠 Навыки через запятую. Например: Python, ремонт ПК, математика. Можно «нет».',reply_markup=cancel_kb())
@router.message(Registration.skills,F.text)
async def reg_skills(m,state): await state.update_data(skills='' if m.text.strip().lower()=='нет' else m.text.strip()); await state.set_state(Registration.portfolio); await m.answer('🖼 Ссылка или короткое описание портфолио. Если нет — «нет».',reply_markup=cancel_kb())
@router.message(Registration.portfolio,F.text)
async def reg_portfolio(m,state):
    d=await state.update_data(portfolio='' if m.text.strip().lower()=='нет' else m.text.strip()); create_user(m.from_user.id,d['name'],m.from_user.username); set_profile(m.from_user.id,d['skills'],d['portfolio']); await state.clear(); await m.answer(f'✅ Профиль создан. Стартовый баланс: <b>{START_BALANCE} HP</b>.',reply_markup=main_menu_kb())
@router.message(Command('cancel'))
@router.message(F.text==BTN_CANCEL)
async def cancel(m,state): await state.clear(); await m.answer('Действие отменено.',reply_markup=main_menu_kb())
@router.message(Command('profile'))
@router.message(StateFilter(None),F.text==BTN_PROFILE)
async def profile(m,state):
    if await ensure(m,state): await m.answer(profile_text(get_user(tg_uid(m.from_user.id))),reply_markup=profile_kb())
@router.callback_query(F.data=='profile:edit')
async def profile_edit(c,state): await c.answer(); await state.set_state(ProfileEdit.skills); await c.message.answer('🧠 Напишите ваши навыки через запятую:')
@router.message(ProfileEdit.skills,F.text)
async def edit_skills(m,state): await state.update_data(skills=m.text.strip()); await state.set_state(ProfileEdit.portfolio); await m.answer('🖼 Ссылка или описание портфолио:')
@router.message(ProfileEdit.portfolio,F.text)
async def edit_portfolio(m,state):
    d=await state.update_data(portfolio=m.text.strip()); set_profile(tg_uid(m.from_user.id),d['skills'],d['portfolio']); await state.clear(); await m.answer('✅ Профиль обновлён.',reply_markup=main_menu_kb())
@router.message(Command('history'))
@router.message(StateFilter(None),F.text==BTN_HISTORY)
async def history(m,state):
    if not await ensure(m,state): return
    rows=get_history(tg_uid(m.from_user.id),HISTORY_LIMIT); await m.answer('📜 История пока пуста.' if not rows else '\n\n'.join(f"№{r['id']} · {escape(r['what'])}\n{STATUS_TITLES.get(r['status'],r['status'])}" for r in rows),reply_markup=main_menu_kb())
@router.message(Command('settings'))
@router.message(StateFilter(None),F.text==BTN_SETTINGS)
async def settings(m,state):
    if await ensure(m,state): await m.answer('Выберите категории, в которых готовы помогать:',reply_markup=settings_categories_kb(set(get_helper_categories(tg_uid(m.from_user.id)))))
@router.callback_query(F.data=='profile:settings')
async def profile_settings(c): await c.answer(); await c.message.answer('Выберите категории:',reply_markup=settings_categories_kb(set(get_helper_categories(tg_uid(c.from_user.id)))))
@router.callback_query(F.data.startswith('setcat:'))
async def setcat(c):
    a=c.data.split(':',1)[1]; selected=set(get_helper_categories(tg_uid(c.from_user.id)))
    if a=='save': await c.answer('Сохранено'); await c.message.edit_text('✅ Категории сохранены.'); return
    if a in selected:selected.remove(a)
    elif a in CATEGORIES:selected.add(a)
    set_helper_categories(tg_uid(c.from_user.id),list(selected)); await c.answer('Изменено'); await c.message.edit_reply_markup(reply_markup=settings_categories_kb(selected))
@router.message(StateFilter(None),F.text==BTN_NEED_HELP)
async def need(m,state):
    if not await ensure(m,state): return
    if get_in_progress_task(tg_uid(m.from_user.id)): return await m.answer('Сначала завершите текущую активную задачу.')
    u=get_user(tg_uid(m.from_user.id))
    if u['balance']<REQUEST_COST: return await m.answer(f'Нужно минимум {REQUEST_COST} HP. У вас {u["balance"]}.')
    await state.set_state(HelpRequest.what); await m.answer('1/6. Какая помощь нужна?',reply_markup=cancel_kb())
async def text_answer(m):
    if not m.text:return None
    x=m.text.strip(); return x if x and len(x)<=MAX_TEXT_LEN else None
@router.message(HelpRequest.what)
async def q1(m,state):
    x=await text_answer(m)
    if x is None:return await m.answer('Нужен короткий текст.')
    await state.update_data(what=x); await state.set_state(HelpRequest.place); await m.answer('2/6. Где нужна помощь?')
@router.message(HelpRequest.place)
async def q2(m,state):
    x=await text_answer(m)
    if x is None:return await m.answer('Нужен короткий текст.')
    await state.update_data(place=x); await state.set_state(HelpRequest.time_needed); await m.answer('3/6. Когда?')
@router.message(HelpRequest.time_needed)
async def q3(m,state):
    x=await text_answer(m)
    if x is None:return await m.answer('Нужен короткий текст.')
    await state.update_data(time_needed=x); await state.set_state(HelpRequest.urgency); await m.answer('4/6. Срочность:',reply_markup=cancel_kb(URGENCY_OPTIONS))
@router.message(HelpRequest.urgency)
async def q4(m,state):
    x=await text_answer(m)
    if x is None:return await m.answer('Выберите или напишите срочность.')
    await state.update_data(urgency=x); await state.set_state(HelpRequest.details); await m.answer('5/6. Дополнительные детали. Если нет — «Нет».')
@router.message(HelpRequest.details)
async def q5(m,state):
    x=await text_answer(m)
    if x is None:return await m.answer('Напишите детали или «Нет».')
    await state.update_data(details='Нет дополнительных деталей' if x=='Нет' else x); await state.set_state(HelpRequest.required_skills); await m.answer('6/6. Какие навыки нужны? Через запятую. Если специальных навыков не нужно — «нет».')
@router.message(HelpRequest.required_skills)
async def q6(m,state):
    x=await text_answer(m)
    if x is None:return await m.answer('Напишите навыки или «нет».')
    d=await state.update_data(required_skills='' if x.lower()=='нет' else x); await state.clear(); rid=create_request(tg_uid(m.from_user.id),d); await m.answer(f'✅ Заявка создана. Теперь вы сами выбираете помощника из откликнувшихся.\n\n{request_text(get_request(rid))}',reply_markup=cancel_request_kb(rid))
@router.message(StateFilter(None),F.text==BTN_WANT_HELP)
async def want(m,state):
    if not await ensure(m,state):return
    if get_in_progress_task(tg_uid(m.from_user.id)): return await m.answer('Сначала завершите текущую активную задачу.')
    rows=get_open_requests_for_helper(tg_uid(m.from_user.id),5)
    if not rows:return await m.answer('Пока открытых заявок нет.',reply_markup=main_menu_kb())
    for r in rows:
        requester=get_user(r['requester_id'])
        await m.answer(request_text(r)+f'\n\n👤 <b>Автор заявки:</b>\n{user_card(requester)}',reply_markup=request_card_kb(r['id']))
@router.callback_query(F.data.startswith('apply:'))
async def apply(c,bot):
    rid=int(c.data.split(':')[1]); ok=apply_to_request(rid,tg_uid(c.from_user.id)); await c.answer('Отклик отправлен!' if ok else 'Нельзя откликнуться.',show_alert=not ok)
    if ok:
        await c.message.edit_reply_markup(reply_markup=None)
@router.message(StateFilter(None),F.text==BTN_CANDIDATES)
async def candidates(m,state):
    if not await ensure(m,state):return
    c=db_connect(); rows=c.execute('SELECT * FROM requests WHERE requester_id=? AND status=? ORDER BY id DESC LIMIT 10',(tg_uid(m.from_user.id),STATUS_OPEN)).fetchall(); c.close(); found=False
    for r in rows:
        cs=get_candidates(r['id'])
        if cs:
            found=True; await m.answer(f'📋 <b>Заявка №{r["id"]}</b> · {escape(r["what"])}')
            for a in cs: await m.answer(user_card(a),reply_markup=candidate_kb(a['id']))
    if not found: await m.answer('Новых кандидатов пока нет.',reply_markup=main_menu_kb())
@router.callback_query(F.data.startswith('cand_accept:'))
async def cand_accept(c,bot):
    aid=int(c.data.split(':')[1]); result=decide_application(aid,tg_uid(c.from_user.id),True)
    if not result:return await c.answer('Кандидата уже нельзя выбрать.',show_alert=True)
    await c.answer('Кандидат выбран!'); await c.message.edit_reply_markup(reply_markup=None)
@router.callback_query(F.data.startswith('cand_reject:'))
async def cand_reject(c):
    r=decide_application(int(c.data.split(':')[1]),tg_uid(c.from_user.id),False); await c.answer('Кандидат отсеян.' if r else 'Уже обработано.'); await c.message.edit_reply_markup(reply_markup=None)
@router.message(StateFilter(None),F.text==BTN_MY_OFFERS)
async def offers(m,state):
    if not await ensure(m,state):return
    rows=get_my_applications(tg_uid(m.from_user.id))
    if not rows:return await m.answer('У вас пока нет откликов.')
    for a in rows: await m.answer(f'📨 Заявка №{a["request_id"]} · {escape(a["what"])}\nСтатус: {a["status"]}\n\n👤 Автор:\n{user_card(a)}',reply_markup=offer_kb(a['id']) if a['status']==APP_PENDING else None)
@router.callback_query(F.data.startswith('offer_reject:'))
async def offer_reject(c): await c.answer('Отклик отозван.' if reject_application(int(c.data.split(':')[1]),tg_uid(c.from_user.id)) else 'Отклик уже обработан.'); await c.message.edit_reply_markup(reply_markup=None)
@router.callback_query(F.data.startswith('boost:'))
async def boost(c):
    ok,msg=boost_request(int(c.data.split(':')[1]),tg_uid(c.from_user.id)); await c.answer(msg,show_alert=not ok)
@router.callback_query(F.data.startswith('cancel_req:'))
async def cancel_cb(c): await c.answer('Отменено.' if cancel_request(int(c.data.split(':')[1]),tg_uid(c.from_user.id)) else 'Нельзя отменить.',show_alert=True); await c.message.edit_reply_markup(reply_markup=None)
@router.callback_query(F.data.startswith('finish:'))
async def finish(c):
    rid=int(c.data.split(':')[1]); ok=complete_request(rid,tg_uid(c.from_user.id)); await c.answer('Помощь завершена!' if ok else 'Не удалось завершить.',show_alert=not ok)
    if ok: await c.message.edit_reply_markup(reply_markup=rating_kb(rid,'ratehelp'))
@router.callback_query(F.data.startswith('rate:'))
async def rate_req(c):
    _,rid,n=c.data.split(':'); await c.answer('Спасибо за оценку!' if set_rating(int(rid),tg_uid(c.from_user.id),int(n),'requester') else 'Уже оценено.')
@router.callback_query(F.data.startswith('ratehelp:'))
async def rate_help(c):
    _,rid,n=c.data.split(':'); await c.answer('Спасибо!' if set_rating(int(rid),tg_uid(c.from_user.id),int(n),'helper') else 'Уже оценено.')
@router.callback_query()
async def unknown(c): await c.answer('Эта кнопка устарела.',show_alert=True)
@router.message(StateFilter(None))
async def fallback(m): await m.answer('Выберите действие в меню.',reply_markup=main_menu_kb())
