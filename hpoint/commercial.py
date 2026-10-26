"""Private workspaces for coaches, contractors and organisations.

All money in this module is explicitly test money. ``db`` is supplied by the
caller, so web, migrations and isolated tests share the same transactions.
"""
from datetime import datetime, timedelta, timezone
import re


PRICE_RUB = 490
TRIAL_DAYS = 7
KINDS = {"trainer": "Тренер", "organization": "Организация", "foreman": "Прораб", "other": "Специалист"}
BOOKING_STATUSES = {"planned", "completed", "cancelled"}


def initialize_schema(db):
    schema = """
    CREATE TABLE IF NOT EXISTS commercial_profiles(
      user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
      kind TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
      contact TEXT NOT NULL DEFAULT '', trial_started_at TEXT NOT NULL,
      trial_until TEXT NOT NULL, paid_until TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS commercial_services(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', price_rub INTEGER NOT NULL DEFAULT 0,
      duration_minutes INTEGER NOT NULL DEFAULT 60, active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS commercial_clients(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      name TEXT NOT NULL, contact TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
      active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS commercial_bookings(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      client_id INTEGER NOT NULL REFERENCES commercial_clients(id),
      service_id INTEGER REFERENCES commercial_services(id), title TEXT NOT NULL,
      starts_at TEXT NOT NULL, duration_minutes INTEGER NOT NULL DEFAULT 60,
      price_rub INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'planned',
      notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS commercial_renewals(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      purchase_key TEXT NOT NULL UNIQUE, price_rub INTEGER NOT NULL,
      starts_at TEXT NOT NULL, ends_at TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_commercial_services_owner ON commercial_services(owner_id,active,id);
    CREATE INDEX IF NOT EXISTS idx_commercial_clients_owner ON commercial_clients(owner_id,active,id);
    CREATE INDEX IF NOT EXISTS idx_commercial_bookings_owner ON commercial_bookings(owner_id,starts_at);
    CREATE INDEX IF NOT EXISTS idx_commercial_renewals_owner ON commercial_renewals(owner_id,id);
    """
    if getattr(db, "is_postgres", False):
        schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace("INTEGER", "BIGINT")
    db.executescript(schema)


def _now():
    return datetime.now(timezone.utc)


def _date(value):
    date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Укажите время с часовым поясом.")
    return date.astimezone(timezone.utc)


def _text(data, field, maximum, required=False):
    value = data.get(field, "")
    if not isinstance(value, str):
        raise ValueError("Проверьте текстовые поля.")
    value = value.strip()
    if len(value) > maximum or (required and len(value) < 2):
        raise ValueError(f"Поле «{field}»: от {2 if required else 0} до {maximum} символов.")
    return value


def _integer(value, minimum, maximum):
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
        raise ValueError("Укажите целое положительное число.")
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"Допустимое значение: от {minimum} до {maximum}.")
    return result


def _user(db, uid, lock=False):
    suffix = " FOR NO KEY UPDATE" if lock and getattr(db, "is_postgres", False) else ""
    row = db.execute("SELECT * FROM users WHERE user_id=?" + suffix, (uid,)).fetchone()
    if not row or row["is_blocked"]:
        raise ValueError("Аккаунт недоступен.")
    if not row["email"] or not row["email_verified"]:
        raise ValueError("Подтвердите email, чтобы открыть коммерческий кабинет.")
    return row


def _profile(db, uid, lock=False):
    suffix = " FOR UPDATE" if lock and getattr(db, "is_postgres", False) else ""
    return db.execute("SELECT * FROM commercial_profiles WHERE user_id=?" + suffix, (uid,)).fetchone()


def _until(profile):
    dates = [_date(profile["trial_until"])]
    if profile["paid_until"]:
        dates.append(_date(profile["paid_until"]))
    return max(dates)


