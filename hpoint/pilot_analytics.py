"""Private, honest pilot measurements over actual server records.

Outcome counters are derived from domain tables, never client-submitted claims.
Client events only describe authenticated views/interaction days and start now;
they do not retrospectively turn last_seen timestamps into retention evidence.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from . import commercial as c

COHORTS = {"unclassified", "real", "pilot", "demo"}
RESPONSE_EVENTS = {"helper_applied", "helper_accepted", "offer_accepted"}
ASSIGNMENT_EVENTS = {"helper_assigned", "helper_accepted", "offer_accepted"}


def _now():
    return datetime.now(timezone.utc)


def _date(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (result if result.tzinfo else result.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def initialize_schema(db):
    schema = """
    CREATE TABLE IF NOT EXISTS pilot_cohorts(
      user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
      cohort TEXT NOT NULL, updated_at TEXT NOT NULL,
      updated_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS pilot_activity_days(
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      day TEXT NOT NULL, created_at TEXT NOT NULL,
      PRIMARY KEY(user_id,day)
    );
    CREATE TABLE IF NOT EXISTS pilot_service_views(
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      service_id INTEGER NOT NULL REFERENCES commercial_services(id) ON DELETE CASCADE,
      day TEXT NOT NULL, created_at TEXT NOT NULL,
      PRIMARY KEY(user_id,service_id,day)
    );
    CREATE TABLE IF NOT EXISTS pilot_measurement_settings(
      key TEXT PRIMARY KEY,value TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_pilot_activity_day ON pilot_activity_days(day,user_id);
    CREATE INDEX IF NOT EXISTS idx_pilot_views_day ON pilot_service_views(day,user_id);
    """
    if getattr(db, "is_postgres", False):
        schema = schema.replace("INTEGER", "BIGINT")
    db.executescript(schema)
    db.execute("INSERT OR IGNORE INTO pilot_measurement_settings(key,value) VALUES('started_at',?)", (_now().isoformat(),))


def _admin(db, uid):
    user = c._user(db, uid)
    if user["role"] != "admin":
        raise PermissionError("Статистика пилота доступна только администратору.")
    return user


def set_cohort(db, admin_id, data):
    _admin(db, admin_id)
    if not isinstance(data, dict) or not isinstance(data.get("cohort"), str) or data["cohort"] not in COHORTS:
        raise ValueError("Выберите группу: без отметки, реальные, пилот или демо.")
    uid = c._user_id(data.get("user_id"))
    if not db.execute("SELECT user_id FROM users WHERE user_id=?", (uid,)).fetchone():
        raise ValueError("Участник не найден.")
    db.execute("""INSERT INTO pilot_cohorts(user_id,cohort,updated_at,updated_by) VALUES(?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET cohort=excluded.cohort,updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
        (uid, data["cohort"], _now().isoformat(), admin_id))
    return {"user_id": uid, "cohort": data["cohort"]}


def record_activity(db, uid):
    c._user(db, uid)
    now = _now()
    cursor = db.execute("INSERT OR IGNORE INTO pilot_activity_days(user_id,day,created_at) VALUES(?,?,?)",
                        (uid, now.date().isoformat(), now.isoformat()))
    return {"recorded": cursor.rowcount > 0, "day": now.date().isoformat()}


def record_service_view(db, uid, data):
    c._user(db, uid)
    if not isinstance(data, dict):
        raise ValueError("Проверьте данные просмотра.")
    service_id = c._integer(data.get("service_id"), 1, 2**63-1)
    row = db.execute("""SELECT s.owner_id,p.trial_until,p.paid_until FROM commercial_services s
        JOIN commercial_profiles p ON p.user_id=s.owner_id
        JOIN commercial_public_profiles pub ON pub.owner_id=s.owner_id
        JOIN users u ON u.user_id=s.owner_id
        WHERE s.id=? AND s.active=1 AND s.published=1 AND pub.published=1
        AND u.is_blocked=0 AND u.email_verified=1
        AND NOT EXISTS(SELECT 1 FROM commercial_deleted_profiles d WHERE d.user_id=s.owner_id)""", (service_id,)).fetchone()
    if not row or c._until(row) <= _now():
        raise ValueError("Опубликованная услуга недоступна.")
    if row["owner_id"] == uid or db.execute("SELECT 1 FROM commercial_members WHERE owner_id=? AND user_id=?", (row["owner_id"], uid)).fetchone():
        return {"recorded": False, "reason": "own_organization"}
    now = _now()
    cursor = db.execute("INSERT OR IGNORE INTO pilot_service_views(user_id,service_id,day,created_at) VALUES(?,?,?,?)",
                        (uid, service_id, now.date().isoformat(), now.isoformat()))
    return {"recorded": cursor.rowcount > 0, "day": now.date().isoformat()}


def _ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "percent": round(numerator * 100 / denominator, 1) if denominator else None}


def _has_table(db, name):
    if getattr(db, "is_postgres", False):
        return bool(db.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?", (name,)).fetchone())
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


def summary(db, admin_id, days=14, cohort="all"):
    _admin(db, admin_id)
    days = c._integer(days, 1, 90)
    if not isinstance(cohort, str) or (cohort != "all" and cohort not in COHORTS):
        raise ValueError("Неизвестная группа участников.")
    now = _now()
    start = datetime.combine(now.date()-timedelta(days=days-1), datetime.min.time(), timezone.utc)
    within = lambda value: bool((moment := _date(value)) and start <= moment <= now)
    started_row = db.execute("SELECT value FROM pilot_measurement_settings WHERE key='started_at'").fetchone()
    measured_since = (_date(started_row["value"]) if started_row else None) or now
    users = [dict(row) for row in db.execute("""SELECT u.user_id,u.created_at,u.email_verified,u.is_blocked,
        COALESCE(p.cohort,'unclassified') cohort FROM users u LEFT JOIN pilot_cohorts p ON p.user_id=u.user_id""").fetchall()]
    users = [row for row in users if _date(row["created_at"]) and _date(row["created_at"]) <= now]
    distribution = Counter(row["cohort"] for row in users)
    selected = {row["user_id"]: row for row in users if cohort == "all" or row["cohort"] == cohort}
    registrations = [row for row in selected.values() if within(row["created_at"])]
    verified = sum(bool(row["email_verified"]) for row in registrations)

    requests = [dict(row) for row in db.execute("SELECT id,requester_id,helper_id,status,created_at,completed_at FROM requests").fetchall()
                if row["requester_id"] in selected and within(row["created_at"])]
    request_by_id = {row["id"]: row for row in requests}
    response_times, responded, assigned = {}, set(), set()
    for event in db.execute("""SELECT request_id,actor_id,event_type,created_at FROM request_events
            WHERE event_type IN ('helper_applied','helper_accepted','offer_accepted','helper_assigned')""").fetchall():
        row = request_by_id.get(event["request_id"])
        moment = _date(event["created_at"])
        if not row or not moment or not (_date(row["created_at"]) <= moment <= now):
            continue
        if event["event_type"] in RESPONSE_EVENTS and event["actor_id"] is not None and event["actor_id"] != row["requester_id"]:
            responded.add(row["id"])
            seconds = (moment-_date(row["created_at"])).total_seconds()
            response_times[row["id"]] = min(response_times.get(row["id"], seconds), seconds)
        if event["event_type"] in ASSIGNMENT_EVENTS:
            assigned.add(row["id"])
    assigned.update(row["id"] for row in requests if row["helper_id"] is not None)
    completed = sum(row["status"] == "done" and bool(_date(row["completed_at"])) and _date(row["completed_at"]) <= now for row in requests)
    response_values = list(response_times.values())

    activity = defaultdict(set)
    for row in db.execute("SELECT user_id,day,created_at FROM pilot_activity_days").fetchall():
        if row["user_id"] in selected and within(row["created_at"]):
            activity[row["user_id"]].add(row["day"])
    repeated = sum(len(value) >= 2 for value in activity.values())
    all_activity = {(row["user_id"], row["day"]) for row in db.execute("SELECT user_id,day FROM pilot_activity_days").fetchall()}
    eligible, returned, immature, not_covered = 0, 0, 0, 0
    for user in registrations:
        if not user["email_verified"]:
            continue
        registered = _date(user["created_at"])
        if registered < measured_since:
            not_covered += 1
            continue
        target = registered.date()+timedelta(days=7)
        # A still-running UTC day is not a complete retention opportunity.
        # Wait until participants have had their entire seventh day to return.
        if target >= now.date():
            immature += 1
            continue
        eligible += 1
        returned += (user["user_id"], target.isoformat()) in all_activity

    views = {}
    for row in db.execute("SELECT user_id,service_id,created_at FROM pilot_service_views").fetchall():
        if row["user_id"] in selected and within(row["created_at"]):
            key = (row["user_id"], row["service_id"])
            moment = _date(row["created_at"])
            views[key] = min(views.get(key, moment), moment)
    inquiry_available = _has_table(db, "commercial_inquiries")
    inquiries = [dict(row) for row in db.execute("SELECT author_id,service_id,status,booking_id,created_at,accepted_at FROM commercial_inquiries").fetchall()
                 if row["author_id"] in selected and within(row["created_at"])] if inquiry_available else []
    accepted = sum(bool(_date(row["accepted_at"])) and _date(row["accepted_at"]) <= now for row in inquiries)
    converted = sum(bool(row["booking_id"]) and bool(_date(row["accepted_at"])) and _date(row["accepted_at"]) <= now for row in inquiries)
    converted_views = {(row["author_id"], row["service_id"]) for row in inquiries
                       if (row["author_id"], row["service_id"]) in views and _date(row["created_at"]) >= views[(row["author_id"], row["service_id"])]}

    work_dates = defaultdict(set)
    work_tables = ("commercial_clients", "commercial_services", "commercial_bookings", "commercial_objects",
                   "commercial_tasks", "commercial_estimates", "commercial_shifts", "commercial_professional_records")
    updated_tables = set(work_tables)-{"commercial_clients", "commercial_services"}
    live_owners = {row["user_id"] for row in db.execute("""SELECT user_id FROM commercial_profiles p
        WHERE NOT EXISTS(SELECT 1 FROM commercial_deleted_profiles d WHERE d.user_id=p.user_id)""").fetchall()}
    for table in work_tables:
        columns = "owner_id,created_at,updated_at" if table in updated_tables else "owner_id,created_at"
        for row in db.execute("SELECT "+columns+" FROM "+table).fetchall():
            if row["owner_id"] not in selected or row["owner_id"] not in live_owners:
                continue
            for key in ("created_at", "updated_at") if table in updated_tables else ("created_at",):
                if within(row[key]):
                    work_dates[row["owner_id"]].add(_date(row[key]).date().isoformat())
    work_repeated = sum(len(value) >= 2 for value in work_dates.values())
    return {
        "version": 1, "generated_at": now.isoformat(), "period": {"from": start.isoformat(), "to": now.isoformat(), "days": days, "timezone": "UTC"},
        "cohort": cohort, "cohorts": {key: distribution.get(key, 0) for key in sorted(COHORTS)},
        "registrations": {"created": len(registrations), "verified_now": verified, "confirmation": _ratio(verified, len(registrations))},
        "help": {"created": len(requests), "responded": len(responded), "assigned": len(assigned), "completed": completed,
                 "cancelled": sum(row["status"] == "cancelled" for row in requests),
                 "response_conversion": _ratio(len(responded), len(requests)), "completion_conversion": _ratio(completed, len(requests)),
                 "first_response": {"sample_size": len(response_values), "median_seconds": round(median(response_values), 1) if response_values else None}},
        "services": {"authenticated_viewer_service_pairs": len(views), "view_to_inquiry": _ratio(len(converted_views), len(views))},
        "inquiries": {"available": inquiry_available, "created": len(inquiries), "accepted": accepted, "converted_to_booking": converted,
                      "acceptance_conversion": _ratio(accepted, len(inquiries)), "booking_conversion": _ratio(converted, len(inquiries))},
        "activity": {"active_users": len(activity), "users_on_multiple_days": repeated, "repeat_conversion": _ratio(repeated, len(activity))},
        "work": {"active_workspaces": len(work_dates), "workspaces_on_multiple_days": work_repeated, "repeat_conversion": _ratio(work_repeated, len(work_dates))},
        "d7": {**_ratio(returned, eligible), "not_mature": immature, "before_measurement": not_covered},
        "quality": {"measurement_started_at": measured_since.isoformat(), "unclassified_users": distribution.get("unclassified", 0),
                    "classified_users": len(users)-distribution.get("unclassified", 0), "money_mode": "TEST_ONLY",
                    "notes": ["Группа задаётся администратором; существующие аккаунты автоматически не считаются реальными участниками.",
                              "Регистрация — в выбранном периоде; подтверждение email и результаты заявок показаны на текущий момент.",
                              "Медиана отклика использует только записанное действие другого участника, без подстановки времени назначения.",
                              "Просмотры охватывают только вошедших пользователей, не сотрудников своей организации; повтор одного человека и услуги в периоде объединён.",
                              "Активность учитывает явное взаимодействие в открытой вкладке; до начала измерений посещения не восстанавливаются.",
                              "D7 — возврат подтверждённого участника на седьмые сутки UTC; в знаменателе только полностью завершившиеся дни, незрелые и старые когорты исключены.",
                              "Рабочие действия считаются по созданию/изменению сохранённых записей, группа кабинета определяется по владельцу.",
                              "Удаление аккаунтов, организаций и записей может уменьшить исторические показатели. Тестовые суммы не являются выручкой."]}
    }
