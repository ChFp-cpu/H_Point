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
    CREATE TABLE IF NOT EXISTS commercial_deleted_profiles(
      user_id INTEGER PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
      deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_commercial_services_owner ON commercial_services(owner_id,active,id);
    CREATE INDEX IF NOT EXISTS idx_commercial_clients_owner ON commercial_clients(owner_id,active,id);
    CREATE INDEX IF NOT EXISTS idx_commercial_bookings_owner ON commercial_bookings(owner_id,starts_at);
    CREATE INDEX IF NOT EXISTS idx_commercial_renewals_owner ON commercial_renewals(owner_id,id);
    """
    if getattr(db, "is_postgres", False):
        schema = schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY").replace("INTEGER", "BIGINT")
    db.executescript(schema)
    from . import commercial_team
    commercial_team.initialize_schema(db)


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


def _user_id(value):
    if isinstance(value,bool) or not re.fullmatch(r"-?[0-9]{1,19}",str(value)):
        raise ValueError("Некорректный идентификатор организации или участника.")
    result=int(value)
    if not -(2**63)<result<2**63 or result==0:
        raise ValueError("Некорректный идентификатор организации или участника.")
    return result


def _user(db, uid, lock=False):
    suffix = " FOR NO KEY UPDATE" if lock and getattr(db, "is_postgres", False) else ""
    row = db.execute("SELECT * FROM users WHERE user_id=?" + suffix, (uid,)).fetchone()
    if not row or row["is_blocked"]:
        raise ValueError("Аккаунт недоступен.")
    if not row["email"] or not row["email_verified"]:
        raise ValueError("Подтвердите email, чтобы открыть коммерческий кабинет.")
    return row


def _profile(db, uid, lock=False, include_deleted=False):
    suffix = " FOR UPDATE" if lock and getattr(db, "is_postgres", False) else ""
    visible = "" if include_deleted else " AND NOT EXISTS (SELECT 1 FROM commercial_deleted_profiles d WHERE d.user_id=commercial_profiles.user_id)"
    return db.execute("SELECT * FROM commercial_profiles WHERE user_id=?" + visible + suffix, (uid,)).fetchone()


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


def _context(db, uid, owner_id=None, lock=False):
    """Resolve one explicitly authorised organisation; never trust a form owner."""
    _user(db, uid)
    if owner_id is None:
        own = _profile(db, uid)
        if own:
            owner_id = uid
        else:
            membership = db.execute("""SELECT m.owner_id FROM commercial_members m
                JOIN commercial_profiles p ON p.user_id=m.owner_id
                JOIN users u ON u.user_id=p.user_id
                WHERE m.user_id=? AND u.is_blocked=0
                AND NOT EXISTS(SELECT 1 FROM commercial_deleted_profiles d WHERE d.user_id=p.user_id)
                ORDER BY p.title,m.owner_id LIMIT 1""", (uid,)).fetchone()
            if not membership:
                return None, None, None
            owner_id = membership["owner_id"]
    owner_id = _user_id(owner_id)
    _user(db, owner_id, lock=lock)
    profile = _profile(db, owner_id, lock=lock)
    if not profile:
        if owner_id == uid:
            return None, None, None
        raise ValueError("Организация недоступна.")
    if owner_id == uid:
        role = "owner"
    else:
        member = db.execute("SELECT role FROM commercial_members WHERE owner_id=? AND user_id=?", (owner_id,uid)).fetchone()
        if not member:
            raise PermissionError("Нет доступа к этой организации.")
        role = member["role"]
    return owner_id, profile, role


def save_profile(db, uid, data, owner_id=None):
    kind = data.get("kind")
    if not isinstance(kind,str) or kind not in KINDS:
        raise ValueError("Выберите тип кабинета.")
    title = _text(data, "title", 120, True)
    description = _text(data, "description", 2000)
    contact = _text(data, "contact", 240)
    owner_id = uid if owner_id is None else _user_id(owner_id)
    db.execute("BEGIN IMMEDIATE")
    try:
        _user(db, uid)
        _user(db, owner_id, lock=True)
        if owner_id != uid:
            _,_,role = _context(db,uid,owner_id)
            if role not in ("owner","admin"):raise PermissionError("Изменять организацию может только руководитель.")
        profile = _profile(db, owner_id, lock=True, include_deleted=True)
        deleted = db.execute("SELECT 1 FROM commercial_deleted_profiles WHERE user_id=?", (owner_id,)).fetchone()
        if profile:
            if not deleted:
                _active(profile)
            db.execute("UPDATE commercial_profiles SET kind=?,title=?,description=?,contact=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?", (kind,title,description,contact,owner_id))
            db.execute("DELETE FROM commercial_deleted_profiles WHERE user_id=?", (owner_id,))
        else:
            now = _now()
            db.execute("INSERT INTO commercial_profiles(user_id,kind,title,description,contact,trial_started_at,trial_until) VALUES(?,?,?,?,?,?,?)", (owner_id,kind,title,description,contact,now.isoformat(),(now+timedelta(days=TRIAL_DAYS)).isoformat()))
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return dashboard(db, uid, owner_id)


def delete_profile(db, uid, confirmed=False, owner_id=None):
    """Erase private workspace content while retaining payment/trial history.

    The tombstone hides the profile from all reads. Keeping its access dates and
    renewal keys prevents delete/recreate from granting another trial or charge.
    """
    if confirmed is not True:
        raise ValueError("Подтвердите удаление кабинета.")
    if owner_id is not None and _user_id(owner_id) != uid:
        raise PermissionError("Удалить организацию может только её владелец.")
    db.execute("BEGIN IMMEDIATE")
    try:
        _user(db, uid, lock=True)
        profile = _profile(db, uid, lock=True, include_deleted=True)
        already_deleted = db.execute("SELECT 1 FROM commercial_deleted_profiles WHERE user_id=?", (uid,)).fetchone()
        if not profile or already_deleted:
            db.execute("COMMIT")
            return {"deleted":False}
        from . import commercial_team
        commercial_team.erase_workspace(db,uid)
        for table in ("commercial_bookings", "commercial_clients", "commercial_services"):
            db.execute("DELETE FROM " + table + " WHERE owner_id=?", (uid,))
        db.execute("UPDATE commercial_profiles SET kind='other',title='',description='',contact='',updated_at=CURRENT_TIMESTAMP WHERE user_id=?", (uid,))
        db.execute("INSERT INTO commercial_deleted_profiles(user_id) VALUES(?)", (uid,))
        db.execute("COMMIT")
        return {"deleted":True}
    except Exception:
        db.execute("ROLLBACK")
        raise


def renew(db, uid, purchase_key, add_wallet_entry=None, owner_id=None):
    """Spend test funds and extend by 30 days, atomically and idempotently."""
    if owner_id is not None and _user_id(owner_id) != uid:
        raise PermissionError("Продлить подписку может только владелец организации.")
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


def _mutate(db, uid, function, owner_id=None, manage=False, allow_expired=False):
    db.execute("BEGIN IMMEDIATE")
    try:
        owner,profile,role = _context(db,uid,owner_id,lock=True)
        if not profile:raise ValueError("Сначала создайте коммерческий кабинет.")
        if manage and role not in ("owner","admin"):
            raise PermissionError("Это действие доступно только руководителям организации.")
        if not allow_expired:_active(profile)
        result = function(owner)
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


def save_service(db,uid,data,owner_id=None):
    title=_text(data,"title",120,True)
    description=_text(data,"description",2000)
    price=_integer(data.get("price_rub",0),0,1_000_000)
    duration=_integer(data.get("duration_minutes",60),5,1440)
    active=data.get("active",True)
    if not isinstance(active,bool):raise ValueError("Проверьте статус услуги.")
    item_id=_integer(data["id"],1,2**63-1) if data.get("id") is not None else None
    def save(owner):
        if item_id:
            _owned(db,"commercial_services",owner,item_id)
            db.execute("UPDATE commercial_services SET title=?,description=?,price_rub=?,duration_minutes=?,active=? WHERE id=? AND owner_id=?",(title,description,price,duration,int(active),item_id,owner))
            return item_id
        return _insert_id(db,"INSERT INTO commercial_services(owner_id,title,description,price_rub,duration_minutes,active) VALUES(?,?,?,?,?,?)",(owner,title,description,price,duration,int(active)))
    return {"id":_mutate(db,uid,save,owner_id,manage=True)}


def save_client(db,uid,data,owner_id=None):
    name=_text(data,"name",120,True)
    contact=_text(data,"contact",240)
    notes=_text(data,"notes",4000)
    active=data.get("active",True)
    if not isinstance(active,bool):raise ValueError("Проверьте статус клиента.")
    item_id=_integer(data["id"],1,2**63-1) if data.get("id") is not None else None
    def save(owner):
        if item_id:
            _owned(db,"commercial_clients",owner,item_id)
            db.execute("UPDATE commercial_clients SET name=?,contact=?,notes=?,active=? WHERE id=? AND owner_id=?",(name,contact,notes,int(active),item_id,owner))
            return item_id
        return _insert_id(db,"INSERT INTO commercial_clients(owner_id,name,contact,notes,active) VALUES(?,?,?,?,?)",(owner,name,contact,notes,int(active)))
    return {"id":_mutate(db,uid,save,owner_id,manage=True)}


def save_booking(db,uid,data,owner_id=None):
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
    def save(owner):
        from . import commercial_team
        assignee= commercial_team.assignee(db,owner,data.get("assignee_id"))
        obj= commercial_team.object_id(db,owner,data.get("object_id"))
        if assignee is not None and status=="planned":
            commercial_team.check_booking_overlap(db,owner,assignee,starts,starts+timedelta(minutes=duration),item_id)
        _owned(db,"commercial_clients",owner,client_id)
        if service_id:_owned(db,"commercial_services",owner,service_id)
        if item_id:
            _owned(db,"commercial_bookings",owner,item_id)
            db.execute("UPDATE commercial_bookings SET client_id=?,service_id=?,title=?,starts_at=?,duration_minutes=?,price_rub=?,status=?,notes=?,assignee_id=?,object_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner_id=?",(client_id,service_id,title,starts.isoformat(),duration,price,status,notes,assignee,obj,item_id,owner))
            return item_id
        return _insert_id(db,"INSERT INTO commercial_bookings(owner_id,client_id,service_id,title,starts_at,duration_minutes,price_rub,status,notes,assignee_id,object_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(owner,client_id,service_id,title,starts.isoformat(),duration,price,status,notes,assignee,obj))
    return {"id":_mutate(db,uid,save,owner_id,manage=False)}


def set_booking_status(db,uid,item_id,status,owner_id=None):
    item_id=_integer(item_id,1,2**63-1)
    if not isinstance(status,str) or status not in BOOKING_STATUSES:raise ValueError("Неизвестный статус записи.")
    def save(owner):
        row=_owned(db,"commercial_bookings",owner,item_id)
        if status=="planned" and row["assignee_id"] is not None:
            from . import commercial_team
            start=_date(row["starts_at"])
            commercial_team.assignee(db,owner,row["assignee_id"])
            commercial_team.check_booking_overlap(db,owner,row["assignee_id"],start,start+timedelta(minutes=row["duration_minutes"]),item_id)
        db.execute("UPDATE commercial_bookings SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner_id=?",(status,item_id,owner))
        return {"id":item_id,"status":status}
    return _mutate(db,uid,save,owner_id,manage=False)


def _dashboard_core(db,uid):
    _user(db,uid)
    row=_profile(db,uid)
    prior=_profile(db,uid,include_deleted=True)
    base={"price_rub":PRICE_RUB,"trial_days":TRIAL_DAYS,"kinds":KINDS,"currency":"TEST_RUB","trial_available":prior is None}
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


def _summary_core(db,uid):
    """Small private home-page overview; contacts and notes never leave here."""
    _user(db,uid)
    profile=_profile(db,uid)
    if not profile:
        return {"exists":False}
    now=_now()
    end=_until(profile)
    counts=db.execute("""SELECT
        (SELECT COUNT(*) FROM commercial_clients WHERE owner_id=? AND active=1) clients,
        (SELECT COUNT(*) FROM commercial_services WHERE owner_id=? AND active=1) services,
        (SELECT COUNT(*) FROM commercial_bookings WHERE owner_id=? AND status='planned') planned,
        (SELECT COUNT(*) FROM commercial_bookings WHERE owner_id=? AND status='completed') completed,
        (SELECT COALESCE(SUM(price_rub),0) FROM commercial_bookings WHERE owner_id=? AND status='completed') revenue
        """,(uid,uid,uid,uid,uid)).fetchone()
    upcoming=db.execute("""SELECT b.id,b.title,b.starts_at,c.name client_name
        FROM commercial_bookings b JOIN commercial_clients c ON c.id=b.client_id
        WHERE b.owner_id=? AND b.status='planned' AND b.starts_at>=?
        ORDER BY b.starts_at,b.id LIMIT 3""",(uid,now.isoformat())).fetchall()
    return {"exists":True,"title":profile["title"],"kind":profile["kind"],
        "kind_title":KINDS.get(profile["kind"],"Специалист"),"active":end>now,
        "trial_active":_date(profile["trial_until"])>now,"access_until":end.isoformat(),
        "days_remaining":max(0,int((end-now).total_seconds()+86399)//86400),
        "metrics":{"clients":int(counts["clients"]),"services":int(counts["services"]),
            "planned":int(counts["planned"]),"completed":int(counts["completed"]),
            "revenue_test_rub":int(counts["revenue"])},
        "next_appointments":[dict(row) for row in upcoming]}


def dashboard(db,uid,owner_id=None):
    from . import commercial_team
    owner,profile,role = _context(db,uid,owner_id)
    data = _dashboard_core(db,owner if owner is not None else uid)
    return commercial_team.enrich_dashboard(db,uid,owner,role,data)


def summary(db,uid,owner_id=None):
    owner,profile,role = _context(db,uid,owner_id)
    if owner is None:return {"exists":False}
    data = _summary_core(db,owner)
    data.update(owner_id=owner,role=role)
    return data


def public_organization(db,slug):
    from . import commercial_team
    return commercial_team.public_organization(db,slug)


def public_services(db):
    from . import commercial_team
    return commercial_team.public_services(db)


def post_action(db,uid,path,data,add_wallet_entry=None):
    """Authenticated route adapter. Organisation selection is always authorised."""
    if not isinstance(data,dict):raise ValueError("Проверьте данные формы.")
    owner=data.get("owner_id",data.get("organization_id"))
    if path=="/api/commercial/profile":return save_profile(db,uid,data,owner)
    if path=="/api/commercial/delete":return delete_profile(db,uid,data.get("confirm"),owner)
    if path=="/api/commercial/renew":return renew(db,uid,data.get("purchase_key"),add_wallet_entry,owner)
    if path=="/api/commercial/services":return save_service(db,uid,data,owner)
    if path=="/api/commercial/clients":return save_client(db,uid,data,owner)
    if path=="/api/commercial/bookings":return save_booking(db,uid,data,owner)
    if path=="/api/commercial/bookings/status":return set_booking_status(db,uid,data.get("id"),data.get("status"),owner)
    from . import commercial_team
    return commercial_team.post_action(db,uid,path,data,owner)