def _active(profile):
    if not profile:
        raise ValueError("Сначала создайте коммерческий кабинет.")
    if _until(profile) <= _now():
        raise ValueError("Пробный период завершён. Продлите кабинет за 490 тестовых ₽ на 30 дней.")


def _insert_id(db, sql, args):
    if getattr(db, "is_postgres", False):
        return db.execute(sql + " RETURNING id", args).fetchone()["id"]
    return db.execute(sql, args).lastrowid


def save_profile(db, uid, data):
    kind = data.get("kind")
    if not isinstance(kind,str) or kind not in KINDS:
        raise ValueError("Выберите тип кабинета.")
    title = _text(data, "title", 120, True)
    description = _text(data, "description", 2000)
    contact = _text(data, "contact", 240)
    db.execute("BEGIN IMMEDIATE")
    try:
        _user(db, uid, lock=True)
        profile = _profile(db, uid, lock=True)
        if profile:
            _active(profile)
            db.execute("UPDATE commercial_profiles SET kind=?,title=?,description=?,contact=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?", (kind,title,description,contact,uid))
        else:
            now = _now()
            db.execute("INSERT INTO commercial_profiles(user_id,kind,title,description,contact,trial_started_at,trial_until) VALUES(?,?,?,?,?,?,?)", (uid,kind,title,description,contact,now.isoformat(),(now+timedelta(days=TRIAL_DAYS)).isoformat()))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return dashboard(db, uid)


