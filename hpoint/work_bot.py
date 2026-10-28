"""Small paid-work Telegram companion. No clinical or private CRM payloads."""
from datetime import datetime, timedelta, timezone
from html import escape
import asyncio
import logging

from . import commercial
from .config import WEB_PUBLIC_URL

WORK_BUTTON = "💼 Для работы"
MOSCOW = timezone(timedelta(hours=3), "МСК")
ITEMS = {"booking": ("commercial_bookings", "starts_at", "planned", "completed"),
         "task": ("commercial_tasks", "due_at", None, "done"),
         "shift": ("commercial_shifts", "starts_at", None, None)}


def initialize_schema(db):
    schema="""
    CREATE TABLE IF NOT EXISTS work_bot_preferences(
      user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
      reminders_enabled INTEGER NOT NULL DEFAULT 0,lead_minutes INTEGER NOT NULL DEFAULT 60,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS work_bot_reminders(
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      item_type TEXT NOT NULL,item_id INTEGER NOT NULL,scheduled_at TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'claimed',attempts INTEGER NOT NULL DEFAULT 1,
      claimed_at TEXT NOT NULL,sent_at TEXT,
      PRIMARY KEY(user_id,owner_id,item_type,item_id,scheduled_at)
    );
    """
    if getattr(db,"is_postgres",False):schema=schema.replace("INTEGER","BIGINT")
    db.executescript(schema)


def now():
    return datetime.now(timezone.utc)


def paid_organizations(db, uid, at=None):
    at = at or now()
    actor = db.execute("SELECT email,email_verified,is_blocked,tg_user_id FROM users WHERE user_id=?",(uid,)).fetchone()
    if not actor or actor["is_blocked"] or not actor["email_verified"] or not actor["email"] or not actor["tg_user_id"]:
        return []
    rows = db.execute("""SELECT p.user_id owner_id,p.title,p.paid_until,
        CASE WHEN p.user_id=? THEN 'owner' ELSE m.role END member_role
        FROM commercial_profiles p JOIN users u ON u.user_id=p.user_id
        LEFT JOIN commercial_members m ON m.owner_id=p.user_id AND m.user_id=?
        WHERE (p.user_id=? OR m.user_id=?) AND p.paid_until IS NOT NULL
        AND u.is_blocked=0 AND u.email_verified=1
        AND NOT EXISTS(SELECT 1 FROM commercial_deleted_profiles d WHERE d.user_id=p.user_id)
        ORDER BY p.title,p.user_id""",(uid,uid,uid,uid)).fetchall()
    result=[]
    for row in rows:
        try:active=commercial._date(row["paid_until"])>at
        except (ValueError,TypeError):active=False
        if active:result.append(dict(row))
    return result


def has_paid_access(db, uid):
    return bool(uid is not None and paid_organizations(db,uid))


def organization(db, uid, owner_id=None, at=None):
    rows=paid_organizations(db,uid,at)
    owner_id=commercial._user_id(owner_id) if owner_id is not None else None
    selected=next((row for row in rows if row["owner_id"]==owner_id),None) if owner_id is not None else next(iter(rows),None)
    if not selected:raise PermissionError("Раздел доступен участникам оплаченного кабинета «Для работы».")
    return selected


def preferences(db, uid):
    row=db.execute("SELECT reminders_enabled,lead_minutes FROM work_bot_preferences WHERE user_id=?",(uid,)).fetchone()
    return {"enabled":bool(row["reminders_enabled"]) if row else False,"lead_minutes":int(row["lead_minutes"]) if row else 60}


def set_preferences(db, uid, enabled, lead_minutes=60):
    if not isinstance(enabled,bool) or isinstance(lead_minutes,bool) or lead_minutes not in (15,60):
        raise ValueError("Выберите напоминания за 15 или 60 минут.")
    db.execute("BEGIN IMMEDIATE")
    try:
        organization(db,uid)
        db.execute("INSERT OR IGNORE INTO work_bot_preferences(user_id) VALUES(?)",(uid,))
        db.execute("UPDATE work_bot_preferences SET reminders_enabled=?,lead_minutes=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",(int(enabled),lead_minutes,uid))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK");raise
    return preferences(db,uid)


def disable_reminders(db, uid):
    """An opt-out from an old reminder must also work after paid access ends."""
    commercial._user(db,uid)
    db.execute("UPDATE work_bot_preferences SET reminders_enabled=0,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",(uid,))


def website(owner_id, section="overview"):
    if section not in {"overview","bookings","tasks","subscription"}:section="overview"
    return WEB_PUBLIC_URL.rstrip("/")+"/#/work/"+str(int(owner_id))+"/"+section


def _visible_item(row, uid, role):
    return role in ("owner","admin") or row["assignee_id"]==uid


