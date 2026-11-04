"""Private support conversations with durable history and per-viewer read state.

Legacy ticket columns remain compatible. Their original text and last saved
reply are imported idempotently; text overwritten before this migration cannot
be reconstructed. Internal sync helpers deliberately never start transactions.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid


STATUSES = {"open", "answered", "resolved"}


def _now():
    return datetime.now(timezone.utc)


def _id(value, minimum=1, maximum=2**63-1):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,19}", str(value)):
        raise ValueError("Некорректный идентификатор или размер страницы.")
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError("Проверьте идентификатор или размер страницы.")
    return result


def _data(data):
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект.")
    return data


def _text(data, key, maximum, minimum=1):
    value = data.get(key, "")
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(f"Поле «{key}»: от {minimum} до {maximum} символов.")
    return value.strip()


def _actor(db, uid, admin=False, lock=False):
    if not isinstance(admin, bool):
        raise ValueError("Некорректный режим поддержки.")
    suffix = " FOR NO KEY UPDATE" if lock and getattr(db, "is_postgres", False) else ""
    user = db.execute("SELECT * FROM users WHERE user_id=?"+suffix, (uid,)).fetchone()
    if not user or user["is_blocked"] or not user["email"] or not user["email_verified"]:
        raise PermissionError("Войдите в аккаунт с подтверждённым email.")
    if admin and user["role"] != "admin":
        raise PermissionError("Раздел доступен только администратору.")
    return user


def _ticket(db, uid, ticket_id, admin=False, lock=False):
    ticket_id = _id(ticket_id)
    suffix = " FOR UPDATE" if lock and getattr(db, "is_postgres", False) else ""
    row = db.execute("SELECT * FROM support_tickets WHERE id=?"+suffix, (ticket_id,)).fetchone()
    if not row or (not admin and row["user_id"] != uid):
        raise PermissionError("Обращение недоступно.")
    return row


def _insert(db, sql, values):
    if getattr(db, "is_postgres", False):
        return db.execute(sql+" RETURNING id", values).fetchone()["id"]
    return db.execute(sql, values).lastrowid


def initialize_schema(db):
    schema = """
    CREATE TABLE IF NOT EXISTS support_messages(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ticket_id INTEGER NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
      sender_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
      sender_role TEXT NOT NULL, message TEXT NOT NULL, search_text TEXT NOT NULL DEFAULT '', request_key TEXT NOT NULL,
      created_at TEXT NOT NULL, UNIQUE(ticket_id,request_key));
    CREATE TABLE IF NOT EXISTS support_read_markers(
      ticket_id INTEGER NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      last_message_id INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL,
      PRIMARY KEY(ticket_id,user_id));
    CREATE TABLE IF NOT EXISTS support_ticket_state(
      ticket_id INTEGER PRIMARY KEY REFERENCES support_tickets(id) ON DELETE CASCADE,
      legacy_reply_hash TEXT NOT NULL DEFAULT '', subject_search TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS support_operations(
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      request_key TEXT NOT NULL, action TEXT NOT NULL, payload_hash TEXT NOT NULL,
      ticket_id INTEGER NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
      message_id INTEGER REFERENCES support_messages(id) ON DELETE SET NULL,
      created_at TEXT NOT NULL, PRIMARY KEY(user_id,request_key));
    CREATE INDEX IF NOT EXISTS idx_support_messages_ticket ON support_messages(ticket_id,id);
    CREATE INDEX IF NOT EXISTS idx_support_operations_recent ON support_operations(user_id,action,created_at);
    CREATE INDEX IF NOT EXISTS idx_support_tickets_user ON support_tickets(user_id,id);
    """
    if getattr(db, "is_postgres", False):
        schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace("INTEGER", "BIGINT")
    db.executescript(schema)
    # Only the new support tables evolve; existing ticket snapshots are never
    # rewritten by this migration.
    for table, field in (("support_messages", "search_text"), ("support_ticket_state", "subject_search")):
        columns = {r["column_name"] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?", (table,)).fetchall()} if getattr(db, "is_postgres", False) else {r["name"] for r in db.execute("PRAGMA table_info("+table+")").fetchall()}
        if field not in columns:
            db.execute("ALTER TABLE "+table+" ADD COLUMN "+field+" TEXT NOT NULL DEFAULT ''")
            if table == "support_messages":
                for item in db.execute("SELECT id,message FROM support_messages").fetchall():
                    db.execute("UPDATE support_messages SET search_text=? WHERE id=?", (item["message"].casefold(), item["id"]))
    # A database migration is run with writers stopped. Repeated initialisation
    # must also preserve messages subsequently written through this module.
    for row in db.execute("SELECT * FROM support_tickets ORDER BY id").fetchall():
        sync_legacy_ticket(db, row["id"])


def _reply_hash(row):
    return hashlib.sha256(json.dumps([row["admin_reply"], row["replied_at"], row["replied_by"]], ensure_ascii=False).encode()).hexdigest() if row["admin_reply"] else ""


def _append(db, ticket_id, sender_id, role, message, key, created=None):
    stamp = created or _now().isoformat()
    db.execute("""INSERT OR IGNORE INTO support_messages(ticket_id,sender_id,sender_role,message,search_text,request_key,created_at)
        VALUES(?,?,?,?,?,?,?)""", (ticket_id, sender_id, role, message, message.casefold(), key, stamp))
    row = db.execute("SELECT id FROM support_messages WHERE ticket_id=? AND request_key=?", (ticket_id, key)).fetchone()
    db.execute("UPDATE support_ticket_state SET updated_at=? WHERE ticket_id=?", (stamp, ticket_id))
    return row["id"]


def sync_legacy_ticket(db, ticket_id):
    """Import a legacy write inside its caller's existing transaction."""
    row = db.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
    if not row:
        return
    state = db.execute("SELECT * FROM support_ticket_state WHERE ticket_id=?", (ticket_id,)).fetchone()
    if not state:
        db.execute("INSERT OR IGNORE INTO support_ticket_state(ticket_id,updated_at) VALUES(?,?)", (ticket_id, row["created_at"]))
    db.execute("UPDATE support_ticket_state SET subject_search=? WHERE ticket_id=?", (row["subject"].casefold(), ticket_id))
    if not db.execute("SELECT 1 FROM support_messages WHERE ticket_id=? AND request_key='legacy:initial'", (ticket_id,)).fetchone():
        sender = row["user_id"] if db.execute("SELECT 1 FROM users WHERE user_id=?", (row["user_id"],)).fetchone() else None
        _append(db, ticket_id, sender, "user", row["message"], "legacy:initial", row["created_at"])
    state = db.execute("SELECT * FROM support_ticket_state WHERE ticket_id=?", (ticket_id,)).fetchone()
    fingerprint = _reply_hash(row)
    if fingerprint and fingerprint != state["legacy_reply_hash"]:
        sender = row["replied_by"] if row["replied_by"] is not None and db.execute("SELECT 1 FROM users WHERE user_id=?", (row["replied_by"],)).fetchone() else None
        _append(db, ticket_id, sender, "admin", row["admin_reply"], "legacy:reply:"+fingerprint, row["replied_at"] or row["created_at"])
        db.execute("UPDATE support_ticket_state SET legacy_reply_hash=? WHERE ticket_id=?", (fingerprint, ticket_id))


def record_request_closure(db, request_id, actor_id, reason):
    """Keep dispute cancellation in the conversation, without nesting a write."""
    for row in db.execute("SELECT id FROM support_tickets WHERE request_id=?", (request_id,)).fetchall():
        sync_legacy_ticket(db, row["id"])
        _append(db, row["id"], actor_id, "system", "Заявка закрыта. "+str(reason)[:2000], "request:closed:"+str(request_id))


def _operation(db, uid, action, data, payload):
    key = data.get("request_key")
    if key is not None and (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key)):
        raise ValueError("Обновите форму обращения и повторите отправку.")
    fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if key:
        previous = db.execute("SELECT * FROM support_operations WHERE user_id=? AND request_key=?", (uid, key)).fetchone()
        if previous and (previous["action"] != action or previous["payload_hash"] != fingerprint):
            raise ValueError("Этот запрос уже использован для других данных.")
    else:
        # Compatibility for older already-open browser tabs. New clients send
        # an explicit key, so intentional repetitions remain possible.
        previous = db.execute("""SELECT * FROM support_operations WHERE user_id=? AND action=?
            AND payload_hash=? AND created_at>=? ORDER BY created_at DESC LIMIT 1""",
            (uid, action, fingerprint, (_now()-timedelta(seconds=60)).isoformat())).fetchone()
        key = uuid.uuid4().hex
    return key, fingerprint, previous


