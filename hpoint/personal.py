"""Personal PRO limits, reusable drafts and exactly-once scheduled publications.

Only personal authoring lives here. Professional Work rights are independent.
All mutations share the same owner-row lock as request creation and purchases.
"""
import calendar
import json
import math
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone

from .config import CATEGORIES, MAX_TEXT_LEN, REQUEST_COST, STATUS_OPEN, STATUS_IN_PROGRESS

MOSCOW = timezone(timedelta(hours=3), "Europe/Moscow")
TIMEZONE = "Europe/Moscow"
ACTIVE = (STATUS_OPEN, STATUS_IN_PROGRESS)


def _db(db_connection=None):
    if db_connection is not None:
        return db_connection
    from . import database
    return database.db


def _date(value):
    if not value:
        return None
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _now(value=None):
    result = _date(value) if value is not None else datetime.now(timezone.utc)
    if result is None:
        raise ValueError("Некорректное время проверки.")
    return result


def _month(at):
    local = at.astimezone(MOSCOW)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return local.strftime("%Y-%m"), datetime(year, month, 1, tzinfo=MOSCOW).isoformat()


def _in_transaction(connection):
    native = connection._connection() if hasattr(connection, "_connection") else connection
    if getattr(connection, "is_postgres", False):
        return bool(native.info.transaction_status)
    return bool(native.in_transaction)


@contextmanager
def owner_transaction(user_id, db_connection=None):
    """Join existing transactions safely and serialize every mutation per owner."""
    connection = _db(db_connection)
    nested = _in_transaction(connection)
    savepoint = "personal_" + uuid.uuid4().hex
    connection.execute("SAVEPOINT " + savepoint if nested else "BEGIN IMMEDIATE")
    try:
        suffix = " FOR NO KEY UPDATE" if getattr(connection, "is_postgres", False) else ""
        user = connection.execute("SELECT * FROM users WHERE user_id=?" + suffix, (user_id,)).fetchone()
        if not user:
            raise ValueError("Аккаунт не найден.")
        yield user
        connection.execute("RELEASE SAVEPOINT " + savepoint if nested else "COMMIT")
    except BaseException:
        if nested:
            connection.execute("ROLLBACK TO SAVEPOINT " + savepoint)
            connection.execute("RELEASE SAVEPOINT " + savepoint)
        else:
            connection.execute("ROLLBACK")
        raise


def is_pro(user_id, now=None, db_connection=None):
    user = _db(db_connection).execute("SELECT pro_until FROM users WHERE user_id=?", (user_id,)).fetchone()
    end = _date(user["pro_until"]) if user else None
    return bool(end and end > _now(now))


