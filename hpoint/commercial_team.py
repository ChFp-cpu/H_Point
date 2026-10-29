"""Organisation collaboration, planning and explicitly public service listings.

Every write is serialised on the organisation owner, before checking membership.
Private clients, internal notes and employee email addresses never enter public DTOs.
Amounts describe test estimates and bookkeeping, never a transfer of real funds.
"""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import re

from . import commercial as c

OBJECT_STATUSES = {"planned", "active", "completed", "cancelled"}
TASK_STATUSES = {"todo", "in_progress", "done", "cancelled"}
ESTIMATE_STATUSES = {"draft", "approved", "completed", "cancelled"}
CENT = Decimal("0.01")


def initialize_schema(db):
    schema = """
    CREATE TABLE IF NOT EXISTS commercial_members(
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      role TEXT NOT NULL DEFAULT 'member', joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(owner_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS commercial_invitations(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      email TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'member', status TEXT NOT NULL DEFAULT 'pending',
      expires_at TEXT NOT NULL, invited_by INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(owner_id,email)
    );
    CREATE TABLE IF NOT EXISTS commercial_objects(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      title TEXT NOT NULL, address TEXT NOT NULL DEFAULT '',
      client_id INTEGER REFERENCES commercial_clients(id) ON DELETE SET NULL,
      assignee_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
      status TEXT NOT NULL DEFAULT 'planned', budget_rub INTEGER NOT NULL DEFAULT 0,
      actual_rub INTEGER NOT NULL DEFAULT 0, starts_on TEXT NOT NULL DEFAULT '', ends_on TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS commercial_tasks(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      title TEXT NOT NULL, object_id INTEGER REFERENCES commercial_objects(id) ON DELETE SET NULL,
      assignee_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
      status TEXT NOT NULL DEFAULT 'todo', due_at TEXT, notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS commercial_estimates(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      title TEXT NOT NULL, object_id INTEGER REFERENCES commercial_objects(id) ON DELETE SET NULL,
      status TEXT NOT NULL DEFAULT 'draft', markup_percent TEXT NOT NULL DEFAULT '0.00',
      items_json TEXT NOT NULL DEFAULT '[]', subtotal_rub TEXT NOT NULL DEFAULT '0.00',
      total_rub TEXT NOT NULL DEFAULT '0.00', cost_rub TEXT NOT NULL DEFAULT '0.00',
      profit_rub TEXT NOT NULL DEFAULT '0.00', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS commercial_shifts(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      title TEXT NOT NULL, assignee_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
      object_id INTEGER REFERENCES commercial_objects(id) ON DELETE SET NULL,
      starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS commercial_public_profiles(
      owner_id INTEGER PRIMARY KEY REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      slug TEXT NOT NULL UNIQUE, published INTEGER NOT NULL DEFAULT 0,
      description TEXT NOT NULL DEFAULT '', contact TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '',
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_commercial_members_user ON commercial_members(user_id,owner_id);
    CREATE INDEX IF NOT EXISTS idx_commercial_invitations_email ON commercial_invitations(email,status);
    CREATE INDEX IF NOT EXISTS idx_commercial_objects_owner ON commercial_objects(owner_id,status,id);
    CREATE INDEX IF NOT EXISTS idx_commercial_tasks_owner ON commercial_tasks(owner_id,status,id);
    CREATE INDEX IF NOT EXISTS idx_commercial_estimates_owner ON commercial_estimates(owner_id,id);
    CREATE INDEX IF NOT EXISTS idx_commercial_shifts_owner ON commercial_shifts(owner_id,assignee_id,starts_at);
    """
    if getattr(db,"is_postgres",False):
        schema=schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT","BIGSERIAL PRIMARY KEY").replace("INTEGER","BIGINT")
    db.executescript(schema)
    for table,field,definition in (
        ("commercial_services","published","INTEGER NOT NULL DEFAULT 0"),
        ("commercial_bookings","assignee_id","INTEGER REFERENCES users(user_id) ON DELETE SET NULL"),
        ("commercial_bookings","object_id","INTEGER REFERENCES commercial_objects(id) ON DELETE SET NULL"),
    ):
        if getattr(db,"is_postgres",False):
            db.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {field} {definition.replace('INTEGER','BIGINT')}")
        elif field not in {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {field} {definition}")
    db.execute("CREATE INDEX IF NOT EXISTS idx_commercial_bookings_assignee ON commercial_bookings(owner_id,assignee_id,status,starts_at)")


def erase_workspace(db,owner):
    for table in ("commercial_shifts","commercial_tasks","commercial_estimates","commercial_objects",
                  "commercial_public_profiles","commercial_invitations","commercial_members"):
        db.execute("DELETE FROM "+table+" WHERE owner_id=?",(owner,))


def _id(data,key="id"):
    return c._integer(data[key],1,2**63-1) if data.get(key) not in (None,"") else None


def assignee(db,owner,value):
    if value in (None,""):return None
    uid=c._user_id(value)
    c._user(db,uid)
    if uid!=owner and not db.execute("SELECT 1 FROM commercial_members WHERE owner_id=? AND user_id=?",(owner,uid)).fetchone():
        raise ValueError("Ответственный должен состоять в этой организации.")
    return uid


def object_id(db,owner,value):
    if value in (None,""):return None
    item=c._integer(value,1,2**63-1)
    c._owned(db,"commercial_objects",owner,item)
    return item


def _status(value,allowed):
    if not isinstance(value,str) or value not in allowed:raise ValueError("Неизвестный статус.")
    return value


def _day(value):
    if value in (None,""):return ""
    if not isinstance(value,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",value):
        raise ValueError("Укажите дату в формате ГГГГ-ММ-ДД.")
    try:return date.fromisoformat(value).isoformat()
    except ValueError:raise ValueError("Проверьте календарную дату.")


def _moment(value,optional=False):
    if optional and value in (None,""):return None
    try:return c._date(value)
    except (ValueError,TypeError,OverflowError):raise ValueError("Укажите дату и время с часовым поясом.")


def _upsert(db,table,owner,item,values):
    if item:
        c._owned(db,table,owner,item)
        sets=",".join(key+"=?" for key in values)
        db.execute(f"UPDATE {table} SET {sets},updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner_id=?",tuple(values.values())+(item,owner))
        return {"id":item}
    keys=",".join(values)
    marks=",".join("?" for _ in values)
    return {"id":c._insert_id(db,f"INSERT INTO {table}(owner_id,{keys}) VALUES(?,{marks})",(owner,*values.values()))}


def save_object(db,uid,data,owner_id=None):
    item=_id(data)
    values=dict(title=c._text(data,"title",160,True),address=c._text(data,"address",400),
                status=_status(data.get("status","planned"),OBJECT_STATUSES),
                budget_rub=c._integer(data.get("budget_rub",0),0,1_000_000_000),
                actual_rub=c._integer(data.get("actual_rub",0),0,1_000_000_000),
                starts_on=_day(data.get("starts_on")),ends_on=_day(data.get("ends_on")),notes=c._text(data,"notes",4000))
    if values["starts_on"] and values["ends_on"] and values["ends_on"]<values["starts_on"]:
        raise ValueError("Дата окончания должна быть не раньше начала.")
    def save(owner):
        client=_id(data,"client_id")
        if client:c._owned(db,"commercial_clients",owner,client)
        return _upsert(db,"commercial_objects",owner,item,{**values,"client_id":client,"assignee_id":assignee(db,owner,data.get("assignee_id"))})
    return c._mutate(db,uid,save,owner_id)


def save_task(db,uid,data,owner_id=None):
    item=_id(data)
    due=_moment(data.get("due_at"),True)
    values=dict(title=c._text(data,"title",160,True),status=_status(data.get("status","todo"),TASK_STATUSES),
                due_at=due.isoformat() if due else None,notes=c._text(data,"notes",4000))
    def save(owner):
        return _upsert(db,"commercial_tasks",owner,item,{**values,"object_id":object_id(db,owner,data.get("object_id")),"assignee_id":assignee(db,owner,data.get("assignee_id"))})
    return c._mutate(db,uid,save,owner_id)


def set_task_status(db,uid,data,owner_id=None):
    item=c._integer(data.get("id"),1,2**63-1)
    status=_status(data.get("status"),TASK_STATUSES)
    def save(owner):return _upsert(db,"commercial_tasks",owner,item,{"status":status})
    return c._mutate(db,uid,save,owner_id)


def check_booking_overlap(db,owner,person,start,end,exclude=None):
    # UTC strings are canonical, but legacy strings may have offsets: compare instants.
    rows=db.execute("SELECT id,starts_at,duration_minutes FROM commercial_bookings WHERE owner_id=? AND assignee_id=? AND status='planned'",(owner,person)).fetchall()
    for row in rows:
        other=c._date(row["starts_at"])
        if row["id"]!=exclude and start<other+timedelta(minutes=row["duration_minutes"]) and end>other:
            raise ValueError("У сотрудника уже есть запись на это время.")


def save_shift(db,uid,data,owner_id=None):
    item=_id(data)
    start,end=_moment(data.get("starts_at")),_moment(data.get("ends_at"))
    if end-start<timedelta(minutes=1) or end-start>timedelta(days=7):raise ValueError("Смена должна длиться от одной минуты до 7 дней.")
    title=c._text(data,"title",160,True);notes=c._text(data,"notes",4000)
    def save(owner):
        person=assignee(db,owner,data.get("assignee_id"))
        if person is None:raise ValueError("Выберите сотрудника для смены.")
        for row in db.execute("SELECT id,starts_at,ends_at FROM commercial_shifts WHERE owner_id=? AND assignee_id=?",(owner,person)).fetchall():
            if row["id"]!=item and start<c._date(row["ends_at"]) and end>c._date(row["starts_at"]):
                raise ValueError("Смены этого сотрудника пересекаются.")
        return _upsert(db,"commercial_shifts",owner,item,dict(title=title,assignee_id=person,object_id=object_id(db,owner,data.get("object_id")),starts_at=start.isoformat(),ends_at=end.isoformat(),notes=notes))
    return c._mutate(db,uid,save,owner_id)


def delete_shift(db,uid,data,owner_id=None):
    item=c._integer(data.get("id"),1,2**63-1)
    def remove(owner):
        c._owned(db,"commercial_shifts",owner,item)
        db.execute("DELETE FROM commercial_shifts WHERE id=? AND owner_id=?",(item,owner))
        return {"id":item,"deleted":True}
    return c._mutate(db,uid,remove,owner_id)


def _decimal(value,maximum,positive=False):
    if isinstance(value,bool) or not isinstance(value,(str,int,float,Decimal)) or len(str(value))>32:
        raise ValueError("Проверьте числовые значения сметы.")
    try:result=Decimal(str(value).replace(",","."))
    except (InvalidOperation,ValueError):raise ValueError("Проверьте числовые значения сметы.")
    if not result.is_finite() or result<0 or result>maximum or (positive and result<=0):
        raise ValueError("Значение сметы выходит за допустимые границы.")
    if result.as_tuple().exponent < -4:raise ValueError("В смете допускается не более четырёх знаков после запятой.")
    return result


def _money(value):return format(value.quantize(CENT,rounding=ROUND_HALF_UP),".2f")


def save_estimate(db,uid,data,owner_id=None):
    item=_id(data);title=c._text(data,"title",160,True)
    status=_status(data.get("status","draft"),ESTIMATE_STATUSES)
    markup=_decimal(data.get("markup_percent",0),Decimal("1000"))
    lines=data.get("items")
    if not isinstance(lines,list) or not 1<=len(lines)<=100:raise ValueError("Добавьте от 1 до 100 строк сметы.")
    normalized=[];subtotal=Decimal(0);cost=Decimal(0)
    for line in lines:
        if not isinstance(line,dict):raise ValueError("Проверьте строки сметы.")
        name=c._text(line,"title",160,True);unit=c._text(line,"unit",24) or "шт."
        quantity=_decimal(line.get("quantity",1),Decimal("1000000"),True)
        price=_decimal(line.get("price_rub",0),Decimal("100000000")).quantize(CENT,rounding=ROUND_HALF_UP)
        expense=_decimal(line.get("cost_rub",0),Decimal("100000000")).quantize(CENT,rounding=ROUND_HALF_UP)
        amount=(quantity*price).quantize(CENT,rounding=ROUND_HALF_UP)
        line_cost=(quantity*expense).quantize(CENT,rounding=ROUND_HALF_UP)
        subtotal+=amount;cost+=line_cost
        normalized.append(dict(title=name,unit=unit,quantity=format(quantity,"f"),price_rub=_money(price),cost_rub=_money(expense),total_rub=_money(amount),cost_total_rub=_money(line_cost)))
    total=(subtotal*(Decimal(1)+markup/100)).quantize(CENT,rounding=ROUND_HALF_UP)
    if total>Decimal("1000000000000") or cost>Decimal("1000000000000"):
        raise ValueError("Итог сметы не должен превышать один триллион тестовых ₽.")
    def save(owner):
        return _upsert(db,"commercial_estimates",owner,item,dict(title=title,status=status,object_id=object_id(db,owner,data.get("object_id")),markup_percent=format(markup,"f"),items_json=json.dumps(normalized,ensure_ascii=False),subtotal_rub=_money(subtotal),total_rub=_money(total),cost_rub=_money(cost),profit_rub=_money(total-cost)))
    return c._mutate(db,uid,save,owner_id,manage=True)


def _role(db,uid,owner):
    return c._context(db,uid,owner)[2]


def invite(db,uid,data,owner_id=None):
    email=c._text(data,"email",254,True).casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+",email):raise ValueError("Укажите email участника.")
    role=_status(data.get("role","member"),{"admin","member"})
    def save(owner):
        if role=="admin" and uid!=owner:raise PermissionError("Назначить руководителя может только владелец.")
        if c._user(db,owner)["email"].casefold()==email:raise ValueError("Владелец уже состоит в организации.")
        member=db.execute("SELECT 1 FROM commercial_members m JOIN users u ON u.user_id=m.user_id WHERE m.owner_id=? AND LOWER(u.email)=?",(owner,email)).fetchone()
        if member:raise ValueError("Этот пользователь уже состоит в организации.")
        end=(c._now()+timedelta(days=7)).isoformat()
        row=db.execute("SELECT id FROM commercial_invitations WHERE owner_id=? AND email=?",(owner,email)).fetchone()
        if row:
            db.execute("UPDATE commercial_invitations SET role=?,status='pending',expires_at=?,invited_by=?,created_at=CURRENT_TIMESTAMP WHERE id=?",(role,end,uid,row["id"]))
            item=row["id"]
        else:item=c._insert_id(db,"INSERT INTO commercial_invitations(owner_id,email,role,expires_at,invited_by) VALUES(?,?,?,?,?)",(owner,email,role,end,uid))
        return {"id":item,"expires_at":end}
    return c._mutate(db,uid,save,owner_id,manage=True)


def invitation_action(db,uid,data,action,owner_id=None):
    item=c._integer(data.get("invitation_id"),1,2**63-1)
    user=c._user(db,uid)
    prior=db.execute("SELECT owner_id FROM commercial_invitations WHERE id=?",(item,)).fetchone()
    if not prior:raise ValueError("Приглашение недоступно.")
    owner=prior["owner_id"]
    if action=="revoke":
        def revoke(resolved):
            if resolved!=owner:raise PermissionError("Приглашение другой организации недоступно.")
            row=db.execute("SELECT * FROM commercial_invitations WHERE id=? AND owner_id=?",(item,resolved)).fetchone()
            if row["role"]=="admin" and uid!=resolved:raise PermissionError("Управлять руководителями может только владелец.")
            db.execute("UPDATE commercial_invitations SET status='revoked' WHERE id=? AND status='pending'",(item,))
            return {"id":item,"revoked":True}
        return c._mutate(db,uid,revoke,owner_id,manage=True,allow_expired=True)
    # New member has no membership yet: lock organisation first, then validate invite.
    db.execute("BEGIN IMMEDIATE")
    try:
        c._user(db,owner,lock=True)
        profile=c._profile(db,owner,lock=True)
        if not profile:raise ValueError("Организация недоступна.")
        row=db.execute("SELECT * FROM commercial_invitations WHERE id=?",(item,)).fetchone()
        if row["email"].casefold()!=user["email"].casefold():raise PermissionError("Это приглашение предназначено другому email.")
        if action=="accept" and row["status"]=="accepted" and db.execute("SELECT 1 FROM commercial_members WHERE owner_id=? AND user_id=?",(owner,uid)).fetchone():
            db.execute("COMMIT");return {"accepted":True,"owner_id":owner}
        if row["status"]!="pending" or c._date(row["expires_at"])<=c._now():raise ValueError("Приглашение отменено или срок истёк.")
        if action=="accept":
            c._active(profile)
            if uid==owner:raise ValueError("Владелец уже состоит в организации.")
            db.execute("INSERT OR IGNORE INTO commercial_members(owner_id,user_id,role) VALUES(?,?,?)",(owner,uid,row["role"]))
        db.execute("UPDATE commercial_invitations SET status=? WHERE id=?",("accepted" if action=="accept" else "declined",item))
        db.execute("COMMIT")
        return {"accepted":action=="accept","owner_id":owner}
    except Exception:
        db.execute("ROLLBACK");raise


def member_action(db,uid,data,action,owner_id=None):
    target=uid if action=="leave" else c._user_id(data.get("user_id"))
    def save(owner):
        if target==owner:raise ValueError("Владелец не может выйти из организации. Он может удалить её в настройках.")
        member=db.execute("SELECT role FROM commercial_members WHERE owner_id=? AND user_id=?",(owner,target)).fetchone()
        if not member:raise ValueError("Участник не найден в организации.")
        if action!="leave" and (member["role"]=="admin" or action=="role") and uid!=owner:
            raise PermissionError("Управлять руководителями может только владелец.")
        if action=="role":
            role=_status(data.get("role"),{"admin","member"})
            db.execute("UPDATE commercial_members SET role=? WHERE owner_id=? AND user_id=?",(role,owner,target))
        else:
            db.execute("DELETE FROM commercial_members WHERE owner_id=? AND user_id=?",(owner,target))
            for table in ("commercial_bookings","commercial_tasks","commercial_objects","commercial_professional_records"):
                db.execute("UPDATE "+table+" SET assignee_id=NULL WHERE owner_id=? AND assignee_id=?",(owner,target))
            db.execute("DELETE FROM commercial_shifts WHERE owner_id=? AND assignee_id=?",(owner,target))
        return {"user_id":target,"left":action=="leave","removed":action=="remove"}
    return c._mutate(db,uid,save,owner_id,manage=action!="leave",allow_expired=True)


def save_public_profile(db,uid,data,owner_id=None):
    published=data.get("published",False)
    if not isinstance(published,bool):raise ValueError("Проверьте статус публикации.")
    slug=c._text(data,"slug",64,True).lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,62}[a-z0-9])",slug):
        raise ValueError("Адрес страницы: 3–64 латинские буквы, цифры и дефисы.")
    description=c._text(data,"description",2000);contact=c._text(data,"contact",240);address=c._text(data,"address",400)
    def save(owner):
        collision=db.execute("SELECT owner_id FROM commercial_public_profiles WHERE slug=? AND owner_id<>?",(slug,owner)).fetchone()
        if collision:raise ValueError("Этот адрес страницы уже занят.")
        row=db.execute("SELECT 1 FROM commercial_public_profiles WHERE owner_id=?",(owner,)).fetchone()
        if row:db.execute("UPDATE commercial_public_profiles SET slug=?,published=?,description=?,contact=?,address=?,updated_at=CURRENT_TIMESTAMP WHERE owner_id=?",(slug,int(published),description,contact,address,owner))
        else:db.execute("INSERT INTO commercial_public_profiles(owner_id,slug,published,description,contact,address) VALUES(?,?,?,?,?,?)",(owner,slug,int(published),description,contact,address))
        return {"published":published,"slug":slug,"url":"/organizations/"+slug}
    try:
        return c._mutate(db,uid,save,owner_id,manage=True,allow_expired=not published)
    except Exception as error:
        if getattr(error,"sqlstate",None)=="23505" or "UNIQUE constraint failed: commercial_public_profiles.slug" in str(error):
            raise ValueError("Этот адрес страницы уже занят.") from error
        raise