def _remember(db, uid, key, action, fingerprint, ticket_id, message_id):
    db.execute("""INSERT INTO support_operations(user_id,request_key,action,payload_hash,ticket_id,message_id,created_at)
        VALUES(?,?,?,?,?,?,?)""", (uid, key, action, fingerprint, ticket_id, message_id, _now().isoformat()))


def create(db, uid, data):
    data = _data(data)
    subject, message = _text(data, "subject", 120, 2), _text(data, "message", 4000)
    if data.get("request_id") is not None:
        raise ValueError("Откройте проблему по помощи из самой заявки.")
    db.execute("BEGIN IMMEDIATE")
    try:
        _actor(db, uid, lock=True)
        key, fingerprint, previous = _operation(db, uid, "create", data, {"subject": subject, "message": message})
        if previous:
            db.execute("COMMIT")
            return {"ticket_id": previous["ticket_id"], "created": False}
        active = db.execute("SELECT COUNT(*) n FROM support_tickets WHERE user_id=? AND status IN ('open','answered')", (uid,)).fetchone()["n"]
        daily = db.execute("SELECT COUNT(*) n FROM support_tickets WHERE user_id=? AND created_at>=?", (uid, _now().date().isoformat())).fetchone()["n"]
        if active >= 20 or daily >= 30:
            raise ValueError("Слишком много обращений. Продолжите переписку в существующем обращении.")
        ticket_id = _insert(db, "INSERT INTO support_tickets(user_id,subject,message,created_at) VALUES(?,?,?,?)", (uid, subject, message, _now().isoformat()))
        sync_legacy_ticket(db, ticket_id)
        message_id = db.execute("SELECT id FROM support_messages WHERE ticket_id=?", (ticket_id,)).fetchone()["id"]
        _remember(db, uid, key, "create", fingerprint, ticket_id, message_id)
        db.execute("COMMIT")
        return {"ticket_id": ticket_id, "created": True}
    except Exception:
        db.execute("ROLLBACK")
        raise