def agenda(db, uid, owner_id=None, at=None):
    at=at or now();org=organization(db,uid,owner_id,at);owner=org["owner_id"]
    result={"organization":org,"preferences":preferences(db,uid),"bookings":[],"tasks":[],"shifts":[]}
    for kind,(table,field,_,_) in ITEMS.items():
        status=" AND status='planned'" if kind=="booking" else " AND status IN ('todo','in_progress')" if kind=="task" else ""
        scope="" if org["member_role"] in ("owner","admin") else " AND assignee_id=?"
        params=[owner]+([] if not scope else [uid])
        if kind=="task":
            window=" AND ("+field+" IS NULL OR "+field+"<=?)";params.append((at+timedelta(days=7)).isoformat())
            ordering="CASE WHEN "+field+" IS NULL THEN 1 ELSE 0 END,"+field+",id"
        else:
            window=" AND "+field+">=? AND "+field+"<=?";params.extend([at.isoformat(),(at+timedelta(days=7)).isoformat()]);ordering=field+",id"
        rows=db.execute("SELECT id,title,assignee_id,"+field+" scheduled_at FROM "+table+" WHERE owner_id=?"+status+scope+window+" ORDER BY "+ordering+" LIMIT 5",tuple(params)).fetchall()
        visible=[]
        for row in rows:
            if not _visible_item(row,uid,org["member_role"]):continue
            if row["scheduled_at"]:
                try:date=commercial._date(row["scheduled_at"])
                except (ValueError,TypeError):continue
                if date>at+timedelta(days=7) or (date<at and kind!="task"):continue
            else:
                if kind!="task":continue
            visible.append({"id":row["id"],"title":str(row["title"])[:160],"scheduled_at":row["scheduled_at"],"mine":row["assignee_id"] in (uid,None)})
        result[{"booking":"bookings","task":"tasks","shift":"shifts"}[kind]]=visible[:5]
    return result


def complete_item(db, uid, owner_id, kind, item_id):
    if kind not in ("task","booking"):raise ValueError("Это действие доступно на сайте.")
    item_id=commercial._integer(item_id,1,2**63-1);owner_id=commercial._user_id(owner_id)
    table=ITEMS[kind][0]
    db.execute("BEGIN IMMEDIATE")
    try:
        org=organization(db,uid,owner_id)
        commercial._context(db,uid,owner_id,lock=True)
        org=organization(db,uid,owner_id)
        row=commercial._owned(db,table,owner_id,item_id)
        if not _visible_item(row,uid,org["member_role"]):raise PermissionError("Можно отмечать только свои рабочие записи.")
        target=ITEMS[kind][3]
        if row["status"] in ("cancelled",):raise ValueError("Отменённую запись нельзя завершить.")
        changed=row["status"]!=target
        if changed:db.execute("UPDATE "+table+" SET status=?,updated_at=CURRENT_TIMESTAMP WHERE owner_id=? AND id=?",(target,owner_id,item_id))
        db.execute("COMMIT")
        return {"changed":changed,"title":str(row["title"])[:160]}
    except Exception:
        db.execute("ROLLBACK");raise


def _reminder_item(db, uid, owner, kind, item_id, scheduled, at, lead):
    if kind not in ITEMS:return None
    table,field,_,_=ITEMS[kind]
    row=db.execute("SELECT * FROM "+table+" WHERE id=? AND owner_id=?",(item_id,owner)).fetchone()
    if not row or row[field]!=scheduled:return None
    if kind=="booking" and row["status"]!="planned":return None
    if kind=="task" and row["status"] not in ("todo","in_progress"):return None
    if row["assignee_id"]!=uid and not (owner==uid and row["assignee_id"] is None):return None
    try:moment=commercial._date(scheduled)
    except (ValueError,TypeError):return None
    return row if at<moment<=at+timedelta(minutes=lead) else None


def claim_reminder(db, uid, owner, kind, item_id, scheduled, at=None):
    at=at or now()
    db.execute("BEGIN IMMEDIATE")
    try:
        commercial._context(db,uid,owner,lock=True)
        org=organization(db,uid,owner,at)
        pref=preferences(db,uid)
        user=db.execute("SELECT tg_user_id FROM users WHERE user_id=?",(uid,)).fetchone()
        item=_reminder_item(db,uid,owner,kind,item_id,scheduled,at,pref["lead_minutes"])
        if not pref["enabled"] or not user["tg_user_id"] or not item:
            db.execute("COMMIT");return None
        prior=db.execute("SELECT status,attempts,claimed_at FROM work_bot_reminders WHERE user_id=? AND owner_id=? AND item_type=? AND item_id=? AND scheduled_at=?",(uid,owner,kind,item_id,scheduled)).fetchone()
        if prior and (prior["status"]=="sent" or prior["attempts"]>=3 or commercial._date(prior["claimed_at"])+timedelta(minutes=3)>at):
            db.execute("COMMIT");return None
        if prior:
            db.execute("UPDATE work_bot_reminders SET status='claimed',attempts=attempts+1,claimed_at=? WHERE user_id=? AND owner_id=? AND item_type=? AND item_id=? AND scheduled_at=?",(at.isoformat(),uid,owner,kind,item_id,scheduled))
        else:db.execute("INSERT INTO work_bot_reminders(user_id,owner_id,item_type,item_id,scheduled_at,claimed_at) VALUES(?,?,?,?,?,?)",(uid,owner,kind,item_id,scheduled,at.isoformat()))
        db.execute("COMMIT")
        return {"user_id":uid,"owner_id":owner,"kind":kind,"item_id":item_id,"scheduled_at":scheduled,"telegram_id":user["tg_user_id"],"title":str(item["title"])[:160],"organization_title":org["title"]}
    except (PermissionError,ValueError):
        db.execute("ROLLBACK");return None
    except Exception:
        db.execute("ROLLBACK");raise