def publish_service(db,uid,data,owner_id=None):
    item=c._integer(data.get("id"),1,2**63-1);published=data.get("published")
    if not isinstance(published,bool):raise ValueError("Проверьте статус публикации услуги.")
    def save(owner):
        service=c._owned(db,"commercial_services",owner,item)
        page=db.execute("SELECT published FROM commercial_public_profiles WHERE owner_id=?",(owner,)).fetchone()
        if published and (not page or not page["published"]):raise ValueError("Сначала опубликуйте страницу организации.")
        if published and not service["active"]:raise ValueError("Сначала включите услугу.")
        db.execute("UPDATE commercial_services SET published=? WHERE owner_id=? AND id=?",(int(published),owner,item))
        return {"id":item,"published":published}
    return c._mutate(db,uid,save,owner_id,manage=True,allow_expired=not published)


def _public_rows(db):
    rows=db.execute("""SELECT p.user_id,p.title,p.kind,p.trial_until,p.paid_until,
        s.slug,s.description,s.contact,s.address FROM commercial_public_profiles s
        JOIN commercial_profiles p ON p.user_id=s.owner_id JOIN users u ON u.user_id=p.user_id
        WHERE s.published=1 AND u.is_blocked=0 AND u.email_verified=1
        AND NOT EXISTS(SELECT 1 FROM commercial_deleted_profiles d WHERE d.user_id=p.user_id)
        ORDER BY p.title,p.user_id""").fetchall()
    now=c._now()
    return [r for r in rows if c._until(r)>now]