def reply(db, uid, data, admin=False):
    data = _data(data)
    ticket_id, message = _id(data.get("ticket_id")), _text(data, "message", 4000)
    db.execute("BEGIN IMMEDIATE")
    try:
        _actor(db, uid, admin, lock=True)
        ticket = _ticket(db, uid, ticket_id, admin, lock=True)
        sync_legacy_ticket(db, ticket_id)
        key, fingerprint, previous = _operation(db, uid, "admin_reply" if admin else "reply", data, {"ticket_id": ticket_id, "message": message})
        if previous:
            db.execute("COMMIT")
            return {"ticket_id": ticket_id, "message_id": previous["message_id"], "created": False}
        size = db.execute("SELECT COUNT(*) n FROM support_messages WHERE ticket_id=?", (ticket_id,)).fetchone()["n"]
        daily = db.execute("SELECT COUNT(*) n FROM support_messages WHERE sender_id=? AND created_at>=?", (uid, _now().date().isoformat())).fetchone()["n"]
        if size >= 5000 or (not admin and daily >= 150):
            raise ValueError("Достигнут лимит сообщений. Повторите позже или создайте новое обращение.")
        message_id = _append(db, ticket_id, uid, "admin" if admin else "user", message, "reply:"+key)
        if admin:
            db.execute("UPDATE support_tickets SET admin_reply=?,replied_by=?,replied_at=?,status=CASE WHEN status='resolved' THEN 'resolved' ELSE 'answered' END WHERE id=?", (message, uid, _now().isoformat(), ticket_id))
            updated = db.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
            db.execute("UPDATE support_ticket_state SET legacy_reply_hash=? WHERE ticket_id=?", (_reply_hash(updated), ticket_id))
        else:
            db.execute("UPDATE support_tickets SET status='open' WHERE id=?", (ticket_id,))
        _remember(db, uid, key, "admin_reply" if admin else "reply", fingerprint, ticket_id, message_id)
        db.execute("COMMIT")
        return {"ticket_id": ticket_id, "message_id": message_id, "created": True}
    except Exception:
        db.execute("ROLLBACK")
        raise


