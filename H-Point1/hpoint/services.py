import json
from datetime import datetime, timedelta
from .config import *
from .database import db_connect, get_request, get_user

db = None

def _db(): return db if db is not None else db_connect()
def _close(c):
    if db is None: c.close()

def infer_category(what):
    text = what.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(k in text for k in keywords): return category
    return 'other'

def split_tags(value):
    return [x.strip().lower() for x in (value or '').replace(';', ',').split(',') if x.strip()]

def set_profile(user_id, skills=None, portfolio=None):
    c=_db(); row=get_user(user_id)
    if row is None: _close(c); return False
    c.execute('UPDATE users SET skills=?, portfolio=? WHERE user_id=?', (row['skills'] if skills is None else skills[:MAX_TEXT_LEN], row['portfolio'] if portfolio is None else portfolio[:MAX_TEXT_LEN], user_id)); _close(c); return True

def set_helper_categories(user_id,categories):
    valid=[c for c in categories if c in CATEGORIES]; c=_db(); c.execute('UPDATE users SET helper_categories=? WHERE user_id=?',(json.dumps(valid,ensure_ascii=False),user_id)); _close(c)

def get_helper_categories(user_id):
    row=get_user(user_id)
    if not row or not row['helper_categories']: return []
    try: return [c for c in json.loads(row['helper_categories']) if c in CATEGORIES]
    except (TypeError,ValueError): return []

def create_request(user_id,data):
    category=data.get('category') or infer_category(data['what']); c=_db(); cur=c.execute('INSERT INTO requests(requester_id,category,what,place,time_needed,urgency,details,required_skills,status) VALUES(?,?,?,?,?,?,?,?,?)',(user_id,category,data['what'],data['place'],data['time_needed'],data['urgency'],data['details'],data.get('required_skills',''),STATUS_OPEN)); rid=cur.lastrowid; _close(c); notify_user(user_id, f'🆕 Ваша заявка №{rid} создана через сайт. Откройте раздел «Мои кандидаты», когда появятся отклики.'); return rid

def request_skill_match(request, helper):
    required=set(split_tags(request['required_skills'])); skills=set(split_tags(helper['skills']))
    if not required: return 1.0
    if not skills: return 0.0
    return len(required & skills) / len(required)

def profile_rating(user_id):
    c=_db(); row=c.execute('SELECT AVG(helper_rating) avg FROM requests WHERE helper_id=? AND status=?',(user_id,STATUS_DONE)).fetchone(); _close(c); return float(row['avg']) if row and row['avg'] is not None else 0.0

def match_score(request, helper):
    categories=get_helper_categories(helper['user_id']); score=50 if (not categories or request['category'] in categories) else 0
    score += round(request_skill_match(request, helper)*35)
    score += min(profile_rating(helper['user_id'])*2,10)
    score += 5 if request['urgency']==URGENCY_OPTIONS[0] else 3 if request['urgency']==URGENCY_OPTIONS[1] else 0
    return score

def get_open_requests_for_helper(helper_id, limit=10):
    c=_db(); rows=c.execute("SELECT * FROM requests WHERE status=? AND requester_id!=? ORDER BY CASE WHEN featured_until IS NOT NULL AND datetime(featured_until)>datetime('now') THEN 0 ELSE 1 END, created_at DESC LIMIT 50",(STATUS_OPEN,helper_id)).fetchall(); _close(c); helper=get_user(helper_id); return sorted(rows,key=lambda r: -match_score(r,helper))[:limit]

def apply_to_request(request_id, helper_id):
    c=_db(); c.execute('BEGIN IMMEDIATE'); req=c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
    if not req or req['status']!=STATUS_OPEN or req['requester_id']==helper_id or c.execute('SELECT 1 FROM requests WHERE helper_id=? AND status=?',(helper_id,STATUS_IN_PROGRESS)).fetchone(): c.rollback(); _close(c); return False
    cur=c.execute('INSERT OR IGNORE INTO applications(request_id,helper_id,status) VALUES(?,?,?)',(request_id,helper_id,APP_PENDING)); c.commit(); _close(c);
    if cur.rowcount==1:
        notify_user(req['requester_id'], f'📨 Новый кандидат на заявку №{request_id}. Откройте «Мои кандидаты» в Telegram или на сайте.')
    return cur.rowcount==1

def get_candidates(request_id):
    c=_db(); rows=c.execute('SELECT a.*,u.name,u.username,u.skills,u.portfolio FROM applications a JOIN users u ON u.user_id=a.helper_id WHERE a.request_id=? AND a.status=? ORDER BY a.created_at',(request_id,APP_PENDING)).fetchall(); _close(c); return rows

def get_my_applications(helper_id, limit=20):
    c=_db(); rows=c.execute('SELECT a.*,r.what,r.category,r.required_skills,r.urgency,r.requester_id,u.name requester_name,u.skills requester_skills,u.portfolio requester_portfolio FROM applications a JOIN requests r ON r.id=a.request_id JOIN users u ON u.user_id=r.requester_id WHERE a.helper_id=? ORDER BY a.id DESC LIMIT ?',(helper_id,limit)).fetchall(); _close(c); return rows

