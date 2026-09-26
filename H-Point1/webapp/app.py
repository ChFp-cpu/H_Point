import os, json, secrets, hashlib
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from hpoint.config import *
from hpoint.database import *
from hpoint.services import *

BASE=os.path.dirname(os.path.abspath(__file__))
app=Flask(__name__,template_folder='templates',static_folder='static')
app.secret_key=os.getenv('SECRET_KEY','change-this-secret-in-production')
app.config['MAX_CONTENT_LENGTH']=2*1024*1024
app.config['PERMANENT_SESSION_LIFETIME']=timedelta(days=30)
init_db()

def db(): return db_connect()
def current_user():
    uid=session.get('user_id')
    if not uid: return None
    u=get_user(uid)
    if not u:
        session.clear()
    return u

def hash_password(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def valid_password(value):
    return isinstance(value,str) and 4 <= len(value) <= 128
def login_required(f):
    @wraps(f)
    def w(*a,**kw): return f(*a,**kw) if current_user() else redirect(url_for('login'))
    return w
def active_own(uid): return get_active_own_request(uid)
def active_help(uid): return get_active_help(uid)
def flash_back(msg,cat='info'): flash(msg,cat); return redirect(request.referrer or url_for('dashboard'))
def stats(uid): return get_user_stats(uid)
def get_user_name(uid):
    if not uid:
        return '—'
    u=get_user(uid)
    return u['name'] if u else '—'

@app.context_processor
def inject():
    return {
        'get_user_name': get_user_name,
        'categories': CATEGORIES,
        'statuses': STATUS_TITLES,
        'urgency_options': URGENCY_OPTIONS,
        'current_user': current_user(),
        'request_cost': REQUEST_COST,
        'helper_reward': HELPER_REWARD,
        'boost_cost': BOOST_COST,
        'APP_PENDING': APP_PENDING
    }
@app.route('/')
def index(): return redirect(url_for('dashboard') if current_user() else url_for('login'))
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        mode=request.form.get('mode','login')
        username=normalize_username(request.form.get('username',''))
        password=request.form.get('password','')
        name=request.form.get('name','').strip()
        if not username or len(username)<3 or not valid_password(password):
            flash('Укажите никнейм (от 3 символов) и пароль (минимум 4 символа).','error'); return render_template('login.html')
        existing=get_web_user_by_username(username)
        if mode=='register':
            if existing:
                flash('Такой аккаунт уже существует. Войдите в него.','error'); return render_template('login.html')
            if not name or len(name)>MAX_NAME_LEN:
                flash('Имя должно быть от 1 до 50 символов.','error'); return render_template('login.html')
            uid=create_web_user(name,username,hash_password(password))
        else:
            if not existing:
                flash('Аккаунт не найден. Сначала зарегистрируйтесь.','error'); return render_template('login.html')
            if existing['password_hash'] and existing['password_hash'] != hash_password(password):
                flash('Неверный пароль.','error'); return render_template('login.html')
            if not existing['password_hash']:
                set_user_password(existing['user_id'],hash_password(password))
            uid=existing['user_id']
        session.permanent=True
        session['user_id']=uid
        return redirect(url_for('dashboard'))
    return render_template('login.html')
@app.post('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/dashboard')
@login_required
def dashboard():
    u=current_user(); c=db(); open_count=c.execute("SELECT COUNT(*) FROM requests WHERE status=?",(STATUS_OPEN,)).fetchone()[0]; done_count=c.execute("SELECT COUNT(*) FROM requests WHERE status=?",(STATUS_DONE,)).fetchone()[0]; pending=c.execute("SELECT COUNT(*) FROM applications a JOIN requests r ON r.id=a.request_id WHERE r.requester_id=? AND a.status=?",(u['user_id'],APP_PENDING)).fetchone()[0]; c.close(); return render_template('dashboard.html',own=active_own(u['user_id']),helping=active_help(u['user_id']),open_count=open_count,done_count=done_count,pending=pending)
@app.route('/request-help',methods=['GET','POST'])
@login_required
def request_help():
    u=current_user()
    if get_in_progress_task(u['user_id']): return flash_back('Сначала завершите текущую задачу.','error')
    if request.method=='POST':
        data={k:request.form.get(k,'').strip() for k in ('what','place','time_needed','urgency','details','required_skills')}
        if not data['details']: data['details']='Нет дополнительных деталей'
        if not all(data[k] for k in ('what','place','time_needed','urgency')): flash('Заполните обязательные поля.','error'); return render_template('request.html',data=data)
        if any(len(v)>MAX_TEXT_LEN for v in data.values()): flash('Слишком длинный текст.','error'); return render_template('request.html',data=data)
        rid=create_request(u['user_id'],data); flash('Заявка создана. Теперь вы выбираете помощника из откликов.','success'); return redirect(url_for('request_view',rid=rid))
    return render_template('request.html',data={})
@app.route('/marketplace')
@login_required
def marketplace():
    uid=current_user()['user_id']; rows=get_open_requests_for_helper(uid,30); return render_template('marketplace.html',requests=rows)
@app.post('/request/<int:rid>/apply')
@login_required
def apply_route(rid):
    if apply_to_request(rid,current_user()['user_id']): flash('Отклик отправлен. Автор заявки сможет выбрать вас.','success')
    else: flash('Не удалось отправить отклик. Возможно, заявка уже закрыта.','error')
    return redirect(url_for('marketplace'))
@app.route('/request/<int:rid>')
@login_required
def request_view(rid):
    r=get_request(rid)
    if not r:return render_template('error.html',code=404,message='Заявка не найдена'),404
    uid=current_user()['user_id']
    if r['requester_id']!=uid and r['helper_id']!=uid:return render_template('error.html',code=403,message='Нет доступа'),403
    candidates=get_candidates(rid) if r['requester_id']==uid else []
    requester=get_user(r['requester_id']); helper=get_user(r['helper_id']) if r['helper_id'] else None
    return render_template('request_view.html',r=r,candidates=candidates,reqname=requester,helper=helper)
@app.post('/request/<int:rid>/complete')
@login_required
def complete_route(rid):
    if complete_request(rid,current_user()['user_id']): flash('Помощь завершена. −10 HP у автора и +20 HP помощнику.','success')
    else: flash('Не удалось завершить заявку.','error')
    return redirect(url_for('request_view',rid=rid))
@app.post('/request/<int:rid>/cancel')
@login_required
def cancel(rid):
    flash('Заявка отменена.' if cancel_request(rid,current_user()['user_id']) else 'Заявку уже нельзя отменить.','success'); return redirect(url_for('dashboard'))
@app.post('/application/<int:aid>/accept')
@login_required
def accept_app(aid):
    result=decide_application(aid,current_user()['user_id'],True); flash('Помощник выбран.' if result else 'Кандидата уже нельзя выбрать.','success' if result else 'error'); return redirect(request.referrer or url_for('dashboard'))
@app.post('/application/<int:aid>/reject')
@login_required
def reject_app(aid):
    result=decide_application(aid,current_user()['user_id'],False); flash('Кандидат отсеян.' if result else 'Не удалось обработать кандидата.','success' if result else 'error'); return redirect(request.referrer or url_for('dashboard'))
@app.post('/application/<int:aid>/withdraw')
@login_required
def withdraw_app(aid):
    ok=reject_application(aid,current_user()['user_id']); flash('Отклик отозван.' if ok else 'Отклик уже обработан.','success' if ok else 'error'); return redirect(url_for('my_offers'))
@app.route('/candidates')
@login_required
def candidates():
    uid=current_user()['user_id']; c=db(); rows=c.execute('SELECT * FROM requests WHERE requester_id=? AND status=? ORDER BY id DESC',(uid,STATUS_OPEN)).fetchall(); c.close(); return render_template('candidates.html',requests=[(r,get_candidates(r['id'])) for r in rows])
@app.route('/my-offers')
@login_required
def my_offers(): return render_template('offers.html',offers=get_my_applications(current_user()['user_id']))
@app.post('/request/<int:rid>/boost')
@login_required
def boost(rid):
    ok,msg=boost_request(rid,current_user()['user_id']); flash(msg,'success' if ok else 'error'); return redirect(request.referrer or url_for('request_view',rid=rid))
@app.post('/request/<int:rid>/rate/<side>')
@login_required
def rate(rid,side):
    try: rating=int(request.form.get('rating','0'))
    except ValueError: rating=0
    ok=set_rating(rid,current_user()['user_id'],rating,side,request.form.get('review','')); flash('Оценка сохранена.' if ok else 'Не удалось сохранить оценку.','success' if ok else 'error'); return redirect(request.referrer or url_for('request_view',rid=rid))
@app.post('/telegram-link-code')
@login_required
def telegram_link_code():
    uid=current_user()['user_id']
    code=f'{secrets.randbelow(1000000):06d}'
    expires=(datetime.now()+timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
    create_link_token(uid,code,expires)
    flash(f'Код привязки Telegram: {code}. В боте отправьте /link {code}. Код действует 10 минут.','success')
    return redirect(url_for('profile'))

@app.route('/profile',methods=['GET','POST'])
@login_required
def profile():
    u=current_user()
    if request.method=='POST':
        set_profile(u['user_id'],request.form.get('skills','').strip(),request.form.get('portfolio','').strip()); flash('Профиль обновлён.','success'); return redirect(url_for('profile'))
    return render_template('profile.html',stats=stats(u['user_id']),selected=get_helper_categories(u['user_id']))
@app.post('/settings')
@login_required
def settings():
    set_helper_categories(current_user()['user_id'],[x for x in request.form.getlist('categories') if x in CATEGORIES]); flash('Настройки помощи сохранены.','success'); return redirect(url_for('profile'))
@app.route('/history')
@login_required
def history(): return render_template('history.html',history=get_history(current_user()['user_id'],50))
@app.get('/health')
def health(): return {'status':'ok','service':'hpoint','integration':'web+telegram','matching':'mutual-selection','monetization':'hp-boost'}
@app.errorhandler(404)
def not_found(e): return render_template('error.html',code=404,message='Страница не найдена'),404