def _active_dispute(db, ticket):
    if not ticket["request_id"]:
        return False
    row = db.execute("SELECT status,dispute_status FROM requests WHERE id=?", (ticket["request_id"],)).fetchone()
    return bool(row and row["status"] == "in_progress" and row["dispute_status"] == "open")


def set_status(db, uid, data, admin=False):
    data = _data(data)
    target = data.get("status")
    if target not in ("open", "resolved"):
        raise ValueError("Выберите: открыто или решено.")
    db.execute("BEGIN IMMEDIATE")
    try:
        _actor(db, uid, admin, lock=True)
        ticket = _ticket(db, uid, data.get("ticket_id"), admin, lock=True)
        sync_legacy_ticket(db, ticket["id"])
        if target == "resolved" and _active_dispute(db, ticket):
            raise ValueError("Сначала примите решение по спору в управлении заявкой. Выплата остаётся приостановлена.")
        changed = ticket["status"] != target
        if changed:
            db.execute("UPDATE support_tickets SET status=? WHERE id=?", (target, ticket["id"]))
            _append(db, ticket["id"], uid, "system", "Обращение отмечено решённым." if target == "resolved" else "Обращение снова открыто.", "status:"+uuid.uuid4().hex)
        db.execute("COMMIT")
        return {"ticket_id": ticket["id"], "status": target, "changed": changed}
    except Exception:
        db.execute("ROLLBACK")
        raise


def _unread(db, uid, ticket_id, admin):
    role = "m.sender_role='user'" if admin else "m.sender_role IN ('admin','system')"
    return db.execute("""SELECT COUNT(*) n FROM support_messages m WHERE m.ticket_id=? AND """+role+"""
        AND (m.sender_id IS NULL OR m.sender_id<>?) AND m.id>COALESCE((SELECT last_message_id FROM support_read_markers WHERE ticket_id=? AND user_id=?),0)""",
        (ticket_id, uid, ticket_id, uid)).fetchone()["n"]


def _message_dto(row, uid, admin):
    return {"id": row["id"], "message": row["message"], "created_at": row["created_at"], "author_id": row["sender_id"],
            "author_role": row["sender_role"], "author_name": (row["author_name"] or "Участник") if admin or row["sender_role"] == "user" else "Поддержка H-Point",
            "is_mine": row["sender_id"] == uid}


def _messages(db, ticket_id, suffix=" ORDER BY m.id", params=()):
    return db.execute("SELECT m.*,u.name author_name FROM support_messages m LEFT JOIN users u ON u.user_id=m.sender_id WHERE m.ticket_id=?"+suffix, (ticket_id,)+tuple(params)).fetchall()


