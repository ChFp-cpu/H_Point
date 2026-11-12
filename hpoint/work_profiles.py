"""Validated professional workspaces. Health entries are private observations.

The catalogue describes concrete workflows; it is also the single source for
their forms. Data stays in the organisation, survives a profession change and
never enters public organisation/service DTOs. No medical advice is generated.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import copy
import json
import re

KINDS = {
    "trainer":"Тренер", "tutor":"Репетитор", "beauty":"Бьюти-мастер",
    "repair":"Мастер по ремонту", "foreman":"Прораб", "events":"Организатор мероприятий",
    "studio":"Студия/школа", "organization":"Организация", "other":"Специалист",
}

from . import commercial as c, commercial_team as team


def field(key,label,kind="text",required=False,**limits):
    result=dict(key=key,label=label,type=kind,required=required)
    if kind in ("text","textarea"):result["max_length"]=1000 if kind=="textarea" else 160
    return {**result,**limits}


def module(kind,title,singular,fields,statuses,*,parent=None,sensitive=False,description=""):
    return dict(kind=kind,title=title,singular=singular,description=description,sensitive=sensitive,
                fields=[field("title",singular,required=True),*fields],statuses=statuses,parent=parent)


ACTIVE={"active":"Активно","paused":"Пауза","completed":"Завершено","archived":"В архиве"}
PLANNED={"planned":"Запланировано","completed":"Выполнено","cancelled":"Отменено","archived":"В архиве"}
RECORDED={"recorded":"Записано","archived":"В архиве"}
CLIENT=field("client_id","Клиент","client",True)
PERSON=field("assignee_id","Ответственный","member")

MODULES = {
    "athletes":module("trainer","Подопечные","Имя / карточка подопечного",[
        field("client_id","Контакт в базе (необязательно)","client"),field("assignee_id","Тренер","member"),field("discipline","Вид спорта"),
        field("goals","Цели подготовки","textarea"),field("weight_category","Весовая категория",max_length=80),
        field("started_on","Начало занятий","date"),
    ],ACTIVE,sensitive=True,description="Карточки подопечных, цели и весовые категории."),
    "training_sessions":module("trainer","Дневник тренировок","Тема тренировки",[
        field("athlete_id","Подопечный","record",True,ref="athletes"),field("session_on","Дата тренировки","date",True),
        field("duration_minutes","Продолжительность, минут","integer",True,min=1,max=1440,default=60),
        field("load_intensity","Нагрузка","select",options={"low":"Лёгкая","moderate":"Средняя","high":"Высокая"},default="moderate"),
        field("exercises","План и упражнения","textarea",max_length=2000),field("results","Что получилось","textarea"),
        field("result_score","Результат, 0–100","decimal",min=0,max=100,step="0.1"),
    ],PLANNED,parent="athlete_id",sensitive=True),
    "health_checks":module("trainer","Самочувствие и замеры","Название замера",[
        field("athlete_id","Подопечный","record",True,ref="athletes"),field("measured_on","Дата замера","date",True),
        field("weight_kg","Вес, кг","decimal",min=1,max=500,step="0.01"),
        field("wellbeing","Самочувствие, 1–10","integer",True,min=1,max=10),
        field("sleep_hours","Сон, часов","decimal",min=0,max=24,step="0.1"),
        field("resting_pulse","Пульс в покое","integer",min=20,max=250),
        field("discomfort","Наблюдения подопечного","textarea"),
    ],RECORDED,parent="athlete_id",sensitive=True,description="Личные наблюдения и динамика замеров. Без диагнозов и медицинских рекомендаций."),
    "competitions":module("trainer","Соревнования","Название соревнования",[
        field("athlete_id","Подопечный","record",True,ref="athletes"),field("competition_date","Дата соревнования","date",True),
        field("venue","Место проведения"),field("discipline","Дисциплина"),field("weight_category","Весовая категория",max_length=80),
        field("result","Результат",max_length=400),field("place","Занятое место","integer",min=1,max=100000),
    ],{"planned":"В плане","registered":"Заявлен","completed":"Завершено","cancelled":"Отменено","archived":"В архиве"},parent="athlete_id",sensitive=True),
    "students":module("tutor","Ученики","Карточка ученика",[
        field("client_id","Контакт в базе (необязательно)","client"),PERSON,field("subject","Предмет",required=True),field("level","Класс / уровень"),
        field("goals","Цели обучения","textarea"),field("exam_on","Дата экзамена","date"),
    ],ACTIVE),
    "lessons":module("tutor","Уроки и домашние задания","Тема урока",[
        field("student_id","Ученик","record",True,ref="students"),field("lesson_on","Дата урока","date",True),
        field("duration_minutes","Продолжительность, минут","integer",True,min=1,max=480,default=60),
        field("topic","Пройденная тема"),field("homework","Домашнее задание","textarea"),
        field("homework_status","Домашнее задание","select",options={"not_assigned":"Не задано","assigned":"Задано","submitted":"Сдано","checked":"Проверено"},default="not_assigned"),
        field("grade","Оценка / балл, 0–100","decimal",min=0,max=100,step="0.1"),
        field("results","Результат урока","textarea"),
    ],PLANNED,parent="student_id"),
    "beauty_cards":module("beauty","Карты клиентов","Карточка клиента",[
        CLIENT,field("assignee_id","Мастер","member"),field("preferences","Предпочтения клиента","textarea"),
        field("sensitivities","Ограничения, сообщённые клиентом","textarea"),field("care_notes","История ухода","textarea"),
    ],ACTIVE,sensitive=True),
    "procedures":module("beauty","Процедуры и материалы","Название процедуры",[
        field("card_id","Карта клиента","record",True,ref="beauty_cards"),field("procedure_on","Дата процедуры","date",True),
        field("duration_minutes","Продолжительность, минут","integer",min=1,max=720,default=60),
        field("materials","Использованные материалы","textarea"),field("material_cost_rub","Расход материалов, тест. ₽","decimal",min=0,max=10000000,step="0.01",money=True),
        field("price_rub","Стоимость, тест. ₽","decimal",min=0,max=10000000,step="0.01",money=True),
        field("result","Результат процедуры","textarea"),
    ],PLANNED,parent="card_id",sensitive=True),
    "equipment":module("repair","Оборудование клиентов","Название оборудования",[
        CLIENT,PERSON,field("brand","Марка / модель"),field("serial_number","Серийный номер"),field("condition","Состояние при приёме","textarea"),
    ],ACTIVE),
    "repair_orders":module("repair","Ремонтные заказы","Тема ремонта",[
        field("equipment_id","Оборудование","record",True,ref="equipment"),field("received_on","Дата приёма","date",True),
        field("due_on","Срок готовности","date"),field("diagnostics","Диагностика","textarea"),field("parts","Запчасти и работы","textarea"),
        field("parts_cost_rub","Расход на запчасти, тест. ₽","decimal",min=0,max=100000000,step="0.01",money=True),
        field("price_rub","Стоимость ремонта, тест. ₽","decimal",min=0,max=100000000,step="0.01",money=True),field("result","Результат ремонта","textarea"),
    ],{"received":"Принято","diagnostics":"Диагностика","waiting_parts":"Ожидает запчасти","in_progress":"В работе","completed":"Готово","delivered":"Выдано","cancelled":"Отменено","archived":"В архиве"},parent="equipment_id"),
    "event_projects":module("events","События и подрядчики","Название события",[
        field("client_id","Заказчик","client"),PERSON,field("event_on","Дата события","date",True),field("venue","Площадка"),
        field("guests","Ожидается гостей","integer",min=0,max=1000000),field("vendor","Основной подрядчик"),
        field("budget_rub","Плановый бюджет, тест. ₽","decimal",min=0,max=1000000000,step="0.01",money=True),
        field("actual_rub","Фактические расходы, тест. ₽","decimal",min=0,max=1000000000,step="0.01",money=True),field("brief","План события","textarea"),
    ],PLANNED),
    "event_checklist":module("events","Чек-листы подготовки","Пункт подготовки",[
        field("project_id","Событие","record",True,ref="event_projects"),PERSON,field("due_on","Срок","date"),
        field("vendor","Подрядчик"),field("cost_rub","Расход, тест. ₽","decimal",min=0,max=100000000,step="0.01",money=True),field("result","Результат / договорённость","textarea"),
    ],{"todo":"Предстоит","in_progress":"В работе","completed":"Готово","cancelled":"Отменено","archived":"В архиве"},parent="project_id"),
    "groups":module("studio","Группы","Название группы",[
        PERSON,field("discipline","Направление",required=True),field("level","Уровень / возраст"),
        field("capacity","Вместимость","integer",True,min=1,max=1000,default=10),field("schedule","Регулярное расписание",max_length=400),
        field("tuition_rub","Стоимость занятий, тест. ₽","decimal",min=0,max=10000000,step="0.01",money=True),
    ],ACTIVE),
    "group_classes":module("studio","Занятия групп","Тема занятия",[
        field("group_id","Группа","record",True,ref="groups"),field("class_on","Дата занятия","date",True),
        field("duration_minutes","Продолжительность, минут","integer",True,min=1,max=720,default=60),field("topic","Программа занятия","textarea"),
    ],PLANNED,parent="group_id"),
    "attendance":module("studio","Посещаемость","Отметка посещения",[
        field("class_id","Занятие","record",True,ref="group_classes"),CLIENT,
        field("mark","Присутствие","select",True,options={"present":"Присутствовал","absent":"Отсутствовал","excused":"Уважительная причина"},default="present"),
        field("score","Результат, 0–100","decimal",min=0,max=100,step="0.1"),field("notes","Комментарий",max_length=400),
    ],RECORDED,parent="class_id"),
    "stages":module("foreman","Этапы и объёмы работ","Этап работ",[
        field("object_id","Объект","object",True),PERSON,field("starts_on","Начало этапа","date"),field("ends_on","Окончание этапа","date"),
        field("quantity","Объём работ","decimal",min=0,max=100000000,step="0.001"),field("unit","Единица измерения",max_length=24),
        field("progress_percent","Готовность, %","integer",True,min=0,max=100,default=0),
        field("planned_rub","План, тест. ₽","decimal",min=0,max=1000000000,step="0.01",money=True),
        field("actual_rub","Факт, тест. ₽","decimal",min=0,max=1000000000,step="0.01",money=True),field("result","Приёмка / результат","textarea"),
    ],{"planned":"В плане","in_progress":"В работе","completed":"Принято","cancelled":"Отменено","archived":"В архиве"}),
    "responsibilities":module("organization","Ответственность и результаты","Зона ответственности",[
        field("object_id","Проект / объект","object"),field("assignee_id","Ответственный сотрудник","member",True),
        field("due_on","Контрольный срок","date"),field("target","Ожидаемый результат","textarea",True),
        field("progress_percent","Выполнение, %","integer",True,min=0,max=100,default=0),field("result","Фактический результат","textarea"),
    ],{"planned":"Назначено","in_progress":"В работе","completed":"Принято","cancelled":"Отменено","archived":"В архиве"}),
    "assignments":module("other","Работы и результаты","Название работы",[
        field("client_id","Клиент","client"),field("object_id","Объект","object"),PERSON,field("due_on","Срок","date"),
        field("scope","Состав работы","textarea",True),field("progress_percent","Выполнение, %","integer",min=0,max=100,default=0),
        field("result","Результат","textarea"),
    ],{"planned":"В плане","in_progress":"В работе","completed":"Выполнено","cancelled":"Отменено","archived":"В архиве"}),
}

DESCRIPTIONS = {
    "trainer":"Подопечные, тренировки, самочувствие и соревнования.",
    "tutor":"Ученики, учебные цели, уроки и домашние задания.",
    "beauty":"Карты клиентов, процедуры и расход материалов.",
    "repair":"Оборудование, диагностика, запчасти и ремонтные заказы.",
    "foreman":"Объекты, сметы, этапы и приёмка работ.",
    "events":"События, подрядчики, бюджеты и подготовка.",
    "studio":"Группы, занятия и посещаемость.",
    "organization":"Команда, проекты, задачи и ответственность сотрудников.",
    "other":"Клиенты, работы, сроки и результаты.",
}


def catalog():
    return [dict(key=kind,title=title,description=DESCRIPTIONS[kind],modules=[key for key,m in MODULES.items() if m["kind"]==kind]) for kind,title in KINDS.items()]


def initialize_schema(db):
    schema="""
    CREATE TABLE IF NOT EXISTS commercial_professional_records(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      owner_id INTEGER NOT NULL REFERENCES commercial_profiles(user_id) ON DELETE CASCADE,
      module TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL,
      client_id INTEGER REFERENCES commercial_clients(id) ON DELETE SET NULL,
      object_id INTEGER REFERENCES commercial_objects(id) ON DELETE SET NULL,
      assignee_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
      parent_id INTEGER REFERENCES commercial_professional_records(id) ON DELETE CASCADE,
      data_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_professional_owner_module ON commercial_professional_records(owner_id,module,id);
    CREATE INDEX IF NOT EXISTS idx_professional_parent ON commercial_professional_records(parent_id);
    """
    if getattr(db,"is_postgres",False):schema=schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT","BIGSERIAL PRIMARY KEY").replace("INTEGER","BIGINT")
    db.executescript(schema)


def erase_workspace(db,owner):
    db.execute("DELETE FROM commercial_professional_records WHERE owner_id=?",(owner,))


def _config(key):
    if key not in MODULES:raise ValueError("Неизвестный рабочий раздел.")
    return MODULES[key]


def _get(db,owner,key,item):
    row=db.execute("SELECT * FROM commercial_professional_records WHERE owner_id=? AND module=? AND id=?",(owner,key,item)).fetchone()
    if not row:raise ValueError("Запись не найдена в этой организации и разделе.")
    return row


def _parent(db,row):
    if row["parent_id"] is None:return None
    return db.execute("SELECT * FROM commercial_professional_records WHERE id=? AND owner_id=?",(row["parent_id"],row["owner_id"])).fetchone()


def _coach(db,row):
    # The current parent's coach governs historical measurements too: a coach
    # reassignment cannot leave the former coach access to the child's history.
    parent=_parent(db,row)
    return _coach(db,parent) if parent is not None and MODULES.get(row["module"],{}).get("sensitive") else row["assignee_id"]


def _visible(db,uid,role,row):
    return not MODULES.get(row["module"],{}).get("sensitive") or role in ("owner","admin") or _coach(db,row)==uid


def _assert_visible(db,uid,role,row):
    if not _visible(db,uid,role,row):raise PermissionError("Эта личная карточка доступна только руководителю и назначенному специалисту.")


def _number(value,meta):
    if isinstance(value,bool) or not isinstance(value,(str,int,float)) or len(str(value))>32:
        raise ValueError("Проверьте поле «"+meta["label"]+"».")
    try:result=Decimal(str(value).replace(",","."))
    except (InvalidOperation,ValueError):raise ValueError("Проверьте поле «"+meta["label"]+"».")
    if not result.is_finite() or result<Decimal(str(meta.get("min",0))) or result>Decimal(str(meta.get("max",1000000000))):
        raise ValueError("Значение поля «"+meta["label"]+"» вне допустимого диапазона.")
    if result.as_tuple().exponent < -4:raise ValueError("Допускается не более четырёх знаков после запятой.")
    if meta.get("money"):result=result.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
    return format(result,"f")


def _validate(db,uid,owner,role,key,data):
    conf=_config(key);result={};parent=None
    for meta in conf["fields"]:
        name=meta["key"];value=data.get(name,meta.get("default"))
        if value in (None,""):
            if meta.get("required"):raise ValueError("Заполните поле «"+meta["label"]+"».")
            result[name]=None if meta["type"] not in ("text","textarea","date") else ""
            continue
        typ=meta["type"]
        if typ in ("text","textarea"):
            if not isinstance(value,str) or len(value.strip())>meta["max_length"]:raise ValueError("Проверьте длину поля «"+meta["label"]+"».")
            value=value.strip()
            if meta.get("required") and len(value)<2:raise ValueError("Поле «"+meta["label"]+"» должно содержать хотя бы два символа.")
        elif typ=="integer":value=c._integer(value,meta.get("min",0),meta.get("max",1000000000))
        elif typ=="decimal":value=_number(value,meta)
        elif typ=="date":value=team._day(value)
        elif typ=="select":
            if not isinstance(value,str) or value not in meta["options"]:raise ValueError("Выберите значение поля «"+meta["label"]+"».")
        elif typ=="client":
            value=c._integer(value,1,2**63-1);c._owned(db,"commercial_clients",owner,value)
        elif typ=="object":value=team.object_id(db,owner,value)
        elif typ=="member":value=team.assignee(db,owner,value)
        elif typ=="record":
            value=c._integer(value,1,2**63-1);linked=_get(db,owner,meta["ref"],value)
            _assert_visible(db,uid,role,linked)
            if name==conf.get("parent"):parent=linked
        result[name]=value
    # Only allowed typed fields are stored; extra input cannot smuggle health or
    # accounting fields into another profession's records.
    if parent is not None:
        if "client_id" not in result:result["client_id"]=parent["client_id"]
        if "object_id" not in result:result["object_id"]=parent["object_id"]
        if "assignee_id" not in result:result["assignee_id"]=_coach(db,parent) if conf["sensitive"] else parent["assignee_id"]
    if conf["sensitive"] and parent is None:
        if result.get("assignee_id") is None:result["assignee_id"]=uid if role=="member" else owner
        if role=="member" and result["assignee_id"]!=uid:raise PermissionError("Личную карточку можно назначить только себе.")
    if conf["sensitive"] and role=="member" and result.get("assignee_id")!=uid:
        raise PermissionError("Личная запись доступна только назначенному специалисту.")
    for first,last in (("starts_on","ends_on"),("received_on","due_on")):
        if result.get(first) and result.get(last) and result[last]<result[first]:raise ValueError("Дата окончания должна быть не раньше начала.")
    return result,parent


def _shape(db,row,uid,role,active):
    values=json.loads(row["data_json"])
    result={**values,"id":row["id"],"title":row["title"],"status":row["status"],"archived":row["status"]=="archived",
            "created_at":row["created_at"],"updated_at":row["updated_at"],"can_write":active and _visible(db,uid,role,row)}
    # References are authoritative columns; deleted clients/employees are not
    # resurrected from their historical JSON snapshot.
    for key in ("client_id","object_id","assignee_id"):result[key]=row[key]
    if MODULES.get(row["module"],{}).get("sensitive"):result["assignee_id"]=_coach(db,row)
    return result


def save(db,uid,key,data,owner_id=None):
    conf=_config(key);item=team._id(data)
    status=data.get("status",next(iter(conf["statuses"])))
    if not isinstance(status,str) or status not in conf["statuses"]:raise ValueError("Неизвестный статус записи.")
    def mutate(owner):
        _,profile,role=c._context(db,uid,owner)
        if profile["kind"]!=conf["kind"]:raise PermissionError("Этот раздел доступен для другого формата работы. Старые записи сохранены в истории.")
        previous=_get(db,owner,key,item) if item else None
        if previous is not None:_assert_visible(db,uid,role,previous)
        values,parent=_validate(db,uid,owner,role,key,data)
        if previous is not None and previous["client_id"] is not None and values.get("client_id")!=previous["client_id"] and db.execute("SELECT 1 FROM commercial_professional_records WHERE owner_id=? AND parent_id=? LIMIT 1",(owner,item)).fetchone():
            raise ValueError("У карточки уже есть история. Создайте отдельную карточку для другого клиента.")
        if parent is not None and parent["status"]=="archived" and not item:raise ValueError("Сначала восстановите основную карточку из архива.")
        if key=="attendance":
            _attendance(db,owner,parent,values,status,item)
        title=values["title"];client=values.get("client_id");obj=values.get("object_id");person=values.get("assignee_id")
        args=(title,status,client,obj,person,parent["id"] if parent else None,json.dumps(values,ensure_ascii=False))
        if item:
            db.execute("UPDATE commercial_professional_records SET title=?,status=?,client_id=?,object_id=?,assignee_id=?,parent_id=?,data_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner_id=? AND module=?",(*args,item,owner,key))
        else:
            count=db.execute("SELECT COUNT(*) n FROM commercial_professional_records WHERE owner_id=?",(owner,)).fetchone()["n"]
            if count>=10000:raise ValueError("В организации достигнут лимит 10 000 профильных записей.")
            return {"id":c._insert_id(db,"INSERT INTO commercial_professional_records(owner_id,module,title,status,client_id,object_id,assignee_id,parent_id,data_json) VALUES(?,?,?,?,?,?,?,?,?)",(owner,key,*args))}
        return {"id":item}
    return c._mutate(db,uid,mutate,owner_id)


def _attendance(db,owner,parent,values,status,item=None):
    if status=="archived":return
    duplicate=db.execute("SELECT id FROM commercial_professional_records WHERE owner_id=? AND module='attendance' AND parent_id=? AND client_id=? AND status<>'archived' AND id<>?",(owner,parent["id"],values["client_id"],item or 0)).fetchone()
    if duplicate:raise ValueError("Посещение этого клиента уже отмечено. Измените существующую отметку.")
    group=_parent(db,parent)
    if group and values.get("mark")=="present":
        capacity=json.loads(group["data_json"]).get("capacity")
        attendees=db.execute("SELECT data_json FROM commercial_professional_records WHERE owner_id=? AND module='attendance' AND parent_id=? AND status<>'archived' AND id<>?",(owner,parent["id"],item or 0)).fetchall()
        if capacity and sum(json.loads(r["data_json"]).get("mark")=="present" for r in attendees)>=capacity:
            raise ValueError("Достигнута вместимость группы.")


def action(db,uid,key,data,verb,owner_id=None):
    conf=_config(key);item=c._integer(data.get("id"),1,2**63-1)
    def mutate(owner):
        _,profile,role=c._context(db,uid,owner)
        if profile["kind"]!=conf["kind"]:raise PermissionError("Изменение записей другого формата работы недоступно.")
        row=_get(db,owner,key,item);_assert_visible(db,uid,role,row)
        if verb=="delete":
            if data.get("confirm") is not True:raise ValueError("Подтвердите удаление записи.")
            if db.execute("SELECT 1 FROM commercial_professional_records WHERE owner_id=? AND parent_id=? LIMIT 1",(owner,item)).fetchone():
                raise ValueError("У карточки есть связанные записи. Сохраните историю, переместив карточку в архив.")
            db.execute("DELETE FROM commercial_professional_records WHERE id=? AND owner_id=?",(item,owner))
            return {"id":item,"deleted":True}
        values=json.loads(row["data_json"]);values.update(id=item,status=data.get("status"))
        status=values["status"]
        if not isinstance(status,str) or status not in conf["statuses"]:raise ValueError("Неизвестный статус записи.")
        # Status transitions are validated through the same domain invariants as
        # a full edit (attendance uniqueness/capacity and private references).
        if key=="attendance" and status!="archived":
            parent=_get(db,owner,"group_classes",row["parent_id"])
            _attendance(db,owner,parent,{**values,"client_id":row["client_id"]},status,item)
        db.execute("UPDATE commercial_professional_records SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner_id=?",(status,item,owner))
        return {"id":item,"status":status}
    return c._mutate(db,uid,mutate,owner_id)


def dashboard(db,uid,owner,role,kind,active):
    result=dict(kind=kind,title=KINDS.get(kind,"Для работы"),description=DESCRIPTIONS.get(kind,""),catalog=catalog(),modules=[],history=[],progress={})
    rows=[] if owner is None else db.execute("SELECT * FROM commercial_professional_records WHERE owner_id=? ORDER BY id DESC",(owner,)).fetchall()
    grouped={key:[] for key in MODULES}
    for row in rows:
        if row["module"] in grouped and _visible(db,uid,role,row):grouped[row["module"]].append(_shape(db,row,uid,role,active))
    for key,conf in MODULES.items():
        spec=copy.deepcopy(conf);spec.update(key=key,records=grouped[key],can_write=bool(active),count=len(grouped[key]))
        spec["stats"]=dict(total=len(grouped[key]),archived=sum(r["archived"] for r in grouped[key]),completed=sum(r["status"] in ("completed","delivered") for r in grouped[key]))
        if conf["kind"]==kind:result["modules"].append(spec)
        elif grouped[key]:
            spec["can_write"]=False
            for row in spec["records"]:row["can_write"]=False
            result["history"].append(spec)
    if kind=="trainer":
        visible_athletes={r["id"]:r for r in grouped["athletes"]}
        series=[]
        for row in grouped["health_checks"]:
            if row.get("weight_kg") is not None and row["status"]!="archived":
                series.append(dict(athlete_id=row["athlete_id"],athlete_title=visible_athletes.get(row["athlete_id"],{}).get("title","Подопечный"),date=row["measured_on"],weight_kg=row["weight_kg"]))
        result["progress"]=dict(athletes=sum(r["status"]=="active" for r in grouped["athletes"]),training_completed=sum(r["status"]=="completed" for r in grouped["training_sessions"]),
                                competitions_upcoming=sum(r["status"] in ("planned","registered") and r.get("competition_date","")>=date.today().isoformat() for r in grouped["competitions"]),
                                weight_series=sorted(series,key=lambda r:(r["date"],r["athlete_id"])))
    return result


def post_action(db,uid,path,data,owner_id=None):
    match=re.fullmatch(r"/api/commercial/professional/([a-z_]+)(?:/(status|delete))?",path)
    if not match:raise ValueError("Неизвестное действие профильного кабинета.")
    key,verb=match.groups()
    if verb:return action(db,uid,key,data,verb,owner_id)
    return save(db,uid,key,data,owner_id)
