"""H-Point web-first application: dashboard, requests, Smart Match, chat, profile and RUB billing."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import json, os, secrets, hashlib, hmac, datetime as dt, re
from . import database
from .database import db, get_user, get_user_by_email, create_web_user, get_request, get_user_stats, get_active_own_request, get_history, get_billing_history
from .config import *
from .services import *
from .billing import create_pending_invoice, create_payment, fulfill_invoice

database.init_db()
YANDEX_MAPS_API_KEY = os.getenv("YANDEX_MAPS_API_KEY", "")

def now(): return dt.datetime.now(dt.timezone.utc)
def ph(p,s=None):
    s=s or secrets.token_hex(16)
    return s+"$"+hashlib.pbkdf2_hmac("sha256",p.encode(),s.encode(),180000).hex()
def pv(p,x):
    try:
        s,d=x.split("$",1)
        return hmac.compare_digest(ph(p,s).split("$",1)[1],d)
    except Exception: return False

def get_sess(h):
    c=h.headers.get("Cookie","")
    t=next((x.strip().split("=",1)[1] for x in c.split(";") if x.strip().startswith("hpoint_session=")),None)
    if not t: return None
    r=db.execute("SELECT * FROM sessions WHERE token=? AND expires_at>?",(t,now().isoformat())).fetchone()
    return get_user(r["user_id"]) if r else None

def new_sess(uid):
    t=secrets.token_urlsafe(32)
    e=(now()+dt.timedelta(seconds=SESSION_TTL)).isoformat()
    db.execute("INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)",(t,uid,e))
    return t

def read(h):
    return json.loads(h.rfile.read(int(h.headers.get("Content-Length","0"))) or b"{}")

def reply(h,d,status=200,headers=None):
    b=json.dumps(d,ensure_ascii=False).encode()
    h.send_response(status); h.send_header("Content-Type","application/json;charset=utf-8"); h.send_header("Cache-Control","no-store"); h.send_header("Content-Length",str(len(b)))
    for k,v in (headers or {}).items(): h.send_header(k,v)
    h.end_headers(); h.wfile.write(b)

def auth(h):
    u=get_sess(h)
    if not u:
        reply(h,{"ok":False,"error":"auth_required"},401); return None
    return u

def user_payload(u):
    stats=get_user_stats(u["user_id"])
    return {"id":u["user_id"],"name":u["name"],"email":u["email"],"balance":u["balance"],"city":u["city"] or "","bio":u["bio"] or "","lat":u["lat"],"lon":u["lon"],"verified":bool(u["web_verified"]) or is_verified(u["user_id"]),"tg_linked":bool(u["tg_user_id"]),"link_code":u["verification_code"],"pro_until":u["pro_until"],"verified_until":u["verified_until"],"business_until":u["business_until"],"stats":stats}

def request_payload(r):
    d=dict(r); d["category_name"]=CATEGORIES.get(r["category"],"Другое"); d["status_title"]=STATUS_TITLES.get(r["status"],r["status"]); return d

def chat_for_request(rid):
    row=db.execute("SELECT * FROM chats WHERE request_id=?",(rid,)).fetchone()
    if row: return row["id"]
    r=get_request(rid)
    if not r or not r["helper_id"]: return None
    cur=db.execute("INSERT INTO chats(request_id,user_a_id,user_b_id) VALUES(?,?,?)",(rid,r["requester_id"],r["helper_id"]))
    return cur.lastrowid

PAGE=r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>H·Point — помощь рядом</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet"><script src="https://api-maps.yandex.ru/2.1/?apikey=__YANDEX_MAPS_API_KEY__&lang=ru_RU" type="text/javascript"></script>
<style>
:root{--bg:#f5f7fb;--surface:#fff;--ink:#101828;--muted:#667085;--line:#e6eaf0;--brand:#5b5cf0;--brand2:#7c3aed;--ok:#12b76a;--warn:#f79009;--shadow:0 16px 50px rgba(16,24,40,.08)}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 80% -10%,#e9e8ff 0,transparent 35%),var(--bg);color:var(--ink);font-family:Manrope,system-ui,-apple-system,sans-serif}.nav{position:sticky;top:0;z-index:40;background:rgba(245,247,251,.86);backdrop-filter:blur(18px);border-bottom:1px solid rgba(230,234,240,.8)}.in,.wrap{width:min(1240px,100%);margin:auto;padding:0 24px}.in{height:74px;display:flex;align-items:center;gap:12px}.logo{font-size:25px;font-weight:800;letter-spacing:-1px}.logo b{color:var(--brand)}.sp{flex:1}.btn{border:0;border-radius:14px;padding:12px 17px;font:inherit;font-weight:800;cursor:pointer;transition:.2s;display:inline-flex;align-items:center;justify-content:center;gap:7px}.btn:hover{transform:translateY(-1px)}.dark{background:var(--ink);color:white}.light{background:var(--surface);color:var(--ink);border:1px solid var(--line)}.grad{background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff}.danger{color:#b42318;background:#fff;border:1px solid #fecdca}.ey{display:inline-flex;padding:7px 10px;border-radius:999px;background:#eeefff;color:#4c4fd0;font-size:11px;font-weight:800}.landingHero{padding:76px 0 55px;display:grid;grid-template-columns:1.1fr .9fr;gap:44px;align-items:center}.hero h1{font-size:clamp(46px,6vw,82px);line-height:.95;letter-spacing:-5px;margin:18px 0}.hero p{font-size:18px;line-height:1.7;color:var(--muted);max-width:650px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:25px}.cover{min-height:430px;border-radius:34px;background:linear-gradient(145deg,#111326,#2f3270);box-shadow:0 30px 80px rgba(31,35,90,.28);padding:22px;color:white;position:relative;overflow:hidden}.cover:before{content:"";position:absolute;width:270px;height:270px;border-radius:50%;background:#7778ff55;filter:blur(8px);right:-70px;top:-70px}.coverCard{position:relative;background:#ffffff12;border:1px solid #ffffff1f;border-radius:22px;padding:19px;margin-bottom:12px;backdrop-filter:blur(8px)}.coverCard strong{display:block;font-size:18px}.coverCard small{display:block;color:#cfd2e7;margin-top:7px;line-height:1.5}.coverMap{position:absolute;left:22px;right:22px;bottom:22px;height:110px;border-radius:18px;background:linear-gradient(135deg,#34386e,#171a35);border:1px solid #ffffff1f;display:flex;align-items:center;justify-content:center;color:#cfd2e7}.section{padding:54px 0}.section h2{font-size:34px;letter-spacing:-1.5px}.featureGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.card{background:rgba(255,255,255,.88);border:1px solid var(--line);border-radius:22px;padding:21px;box-shadow:0 8px 30px rgba(16,24,40,.04)}.muted{color:var(--muted)}.price{font-size:28px;font-weight:800}.app{display:none}.appHead{padding:35px 0 0}.welcome{display:flex;align-items:flex-end;gap:15px;justify-content:space-between}.welcome h1{font-size:42px;letter-spacing:-2px;margin:9px 0}.tabs{display:flex;gap:7px;overflow:auto;padding:22px 0 10px;position:sticky;top:74px;z-index:15;background:linear-gradient(var(--bg) 80%,transparent)}.tab{padding:10px 14px;border-radius:12px;border:1px solid transparent;background:transparent;white-space:nowrap;font:inherit;font-weight:700;color:var(--muted);cursor:pointer}.tab.active{background:white;border-color:var(--line);color:var(--ink);box-shadow:0 5px 20px #1018280b}.panel{display:none;padding:18px 0 60px}.panel.active{display:block}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.stat{padding:20px}.stat .big{font-size:28px;font-weight:800;margin-top:5px}.layout{display:grid;grid-template-columns:1.25fr .75fr;gap:16px}.form{display:grid;gap:11px}.input{width:100%;padding:13px 14px;border:1px solid var(--line);border-radius:13px;background:#fff;font:inherit;outline:none}.input:focus{border-color:#8d8ff7;box-shadow:0 0 0 4px #5b5cf012}.textarea{min-height:110px;resize:vertical}.request{display:flex;gap:14px;align-items:center;padding:16px;border:1px solid var(--line);border-radius:17px;background:#fff;margin:9px 0}.requestmain{flex:1;min-width:0}.badge{padding:6px 9px;border-radius:999px;background:#f2f4f7;font-size:11px;font-weight:800;white-space:nowrap}.badge.ok{background:#ecfdf3;color:#027a48}.badge.warn{background:#fffaeb;color:#b54708}.map{height:460px;border-radius:22px;overflow:hidden;border:1px solid var(--line);background:#eef0f5}.match{padding:16px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px}.avatar{width:42px;height:42px;border-radius:14px;background:linear-gradient(135deg,#ececff,#ddd8ff);display:flex;align-items:center;justify-content:center;font-weight:800}.grow{flex:1;min-width:0}.modal{position:fixed;inset:0;background:#10182899;display:none;align-items:center;justify-content:center;z-index:100;padding:20px}.box{background:#fff;border-radius:26px;padding:26px;width:min(600px,100%);max-height:90vh;overflow:auto;box-shadow:0 30px 100px #10182833}.close{float:right;border:0;background:none;font-size:25px;cursor:pointer}.chat{height:480px;display:flex;flex-direction:column}.messages{flex:1;overflow:auto;padding:12px;background:#f7f8fb;border-radius:17px}.msg{max-width:78%;padding:10px 13px;border-radius:16px;background:#fff;margin:7px 0;border:1px solid var(--line)}.msg.mine{margin-left:auto;background:#eef0ff;border-color:#d9dbff}.msg small{display:block;color:var(--muted);font-size:10px;margin-top:4px}.chatbar{display:flex;gap:8px;margin-top:10px}.empty{padding:32px;text-align:center;color:var(--muted)}.toast{position:fixed;right:20px;bottom:20px;z-index:200;background:#101828;color:#fff;border-radius:14px;padding:13px 16px;box-shadow:var(--shadow);display:none}.verify{background:linear-gradient(135deg,#f0f0ff,#fff);border:1px solid #dfe1ff}.profileGrid{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:900px){.landingHero,.layout,.profileGrid{grid-template-columns:1fr}.featureGrid{grid-template-columns:1fr 1fr}.stats{grid-template-columns:1fr 1fr}}@media(max-width:600px){.in,.wrap{padding:0 15px}.featureGrid,.stats{grid-template-columns:1fr}.hero h1{letter-spacing:-3px}.welcome h1{font-size:32px}.cover{min-height:390px}.request{align-items:flex-start;flex-wrap:wrap}}
</style></head><body>
<header class="nav"><div class="in"><div class="logo">H·Point<b>.</b></div><div class="sp"></div><div id="nav"></div></div></header>
<main id="landing" class="wrap"><section class="landingHero"><div class="hero"><span class="ey">ПОМОЩЬ РЯДОМ · SMART MATCH</span><h1>Найди помощь.<br>Помоги другим.</h1><p>H·Point объединяет заявки, людей рядом, умный подбор, карту, рейтинг и Telegram. Сайт — главное пространство, бот — быстрый второй вход.</p><div class="actions"><button class="btn dark" onclick="authForm(true)">Создать аккаунт</button><button class="btn light" onclick="authForm(false)">Войти</button></div></div><div class="cover"><div class="coverCard"><strong>⚡ Smart Match</strong><small>Подбираем помощников по категории, рейтингу, верификации и расстоянию.</small></div><div class="coverCard"><strong>⭐ Живой рейтинг</strong><small>Отзывы появляются после реального взаимодействия.</small></div><div class="coverCard"><strong>💬 Сайт + Telegram</strong><small>Один аккаунт, единая история и заявки.</small></div><div class="coverMap">● 12 помощников рядом · 4 подходят сейчас</div></div></section>
<section class="section"><h2>Как работает H·Point</h2><div class="featureGrid"><div class="card"><h3>01 · Создай заявку</h3><p class="muted">Опиши задачу, место и время. Можно добавить геопозицию.</p></div><div class="card"><h3>02 · Smart Match</h3><p class="muted">Система покажет подходящих людей на карте и в списке.</p></div><div class="card"><h3>03 · Общайтесь</h3><p class="muted">После назначения открывается чат по конкретной заявке.</p></div><div class="card"><h3>04 · Завершите</h3><p class="muted">После помощи обе стороны ставят оценку и оставляют отзыв.</p></div><div class="card"><h3>05 · Telegram</h3><p class="muted">Привяжите Telegram один раз и используйте бота как второй интерфейс.</p></div><div class="card"><h3>06 · H·Point+</h3><p class="muted">Платные функции оплачиваются в рублях через внешний эквайринг.</p></div></div></section>
<section class="section"><h2>H·Point+</h2><p class="muted">Оплата в рублях. Telegram Stars не используются.</p><div id="prices" class="featureGrid"></div></section></main>
<main id="app" class="wrap app"><section class="appHead"><div class="welcome"><div><span class="ey">ТВОЙ H·POINT</span><h1 id="welcome"></h1><div id="verifyNotice"></div></div><button class="btn light" onclick="logout()">Выйти</button></div><div class="tabs"><button class="tab active" data-t="home">Главная</button><button class="tab" data-t="requests">Заявки</button><button class="tab" data-t="match">Smart Match</button><button class="tab" data-t="chat">Чаты</button><button class="tab" data-t="map">Карта</button><button class="tab" data-t="history">История</button><button class="tab" data-t="profile">Профиль</button><button class="tab" data-t="billing">H·Point+</button></div></section>
<section id="p-home" class="panel active"><div class="stats"><div class="card stat"><span class="muted">Баланс</span><div class="big" id="bal"></div></div><div class="card stat"><span class="muted">Ваш рейтинг</span><div class="big" id="rate"></div></div><div class="card stat"><span class="muted">Помощей оказано</span><div class="big" id="helped"></div></div><div class="card stat"><span class="muted">Помощей получено</span><div class="big" id="received"></div></div></div><div class="layout" style="margin-top:16px"><div class="card"><span class="ey">БЫСТРЫЙ СТАРТ</span><h2>Что сделаем сейчас?</h2><div class="actions"><button class="btn grad" onclick="requestForm()">🆘 Нужна помощь</button><button class="btn light" onclick="helper()">🤝 Хочу помочь</button><button class="btn light" onclick="go('match')">⚡ Найти человека</button></div></div><div class="card verify"><h3>🔐 Подтверждение личности</h3><p id="verifyText" class="muted"></p><button class="btn light" onclick="go('profile')">Открыть профиль</button></div></div></section>
<section id="p-requests" class="panel"><div class="layout"><div><div style="display:flex;justify-content:space-between;align-items:center"><h2>Заявки</h2><button class="btn grad" onclick="requestForm()">+ Новая</button></div><div id="mine"></div></div><div class="card"><h3>Умный поиск</h3><input id="searchInput" class="input" placeholder="Например: нужна дрель рядом"><select id="searchCategory" class="input"><option value="">Все категории</option><option value="tech">Техника</option><option value="tools">Инструменты</option><option value="carry">Перенос / переезд</option><option value="shopping">Покупки</option><option value="study">Учёба</option><option value="transport">Транспорт</option><option value="snow">Снег / уборка</option></select><button class="btn dark" style="width:100%" onclick="searchOpen()">Найти заявки</button><div id="searchResults" style="margin-top:12px"></div></div></div></section>
<section id="p-match" class="panel"><div class="layout"><div><h2>Smart Match</h2><div class="card form"><select id="rid" class="input"></select><button class="btn grad" onclick="match()">⚡ Найти лучших кандидатов</button></div><div id="matches" class="card" style="padding:0;margin-top:15px"></div></div><div><div id="mapMatch" class="map"></div></div></div></section>
<section id="p-chat" class="panel"><div class="layout"><div class="card"><h2>Чаты</h2><div id="chatList"></div></div><div class="card"><div id="chatWindow" class="empty">Выберите чат с назначенным помощником или заказчиком.</div></div></div></section>
<section id="p-map" class="panel"><h2>Карта</h2><p class="muted">Открытые заявки и найденные Smart Match-кандидаты.</p><div id="bigMap" class="map"></div></section>
<section id="p-history" class="panel"><h2>История</h2><div id="historyList"></div></section>
<section id="p-profile" class="panel"><div class="profileGrid"><div class="card"><h2>Профиль</h2><div class="form"><input id="pn" class="input" placeholder="Имя"><input id="pc" class="input" placeholder="Город"><textarea id="pb" class="input textarea" placeholder="Коротко о себе"></textarea><button class="btn grad" onclick="saveProfile()">Сохранить профиль</button></div><div id="profInfo" style="margin-top:18px"></div></div><div class="card"><h2>Telegram</h2><p class="muted">Telegram подтверждает связь аккаунта и даёт быстрый доступ к тем же заявкам.</p><div id="tgState"></div><button class="btn light" onclick="linkcode()">Получить новый код привязки</button><div id="code" class="ey" style="margin-top:12px">—</div><p class="muted" style="margin-top:12px">В боте: <b>/link КОД</b>. После привязки обновите страницу.</p></div></div></section>
<section id="p-billing" class="panel"><div class="layout"><div><h2>H·Point+</h2><p class="muted">Платные возможности сайта. Оплата — в рублях через эквайринг.</p><div id="appprices" class="featureGrid"></div></div><div class="card"><h3>Подписки и доступ</h3><div id="subs"></div><hr style="border:0;border-top:1px solid var(--line);margin:18px 0"><h3>Платежи</h3><div id="payments"></div></div></div></section></main>
<div id="modal" class="modal"><div class="box"><button class="close" onclick="closeModal()">×</button><div id="modalbody"></div></div></div><div id="toast" class="toast"></div>
<script>
const products=[['boost','Продвижение заявки','Поднимает заявку в Smart Match',49],['more_responses','Больше откликов','Дополнительный приоритет',79],['pro','H·Point PRO','Расширенные возможности на 30 дней',299],['verification','Верификация','Проверенный профиль на 365 дней',99],['favorites','Избранное+','Дополнительные слоты',149],['business','Business','Инструменты для коммерческих задач',999],['business_pro','Business Pro','Расширенный Business-доступ',1499],['ad','Локальное объявление','Показы объявления 7 дней',199]];
let matchMap=null,bigMap=null,currentChat=null,syncTimer=null;
const $=id=>document.getElementById(id); const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(url,opt={}){let r=await fetch(url,{credentials:'same-origin',headers:{'Content-Type':'application/json',...(opt.headers||{})},...opt});let d=await r.json();if(!r.ok)throw Error(d.error||'Ошибка');return d}
function toast(s){$('toast').textContent=s;$('toast').style.display='block';setTimeout(()=>$('toast').style.display='none',2600)}
function go(t){document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.dataset.t===t));document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('active',x.id==='p-'+t));if(t==='requests')requests();if(t==='match'){requests();setTimeout(initMatchMap,50)}if(t==='chat')loadChats();if(t==='map')setTimeout(loadBigMap,50);if(t==='history')history();if(t==='profile')profile();if(t==='billing'){prices('appprices',true);billing()}}
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>go(b.dataset.t));
function prices(id,paid){$(id).innerHTML=products.map(p=>`<div class="card"><span class="ey">H·POINT+</span><h3>${p[1]}</h3><p class="muted">${p[2]}</p><div class="price">${p[3]} ₽</div>${paid?`<button class="btn grad" onclick="buy('${p[0]}')">Оплатить</button>`:''}</div>`).join('')}
function authForm(reg){$('modal').style.display='flex';$('modalbody').innerHTML=reg?`<h2>Создать аккаунт</h2><p class="muted">После регистрации вы сразу попадёте в личное пространство. Telegram можно привязать в профиле.</p><div class="form"><input id="an" class="input" placeholder="Имя"><input id="ae" class="input" placeholder="Email"><input id="ap" class="input" type="password" placeholder="Пароль от 8 символов"><button class="btn grad" onclick="register()">Создать аккаунт</button><div id="err" class="muted"></div></div>`:`<h2>Войти</h2><div class="form"><input id="ae" class="input" placeholder="Email"><input id="ap" class="input" type="password" placeholder="Пароль"><button class="btn grad" onclick="login()">Войти</button><div id="err" class="muted"></div></div>`}
function closeModal(){$('modal').style.display='none'}
async function register(){try{let d=await api('/api/auth/register',{method:'POST',body:JSON.stringify({name:an.value,email:ae.value,password:ap.value})});closeModal();toast('Аккаунт создан');await load();if(d.link_code)go('profile')}catch(e){$('err').textContent=e.message}}
async function login(){try{await api('/api/auth/login',{method:'POST',body:JSON.stringify({email:ae.value,password:ap.value})});closeModal();await load();toast('С возвращением')}catch(e){$('err').textContent=e.message}}
async function logout(){await fetch('/api/auth/logout',{method:'POST'});location.reload()}
function landing(){ $('landing').style.display='block';$('app').style.display='none';$('nav').innerHTML='<button class="btn light" onclick="authForm(false)">Войти</button><button class="btn dark" onclick="authForm(true)">Регистрация</button>';prices('prices',false)}
async function load(){try{let d=await api('/api/dashboard');$('landing').style.display='none';$('app').style.display='block';$('nav').innerHTML='<button class="btn light" onclick="go(\'profile\')">Профиль</button><button class="btn dark" onclick="requestForm()">+ Заявка</button>';$('welcome').textContent='Добро пожаловать, '+d.user.name;$('bal').textContent=d.user.balance+' HP';$('rate').textContent=d.user.stats.helped_avg?'⭐ '+d.user.stats.helped_avg.toFixed(1):'—';$('helped').textContent=d.user.stats.helped;$('received').textContent=d.user.stats.received;$('verifyText').textContent=d.user.verified?'Профиль подтверждён. Можно пользоваться всеми основными функциями.':'Привяжите Telegram в профиле, чтобы подтвердить аккаунт и получить полный доступ к связке сайта и бота.';$('verifyNotice').innerHTML=d.user.verified?'<span class="badge ok">✓ Профиль подтверждён</span>':'<span class="badge warn">Нужно привязать Telegram</span>';await requests();await profile();prices('appprices',true);await billing();startSync()}catch(e){landing()}}
async function syncTick(){try{let d=await api('/api/dashboard');$('welcome').textContent='Добро пожаловать, '+d.user.name;$('bal').textContent=d.user.balance+' HP';$('rate').textContent=d.user.stats.helped_avg?'⭐ '+d.user.stats.helped_avg.toFixed(1):'—';$('helped').textContent=d.user.stats.helped;$('received').textContent=d.user.stats.received;await requests();let tab=document.querySelector('.tab.active')?.dataset.t;if(tab==='history')await history();if(tab==='billing')await billing()}catch(e){if(e.message==='auth_required')stopSync()}}
function startSync(){if(syncTimer)return;syncTimer=setInterval(()=>{if(document.visibilityState==='visible')syncTick()},1500)}
function stopSync(){if(syncTimer){clearInterval(syncTimer);syncTimer=null}}
async function requests(){let d=await api('/api/requests/mine');$('mine').innerHTML=d.requests.length?d.requests.map(r=>`<div class="request"><div class="avatar">${esc((r.what||'?')[0].toUpperCase())}</div><div class="requestmain"><b>#${r.id} · ${esc(r.what)}</b><div class="muted">${esc(r.category_name)} · ${esc(r.place)} · ${esc(r.status_title)}</div></div><span class="badge ${r.status==='done'?'ok':r.status==='in_progress'?'warn':''}">${esc(r.urgency)}</span>${r.status==='in_progress'&&r.helper_id===d.current_user_id?`<button class="btn grad" onclick="finish(${r.id})">Завершить</button>`:''}${r.status==='in_progress'?`<button class="btn light" onclick="openChat(${r.id})">Чат</button>`:''}${r.status==='done'&&r.requester_id===d.current_user_id&&!r.requester_rating?`<button class="btn light" onclick="review(${r.id},'requester')">Оценить</button>`:''}${r.status==='done'&&r.helper_id===d.current_user_id&&!r.helper_rating?`<button class="btn light" onclick="review(${r.id},'helper')">Оценить</button>`:''}</div>`).join(''):'<div class="empty">Здесь появятся ваши заявки.</div>'; $('rid').innerHTML=d.requests.filter(r=>r.status==='open').map(r=>`<option value="${r.id}">#${r.id} — ${esc(r.what)}</option>`).join('')||'<option value="">Нет открытых заявок</option>'}
function requestForm(){ $('modal').style.display='flex';$('modalbody').innerHTML=`<h2>Новая заявка</h2><p class="muted">Опишите задачу понятно. Геопозиция используется только для подбора.</p><div class="form"><input id="qw" class="input" placeholder="Что нужно сделать?"><input id="qp" class="input" placeholder="Район / ориентир"><input id="qt" class="input" placeholder="Когда нужна помощь?"><select id="qc" class="input"><option value="other">Другое</option><option value="carry">Перенос / переезд</option><option value="shopping">Покупки</option><option value="snow">Снег / уборка</option><option value="tools">Инструменты</option><option value="transport">Транспорт</option><option value="tech">Техника</option><option value="study">Учёба</option></select><select id="qu" class="input"><option>🔥 Очень срочно</option><option>⏳ В течение дня</option><option>🕊 Не срочно</option></select><textarea id="qd" class="input textarea" placeholder="Детали"></textarea><button class="btn grad" onclick="createReq()">Создать заявку</button><div id="rqerr" class="muted"></div></div>`}
function createReq(){navigator.geolocation.getCurrentPosition(p=>sendReq(p.coords.latitude,p.coords.longitude),()=>sendReq(null,null))}
async function sendReq(lat,lon){try{let d=await api('/api/requests',{method:'POST',body:JSON.stringify({what:qw.value,place:qp.value,time_needed:qt.value,urgency:qu.value,details:qd.value,category:qc.value,lat,lon})});closeModal();await requests();toast('Заявка #'+d.request_id+(d.matched?' · помощник уже найден':' создана'));go('match')}catch(e){$('rqerr').textContent=e.message}}
async function helper(){try{let d=await api('/api/helper/queue',{method:'POST'});toast(d.message)}catch(e){toast(e.message)}}
function initMatchMap(){if(!matchMap){matchMap=new ymaps.Map('mapMatch',{center:[55.75,37.62],zoom:10,controls:['zoomControl','searchControl']},{searchControlProvider:'yandex#search'})}setTimeout(()=>matchMap.container.fitToViewport(),100)}
async function match(){if(!rid.value)return;try{let d=await api('/api/smart-match?request_id='+rid.value);$('matches').innerHTML=d.matches.length?d.matches.map(x=>`<div class="match"><div class="avatar">${esc((x.name||'?')[0])}</div><div class="grow"><b>${esc(x.name)} ${x.verified?'✓':''}</b><div class="muted">⭐ ${x.rating||'—'} · ${x.distance_km??'—'} км · ${x.reviews} отзывов · match ${Math.round(x.score)}%</div></div><button class="btn grad" onclick="assign(${rid.value},${x.user_id})">Предложить</button></div>`).join(''):'<div class="empty">Пока нет подходящих кандидатов.</div>';initMatchMap();d.matches.filter(x=>x.lat&&x.lon).forEach(x=>{const pm=new ymaps.Placemark([x.lat,x.lon],{balloonContent:esc(x.name)});matchMap.geoObjects.add(pm)});}catch(e){toast(e.message)}}
async function assign(r,h){try{await api('/api/smart-match/assign',{method:'POST',body:JSON.stringify({request_id:r,helper_id:h})});toast('Помощник назначен, чат создан');await requests();openChat(r)}catch(e){toast(e.message)}}
async function finish(id){try{await api('/api/requests/finish',{method:'POST',body:JSON.stringify({request_id:id})});toast('Помощь завершена');await requests()}catch(e){toast(e.message)}}
function review(id,side){$('modal').style.display='flex';$('modalbody').innerHTML=`<h2>Оценить взаимодействие</h2><div class="form"><select id="rv" class="input"><option value="5">5 ⭐</option><option value="4">4 ⭐</option><option value="3">3 ⭐</option><option value="2">2 ⭐</option><option value="1">1 ⭐</option></select><textarea id="rt" class="input textarea" placeholder="Отзыв"></textarea><button class="btn grad" onclick="sendReview(${id},'${side}')">Сохранить</button></div>`}
async function sendReview(id,side){try{await api('/api/reviews',{method:'POST',body:JSON.stringify({request_id:id,side,rating:Number(rv.value),review:rt.value})});closeModal();toast('Спасибо за отзыв');await requests();await load()}catch(e){toast(e.message)}}
async function profile(){let d=await api('/api/me'),u=d.user;$('pn').value=u.name||'';$('pc').value=u.city||'';$('pb').value=u.bio||'';$('profInfo').innerHTML=`<p><b>${esc(u.name)}</b></p><p class="muted">${esc(u.email||'')}<br>Рейтинг: ${u.stats.helped_avg?u.stats.helped_avg.toFixed(1):'—'} · ${u.stats.helped} помощей</p>`;$('tgState').innerHTML=u.tg_linked?'<span class="badge ok">✓ Telegram привязан</span>':'<span class="badge warn">Telegram не привязан</span>';$('code').textContent=u.link_code||'Код не создан'}
async function saveProfile(){try{await api('/api/profile',{method:'POST',body:JSON.stringify({name:pn.value,city:pc.value,bio:pb.value})});toast('Профиль сохранён');await load()}catch(e){toast(e.message)}}
async function linkcode(){try{let d=await api('/api/auth/link-code',{method:'POST'});$('code').textContent=d.code;toast('Код создан')}catch(e){toast(e.message)}}
async function history(){let d=await api('/api/history');$('historyList').innerHTML=d.requests.length?d.requests.map(r=>`<div class="request"><div class="requestmain"><b>#${r.id} · ${esc(r.what)}</b><div class="muted">${r.role} · ${esc(r.status_title)} · ${new Date(r.created_at).toLocaleString('ru-RU')}</div></div><span class="badge">${r.rating?'⭐ '+r.rating:'без оценки'}</span></div>`).join(''):'<div class="empty">История пока пуста.</div>'}
async function searchOpen(){let q=encodeURIComponent($('searchInput').value),c=encodeURIComponent($('searchCategory').value);let d=await api('/api/search?q='+q+'&category='+c);$('searchResults').innerHTML=d.requests.length?d.requests.map(r=>`<div class="request"><div class="requestmain"><b>#${r.id} · ${esc(r.what)}</b><div class="muted">${esc(r.category_name)} · ${esc(r.place)} · ${esc(r.urgency)}</div></div><button class="btn light" onclick="go('match')">Match</button></div>`).join(''):'<div class="empty">Ничего не найдено.</div>'}
async function loadChats(){let d=await api('/api/chats');$('chatList').innerHTML=d.chats.length?d.chats.map(c=>`<button class="request" style="width:100%;text-align:left;border:1px solid var(--line);cursor:pointer" onclick="openChat(${c.request_id})"><div class="avatar">${esc((c.other_name||'?')[0])}</div><div class="requestmain"><b>${esc(c.other_name)}</b><div class="muted">Заявка #${c.request_id} · ${esc(c.last_message||'Новый чат')}</div></div></button>`).join(''):'<div class="empty">Чатов пока нет. Они появятся после назначения помощника.</div>'}
async function openChat(rid){go('chat');currentChat=rid;let d=await api('/api/chats?request_id='+rid);let c=d.chats[0];if(!c){toast('Чат ещё не создан');return}$('chatWindow').innerHTML=`<div class="chat"><div><b>Заявка #${c.request_id} · ${esc(c.other_name)}</b></div><div id="messages" class="messages"></div><div class="chatbar"><input id="chatInput" class="input" placeholder="Напишите сообщение..."><button class="btn grad" onclick="sendChat()">Отправить</button></div></div>`;renderMessages(c.messages)}
function renderMessages(ms){$('messages').innerHTML=ms.map(m=>`<div class="msg ${m.mine?'mine':''}">${esc(m.text)}<small>${esc(m.author_name)} · ${new Date(m.created_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}</small></div>`).join('');$('messages').scrollTop=$('messages').scrollHeight}
async function sendChat(){let text=$('chatInput').value.trim();if(!text)return;try{let d=await api('/api/chats/send',{method:'POST',body:JSON.stringify({request_id:currentChat,text})});$('chatInput').value='';renderMessages(d.messages)}catch(e){toast(e.message)}}
function loadBigMap(){if(!bigMap){bigMap=new ymaps.Map('bigMap',{center:[55.75,37.62],zoom:10,controls:['zoomControl','searchControl']},{searchControlProvider:'yandex#search'})}setTimeout(()=>bigMap.container.fitToViewport(),100);api('/api/requests?open=1').then(d=>{bigMap.geoObjects.removeAll();d.requests.filter(r=>r.lat&&r.lon).forEach(r=>{const pm=new ymaps.Placemark([r.lat,r.lon],{balloonContent:'#'+r.id+' · '+esc(r.what)});bigMap.geoObjects.add(pm)})}).catch(()=>{})}
async function billing(){let d=await api('/api/billing');$('subs').innerHTML=`<p>PRO: <b>${d.user.pro_until?new Date(d.user.pro_until).toLocaleDateString('ru-RU'):'нет'}</b></p><p>Верификация: <b>${d.user.verified_until?new Date(d.user.verified_until).toLocaleDateString('ru-RU'):'нет'}</b></p><p>Business: <b>${d.user.business_until?new Date(d.user.business_until).toLocaleDateString('ru-RU'):'нет'}</b></p>`;$('payments').innerHTML=d.history.length?d.history.map(x=>`<div class="request"><div class="requestmain"><b>${esc(x.item_type)}</b><div class="muted">${x.amount_rub} ₽ · ${x.status}</div></div></div>`).join(''):'<div class="muted">Платежей пока нет.</div>'}
async function buy(item){let meta={};if(item==='boost'||item==='more_responses'){let id=prompt('ID заявки для продвижения:');if(!id)return;meta.request_id=Number(id)}try{let d=await api('/api/payments/create',{method:'POST',body:JSON.stringify({item_type:item,metadata:meta,request_id:meta.request_id})});location.href=d.confirmation_url}catch(e){toast(e.message)}}
load();
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    server_version="HPointWeb/3.0"
    def log_message(self,f,*a): print("[WEB]",f%a)
    def html(self):
        b=PAGE.replace("__YANDEX_MAPS_API_KEY__", YANDEX_MAPS_API_KEY).encode();self.send_response(200);self.send_header("Content-Type","text/html;charset=utf-8");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        database.init_db(); p=urlparse(self.path)
        try:
            if p.path in ("/","/index.html","/payment/result"): return self.html()
            if p.path=="/api/health": return reply(self,{"ok":True,"database":True,"bot_configured":bool(os.getenv("BOT_TOKEN")),"acquiring_configured":bool(YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY)})
            if p.path=="/api/me":
                u=auth(self)
                if not u:return
                return reply(self,{"ok":True,"user":user_payload(u)})
            if p.path=="/api/dashboard":
                u=auth(self)
                if not u:return
                return reply(self,{"ok":True,"user":user_payload(u)})
            if p.path=="/api/requests/mine":
                u=auth(self)
                if not u:return
                rs=get_history(u["user_id"],HISTORY_LIMIT)
                return reply(self,{"ok":True,"current_user_id":u["user_id"],"requests":[request_payload(r) for r in rs]})
            if p.path=="/api/history":
                u=auth(self)
                if not u:return
                rs=get_history(u["user_id"],100);out=[]
                for r in rs:
                    role="Вы просили помощь" if r["requester_id"]==u["user_id"] else "Вы помогали";rating=r["requester_rating"] if r["requester_id"]==u["user_id"] else r["helper_rating"]
                    x=request_payload(r);x["role"]=role;x["rating"]=rating;out.append(x)
                return reply(self,{"ok":True,"requests":out})
            if p.path=="/api/search":
                u=auth(self)
                if not u:return
                q=parse_qs(p.query).get("q",[""])[0].strip().lower();cat=parse_qs(p.query).get("category",[""])[0]
                rows=db.execute("SELECT * FROM requests WHERE status=? ORDER BY priority_boost DESC,created_at DESC LIMIT 100",(STATUS_OPEN,)).fetchall();out=[]
                for r in rows:
                    if r["requester_id"]==u["user_id"]: continue
                    if cat and r["category"]!=cat: continue
                    hay=(r["what"]+" "+r["details"]+" "+r["place"]).lower()
                    if q and q not in hay: continue
                    out.append(request_payload(r))
                return reply(self,{"ok":True,"requests":out[:30]})
            if p.path=="/api/requests":
                if parse_qs(p.query).get("open",[""])[0]:
                    rs=db.execute("SELECT * FROM requests WHERE status=? ORDER BY priority_boost DESC,created_at DESC LIMIT 100",(STATUS_OPEN,)).fetchall()
                    return reply(self,{"ok":True,"requests":[dict(r) for r in rs]})
                u=auth(self)
                if not u:return
                return reply(self,{"ok":True,"requests":[request_payload(r) for r in get_history(u["user_id"],HISTORY_LIMIT)]})
            if p.path=="/api/smart-match":
                u=auth(self)
                if not u:return
                try: rid=int(parse_qs(p.query).get("request_id",[""])[0])
                except: return reply(self,{"ok":False,"error":"Некорректный request_id"},400)
                r=get_request(rid)
                if not r or r["requester_id"]!=u["user_id"]: return reply(self,{"ok":False,"error":"Заявка не найдена"},404)
                return reply(self,{"ok":True,"matches":smart_match(rid)})
            if p.path=="/api/chats":
                u=auth(self)
                if not u:return
                q=parse_qs(p.query).get("request_id",[None])[0]
                if q:
                    rid=int(q);c=db.execute("SELECT * FROM chats WHERE request_id=? AND (user_a_id=? OR user_b_id=?)",(rid,u["user_id"],u["user_id"])).fetchone()
                    if not c:return reply(self,{"ok":True,"chats":[]})
                    msgs=db.execute("SELECT m.*,u.name author_name FROM chat_messages m JOIN users u ON u.user_id=m.user_id WHERE m.chat_id=? ORDER BY m.id",(c["id"],)).fetchall()
                    other=get_user(c["user_b_id"] if c["user_a_id"]==u["user_id"] else c["user_a_id"])
                    return reply(self,{"ok":True,"chats":[{"request_id":rid,"other_name":other["name"],"messages":[{**dict(m),"mine":m["user_id"]==u["user_id"]} for m in msgs]}]})
                cs=db.execute("SELECT c.*,r.what,u.name other_name,(SELECT text FROM chat_messages m WHERE m.chat_id=c.id ORDER BY m.id DESC LIMIT 1) last_message FROM chats c JOIN requests r ON r.id=c.request_id JOIN users u ON u.user_id=CASE WHEN c.user_a_id=? THEN c.user_b_id ELSE c.user_a_id END WHERE c.user_a_id=? OR c.user_b_id=? ORDER BY c.id DESC",(u["user_id"],u["user_id"],u["user_id"])).fetchall()
                return reply(self,{"ok":True,"chats":[dict(c) for c in cs]})
            if p.path=="/api/billing":
                u=auth(self)
                if not u:return
                return reply(self,{"ok":True,"user":user_payload(u),"history":[dict(x) for x in database.get_billing_history(u["user_id"]) ]})
            self.send_error(404)
        except Exception as e:
            print("[WEB][ERROR]",repr(e));reply(self,{"ok":False,"error":"Внутренняя ошибка сервера"},500)
    def do_POST(self):
        database.init_db(); p=urlparse(self.path)
        try:d=read(self)
        except:return reply(self,{"ok":False,"error":"Некорректный JSON"},400)
        try:
            if p.path=="/api/auth/register":
                n=str(d.get("name","")).strip();e=str(d.get("email","")).strip().lower();pw=str(d.get("password",""))
                if not 2<=len(n)<=MAX_NAME_LEN:return reply(self,{"ok":False,"error":"Имя должно быть от 2 до 50 символов."},400)
                if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",e):return reply(self,{"ok":False,"error":"Введите корректный email."},400)
                if len(pw)<8:return reply(self,{"ok":False,"error":"Пароль должен быть не короче 8 символов."},400)
                if get_user_by_email(e):return reply(self,{"ok":False,"error":"Этот email уже зарегистрирован."},409)
                uid=create_web_user(n,e,ph(pw));t=new_sess(uid);c=secrets.token_hex(4).upper();db.execute("UPDATE users SET verification_code=? WHERE user_id=?",(c,uid))
                return reply(self,{"ok":True,"link_code":c},headers={"Set-Cookie":f"hpoint_session={t}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}"})
            if p.path=="/api/auth/login":
                u=get_user_by_email(str(d.get("email","")).strip().lower())
                if not u or not u["password_hash"] or not pv(str(d.get("password","")),u["password_hash"]):return reply(self,{"ok":False,"error":"Неверный email или пароль."},401)
                t=new_sess(u["user_id"]);return reply(self,{"ok":True},headers={"Set-Cookie":f"hpoint_session={t}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}"})
            if p.path=="/api/auth/logout":
                c=self.headers.get("Cookie","");t=next((x.strip().split("=",1)[1] for x in c.split(";") if x.strip().startswith("hpoint_session=")),None)
                if t:db.execute("DELETE FROM sessions WHERE token=?",(t,))
                return reply(self,{"ok":True},headers={"Set-Cookie":"hpoint_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"})
            if p.path=="/api/auth/link-code":
                u=auth(self)
                if not u:return
                c=secrets.token_hex(4).upper();db.execute("UPDATE users SET verification_code=? WHERE user_id=?",(c,u["user_id"]));return reply(self,{"ok":True,"code":c})
            if p.path=="/api/profile":
                u=auth(self)
                if not u:return
                n=str(d.get("name",u["name"])).strip()[:MAX_NAME_LEN];city=str(d.get("city","")).strip()[:80];bio=str(d.get("bio","")).strip()[:500]
                if len(n)<2:return reply(self,{"ok":False,"error":"Имя слишком короткое."},400)
                db.execute("UPDATE users SET name=?,city=?,bio=? WHERE user_id=?",(n,city,bio,u["user_id"]));return reply(self,{"ok":True})
            if p.path=="/api/requests":
                u=auth(self)
                if not u:return
                if get_active_own_request(u["user_id"]):return reply(self,{"ok":False,"error":"У вас уже есть активная заявка."},409)
                if u["balance"]<REQUEST_COST:return reply(self,{"ok":False,"error":f"Нужно {REQUEST_COST} HP."},400)
                f={k:str(d.get(k,"" )).strip() for k in ("what","place","time_needed","urgency","details")}
                if not all(f.values()):return reply(self,{"ok":False,"error":"Заполните все поля."},400)
                try:lat=float(d["lat"]) if d.get("lat") is not None else None;lon=float(d["lon"]) if d.get("lon") is not None else None
                except:lat=lon=None
                f["category"]=str(d.get("category","other"))
                rid=create_request(u["user_id"],{**f,"lat":lat,"lon":lon})
                req=get_request(rid)
                helper_id=find_best_queued_helper(req)
                matched=False
                if helper_id is not None:
                    matched=try_assign_helper(rid,helper_id)
                    if matched:
                        chat_for_request(rid)
                return reply(self,{"ok":True,"request_id":rid,"matched":matched})
            if p.path=="/api/helper/queue":
                u=auth(self)
                if not u:return
                add_to_queue(u["user_id"]);return reply(self,{"ok":True,"message":"Вы добавлены в очередь помощников."})
            if p.path=="/api/smart-match/assign":
                u=auth(self)
                if not u:return
                rid=int(d["request_id"]);hid=int(d["helper_id"]);r=get_request(rid)
                if not r or r["requester_id"]!=u["user_id"]:return reply(self,{"ok":False,"error":"Недоступно."},403)
                if not try_assign_helper(rid,hid):return reply(self,{"ok":False,"error":"Кандидат уже занят или заявка изменилась."},409)
                chat_for_request(rid);return reply(self,{"ok":True})
            if p.path=="/api/requests/finish":
                u=auth(self)
                if not u:return
                rid=int(d["request_id"])
                if not complete_request(rid,u["user_id"]):return reply(self,{"ok":False,"error":"Завершить может только назначенный помощник."},409)
                return reply(self,{"ok":True})
            if p.path=="/api/reviews":
                u=auth(self)
                if not u:return
                rid=int(d["request_id"]);rating=int(d["rating"]);side=str(d["side"])
                ok=set_rating(rid,u["user_id"],rating) if side=="requester" else set_helper_rating(rid,u["user_id"],rating) if side=="helper" else False
                if not ok:return reply(self,{"ok":False,"error":"Оценка уже поставлена или недоступна."},409)
                review=str(d.get("review","")).strip()[:MAX_TEXT_LEN]
                if review:set_review(rid,u["user_id"],review,side)
                return reply(self,{"ok":True})
            if p.path=="/api/chats/send":
                u=auth(self)
                if not u:return
                rid=int(d["request_id"]);text=str(d.get("text","")).strip()[:1000]
                if not text:return reply(self,{"ok":False,"error":"Сообщение пустое."},400)
                cid=chat_for_request(rid)
                if not cid:return reply(self,{"ok":False,"error":"Чат доступен после назначения помощника."},409)
                c=db.execute("SELECT * FROM chats WHERE id=? AND (user_a_id=? OR user_b_id=?)",(cid,u["user_id"],u["user_id"])).fetchone()
                if not c:return reply(self,{"ok":False,"error":"Нет доступа к чату."},403)
                db.execute("INSERT INTO chat_messages(chat_id,user_id,text) VALUES(?,?,?)",(cid,u["user_id"],text))
                msgs=db.execute("SELECT m.*,u.name author_name FROM chat_messages m JOIN users u ON u.user_id=m.user_id WHERE m.chat_id=? ORDER BY m.id",(cid,)).fetchall()
                return reply(self,{"ok":True,"messages":[{**dict(m),"mine":m["user_id"]==u["user_id"]} for m in msgs]})
            if p.path=="/api/payments/create":
                u=auth(self)
                if not u:return
                item=str(d.get("item_type",""));meta=d.get("metadata") or {}
                if item in ("boost","more_responses"):
                    try:meta["request_id"]=int(d.get("request_id") or meta.get("request_id") or 0)
                    except:meta["request_id"]=0
                    if not meta["request_id"]:return reply(self,{"ok":False,"error":"Для этой функции нужна заявка."},400)
                if item=="ad" and d.get("ad_text"):meta["ad_text"]=str(d["ad_text"])[:MAX_TEXT_LEN]
                try:i,_,_=create_pending_invoice(u["user_id"],item,meta);url,pid=create_payment(i)
                except Exception as x:return reply(self,{"ok":False,"error":str(x)},503)
                return reply(self,{"ok":True,"invoice_id":i,"confirmation_url":url,"payment_id":pid})
            if p.path=="/api/payments/webhook":
                obj=d.get("object") or {};m=obj.get("metadata") or {};iid=m.get("hpoint_invoice_id")
                if d.get("event")=="payment.succeeded" and iid:
                    try:ok,r=fulfill_invoice(int(iid),obj.get("id"));return reply(self,{"ok":ok,"result":r})
                    except Exception as x:return reply(self,{"ok":False,"error":str(x)},500)
                return reply(self,{"ok":True,"ignored":True})
            self.send_error(404)
        except Exception as e:
            print("[WEB][ERROR]",repr(e));reply(self,{"ok":False,"error":"Внутренняя ошибка сервера"},500)

def run():
    database.init_db();s=ThreadingHTTPServer((WEB_HOST,WEB_PORT),Handler);print(f"H-Point website: http://{WEB_HOST}:{WEB_PORT}")
    try:s.serve_forever()
    finally:s.server_close()
if __name__=="__main__":run()