def renew(db, uid, purchase_key, add_wallet_entry=None):
    """Spend test funds and extend by 30 days, atomically and idempotently."""
    if not isinstance(purchase_key, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{8,100}", purchase_key):
        raise ValueError("Обновите страницу и повторите продление.")
    db.execute("BEGIN IMMEDIATE")
    try:
        _user(db, uid, lock=True)
        profile = _profile(db, uid, lock=True)
        if not profile:
            raise ValueError("Сначала создайте коммерческий кабинет.")
        existing = db.execute("SELECT * FROM commercial_renewals WHERE purchase_key=?", (purchase_key,)).fetchone()
        if existing:
            if existing["owner_id"] != uid:
                raise ValueError("Ключ продления уже использован.")
            db.execute("COMMIT")
            return {"created": False, "ends_at": existing["ends_at"], "price_rub": PRICE_RUB}
        available = int(db.execute("SELECT COALESCE(SUM(test_amount_rub),0) amount FROM wallet_transactions WHERE user_id=?",(uid,)).fetchone()["amount"])
        if available < PRICE_RUB:
            raise ValueError("Для продления нужно 490 тестовых ₽ в кошельке.")
        start = max(_now(), _until(profile))
        end = start + timedelta(days=30)
        reference = "commercial-renewal:" + purchase_key
        if add_wallet_entry is None:
            inserted = db.execute("""INSERT OR IGNORE INTO wallet_transactions(user_id,amount_rub,test_amount_rub,kind,description,reference)
                VALUES(?,?,?,'commercial_subscription','Коммерческий кабинет · 30 дней (тестовая оплата)',?)""", (uid,-PRICE_RUB,-PRICE_RUB,reference)).rowcount
        else:
            inserted = add_wallet_entry(uid,-PRICE_RUB,"commercial_subscription","Коммерческий кабинет · 30 дней (тестовая оплата)",reference,test_amount_rub=-PRICE_RUB)
        if not inserted:
            raise ValueError("Это продление уже обработано. Обновите страницу.")
        db.execute("INSERT INTO commercial_renewals(owner_id,purchase_key,price_rub,starts_at,ends_at) VALUES(?,?,?,?,?)", (uid,purchase_key,PRICE_RUB,start.isoformat(),end.isoformat()))
        db.execute("UPDATE commercial_profiles SET paid_until=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",(end.isoformat(),uid))
        db.execute("COMMIT")
        return {"created":True,"ends_at":end.isoformat(),"price_rub":PRICE_RUB}
    except Exception:
        db.execute("ROLLBACK")
        raise


def _mutate(db, uid, function):
    db.execute("BEGIN IMMEDIATE")
    try:
        _user(db,uid,lock=True)
        _active(_profile(db,uid,lock=True))
        result = function()
        db.execute("COMMIT")
        return result
    except Exception:
        db.execute("ROLLBACK")
        raise


def _owned(db, table, uid, item_id):
    row=db.execute(f"SELECT * FROM {table} WHERE id=? AND owner_id=?",(item_id,uid)).fetchone()
    if not row:
        raise ValueError("Запись не найдена в вашем кабинете.")
    return row


def save_service(db,uid,data):
    title=_text(data,"title",120,True)
    description=_text(data,"description",2000)
    price=_integer(data.get("price_rub",0),0,1_000_000)
    duration=_integer(data.get("duration_minutes",60),5,1440)
    active=data.get("active",True)
    if not isinstance(active,bool):raise ValueError("Проверьте статус услуги.")
    item_id=_integer(data["id"],1,2**63-1) if data.get("id") is not None else None
    def save():
        if item_id:
            _owned(db,"commercial_services",uid,item_id)
            db.execute("UPDATE commercial_services SET title=?,description=?,price_rub=?,duration_minutes=?,active=? WHERE id=? AND owner_id=?",(title,description,price,duration,int(active),item_id,uid))
            return item_id
        return _insert_id(db,"INSERT INTO commercial_services(owner_id,title,description,price_rub,duration_minutes,active) VALUES(?,?,?,?,?,?)",(uid,title,description,price,duration,int(active)))
    return {"id":_mutate(db,uid,save)}


def save_client(db,uid,data):
    name=_text(data,"name",120,True)
    contact=_text(data,"contact",240)
    notes=_text(data,"notes",4000)
    active=data.get("active",True)
    if not isinstance(active,bool):raise ValueError("Проверьте статус клиента.")
    item_id=_integer(data["id"],1,2**63-1) if data.get("id") is not None else None
    def save():
        if item_id:
            _owned(db,"commercial_clients",uid,item_id)
            db.execute("UPDATE commercial_clients SET name=?,contact=?,notes=?,active=? WHERE id=? AND owner_id=?",(name,contact,notes,int(active),item_id,uid))
            return item_id
        return _insert_id(db,"INSERT INTO commercial_clients(owner_id,name,contact,notes,active) VALUES(?,?,?,?,?)",(uid,name,contact,notes,int(active)))
    return {"id":_mutate(db,uid,save)}


def save_booking(db,uid,data):
    item_id=_integer(data["id"],1,2**63-1) if data.get("id") is not None else None
    client_id=_integer(data.get("client_id"),1,2**63-1)
    service_id=_integer(data["service_id"],1,2**63-1) if data.get("service_id") is not None else None
    status=data.get("status","planned")
    if not isinstance(status,str) or status not in BOOKING_STATUSES:raise ValueError("Неизвестный статус записи.")
    title=_text(data,"title",160,True)
    notes=_text(data,"notes",4000)
    try:starts=_date(data.get("starts_at"))
    except (ValueError,TypeError):raise ValueError("Укажите дату и время записи с часовым поясом.")
    price=_integer(data.get("price_rub",0),0,1_000_000)
    duration=_integer(data.get("duration_minutes",60),5,1440)
    def save():
        _owned(db,"commercial_clients",uid,client_id)
        if service_id:_owned(db,"commercial_services",uid,service_id)
        if item_id:
            _owned(db,"commercial_bookings",uid,item_id)
            db.execute("UPDATE commercial_bookings SET client_id=?,service_id=?,title=?,starts_at=?,duration_minutes=?,price_rub=?,status=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner_id=?",(client_id,service_id,title,starts.isoformat(),duration,price,status,notes,item_id,uid))
            return item_id
        return _insert_id(db,"INSERT INTO commercial_bookings(owner_id,client_id,service_id,title,starts_at,duration_minutes,price_rub,status,notes) VALUES(?,?,?,?,?,?,?,?,?)",(uid,client_id,service_id,title,starts.isoformat(),duration,price,status,notes))
    return {"id":_mutate(db,uid,save)}


def set_booking_status(db,uid,item_id,status):
    item_id=_integer(item_id,1,2**63-1)
    if not isinstance(status,str) or status not in BOOKING_STATUSES:raise ValueError("Неизвестный статус записи.")
    def save():
        _owned(db,"commercial_bookings",uid,item_id)
        db.execute("UPDATE commercial_bookings SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner_id=?",(status,item_id,uid))
        return {"id":item_id,"status":status}
    return _mutate(db,uid,save)


def dashboard(db,uid):
    _user(db,uid)
    row=_profile(db,uid)
    base={"price_rub":PRICE_RUB,"trial_days":TRIAL_DAYS,"kinds":KINDS,"currency":"TEST_RUB"}
    if not row:return {**base,"profile":None,"services":[],"clients":[],"bookings":[],"renewals":[],"metrics":{}}
    profile=dict(row)
    end=_until(row)
    now=_now()
    profile.update(kind_title=KINDS.get(row["kind"],"Специалист"),active=end>now,access_until=end.isoformat(),trial_active=_date(row["trial_until"])>now,days_remaining=max(0,int((end-now).total_seconds()+86399)//86400))
    services=[dict(r) for r in db.execute("SELECT * FROM commercial_services WHERE owner_id=? ORDER BY active DESC,id DESC",(uid,)).fetchall()]
    clients=[dict(r) for r in db.execute("SELECT * FROM commercial_clients WHERE owner_id=? ORDER BY active DESC,name,id",(uid,)).fetchall()]
    bookings=[dict(r) for r in db.execute("""SELECT b.*,c.name client_name FROM commercial_bookings b
        JOIN commercial_clients c ON c.id=b.client_id WHERE b.owner_id=? ORDER BY b.starts_at DESC,b.id DESC LIMIT 300""",(uid,)).fetchall()]
    totals=db.execute("""SELECT COUNT(*) total,
        COALESCE(SUM(CASE WHEN status='planned' THEN 1 ELSE 0 END),0) planned,
        COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),0) completed,
        COALESCE(SUM(CASE WHEN status='completed' THEN price_rub ELSE 0 END),0) revenue
        FROM commercial_bookings WHERE owner_id=?""",(uid,)).fetchone()
    renewals=[dict(r) for r in db.execute("SELECT price_rub,starts_at,ends_at,created_at FROM commercial_renewals WHERE owner_id=? ORDER BY id DESC LIMIT 20",(uid,)).fetchall()]
    return {**base,"profile":profile,"services":services,"clients":clients,"bookings":bookings,"renewals":renewals,
            "metrics":{"clients":sum(bool(c["active"]) for c in clients),"services":sum(bool(s["active"]) for s in services),"planned":int(totals["planned"]),"completed":int(totals["completed"]),"revenue_test_rub":int(totals["revenue"])}}


def post_action(db,uid,path,data,add_wallet_entry=None):
    """Small adapter for authenticated web routes; raises ValueError on input errors."""
    if not isinstance(data,dict):raise ValueError("Проверьте данные формы.")
    if path=="/api/commercial/profile":return save_profile(db,uid,data)
    if path=="/api/commercial/renew":return renew(db,uid,data.get("purchase_key"),add_wallet_entry)
    if path=="/api/commercial/services":return save_service(db,uid,data)
    if path=="/api/commercial/clients":return save_client(db,uid,data)
    if path=="/api/commercial/bookings":return save_booking(db,uid,data)
    if path=="/api/commercial/bookings/status":return set_booking_status(db,uid,data.get("id"),data.get("status"))
    raise ValueError("Неизвестное действие кабинета.")
