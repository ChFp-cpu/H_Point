"""Private service inquiries and explicit, transactional CRM conversion.

An inquiry is neither a public help request nor a payment. Only the contact
entered by its author is shared. All writes serialize on the organisation owner.
"""
import base64
import hashlib
import json
import re
import uuid
from datetime import timedelta

from . import commercial as c, commercial_team as team, media

STATUSES = ("new", "in_progress", "accepted", "rejected", "cancelled")
OPEN = ("new", "in_progress")


def initialize_schema(db):
    integer = "BIGINT" if getattr(db, "is_postgres", False) else "INTEGER"
    primary = "BIGSERIAL PRIMARY KEY" if getattr(db, "is_postgres", False) else "INTEGER PRIMARY KEY AUTOINCREMENT"
    db.execute(f"""CREATE TABLE IF NOT EXISTS commercial_inquiries(
        id {primary}, owner_id {integer} NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
        service_id {integer} REFERENCES commercial_services(id) ON DELETE SET NULL,
        author_id {integer} NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
        author_name TEXT NOT NULL, organization_title TEXT NOT NULL, organization_slug TEXT NOT NULL,
        service_title TEXT NOT NULL, price_rub {integer} NOT NULL, duration_minutes {integer} NOT NULL,
        message TEXT NOT NULL, preferred_time TEXT NOT NULL DEFAULT '', contact TEXT NOT NULL,
        request_key TEXT NOT NULL, payload_hash TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'service_page',
        status TEXT NOT NULL DEFAULT 'new', reply TEXT NOT NULL DEFAULT '',
        assignee_id {integer} REFERENCES users(user_id) ON DELETE SET NULL,
        client_id {integer} REFERENCES commercial_clients(id) ON DELETE SET NULL,
        booking_id {integer} REFERENCES commercial_bookings(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, accepted_at TEXT,
        UNIQUE(author_id,request_key))""")
    db.execute(f"""CREATE TABLE IF NOT EXISTS commercial_inquiry_photos(
        id TEXT PRIMARY KEY, inquiry_id {integer} NOT NULL REFERENCES commercial_inquiries(id) ON DELETE CASCADE,
        mime TEXT NOT NULL, content_base64 TEXT NOT NULL, width {integer} NOT NULL, height {integer} NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_inquiries_owner_status ON commercial_inquiries(owner_id,status,id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_inquiries_author ON commercial_inquiries(author_id,id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_inquiries_assignee ON commercial_inquiries(owner_id,assignee_id,status)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_inquiry_photos_parent ON commercial_inquiry_photos(inquiry_id)")


def erase_workspace(db, owner):
    db.execute("DELETE FROM commercial_inquiries WHERE owner_id=?", (owner,))


def _id(value):
    return c._integer(value, 1, 2**63 - 1)


def _data(data):
    if not isinstance(data, dict):
        raise ValueError("Проверьте данные обращения.")
    return data


def _service(db, service_id):
    row = db.execute("""SELECT s.*,p.title organization_title,p.kind,p.trial_until,p.paid_until,
        v.slug organization_slug FROM commercial_services s
        JOIN commercial_profiles p ON p.user_id=s.owner_id
        JOIN commercial_public_profiles v ON v.owner_id=p.user_id
        JOIN users u ON u.user_id=p.user_id
        WHERE s.id=? AND s.active=1 AND s.published=1 AND v.published=1
        AND u.is_blocked=0 AND u.email_verified=1
        AND NOT EXISTS(SELECT 1 FROM commercial_deleted_profiles d WHERE d.user_id=p.user_id)""", (service_id,)).fetchone()
    if not row or c._until(row) <= c._now():
        raise ValueError("Услуга сейчас недоступна для новых обращений.")
    return row


def public_service(db, service_id):
    row = _service(db, _id(service_id))
    return {**team._service_public(row), "organization_title": row["organization_title"],
            "organization_kind": row["kind"], "organization_slug": row["organization_slug"],
            "organization_url": "/organizations/" + row["organization_slug"]}


def _raw(db, item_id):
    row = db.execute("SELECT * FROM commercial_inquiries WHERE id=?", (_id(item_id),)).fetchone()
    if not row:
        raise ValueError("Обращение не найдено.")
    return row


def _scope(db, uid, row, owner_id=None):
    c._user(db, uid)
    if row["author_id"] == uid and owner_id is None:
        return "author", False
    owner, profile, role = c._context(db, uid, owner_id if owner_id is not None else row["owner_id"])
    if owner != row["owner_id"] or not profile:
        raise PermissionError("Нет доступа к этому обращению.")
    if role not in ("owner", "admin") and row["assignee_id"] != uid:
        raise PermissionError("Обращение доступно назначенному сотруднику и руководителям.")
    return role, c._until(profile) > c._now()


def _shape(db, uid, row, role, active):
    result = {key: row[key] for key in ("id", "owner_id", "service_id", "author_id", "author_name",
        "organization_title", "organization_slug", "service_title", "price_rub", "duration_minutes",
        "message", "preferred_time", "contact", "status", "reply", "created_at", "updated_at", "accepted_at")}
    manager = role in ("owner", "admin")
    result.update(currency="TEST_RUB", access_active=active, can_cancel=role == "author" and row["status"] in OPEN,
        can_update=role != "author" and active and row["status"] in OPEN,
        can_convert=manager and active and row["status"] in OPEN)
    if role != "author":
        result.update(assignee_id=row["assignee_id"], client_id=row["client_id"], booking_id=row["booking_id"])
    else:
        # Internal CRM IDs and employee contact details never enter author DTOs.
        result.update(assignee_id=None, client_id=None, booking_id=None)
    person = db.execute("SELECT name FROM users WHERE user_id=?", (row["assignee_id"],)).fetchone() if row["assignee_id"] else None
    result["assignee_name"] = person["name"] if person else ""
    result["photos"] = [dict(id=p["id"], url="/api/work-inquiries/photo?id=" + p["id"], width=p["width"], height=p["height"])
        for p in db.execute("SELECT id,width,height FROM commercial_inquiry_photos WHERE inquiry_id=? ORDER BY id", (row["id"],)).fetchall()]
    booking = db.execute("SELECT title,starts_at,duration_minutes,price_rub,status FROM commercial_bookings WHERE id=? AND owner_id=?", (row["booking_id"], row["owner_id"])).fetchone() if row["booking_id"] else None
    result["booking"] = dict(booking) if booking else None
    return result


def detail(db, uid, item_id, owner_id=None):
    row = _raw(db, item_id)
    role, active = _scope(db, uid, row, owner_id)
    return _shape(db, uid, row, role, active)


def mine(db, uid):
    c._user(db, uid)
    rows = db.execute("SELECT * FROM commercial_inquiries WHERE author_id=? ORDER BY id DESC LIMIT 300", (uid,)).fetchall()
    return [_shape(db, uid, row, "author", False) for row in rows]


def dashboard(db, uid, owner_id=None, include_items=True):
    owner, profile, role = c._context(db, uid, owner_id)
    if not profile:
        return {"inquiries": [], "counts": dict.fromkeys(STATUSES, 0), "incoming_count": 0}
    condition, args = "owner_id=?", [owner]
    if role not in ("owner", "admin"):
        condition += " AND assignee_id=?"
        args.append(uid)
    counts = dict.fromkeys(STATUSES, 0)
    for row in db.execute("SELECT status,COUNT(*) n FROM commercial_inquiries WHERE " + condition + " GROUP BY status", tuple(args)).fetchall():
        counts[row["status"]] = int(row["n"])
    rows = db.execute("SELECT * FROM commercial_inquiries WHERE " + condition + " ORDER BY CASE WHEN status IN ('new','in_progress') THEN 0 ELSE 1 END,id DESC LIMIT 300", tuple(args)).fetchall() if include_items else []
    active = c._until(profile) > c._now()
    return {"inquiries": [_shape(db, uid, row, role, active) for row in rows], "counts": counts,
        "incoming_count": counts["new"] + counts["in_progress"]}


def _lock_users(db, ids):
    suffix = " FOR NO KEY UPDATE" if getattr(db, "is_postgres", False) else ""
    for uid in sorted(set(ids)):
        db.execute("SELECT user_id FROM users WHERE user_id=?" + suffix, (uid,)).fetchone()


def create(db, uid, data):
    data = _data(data)
    user = c._user(db, uid)
    service_id = _id(data.get("service_id"))
    message = c._text(data, "message", 4000, True)
    preferred = c._text(data, "preferred_time", 240)
    contact = c._text(data, "contact", 240, True)
    key = data.get("request_key")
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key):
        raise ValueError("Обновите форму обращения и попробуйте снова.")
    photos = media.prepare_photos(data.get("photos", []))
    fingerprint = hashlib.sha256(json.dumps(dict(service_id=service_id, message=message,
        preferred_time=preferred, contact=contact, photos=[hashlib.sha256(p.content).hexdigest() for p in photos]),
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    # Locate an owner before the transaction; all publication/access checks are
    # repeated after locking, so a withdrawn service cannot accept a new inquiry.
    service = db.execute("SELECT owner_id FROM commercial_services WHERE id=?", (service_id,)).fetchone()
    if not service:
        raise ValueError("Услуга не найдена.")
    db.execute("BEGIN IMMEDIATE")
    try:
        _lock_users(db, (uid, service["owner_id"]))
        user = c._user(db, uid)
        previous = db.execute("SELECT * FROM commercial_inquiries WHERE author_id=? AND request_key=?", (uid, key)).fetchone()
        if previous:
            if previous["payload_hash"] != fingerprint:
                raise ValueError("Этот ключ уже использован для другого обращения.")
            item_id = previous["id"]
        else:
            c._user(db, service["owner_id"])
            c._profile(db, service["owner_id"], lock=True)
            published = _service(db, service_id)
            if db.execute("SELECT COUNT(*) n FROM commercial_inquiries WHERE author_id=? AND status IN ('new','in_progress')", (uid,)).fetchone()["n"] >= 20:
                raise ValueError("У вас уже 20 открытых обращений. Дождитесь ответа или отмените ненужные.")
            if db.execute("SELECT COUNT(*) n FROM commercial_inquiries WHERE owner_id=?", (published["owner_id"],)).fetchone()["n"] >= 10000:
                raise ValueError("Организация временно не принимает новые обращения.")
            now = c._now().isoformat()
            item_id = c._insert_id(db, """INSERT INTO commercial_inquiries(owner_id,service_id,author_id,
                author_name,organization_title,organization_slug,service_title,price_rub,duration_minutes,
                message,preferred_time,contact,request_key,payload_hash,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (published["owner_id"], service_id, uid, user["name"],
                published["organization_title"], published["organization_slug"], published["title"],
                published["price_rub"], published["duration_minutes"], message, preferred, contact, key, fingerprint, now, now))
            for photo in photos:
                db.execute("INSERT INTO commercial_inquiry_photos(id,inquiry_id,mime,content_base64,width,height) VALUES(?,?,?,?,?,?)",
                    (uuid.uuid4().hex, item_id, photo.mime, base64.b64encode(photo.content).decode("ascii"), photo.width, photo.height))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return {"id": item_id, "created": previous is None, "inquiry": detail(db, uid, item_id)}


def update(db, uid, data, owner_id=None):
    data = _data(data)
    item_id = _id(data.get("inquiry_id", data.get("id")))
    def save(owner):
        row = c._owned(db, "commercial_inquiries", owner, item_id)
        role, active = _scope(db, uid, row, owner)
        if row["status"] not in OPEN:
            raise ValueError("Это обращение уже закрыто.")
        status = data.get("status", row["status"])
        if status not in ("new", "in_progress", "rejected"):
            raise ValueError("Для принятия подтвердите клиента и время записи.")
        reply = c._text(data, "reply", 4000) if "reply" in data else row["reply"]
        assigned = row["assignee_id"]
        if "assignee_id" in data:
            next_assignee = team.assignee(db, owner, data["assignee_id"])
            if role not in ("owner", "admin") and next_assignee != assigned:
                raise PermissionError("Назначать сотрудника может руководитель.")
            assigned = next_assignee
        changed = (status, reply, assigned) != (row["status"], row["reply"], row["assignee_id"])
        if changed:
            db.execute("UPDATE commercial_inquiries SET status=?,reply=?,assignee_id=?,updated_at=? WHERE id=? AND owner_id=?",
                (status, reply, assigned, c._now().isoformat(), item_id, owner))
        return {"id": item_id, "changed": changed}
    result = c._mutate(db, uid, save, owner_id)
    return {**result, "inquiry": detail(db, uid, item_id, owner_id)}


def cancel(db, uid, data):
    data = _data(data)
    item_id = _id(data.get("inquiry_id", data.get("id")))
    c._user(db, uid)
    row = _raw(db, item_id)
    if row["author_id"] != uid:
        raise PermissionError("Отменить обращение может его автор.")
    db.execute("BEGIN IMMEDIATE")
    try:
        _lock_users(db, (uid, row["owner_id"]))
        c._user(db, uid)
        row = _raw(db, item_id)
        changed = row["status"] != "cancelled"
        if row["status"] == "cancelled":
            pass
        elif row["status"] not in OPEN:
            raise ValueError("Это обращение уже закрыто. По записи свяжитесь с организацией.")
        else:
            db.execute("UPDATE commercial_inquiries SET status='cancelled',updated_at=? WHERE id=?", (c._now().isoformat(), item_id))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return {"id": item_id, "changed": changed, "inquiry": detail(db, uid, item_id)}


def convert(db, uid, data, owner_id=None):
    data = _data(data)
    item_id = _id(data.get("inquiry_id", data.get("id")))
    def save(owner):
        row = c._owned(db, "commercial_inquiries", owner, item_id)
        if row["status"] == "accepted":
            if not row["booking_id"]:
                raise ValueError("Созданная запись больше недоступна.")
            return {"id": item_id, "client_id": row["client_id"], "booking_id": row["booking_id"], "created": False}
        if row["status"] not in OPEN:
            raise ValueError("Нельзя создать запись из закрытого обращения.")
        c._user(db, row["author_id"])
        try:
            starts = c._date(data.get("starts_at"))
        except (ValueError, TypeError, OverflowError):
            raise ValueError("Подтвердите дату и время записи с часовым поясом.")
        if starts <= c._now():
            raise ValueError("Выберите будущее время записи.")
        duration = c._integer(data.get("duration_minutes", row["duration_minutes"]), 5, 1440)
        price = c._integer(data.get("price_rub", row["price_rub"]), 0, 1_000_000)
        try:
            ends = starts + timedelta(minutes=duration)
        except OverflowError:
            raise ValueError("Проверьте дату и длительность записи.")
        title = c._text(data, "title", 160, True) if "title" in data else row["service_title"]
        assigned = team.assignee(db, owner, data.get("assignee_id", row["assignee_id"]))
        obj = team.object_id(db, owner, data.get("object_id"))
        if assigned is not None:
            team.check_booking_overlap(db, owner, assigned, starts, ends)
        client = _id(data["client_id"]) if data.get("client_id") not in (None, "") else None
        if client:
            client_row = c._owned(db, "commercial_clients", owner, client)
            if not client_row["active"]:
                raise ValueError("Выберите активного клиента.")
        else:
            name = c._text(data, "client_name", 120, True) if "client_name" in data else row["author_name"]
            if len(name) < 2:
                raise ValueError("Укажите имя клиента от двух символов.")
            contact = c._text(data, "contact", 240) if "contact" in data else row["contact"]
            client = c._insert_id(db, "INSERT INTO commercial_clients(owner_id,name,contact,notes,active) VALUES(?,?,?,?,1)",
                (owner, name, contact, ""))
        service = db.execute("SELECT id FROM commercial_services WHERE id=? AND owner_id=?", (row["service_id"], owner)).fetchone()
        booking = c._insert_id(db, """INSERT INTO commercial_bookings(owner_id,client_id,service_id,title,
            starts_at,duration_minutes,price_rub,status,notes,assignee_id,object_id)
            VALUES(?,?,?,?,?,?,?,'planned',?,?,?)""", (owner, client, service["id"] if service else None, title,
            starts.isoformat(), duration, price, row["message"], assigned, obj))
        now = c._now().isoformat()
        db.execute("UPDATE commercial_inquiries SET status='accepted',client_id=?,booking_id=?,assignee_id=?,accepted_at=?,updated_at=? WHERE id=? AND owner_id=?",
            (client, booking, assigned, now, now, item_id, owner))
        return {"id": item_id, "client_id": client, "booking_id": booking, "created": True}
    result = c._mutate(db, uid, save, owner_id, manage=True)
    return {**result, "inquiry": detail(db, uid, item_id, owner_id)}


def photo_for_user(db, uid, photo_id):
    c._user(db, uid)
    if not isinstance(photo_id, str) or not re.fullmatch(r"[a-f0-9]{32}", photo_id):
        raise ValueError("Фото не найдено.")
    photo = db.execute("SELECT * FROM commercial_inquiry_photos WHERE id=?", (photo_id,)).fetchone()
    if not photo:
        raise ValueError("Фото не найдено.")
    row = _raw(db, photo["inquiry_id"])
    _scope(db, uid, row)
    return photo["mime"], base64.b64decode(photo["content_base64"], validate=True)