def _ticket_dto(db, row, uid, admin, messages=None):
    if messages is None:
        last_rows = _messages(db, row["id"], " ORDER BY m.id DESC LIMIT 1")
        human_rows = _messages(db, row["id"], " AND m.sender_role IN ('user','admin') ORDER BY m.id DESC LIMIT 1")
        messages = sorted({item["id"]: item for item in last_rows+human_rows}.values(), key=lambda item: item["id"])
    owner = db.execute("SELECT name,email FROM users WHERE user_id=?", (row["user_id"],)).fetchone()
    state = db.execute("SELECT updated_at FROM support_ticket_state WHERE ticket_id=?", (row["id"],)).fetchone()
    last = messages[-1] if messages else None
    human = next((item for item in reversed(messages) if item["sender_role"] in ("user", "admin")), None)
    awaiting = None if row["status"] == "resolved" else "admin" if not human or human["sender_role"] == "user" else "user"
    result = {"id": row["id"], "user_id": row["user_id"], "subject": row["subject"], "message": row["message"],
              "admin_reply": row["admin_reply"], "status": row["status"], "request_id": row["request_id"],
              "created_at": row["created_at"], "updated_at": state["updated_at"] if state else row["created_at"],
              "user_name": owner["name"] if owner else "Участник", "unread_count": _unread(db, uid, row["id"], admin),
              "last_message": _message_dto(last, uid, admin) if last else None, "awaiting": awaiting,
              "is_active_dispute": _active_dispute(db, row), "can_reply": True, "can_resolve": not _active_dispute(db, row), "can_reopen": row["status"] == "resolved"}
    if admin:
        result["user_email"] = owner["email"] if owner else ""
    return result


def list_tickets(db, uid, admin=False, status="all", query="", unread=False, offset=0, limit=30):
    _actor(db, uid, admin)
    if not isinstance(status, str) or status not in STATUSES|{"all", "waiting"}:
        raise ValueError("Неизвестный статус обращения.")
    if not isinstance(query, str) or len(query) > 200 or not isinstance(unread, bool):
        raise ValueError("Проверьте условия поиска.")
    offset, limit = _id(offset, 0, 1_000_000), _id(limit, 1, 100)
    role = "m.sender_role='user'" if admin else "m.sender_role IN ('admin','system')"
    where, args = ([] if admin else ["t.user_id=?"]), [uid, uid]+([] if admin else [uid])
    if query.strip():
        pattern = "%"+query.strip().casefold().replace("!", "!!").replace("%", "!%").replace("_", "!_")+"%"
        where.append("(st.subject_search LIKE ? ESCAPE '!' OR EXISTS(SELECT 1 FROM support_messages search WHERE search.ticket_id=t.id AND search.search_text LIKE ? ESCAPE '!')"+(" OR LOWER(u.email) LIKE ? ESCAPE '!'" if admin else "")+")")
        args.extend([pattern, pattern]+([pattern] if admin else []))
    rows = db.execute("""SELECT t.id,t.status,
        (SELECT MAX(id) FROM support_messages WHERE ticket_id=t.id) last_id,
        (SELECT sender_role FROM support_messages WHERE ticket_id=t.id AND sender_role IN ('user','admin') ORDER BY id DESC LIMIT 1) last_role,
        (SELECT COUNT(*) FROM support_messages m WHERE m.ticket_id=t.id AND """+role+"""
          AND (m.sender_id IS NULL OR m.sender_id<>?) AND m.id>COALESCE(marker.last_message_id,0)) unread_count
        FROM support_tickets t JOIN users u ON u.user_id=t.user_id
        LEFT JOIN support_ticket_state st ON st.ticket_id=t.id
        LEFT JOIN support_read_markers marker ON marker.ticket_id=t.id AND marker.user_id=?"""+
        (" WHERE "+" AND ".join(where) if where else ""), tuple(args)).fetchall()
    items = [{"id": row["id"], "status": row["status"], "unread_count": row["unread_count"], "last_id": row["last_id"] or 0,
              "awaiting": None if row["status"] == "resolved" else "admin" if row["last_role"] in (None, "user") else "user"} for row in rows]
    counts = {"all": len(items), **{key: sum(item["status"] == key for item in items) for key in sorted(STATUSES)},
              "unread": sum(item["unread_count"] > 0 for item in items),
              "waiting_for_admin": sum(item["awaiting"] == "admin" for item in items),
              "waiting_for_user": sum(item["awaiting"] == "user" for item in items)}
    counts["waiting"] = counts["waiting_for_admin" if admin else "waiting_for_user"]
    filtered = [item for item in items if (status == "all" or (item["awaiting"] == ("admin" if admin else "user") if status == "waiting" else item["status"] == status)) and (not unread or item["unread_count"] > 0)]
    filtered.sort(key=lambda item: (item["last_id"], item["id"]), reverse=True)
    page = [_ticket_dto(db, _ticket(db, uid, item["id"], admin), uid, admin) for item in filtered[offset:offset+limit]]
    return {"tickets": page, "counts": counts, "total": len(filtered), "has_more": offset+limit < len(filtered), "offset": offset, "limit": limit}