def _service_public(row):
    return {key:row[key] for key in ("id","title","description","price_rub","duration_minutes")}|{"currency":"TEST_RUB"}


def public_organization(db,slug):
    if not isinstance(slug,str) or len(slug)>64:raise ValueError("Страница организации не найдена.")
    for row in _public_rows(db):
        if row["slug"]!=slug:continue
        services=[_service_public(r) for r in db.execute("SELECT id,title,description,price_rub,duration_minutes FROM commercial_services WHERE owner_id=? AND active=1 AND published=1 ORDER BY id DESC",(row["user_id"],)).fetchall()]
        return dict(slug=slug,title=row["title"],kind=row["kind"],kind_title=c.KINDS.get(row["kind"],"Специалист"),description=row["description"],contact=row["contact"],address=row["address"],url="/organizations/"+slug,services=services,currency="TEST_RUB")
    raise ValueError("Страница организации не найдена.")


def public_services(db):
    result=[]
    for row in _public_rows(db):
        for service in db.execute("SELECT id,title,description,price_rub,duration_minutes FROM commercial_services WHERE owner_id=? AND active=1 AND published=1 ORDER BY id DESC",(row["user_id"],)).fetchall():
            result.append({**_service_public(service),"organization_title":row["title"],"organization_kind":row["kind"],"organization_slug":row["slug"],"organization_url":"/organizations/"+row["slug"]})
    return sorted(result,key=lambda row:row["id"],reverse=True)[:300]


