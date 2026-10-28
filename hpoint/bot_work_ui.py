"""A few work actions in Telegram; the full workspace stays on the website."""
from html import escape
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from . import work_bot
from .config import WEB_PUBLIC_URL


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


def button(text, action):
    return InlineKeyboardButton(text=text,callback_data="work:"+action)


def date(value):
    if not value:return "без срока"
    return work_bot.commercial._date(value).astimezone(work_bot.MOSCOW).strftime("%d.%m · %H:%M МСК")


def view(db,uid,owner=None,section="overview"):
    data=work_bot.agenda(db,uid,owner);org=data["organization"];owner=org["owner_id"]
    text="💼 <b>"+escape(str(org["title"])[:120])+"</b>\n"
    rows=[]
    if section=="tasks":
        text+="\n<b>Ближайшие задачи</b>\n"
        if not data["tasks"]:text+="Задач пока нет."
        for item in data["tasks"]:
            text+="\n• "+escape(item["title"])+"\n"+date(item["scheduled_at"])+"\n"
            rows.append([button("✓ "+item["title"][:42],"confirm:task:"+str(owner)+":"+str(item["id"]))])
    else:
        text+="\n<b>Ближайшие записи</b>\n"
        if not data["bookings"]:text+="Записей на ближайшую неделю нет.\n"
        for item in data["bookings"]:
            text+="\n• "+escape(item["title"])+"\n"+date(item["scheduled_at"])+"\n"
            rows.append([button("✓ "+item["title"][:42],"confirm:booking:"+str(owner)+":"+str(item["id"]))])
        if data["shifts"]:
            text+="\n<b>Смены</b>\n"+"\n".join("• "+escape(item["title"])+" · "+date(item["scheduled_at"]) for item in data["shifts"][:3])
        text+="\n\nЗадач в списке: "+str(len(data["tasks"]))
    rows.append([button("Ближайшее","org:"+str(owner)),button("Задачи","tasks:"+str(owner))])
    pref=data["preferences"]
    rows.append([button("Напоминания: "+("включены" if pref["enabled"] else "выключены"),"settings:"+str(owner))])
    rows.append([InlineKeyboardButton(text="Все инструменты на сайте →",url=work_bot.website(owner,"tasks" if section=="tasks" else "overview"))])
    if len(work_bot.paid_organizations(db,uid))>1:rows.append([button("Другая организация","list")])
    return text,keyboard(rows)


def selection(db,uid):
    orgs=work_bot.paid_organizations(db,uid)
    if len(orgs)==1:return view(db,uid,orgs[0]["owner_id"])
    return "💼 <b>Для работы</b>\n\nВыберите оплаченный кабинет.",keyboard([[button(str(org["title"])[:60],"org:"+str(org["owner_id"]))] for org in orgs])


def settings_view(db,uid,owner):
    work_bot.organization(db,uid,owner)
    pref=work_bot.preferences(db,uid)
    text=("🔔 <b>Рабочие напоминания</b>\n\n"+("Включены за "+str(pref["lead_minutes"])+" минут." if pref["enabled"] else "Сейчас выключены.")
          +"\nДля всех ваших оплаченных кабинетов: записи, смены и задачи, назначенные вам. Владелец также получает напоминания по записям без ответственного. Время указано по Москве.\n\nЛичные показатели и внутренние заметки в Telegram не отправляются.")
    rows=[[button("За 15 минут","reminders:15:"+str(owner)),button("За 1 час","reminders:60:"+str(owner))],
          [button("Выключить","reminders:off:"+str(owner))],[button("Назад","org:"+str(owner))]]
    return text,keyboard(rows)


async def handle_event(event,state_data,user,db):
    callback=isinstance(event,CallbackQuery)
    text=str(getattr(event,"text","") or "")
    command=text.split(maxsplit=1)[0].split("@",1)[0] if text else ""
    action=str(getattr(event,"data","") or "")
    if not ((callback and action.startswith("work:")) or (not callback and (text==work_bot.WORK_BUTTON or command in ("/work","/commercial")))):
        return False
    message=event.message if callback else event
    if not message or message.chat.type!="private" or user["tg_user_id"]!=event.from_user.id:
        if callback:await event.answer("Откройте личный чат привязанного бота.",show_alert=True)
        elif message:await message.answer("Для управления работой откройте личный чат привязанного бота.")
        return True
    uid=user["user_id"]
    state=state_data.get("state")
    if state:await state.clear()
    if callback and action.split(":")[:3]==["work","reminders","off"] and not work_bot.has_paid_access(db,uid):
        work_bot.disable_reminders(db,uid)
        await event.answer("Напоминания отключены")
        from .keyboards import main_menu_kb
        await message.answer("Рабочие напоминания отключены.",reply_markup=main_menu_kb())
        return True
    if not work_bot.has_paid_access(db,uid):
        if callback:await event.answer("Нужна действующая оплата кабинета «Для работы».",show_alert=True)
        from .keyboards import main_menu_kb
        await message.answer("Управление работой в боте доступно участникам оплаченного кабинета «Для работы». Пробный период и PRO этот раздел не открывают.",reply_markup=main_menu_kb())
        await message.answer("Кабинет и подписка — на сайте.",reply_markup=keyboard([[InlineKeyboardButton(text="Открыть «Для работы»",url=WEB_PUBLIC_URL.rstrip("/")+"/#/work")]]))
        return True
    try:
        if not callback or action=="work:list":result=selection(db,uid)
        else:
            parts=action.split(":");verb=parts[1]
            if verb in ("org","tasks","settings") and len(parts)==3:
                owner=work_bot.commercial._user_id(parts[2])
                result=settings_view(db,uid,owner) if verb=="settings" else view(db,uid,owner,"tasks" if verb=="tasks" else "overview")
            elif verb=="reminders" and len(parts) in (3,4):
                option=parts[2]
                org=work_bot.organization(db,uid,parts[3] if len(parts)==4 else None)
                if option not in ("off","15","60"):raise ValueError("Неизвестная настройка.")
                work_bot.set_preferences(db,uid,option!="off",int(option) if option!="off" else work_bot.preferences(db,uid)["lead_minutes"])
                result=settings_view(db,uid,org["owner_id"])
            elif verb in ("confirm","done") and len(parts)==5:
                kind,owner,item=parts[2],work_bot.commercial._user_id(parts[3]),work_bot.commercial._integer(parts[4],1,2**63-1)
                if kind not in ("booking","task"):raise ValueError("Откройте это действие на сайте.")
                data=work_bot.agenda(db,uid,owner)
                row=next((row for row in data["tasks" if kind=="task" else "bookings"] if row["id"]==item),None)
                if verb=="confirm":
                    if not row:raise ValueError("Запись изменилась. Обновите список.")
                    result=("Отметить выполненным?\n\n<b>"+escape(row["title"])+"</b>\nДенежных операций не будет.",keyboard([[button("Да, выполнено","done:"+kind+":"+str(owner)+":"+str(item))],[button("Назад",("tasks:" if kind=="task" else "org:")+str(owner))]]))
                else:
                    work_bot.complete_item(db,uid,owner,kind,item)
                    result=view(db,uid,owner,"tasks" if kind=="task" else "overview")
            else:raise ValueError("Обновите рабочее меню.")
        if callback:await event.answer()
        # New messages keep the context of an explicit completion confirmation.
        await message.answer(result[0],reply_markup=result[1])
    except (ValueError,PermissionError) as error:
        if callback:await event.answer(str(error)[:180],show_alert=True)
        else:await message.answer(str(error))
    return True