def detail(db, uid, ticket_id, admin=False, after=0, before=0, limit=100):
    _actor(db, uid, admin)
    row = _ticket(db, uid, ticket_id, admin)
    after, before, limit = _id(after, 0), _id(before, 0), _id(limit, 1, 200)
    if after and before:
        raise ValueError("Выберите одно направление загрузки сообщений.")
    if after:
        selected = _messages(db, row["id"], " AND m.id>? ORDER BY m.id LIMIT ?", (after, limit))
    elif before:
        selected = list(reversed(_messages(db, row["id"], " AND m.id<? ORDER BY m.id DESC LIMIT ?", (before, limit))))
    else:
        selected = list(reversed(_messages(db, row["id"], " ORDER BY m.id DESC LIMIT ?", (limit,))))
    first, last = (selected[0]["id"], selected[-1]["id"]) if selected else (0, 0)
    older = bool(first and db.execute("SELECT 1 FROM support_messages WHERE ticket_id=? AND id<? LIMIT 1", (row["id"], first)).fetchone())
    newer = bool(last and db.execute("SELECT 1 FROM support_messages WHERE ticket_id=? AND id>? LIMIT 1", (row["id"], last)).fetchone())
    ticket = _ticket_dto(db, row, uid, admin)
    return {"ticket": ticket, "messages": [_message_dto(item, uid, admin) for item in selected], "can_reply": True,
            "permissions": {key: ticket[key] for key in ("can_reply", "can_resolve", "can_reopen")},
            "first_message_id": first, "last_message_id": last, "has_older": older, "has_newer": newer, "has_more": newer if after else older}


def mark_read(db, uid, data, admin=False):
    data = _data(data)
    last = _id(data.get("last_message_id"), 0)
    db.execute("BEGIN IMMEDIATE")
    try:
        _actor(db, uid, admin, lock=True)
        ticket = _ticket(db, uid, data.get("ticket_id"), admin, lock=True)
        sync_legacy_ticket(db, ticket["id"])
        if last and not db.execute("SELECT 1 FROM support_messages WHERE id=? AND ticket_id=?", (last, ticket["id"])).fetchone():
            raise ValueError("Сообщение не относится к этому обращению.")
        db.execute("""INSERT INTO support_read_markers(ticket_id,user_id,last_message_id,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(ticket_id,user_id) DO UPDATE SET last_message_id=CASE WHEN excluded.last_message_id>support_read_markers.last_message_id THEN excluded.last_message_id ELSE support_read_markers.last_message_id END,updated_at=excluded.updated_at""",
            (ticket["id"], uid, last, _now().isoformat()))
        stored = db.execute("SELECT last_message_id FROM support_read_markers WHERE ticket_id=? AND user_id=?", (ticket["id"], uid)).fetchone()["last_message_id"]
        count = _unread(db, uid, ticket["id"], admin)
        db.execute("COMMIT")
        return {"ticket_id": ticket["id"], "last_message_id": stored, "unread_count": count}
    except Exception:
        db.execute("ROLLBACK")
        raise