def _members(db,owner):
    row=c._user(db,owner)
    result=[dict(user_id=owner,name=row["name"],email=row["email"],role="owner")]
    result.extend(dict(r) for r in db.execute("SELECT u.user_id,u.name,u.email,m.role FROM commercial_members m JOIN users u ON u.user_id=m.user_id WHERE m.owner_id=? ORDER BY m.role,u.name,u.user_id",(owner,)).fetchall())
    return result


def _performance(db,owner,members):
    now=c._now();first=now.date()-timedelta(days=29)
    series={str(first+timedelta(days=i)):dict(date=str(first+timedelta(days=i)),completed=0,revenue_test_rub=0) for i in range(30)}
    by_member={r["user_id"]:dict(user_id=r["user_id"],name=r["name"],bookings_completed=0,tasks_done=0,revenue_test_rub=0) for r in members}
    totals=dict(completed=0,planned=0,cancelled=0,revenue_test_rub=0)
    for row in db.execute("SELECT starts_at,status,price_rub,assignee_id FROM commercial_bookings WHERE owner_id=?",(owner,)).fetchall():
        day=c._date(row["starts_at"]).date()
        if not first<=day<=now.date():continue
        status=row["status"]
        if status in totals:totals[status]+=1
        if status=="completed":
            totals["revenue_test_rub"]+=row["price_rub"]
            series[str(day)]["completed"]+=1;series[str(day)]["revenue_test_rub"]+=row["price_rub"]
            person=by_member.get(row["assignee_id"])
            if person:person["bookings_completed"]+=1;person["revenue_test_rub"]+=row["price_rub"]
    tasks_done=tasks_overdue=0
    for row in db.execute("SELECT status,due_at,assignee_id FROM commercial_tasks WHERE owner_id=?",(owner,)).fetchall():
        if row["status"]=="done":
            tasks_done+=1
            if row["assignee_id"] in by_member:by_member[row["assignee_id"]]["tasks_done"]+=1
        if row["status"] in ("todo","in_progress") and row["due_at"] and c._date(row["due_at"])<now:tasks_overdue+=1
    estimates=db.execute("SELECT total_rub,cost_rub FROM commercial_estimates WHERE owner_id=? AND status IN ('approved','completed')",(owner,)).fetchall()
    total=sum((Decimal(r["total_rub"]) for r in estimates),Decimal(0));cost=sum((Decimal(r["cost_rub"]) for r in estimates),Decimal(0))
    count=sum(totals[k] for k in ("completed","planned","cancelled"))
    objects=db.execute("SELECT COUNT(*) n FROM commercial_objects WHERE owner_id=? AND status='active'",(owner,)).fetchone()["n"]
    return {**totals,"period_days":30,"completion_percent":round(totals["completed"]*100/count) if count else 0,
            "tasks_done":tasks_done,"tasks_overdue":tasks_overdue,"objects_active":objects,
            "estimate_total_rub":_money(total),"cost_total_rub":_money(cost),"profit_total_rub":_money(total-cost),
            "series":list(series.values()),"by_member":list(by_member.values()),"currency":"TEST_RUB"}