def usage(user_id, now=None, db_connection=None):
    connection, at = _db(db_connection), _now(now)
    user = connection.execute("SELECT pro_until FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not user:
        raise ValueError("Аккаунт не найден.")
    end = _date(user["pro_until"])
    pro = bool(end and end > at)
    active = int(connection.execute("SELECT COUNT(*) n FROM requests WHERE requester_id=? AND status IN (?,?)", (user_id, *ACTIVE)).fetchone()["n"])
    month, resets = _month(at)
    used = int(connection.execute("SELECT COUNT(*) n FROM personal_activity_publications WHERE owner_id=? AND month_key=?", (user_id, month)).fetchone()["n"])
    limit = 5 if pro else 1
    return {"pro_active": pro, "pro_until": end.isoformat() if end else None,
            "requests": {"active": active, "limit": limit, "remaining": max(0, limit-active)},
            "activities": {"used": used, "limit": None if pro else 2,
                           "remaining": None if pro else max(0, 2-used),
                           "month": month, "timezone": TIMEZONE, "resets_at": resets},
            "templates_enabled": pro, "recurrence_enabled": pro, "telegram_management": pro}


class PersonalLimitError(ValueError):
    def __init__(self, message, code, user_usage=None):
        super().__init__(message)
        self.code, self.usage = code, user_usage


def _require_pro(user_id, connection, at=None):
    user = connection.execute("SELECT is_blocked FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not user or user["is_blocked"]:
        raise PermissionError("Аккаунт недоступен.")
    if not is_pro(user_id, at, connection):
        raise PersonalLimitError("Эта возможность доступна с H-Point PRO. Данные сохранены.", "pro_required", usage(user_id, at, connection))


def assert_request_capacity(user_id, db_connection=None, now=None):
    """Read-only check. Caller must hold owner_transaction through insertion."""
    connection = _db(db_connection)
    actor = connection.execute("SELECT is_blocked FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not actor or actor["is_blocked"]:
        raise PermissionError("Аккаунт недоступен.")
    current = usage(user_id, now, connection)
    if current["requests"]["remaining"] <= 0:
        limit = current["requests"]["limit"]
        raise PersonalLimitError(f"Одновременно доступны {limit} собственных активных заявок. Завершите или отмените одну из них.", "active_request_limit", current)
    return current


def assert_activity_capacity(user_id, db_connection=None, now=None):
    connection = _db(db_connection)
    actor = connection.execute("SELECT is_blocked FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not actor or actor["is_blocked"]:
        raise PermissionError("Аккаунт недоступен.")
    current = usage(user_id, now, connection)
    if not current["pro_active"] and current["activities"]["remaining"] <= 0:
        raise PersonalLimitError("Бесплатно доступны 2 публикации активностей в месяц по московскому времени. Дождитесь обновления лимита или подключите PRO.", "activity_publication_limit", current)
    return current


def record_activity_publication(user_id, event_id, db_connection=None, now=None):
    """Call after a successful INSERT, in the same owner-locked transaction."""
    connection, at = _db(db_connection), _now(now)
    connection.execute("INSERT OR IGNORE INTO personal_activity_publications(owner_id,event_id,published_at,month_key) VALUES(?,?,?,?)", (user_id, event_id, at.isoformat(), _month(at)[0]))


def initialize_schema(connection):
    schema = """
    CREATE TABLE IF NOT EXISTS personal_activity_publications(
      id INTEGER PRIMARY KEY AUTOINCREMENT,owner_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      event_id INTEGER UNIQUE REFERENCES community_events(id) ON DELETE SET NULL,
      published_at TEXT NOT NULL,month_key TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_personal_activity_month ON personal_activity_publications(owner_id,month_key);
    CREATE TABLE IF NOT EXISTS personal_templates(
      id INTEGER PRIMARY KEY AUTOINCREMENT,owner_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      name TEXT NOT NULL,fields_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_personal_templates_owner ON personal_templates(owner_id,id);
    CREATE TABLE IF NOT EXISTS personal_schedules(
      id INTEGER PRIMARY KEY AUTOINCREMENT,owner_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      template_id INTEGER REFERENCES personal_templates(id) ON DELETE SET NULL,name TEXT NOT NULL,fields_json TEXT NOT NULL,
      frequency TEXT NOT NULL,local_time TEXT NOT NULL,weekday INTEGER NOT NULL DEFAULT 0,day_of_month INTEGER NOT NULL DEFAULT 1,
      timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',status TEXT NOT NULL DEFAULT 'active',next_run_at TEXT NOT NULL,
      last_run_at TEXT,last_status TEXT,last_reason TEXT,last_request_id INTEGER REFERENCES requests(id) ON DELETE SET NULL,
      created_at TEXT NOT NULL,updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_personal_schedule_due ON personal_schedules(status,next_run_at,id);
    CREATE INDEX IF NOT EXISTS idx_personal_schedule_owner ON personal_schedules(owner_id,id);
    CREATE TABLE IF NOT EXISTS personal_schedule_runs(
      id INTEGER PRIMARY KEY AUTOINCREMENT,schedule_id INTEGER NOT NULL REFERENCES personal_schedules(id) ON DELETE CASCADE,
      scheduled_for TEXT NOT NULL,status TEXT NOT NULL,reason TEXT,
      request_id INTEGER REFERENCES requests(id) ON DELETE SET NULL,processed_at TEXT NOT NULL,
      UNIQUE(schedule_id,scheduled_for)
    );
    """
    if getattr(connection, "is_postgres", False):
        schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace("INTEGER", "BIGINT")
    connection.executescript(schema)
    # Successful historical publications count, even if subsequently cancelled.
    # Rows are never rewritten; unique event IDs make restarts/backfill idempotent.
    rows = connection.execute("SELECT e.id,e.creator_id,e.created_at FROM community_events e WHERE e.status IN ('published','cancelled') AND NOT EXISTS(SELECT 1 FROM personal_activity_publications p WHERE p.event_id=e.id)").fetchall()
    for row in rows:
        at = _date(row["created_at"]) or _now()
        record_activity_publication(row["creator_id"], row["id"], connection, at)


def _id(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]*", str(value or "")):
        raise ValueError("Некорректный идентификатор.")
    return int(value)


def _integer(value, minimum, maximum, label):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError(label)
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError(label)
    return result


def sanitize_fields(fields):
    """Keep content only. Never persist a prior agreement, payment or photo ID."""
    if not isinstance(fields, dict):
        raise ValueError("Проверьте поля шаблона.")
    clean = {}
    for key in ("what", "place", "time_needed", "urgency", "details"):
        value = fields.get(key, "Без дополнительных деталей" if key == "details" else "")
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_TEXT_LEN:
            raise ValueError(f"Заполните поле {key}: до {MAX_TEXT_LEN} символов.")
        clean[key] = value.strip()
    if len(clean["what"]) < 3 or len(clean["place"]) < 2:
        raise ValueError("Опишите задачу минимум 3 символами и укажите место минимум 2 символами.")
    category = fields.get("category", "other")
    if category not in CATEGORIES:
        raise ValueError("Выберите направление помощи.")
    clean["category"] = category
    clean["expires_in_hours"] = _integer(fields.get("expires_in_hours", 48), 1, 168, "Срок заявки — от 1 часа до 7 дней.")
    clean["reward_rub"] = _integer(fields.get("reward_rub", 0), 0, 100000, "Вознаграждение — от 0 до 100 000 ₽.")
    lat, lon = fields.get("lat"), fields.get("lon")
    if lat is None and lon is None:
        clean.update(lat=None, lon=None)
    else:
        try:
            if isinstance(lat, bool) or isinstance(lon, bool):
                raise ValueError()
            lat, lon = float(lat), float(lon)
            if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError()
        except (TypeError, ValueError):
            raise ValueError("Некорректные координаты.")
        clean.update(lat=lat, lon=lon)
    return clean


def _template(row, enabled=True):
    return {"id": row["id"], "name": row["name"], "fields": json.loads(row["fields_json"]) if enabled else None,
            "created_at": row["created_at"], "updated_at": row["updated_at"], "usable": enabled}


def list_templates(user_id, db_connection=None):
    connection = _db(db_connection)
    enabled = is_pro(user_id, db_connection=connection)
    return [_template(row, enabled) for row in connection.execute("SELECT * FROM personal_templates WHERE owner_id=? ORDER BY id DESC", (user_id,)).fetchall()]


def get_template(user_id, template_id, for_use=True, db_connection=None):
    connection = _db(db_connection)
    if for_use:
        _require_pro(user_id, connection)
    row = connection.execute("SELECT * FROM personal_templates WHERE id=? AND owner_id=?", (_id(template_id), user_id)).fetchone()
    if not row:
        raise ValueError("Шаблон не найден.")
    return _template(row)


def save_template(user_id, data, template_id=None, db_connection=None):
    connection = _db(db_connection)
    if not isinstance(data, dict):
        raise ValueError("Проверьте шаблон.")
    with owner_transaction(user_id, connection):
        _require_pro(user_id, connection)
        previous = get_template(user_id, template_id, False, connection) if template_id is not None else {}
        name = data.get("name", previous.get("name", ""))
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Название шаблона — от 1 до 80 символов.")
        fields = sanitize_fields(data.get("fields", previous.get("fields")))
        at, encoded = _now().isoformat(), json.dumps(fields, ensure_ascii=False)
        if previous:
            template_id = previous["id"]
            connection.execute("UPDATE personal_templates SET name=?,fields_json=?,updated_at=? WHERE id=? AND owner_id=?", (name.strip(), encoded, at, template_id, user_id))
        else:
            # Use the caller's connection, including isolated test databases.
            sql = "INSERT INTO personal_templates(owner_id,name,fields_json,created_at,updated_at) VALUES(?,?,?,?,?)"
            cursor = connection.execute(sql + (" RETURNING id" if getattr(connection, "is_postgres", False) else ""), (user_id, name.strip(), encoded, at, at))
            template_id = cursor.fetchone()["id"] if getattr(connection, "is_postgres", False) else cursor.lastrowid
        return get_template(user_id, template_id, False, connection)


def delete_template(user_id, template_id, db_connection=None):
    connection = _db(db_connection)
    with owner_transaction(user_id, connection):
        identifier = get_template(user_id, template_id, False, connection)["id"]
        connection.execute("UPDATE personal_schedules SET status='disabled',last_status='disabled',last_reason='template_deleted',updated_at=? WHERE owner_id=? AND template_id=?", (_now().isoformat(), user_id, identifier))
        return connection.execute("DELETE FROM personal_templates WHERE id=? AND owner_id=?", (identifier, user_id)).rowcount == 1


def next_run(frequency, local_time, weekday=0, day_of_month=1, now=None):
    """Always strictly future; monthly day 31 clamps without drifting its anchor."""
    at = _now(now).astimezone(MOSCOW)
    if frequency not in {"daily", "weekly", "monthly"} or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", str(local_time)):
        raise ValueError("Выберите период и время публикации по Москве.")
    weekday = _integer(weekday, 0, 6, "День недели — от 0 до 6.")
    day_of_month = _integer(day_of_month, 1, 31, "День месяца — от 1 до 31.")
    hour, minute = map(int, local_time.split(":"))
    candidate = datetime.combine(at.date(), time(hour, minute), MOSCOW)
    if frequency == "daily":
        if candidate <= at:
            candidate += timedelta(days=1)
    elif frequency == "weekly":
        candidate += timedelta(days=(weekday-at.weekday()) % 7)
        if candidate <= at:
            candidate += timedelta(days=7)
    else:
        candidate = candidate.replace(day=min(day_of_month, calendar.monthrange(at.year, at.month)[1]))
        if candidate <= at:
            year, month = (at.year+1, 1) if at.month == 12 else (at.year, at.month+1)
            candidate = candidate.replace(year=year, month=month, day=min(day_of_month, calendar.monthrange(year, month)[1]))
    return candidate.astimezone(timezone.utc).isoformat()


def _schedule(row, pro=True):
    return {"id": row["id"], "template_id": row["template_id"], "name": row["name"], "fields": json.loads(row["fields_json"]),
            "frequency": row["frequency"], "time": row["local_time"], "weekday": row["weekday"], "day_of_month": row["day_of_month"],
            "timezone": TIMEZONE, "status": row["status"], "next_run_at": row["next_run_at"],
            "last_run_at": row["last_run_at"], "last_status": row["last_status"], "last_reason": row["last_reason"],
            "last_request_id": row["last_request_id"], "created_at": row["created_at"], "updated_at": row["updated_at"], "pro_required": not pro}


def list_schedules(user_id, db_connection=None):
    connection = _db(db_connection)
    enabled = is_pro(user_id, db_connection=connection)
    return [_schedule(row, enabled) for row in connection.execute("SELECT * FROM personal_schedules WHERE owner_id=? ORDER BY id DESC", (user_id,)).fetchall()]


def get_schedule(user_id, schedule_id, db_connection=None):
    connection = _db(db_connection)
    row = connection.execute("SELECT * FROM personal_schedules WHERE id=? AND owner_id=?", (_id(schedule_id), user_id)).fetchone()
    if not row:
        raise ValueError("Расписание не найдено.")
    return _schedule(row, is_pro(user_id, db_connection=connection))


def save_schedule(user_id, data, schedule_id=None, db_connection=None):
    connection = _db(db_connection)
    if not isinstance(data, dict):
        raise ValueError("Проверьте расписание.")
    with owner_transaction(user_id, connection):
        _require_pro(user_id, connection)
        previous = get_schedule(user_id, schedule_id, connection) if schedule_id is not None else {}
        template_id = data.get("template_id", previous.get("template_id"))
        template = get_template(user_id, template_id, False, connection)
        fields = sanitize_fields(data.get("fields", previous.get("fields", template["fields"])))
        name = data.get("name", previous.get("name", template["name"]))
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Название повтора — от 1 до 80 символов.")
        if data.get("timezone", TIMEZONE) != TIMEZONE:
            raise ValueError("Часовой пояс расписания — Europe/Moscow (МСК).")
        frequency, local_time = data.get("frequency", previous.get("frequency", "daily")), data.get("time", previous.get("time", "09:00"))
        weekday = _integer(data.get("weekday", previous.get("weekday", 0)), 0, 6, "Проверьте день недели.")
        day = _integer(data.get("day_of_month", previous.get("day_of_month", 1)), 1, 31, "Проверьте день месяца.")
        status = data.get("status", previous.get("status", "active"))
        if status not in {"active", "paused", "disabled"}:
            raise ValueError("Некорректное состояние расписания.")
        next_at = next_run(frequency, local_time, weekday, day)
        at = _now().isoformat()
        values = (template["id"], name.strip(), json.dumps(fields, ensure_ascii=False), frequency, local_time, weekday, day, status, next_at, at)
        if previous:
            schedule_id = previous["id"]
            connection.execute("UPDATE personal_schedules SET template_id=?,name=?,fields_json=?,frequency=?,local_time=?,weekday=?,day_of_month=?,status=?,next_run_at=?,updated_at=? WHERE id=? AND owner_id=?", (*values, schedule_id, user_id))
        else:
            sql = "INSERT INTO personal_schedules(template_id,name,fields_json,frequency,local_time,weekday,day_of_month,status,next_run_at,updated_at,created_at,owner_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
            cursor = connection.execute(sql + (" RETURNING id" if getattr(connection, "is_postgres", False) else ""), (*values, at, user_id))
            schedule_id = cursor.fetchone()["id"] if getattr(connection, "is_postgres", False) else cursor.lastrowid
        return get_schedule(user_id, schedule_id, connection)


def set_schedule_status(user_id, schedule_id, status, db_connection=None):
    if status not in {"active", "paused", "disabled"}:
        raise ValueError("Некорректное состояние расписания.")
    connection = _db(db_connection)
    with owner_transaction(user_id, connection):
        row = get_schedule(user_id, schedule_id, connection)
        if status == "active":
            _require_pro(user_id, connection)
            if row["template_id"] is None:
                raise ValueError("Шаблон удалён. Сохраните новый шаблон для повтора.")
        future = next_run(row["frequency"], row["time"], row["weekday"], row["day_of_month"])
        connection.execute("UPDATE personal_schedules SET status=?,next_run_at=?,last_status=?,last_reason=NULL,updated_at=? WHERE id=? AND owner_id=?", (status, future, "resumed" if status == "active" else status, _now().isoformat(), row["id"], user_id))
        return get_schedule(user_id, row["id"], connection)


def _run_one(candidate, connection, at):
    from . import services
    with owner_transaction(candidate["owner_id"], connection) as user:
        suffix = " FOR UPDATE" if getattr(connection, "is_postgres", False) else ""
        row = connection.execute("SELECT * FROM personal_schedules WHERE id=?" + suffix, (candidate["id"],)).fetchone()
        if not row or row["status"] != "active":
            return None
        due = _date(row["next_run_at"]) or at
        reason = "account_unavailable" if user["is_blocked"] or not user["email_verified"] or not user["email"] else "pro_expired" if not is_pro(user["user_id"], at, connection) else None
        if due > at and not reason:
            return None
        following = next_run(row["frequency"], row["local_time"], row["weekday"], row["day_of_month"], at)
        event = {"user_id": user["user_id"], "schedule_id": row["id"]}
        if reason:
            connection.execute("UPDATE personal_schedules SET status='paused',next_run_at=?,last_run_at=?,last_status='paused',last_reason=?,updated_at=? WHERE id=?", (following, at.isoformat(), reason, at.isoformat(), row["id"]))
            if due <= at:
                connection.execute("INSERT OR IGNORE INTO personal_schedule_runs(schedule_id,scheduled_for,status,reason,processed_at) VALUES(?,?,'skipped',?,?)", (row["id"], row["next_run_at"], reason, at.isoformat()))
            return "skipped", {**event, "reason": reason}
        claim = connection.execute("INSERT OR IGNORE INTO personal_schedule_runs(schedule_id,scheduled_for,status,processed_at) VALUES(?,?,'processing',?)", (row["id"], row["next_run_at"], at.isoformat()))
        if claim.rowcount != 1:
            connection.execute("UPDATE personal_schedules SET next_run_at=? WHERE id=?", (following, row["id"]))
            return None
        if row["last_request_id"]:
            old = connection.execute("SELECT status FROM requests WHERE id=?", (row["last_request_id"],)).fetchone()
            if old and old["status"] in ACTIVE:
                reason = "previous_active"
        fields = None
        try:
            fields = sanitize_fields(json.loads(row["fields_json"]))
        except (TypeError, ValueError):
            reason = reason or "request_validation"
        if not reason:
            try:
                assert_request_capacity(user["user_id"], connection, at)
                if not fields["reward_rub"] and int(user["balance"] or 0) < REQUEST_COST:
                    reason = "insufficient_hp"
            except PersonalLimitError:
                reason = "active_request_limit"
        request_id = None
        if not reason:
            # services owns a nested savepoint; failed validation cannot leave
            # a partial request or an aborted outer PostgreSQL transaction.
            try:
                request_id = services.create_request(user["user_id"], fields)
            except (ValueError, PermissionError):
                reason = "request_validation"
        state = "skipped" if reason else "published"
        connection.execute("UPDATE personal_schedule_runs SET status=?,reason=?,request_id=? WHERE schedule_id=? AND scheduled_for=?", (state, reason, request_id, row["id"], row["next_run_at"]))
        connection.execute("UPDATE personal_schedules SET next_run_at=?,last_run_at=?,last_status=?,last_reason=?,last_request_id=COALESCE(?,last_request_id),updated_at=? WHERE id=?", (following, at.isoformat(), state, reason, request_id, at.isoformat(), row["id"]))
        if reason:
            return "skipped", {**event, "reason": reason}
        request = connection.execute("SELECT reserve_deadline_at FROM requests WHERE id=?", (request_id,)).fetchone()
        return "published", {**event, "request_id": request_id, "paid": bool(fields["reward_rub"]), "reserve_deadline_at": request["reserve_deadline_at"]}


def process_due(now=None):
    """One run per due schedule, atomically with creation; never replay backlog.

    Events are returned only after the transaction commits, for best-effort
    notifications by the existing worker. No mail, Telegram or funds are sent.
    """
    connection, at = _db(), _now(now)
    result = {"published": [], "skipped": [], "errors": []}
    rows = connection.execute("SELECT id,owner_id,next_run_at FROM personal_schedules WHERE status='active' ORDER BY next_run_at,id LIMIT 500").fetchall()
    for candidate in rows:
        if len(result["published"])+len(result["skipped"]) >= 100:
            break
        due = _date(candidate["next_run_at"]) or at
        if due > at and is_pro(candidate["owner_id"], at, connection):
            continue
        try:
            outcome = _run_one(candidate, connection, at)
            if outcome:
                kind, event = outcome
                result[kind].append(event)
        except Exception:
            # No account address, content or payment data enters the error DTO.
            result["errors"].append({"schedule_id": candidate["id"], "reason": "processing_error"})
    return result