def collect_reminders(db, at=None, limit=30):
    at=at or now();jobs=[]
    users=db.execute("""SELECT p.user_id,p.lead_minutes FROM work_bot_preferences p JOIN users u ON u.user_id=p.user_id
        WHERE p.reminders_enabled=1 AND u.tg_user_id IS NOT NULL AND u.is_blocked=0 AND u.email_verified=1""").fetchall()
    for user in users:
        uid=user["user_id"]
        for org in paid_organizations(db,uid,at):
            owner=org["owner_id"]
            for kind,(table,field,_,_) in ITEMS.items():
                rows=db.execute("SELECT id,"+field+" scheduled_at FROM "+table+" WHERE owner_id=? AND "+field+" IS NOT NULL AND "+field+">? AND "+field+"<=? AND (assignee_id=? OR (assignee_id IS NULL AND owner_id=?)) ORDER BY "+field+",id LIMIT 30",(owner,at.isoformat(),(at+timedelta(minutes=user["lead_minutes"])).isoformat(),uid,uid)).fetchall()
                for row in rows:
                    job=claim_reminder(db,uid,owner,kind,row["id"],row["scheduled_at"],at)
                    if job:jobs.append(job)
                    if len(jobs)>=limit:return jobs
    return jobs


def finish_reminder(db, job, sent):
    try:db.execute("UPDATE work_bot_reminders SET status=?,sent_at=? WHERE user_id=? AND owner_id=? AND item_type=? AND item_id=? AND scheduled_at=?",("sent" if sent else "failed",now().isoformat() if sent else None,job["user_id"],job["owner_id"],job["kind"],job["item_id"],job["scheduled_at"]))
    finally:
        if hasattr(db,"is_postgres"):db.close()


def reminder_text(job):
    label={"booking":"Запись","task":"Задача","shift":"Смена"}[job["kind"]]
    stamp=commercial._date(job["scheduled_at"]).astimezone(MOSCOW).strftime("%d.%m · %H:%M МСК")
    return "💼 <b>"+escape(label)+" скоро</b>\n"+escape(str(job["organization_title"])[:120])+"\n\n"+escape(job["title"])+"\n"+stamp


async def deliver_reminders(bot, db):
    def collect():
        try:return collect_reminders(db)
        finally:
            if hasattr(db,"is_postgres"):db.close()
    jobs=await asyncio.to_thread(collect)
    for job in jobs:
        # Access and link are rechecked immediately before sending, too.
        def still_allowed():
            try:
                org=organization(db,job["user_id"],job["owner_id"])
                user=db.execute("SELECT tg_user_id FROM users WHERE user_id=?",(job["user_id"],)).fetchone()
                return bool(org and preferences(db,job["user_id"])["enabled"] and user["tg_user_id"]==job["telegram_id"] and _reminder_item(db,job["user_id"],job["owner_id"],job["kind"],job["item_id"],job["scheduled_at"],now(),preferences(db,job["user_id"])["lead_minutes"]))
            except (PermissionError,ValueError):return False
            finally:
                if hasattr(db,"is_postgres"):db.close()
        if not await asyncio.to_thread(still_allowed):
            await asyncio.to_thread(finish_reminder,db,job,True);continue
        try:
            from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
            section="tasks" if job["kind"]=="task" else "bookings"
            await bot.send_message(job["telegram_id"],reminder_text(job),reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть на сайте",url=website(job["owner_id"],section))],[InlineKeyboardButton(text="Отключить напоминания",callback_data="work:reminders:off")]]))
        except Exception:
            logging.warning("Work reminder delivery failed")
            await asyncio.to_thread(finish_reminder,db,job,False)
        else:await asyncio.to_thread(finish_reminder,db,job,True)


async def reminder_loop(bot, db):
    while True:
        try:await deliver_reminders(bot,db)
        except asyncio.CancelledError:raise
        except Exception:logging.exception("Work reminders maintenance failed")
        await asyncio.sleep(30)