def enrich_dashboard(db,uid,owner,role,data):
    user=c._user(db,uid)
    organizations=[]
    for row in db.execute("""SELECT p.*,m.role member_role FROM commercial_profiles p
        LEFT JOIN commercial_members m ON m.owner_id=p.user_id AND m.user_id=?
        JOIN users u ON u.user_id=p.user_id
        WHERE (p.user_id=? OR m.user_id=?) AND u.is_blocked=0 AND u.email_verified=1
        AND NOT EXISTS(SELECT 1 FROM commercial_deleted_profiles d WHERE d.user_id=p.user_id)
        ORDER BY p.title,p.user_id""",(uid,uid,uid)).fetchall():
        organizations.append(dict(id=row["user_id"],owner_id=row["user_id"],title=row["title"],role="owner" if row["user_id"]==uid else row["member_role"],active=c._until(row)>c._now()))
    incoming=[dict(r) for r in db.execute("""SELECT i.id,i.owner_id,p.title organization_title,i.role,i.expires_at
        FROM commercial_invitations i JOIN commercial_profiles p ON p.user_id=i.owner_id
        JOIN users u ON u.user_id=p.user_id
        WHERE i.email=? AND i.status='pending' AND i.expires_at>? AND u.is_blocked=0
        AND NOT EXISTS(SELECT 1 FROM commercial_deleted_profiles d WHERE d.user_id=p.user_id)
        ORDER BY i.id DESC""",(user["email"].casefold(),c._now().isoformat())).fetchall()]
    data.update(organizations=organizations,selected_owner_id=owner,role=role,
                permissions=dict(manage=role in ("owner","admin"),write=bool(role),owner=role=="owner"),
                incoming_invitations=incoming,members=[],invitations=[],objects=[],tasks=[],estimates=[],shifts=[],performance={},public_profile=None)
    data["trial_available"]=c._profile(db,uid,include_deleted=True) is None
    if owner is None:return data
    members=_members(db,owner);data["members"]=members
    if role in ("owner","admin"):
        data["invitations"]=[dict(r) for r in db.execute("SELECT id,email,role,status,expires_at FROM commercial_invitations WHERE owner_id=? ORDER BY id DESC LIMIT 200",(owner,)).fetchall()]
    for key,table,order in (("objects","commercial_objects","id DESC"),("tasks","commercial_tasks","id DESC"),("estimates","commercial_estimates","id DESC"),("shifts","commercial_shifts","starts_at DESC,id DESC")):
        data[key]=[dict(r) for r in db.execute("SELECT * FROM "+table+" WHERE owner_id=? ORDER BY "+order+" LIMIT 1000",(owner,)).fetchall()]
    for estimate in data["estimates"]:estimate["items"]=json.loads(estimate.pop("items_json"))
    for service in data["services"]:service["published"]=bool(service["published"])
    names={m["user_id"]:m["name"] for m in members};objects={r["id"]:r["title"] for r in data["objects"]}
    for collection in ("bookings","tasks","objects","shifts"):
        for row in data[collection]:
            row["assignee_name"]=names.get(row.get("assignee_id"),"")
            row["object_title"]=objects.get(row.get("object_id"),"")
    data["performance"]=_performance(db,owner,members)
    public=db.execute("SELECT slug,published,description,contact,address FROM commercial_public_profiles WHERE owner_id=?",(owner,)).fetchone()
    data["public_profile"]=dict(public) if public else dict(slug="org-"+str(abs(owner)),published=False,description="",contact="",address="")
    data["public_profile"]["published"]=bool(data["public_profile"]["published"])
    data["public_profile"]["url"]="/organizations/"+data["public_profile"]["slug"]
    return data


def post_action(db,uid,path,data,owner_id=None):
    actions={"/objects":save_object,"/tasks":save_task,"/tasks/status":set_task_status,
             "/estimates":save_estimate,"/shifts":save_shift,"/shifts/delete":delete_shift,"/team/invite":invite,
             "/public-profile":save_public_profile,"/services/publish":publish_service}
    suffix=path.removeprefix("/api/commercial")
    if suffix in actions:return actions[suffix](db,uid,data,owner_id)
    if suffix in ("/team/accept","/team/decline","/team/revoke"):
        return invitation_action(db,uid,data,suffix.rsplit("/",1)[-1],owner_id)
    if suffix in ("/team/leave","/team/remove","/team/role"):
        return member_action(db,uid,data,suffix.rsplit("/",1)[-1],owner_id)
    raise ValueError("Неизвестное действие кабинета.")