def decide_application(application_id, requester_id, accept):
    c=_db(); c.execute('BEGIN IMMEDIATE'); app=c.execute('SELECT * FROM applications WHERE id=?',(application_id,)).fetchone()
    if not app: c.rollback(); _close(c); return None
    req=c.execute('SELECT * FROM requests WHERE id=?',(app['request_id'],)).fetchone()
    if not req or req['requester_id']!=requester_id or req['status']!=STATUS_OPEN or app['status']!=APP_PENDING: c.rollback(); _close(c); return None
    if not accept:
        c.execute('UPDATE applications SET status=? WHERE id=?',(APP_REJECTED,application_id)); c.commit(); _close(c); notify_user(app['helper_id'], f'❌ Ваш отклик на заявку №{req["id"]} отклонён автором. Вы можете выбрать другую заявку.'); return {'accepted':False,'request_id':req['id'],'helper_id':app['helper_id']}
    active=c.execute('SELECT 1 FROM requests WHERE helper_id=? AND status=?',(app['helper_id'],STATUS_IN_PROGRESS)).fetchone()
    if active: c.rollback(); _close(c); return None
    c.execute('UPDATE requests SET helper_id=?,status=? WHERE id=? AND status=?',(app['helper_id'],STATUS_IN_PROGRESS,req['id'],STATUS_OPEN)); c.execute('UPDATE applications SET status=? WHERE id=?',(APP_ACCEPTED,application_id)); c.execute('UPDATE applications SET status=? WHERE request_id=? AND id!=? AND status=?',(APP_REJECTED,req['id'],application_id,APP_PENDING)); c.commit(); _close(c);
    notify_user(app['helper_id'], f'🎉 Вас выбрали помощником по заявке №{req["id"]}! Откройте Telegram, чтобы продолжить взаимодействие.')
    return {'accepted':True,'request_id':req['id'],'helper_id':app['helper_id']}

def reject_application(application_id, helper_id):
    c=_db(); row=c.execute('SELECT request_id FROM applications WHERE id=? AND helper_id=? AND status=?',(application_id,helper_id,APP_PENDING)).fetchone()
    if not row: _close(c); return False
    cur=c.execute('UPDATE applications SET status=? WHERE id=? AND helper_id=? AND status=?',(APP_REJECTED,application_id,helper_id,APP_PENDING)); _close(c)
    if cur.rowcount==1:
        notify_user(get_request(row['request_id'])['requester_id'], f'↩️ Помощник отозвал отклик на заявку №{row["request_id"]}.'); return True
    return False

def boost_request(request_id,user_id):
    c=_db(); c.execute('BEGIN IMMEDIATE'); req=c.execute('SELECT * FROM requests WHERE id=? AND requester_id=? AND status=?',(request_id,user_id,STATUS_OPEN)).fetchone()
    if not req: c.rollback(); _close(c); return False,'Заявка недоступна.'
    bal=c.execute('SELECT balance FROM users WHERE user_id=?',(user_id,)).fetchone()
    if not bal or bal['balance']<BOOST_COST: c.rollback(); _close(c); return False,f'Нужно {BOOST_COST} HP.'
    until=(datetime.now().replace(microsecond=0)+timedelta(hours=BOOST_HOURS)).strftime('%Y-%m-%d %H:%M:%S'); c.execute('UPDATE users SET balance=balance-? WHERE user_id=?',(BOOST_COST,user_id)); c.execute('UPDATE requests SET featured_until=? WHERE id=?',(until,request_id)); c.commit(); _close(c); return True,'Заявка поднята в приоритет на 24 часа.'

def complete_request(request_id,helper_id):
    c=_db(); c.execute('BEGIN IMMEDIATE'); req=c.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
    if req is None or req['status']!=STATUS_IN_PROGRESS or req['helper_id']!=helper_id: c.rollback(); _close(c); return False
    requester=c.execute('SELECT balance FROM users WHERE user_id=?',(req['requester_id'],)).fetchone()
    if requester is None or requester['balance']<REQUEST_COST: c.rollback(); _close(c); return False
    c.execute('UPDATE requests SET status=?,completed_at=CURRENT_TIMESTAMP WHERE id=?',(STATUS_DONE,request_id)); c.execute('UPDATE users SET balance=balance-? WHERE user_id=?',(REQUEST_COST,req['requester_id'])); c.execute('UPDATE users SET balance=balance+? WHERE user_id=?',(HELPER_REWARD,helper_id)); c.commit(); _close(c); notify_user(req['requester_id'], f'✅ Помощь по заявке №{request_id} завершена. Откройте заявку для оценки помощника.'); notify_user(helper_id, f'✅ Заявка №{request_id} завершена. Вам начислено {HELPER_REWARD} HP.'); return True

def set_rating(request_id,user_id,rating,side,review=''):
    if not 1<=rating<=5:return False
    col='requester_rating' if side=='requester' else 'helper_rating' if side=='helper' else None; rev='requester_review' if side=='requester' else 'helper_review' if side=='helper' else None; who='requester_id' if side=='requester' else 'helper_id' if side=='helper' else None
    if not col:return False
    c=_db(); cur=c.execute(f'UPDATE requests SET {col}=?,{rev}=? WHERE id=? AND {who}=? AND status=? AND {col} IS NULL',(rating,review[:MAX_TEXT_LEN],request_id,user_id,STATUS_DONE)); _close(c); return cur.rowcount==1

def cancel_request(request_id,user_id):
    c=_db(); cur=c.execute('UPDATE requests SET status=? WHERE id=? AND requester_id=? AND status=?',(STATUS_CANCELLED,request_id,user_id,STATUS_OPEN)); _close(c); return cur.rowcount==1

def add_to_queue(user_id): c=_db(); c.execute('INSERT OR IGNORE INTO helper_queue(user_id) VALUES(?)',(user_id,)); _close(c)
def remove_from_queue(user_id): c=_db(); c.execute('DELETE FROM helper_queue WHERE user_id=?',(user_id,)); _close(c)
def is_in_queue(user_id): c=_db(); r=c.execute('SELECT 1 FROM helper_queue WHERE user_id=?',(user_id,)).fetchone(); _close(c); return r is not None


def notify_user(user_id, text):
    from .database import enqueue_notification
    enqueue_notification(user_id, text)
