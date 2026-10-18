"""H-Point web-first application: dashboard, requests, Smart Match, chat, profile and RUB billing."""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from email.message import EmailMessage
import asyncio, json, logging, os, secrets, hashlib, hmac, datetime as dt, re, smtplib, ssl
from pathlib import Path
from html import escape
from . import database
from .database import db, get_user, get_user_by_email, create_web_user, get_request, get_user_stats, get_active_own_request, get_history, get_billing_history, is_user_blocked, admin_summary, set_user_blocked
from .config import *
from .services import *
from .billing import create_pending_invoice, create_payment, fulfill_invoice, purchase_with_points, verify_robokassa_result

database.init_db()
YANDEX_MAPS_API_KEY = os.getenv("YANDEX_MAPS_API_KEY", "")
_telegram_bot = None
_telegram_loop = None
_telegram_username = BOT_USERNAME or None
ASSETS = {
    "favicon.svg": (Path(__file__).resolve().parent.parent / "assets" / "favicon.svg", "image/svg+xml"),
    "hpoint-logo.png": (Path(__file__).resolve().parent.parent / "assets" / "hpoint-logo.png", "image/png"),
    "hpoint-logo-dark.png": (Path(__file__).resolve().parent.parent / "assets" / "hpoint-logo-dark.png", "image/png"),
    "hpoint-brand-hero.png": (Path(__file__).resolve().parent.parent / "assets" / "hpoint-brand-hero.png", "image/png"),
    "hpoint-neighbors-hero.png": (Path(__file__).resolve().parent.parent / "assets" / "hpoint-neighbors-hero.png", "image/png"),
    "hpoint-route-network.png": (Path(__file__).resolve().parent.parent / "assets" / "hpoint-route-network.png", "image/png"),
    "hpoint-match-field.png": (Path(__file__).resolve().parent.parent / "assets" / "hpoint-match-field.png", "image/png"),
}
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' "
       "https://api-maps.yandex.ru https://*.api-maps.yandex.ru "
       "https://suggest-maps.yandex.ru https://yastatic.net https://yandex.ru; "
       "style-src 'self' 'unsafe-inline' blob: https://api-maps.yandex.ru "
       "https://*.api-maps.yandex.ru https://yastatic.net https://fonts.googleapis.com; "
       "font-src 'self' data: https://fonts.gstatic.com; "
       "img-src 'self' data: https://api-maps.yandex.ru https://*.api-maps.yandex.ru "
       "https://*.maps.yandex.net https://yastatic.net https://yandex.ru; "
       "connect-src 'self' https://api-maps.yandex.ru https://*.api-maps.yandex.ru "
       "https://*.maps.yandex.net https://suggest-maps.yandex.ru "
       "https://search-maps.yandex.ru https://api.routing.yandex.net https://yandex.ru; "
       "worker-src data: blob: https://api-maps.yandex.ru https://*.api-maps.yandex.ru "
       "https://yastatic.net; child-src https://api-maps.yandex.ru; "
       "frame-src https://api-maps.yandex.ru; frame-ancestors 'none'; "
       "base-uri 'self'; form-action 'self'")

def configure_telegram_notifications(bot, username=None):
    """Enable best-effort Telegram notifications for requests created on the web."""
    global _telegram_bot, _telegram_loop, _telegram_username
    _telegram_bot = bot
    _telegram_loop = asyncio.get_running_loop()
    _telegram_username = username

def notify_telegram_user(user_id, text, reply_markup=None):
    if _telegram_bot is None or _telegram_loop is None:
        return
    try:
        future = asyncio.run_coroutine_threadsafe(
            _telegram_bot.send_message(user_id, text, reply_markup=reply_markup), _telegram_loop
        )
    except RuntimeError:
        logging.warning("Telegram notification could not be scheduled")
        return

    def report_failure(result):
        try:
            result.result()
        except Exception:
            logging.warning("Telegram notification failed")

    future.add_done_callback(report_failure)

def now(): return dt.datetime.now(dt.timezone.utc)
def ph(password, salt=None):
    """Use a memory-hard password hash for new credentials."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt}${digest.hex()}"
def pv(password, stored):
    try:
        parts = stored.split("$")
        if parts[0] == "scrypt" and len(parts) == 6:
            _, n, r, p, salt, digest = parts
            actual = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=int(n), r=int(r), p=int(p), dklen=32).hex()
            return hmac.compare_digest(actual, digest)
        # Existing accounts keep working and are transparently upgraded at login.
        salt, digest = stored.split("$", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 180000).hex()
        return hmac.compare_digest(actual, digest)
    except Exception: return False
def password_needs_upgrade(stored): return not stored.startswith("scrypt$")

def password_error(password):
    if not 6 <= len(password) <= 256:
        return "Пароль должен быть от 6 до 256 символов."
    if not re.search(r"[a-z]", password) or not re.search(r"[A-Z]", password) or not re.search(r"\d", password):
        return "В пароле нужны строчная и заглавная латинские буквы, а также цифра."
    return None

def email_delivery_configured():
    return bool(SMTP_HOST and SMTP_FROM)

def send_email_verification_code(address, code):
    """Send a short code through the configured transactional SMTP mailbox."""
    if not email_delivery_configured():
        return False
    message = EmailMessage()
    message["Subject"] = "Код подтверждения H-Point"
    message["From"] = SMTP_FROM
    message["To"] = address
    message.set_content(
        "Ваш код подтверждения H-Point: " + code + "\n\n"
        f"Код действует {max(1, EMAIL_VERIFICATION_TTL_SECONDS // 60)} минут. "
        "Никому его не сообщайте."
    )
    try:
        context = ssl.create_default_context()
        if SMTP_USE_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS, context=context) as client:
                if SMTP_USERNAME:
                    client.login(SMTP_USERNAME, SMTP_PASSWORD)
                client.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS) as client:
                client.ehlo()
                if SMTP_USE_TLS:
                    client.starttls(context=context)
                    client.ehlo()
                if SMTP_USERNAME:
                    client.login(SMTP_USERNAME, SMTP_PASSWORD)
                client.send_message(message)
        return True
    except Exception:
        logging.exception("Email verification delivery failed")
        return False

def cookie_value(h, name):
    c=h.headers.get("Cookie","")
    return next((x.strip().split("=",1)[1] for x in c.split(";") if x.strip().startswith(name+"=")),None)

def get_sess(h):
    t=cookie_value(h,"hpoint_session")
    if not t: return None
    r=db.execute("SELECT * FROM sessions WHERE token=? AND expires_at>?",(t,now().isoformat())).fetchone()
    return get_user(r["user_id"]) if r else None

def new_sess(uid, device_id=None):
    t=secrets.token_urlsafe(32)
    e=(now()+dt.timedelta(seconds=SESSION_TTL)).isoformat()
    db.execute("DELETE FROM sessions WHERE expires_at<=?", (now().isoformat(),))
    db.execute("INSERT INTO sessions(token,user_id,expires_at,device_id) VALUES(?,?,?,?)",(t,uid,e,device_id))
    return t

def session_cookie(value, max_age):
    secure = "; Secure" if SESSION_COOKIE_SECURE else ""
    return f"hpoint_session={value}; HttpOnly; SameSite=Lax; Path=/; Max-Age={max_age}{secure}"

def device_cookie(value):
    secure = "; Secure" if SESSION_COOKIE_SECURE else ""
    return f"hpoint_device={value}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_TTL}{secure}"

def session_headers(h, uid):
    device = cookie_value(h, "hpoint_device") or secrets.token_urlsafe(24)
    return {"Set-Cookie": [session_cookie(new_sess(uid, device), SESSION_TTL), device_cookie(device)]}

MAX_JSON_BODY = 20_000

def read(h):
    try: length = int(h.headers.get("Content-Length", "0"))
    except ValueError: raise ValueError("Некорректный размер запроса")
    if length < 0 or length > MAX_JSON_BODY: raise ValueError("Слишком большой запрос")
    return json.loads(h.rfile.read(length) or b"{}")

def reply(h,d,status=200,headers=None):
    b=json.dumps(d,ensure_ascii=False).encode()
    h.send_response(status); h.send_header("Content-Type","application/json;charset=utf-8"); h.send_header("Cache-Control","no-store"); h.send_header("X-Content-Type-Options","nosniff"); h.send_header("Referrer-Policy","same-origin"); h.send_header("Content-Length",str(len(b)))
    for k,v in (headers or {}).items():
        for value in (v if k.lower()=="set-cookie" and isinstance(v,(list,tuple)) else (v,)):
            h.send_header(k,value)
    h.end_headers(); h.wfile.write(b)

def auth(h):
    u=get_sess(h)
    if not u:
        reply(h,{"ok":False,"error":"auth_required"},401); return None
    if u["is_blocked"]:
        reply(h,{"ok":False,"error":"account_blocked"},403); return None
    return u

def account_is_verified(u):
    return bool(u["tg_user_id"] or u["email_verified"])

def verified_community_account(h, u):
    if account_is_verified(u):
        return True
    reply(h, {"ok": False, "error": "Подтвердите email кодом из письма или привяжите Telegram, прежде чем пользоваться заявками."}, 403)
    return False

def admin_auth(h):
    u = auth(h)
    if u and u["role"] != "admin":
        reply(h,{"ok":False,"error":"forbidden"},403); return None
    return u

def valid_origin(h):
    origin = h.headers.get("Origin")
    if not origin:
        # Browser fetch/XHR sends Origin for unsafe requests.  Requiring it in
        # production prevents a request with an ambient session cookie from
        # being accepted when a proxy or browser misbehaves around SameSite.
        # Keep direct, local development clients convenient.
        return APP_ENV not in {"production", "prod"}
    public = urlparse(WEB_PUBLIC_URL)
    expected = f"{public.scheme}://{public.netloc}"
    return hmac.compare_digest(origin.rstrip("/"), expected.rstrip("/"))

def client_key(h):
    if TRUST_PROXY_HEADERS:
        forwarded=h.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if forwarded:return forwarded
    return h.client_address[0]

def user_payload(u):
    stats=get_user_stats(u["user_id"])
    code_valid=bool(u["verification_code"] and u["verification_code_expires_at"] and u["verification_code_expires_at"]>now().isoformat())
    identity=database.get_identity_verification(u["user_id"])
    identity_payload={"status":identity["status"],"submitted_at":identity["submitted_at"],"reviewed_at":identity["reviewed_at"],"note":identity["note"]} if identity else {"status":"not_requested"}
    return {"id":u["user_id"],"name":u["name"],"email":u["email"],"balance":u["balance"],"city":u["city"] or "","bio":u["bio"] or "","lat":u["lat"],"lon":u["lon"],"verified":bool(u["web_verified"]) or is_verified(u["user_id"]),"email_verified":bool(u["email_verified"]),"account_verified":account_is_verified(u),"email_delivery_configured":email_delivery_configured(),"identity_verified":identity_payload["status"]=="approved","identity_verification":identity_payload,"tg_linked":bool(u["tg_user_id"]),"telegram_url":f"https://t.me/{_telegram_username}?start=profile" if u["tg_user_id"] and _telegram_username else None,"link_code":u["verification_code"] if code_valid else None,"pro_until":u["pro_until"],"verified_until":u["verified_until"],"business_until":u["business_until"],"stats":stats}

def request_payload(r):
    d=dict(r); d["category_name"]=CATEGORIES.get(r["category"],"Другое"); d["status_title"]=STATUS_TITLES.get(r["status"],r["status"]); return d

def public_request_payload(r):
    """Discovery and map records never disclose address details or exact coordinates."""
    return {"id": r["id"], "what": r["what"], "category": r["category"],
            "category_name": CATEGORIES.get(r["category"], "Другое"), "urgency": r["urgency"],
            # The free-text place field can contain a home address.  It is
            # shared only with the assigned helper through the private flow.
            "place": "Район уточняется после назначения", "lat": None, "lon": None}

def chat_for_request(rid):
    return database.get_or_create_chat_for_request(rid)

PAGE=r'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>H·Point — помощь рядом</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&display=swap" rel="stylesheet"><script src="https://api-maps.yandex.ru/2.1/?apikey=__YANDEX_MAPS_API_KEY__&lang=ru_RU&csp=true" type="text/javascript"></script>
<style>
:root{--bg:#f5f7fb;--surface:#fff;--ink:#101828;--muted:#667085;--line:#e6eaf0;--brand:#5b5cf0;--brand2:#7c3aed;--ok:#12b76a;--warn:#f79009;--shadow:0 16px 50px rgba(16,24,40,.08)}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(circle at 80% -10%,#e9e8ff 0,transparent 35%),var(--bg);color:var(--ink);font-family:Manrope,system-ui,-apple-system,sans-serif}.nav{position:sticky;top:0;z-index:40;background:rgba(245,247,251,.86);backdrop-filter:blur(18px);border-bottom:1px solid rgba(230,234,240,.8)}.in,.wrap{width:min(1240px,100%);margin:auto;padding:0 24px}.in{height:74px;display:flex;align-items:center;gap:12px}.logo{font-size:25px;font-weight:800;letter-spacing:-1px}.logo b{color:var(--brand)}.sp{flex:1}.btn{border:0;border-radius:14px;padding:12px 17px;font:inherit;font-weight:800;cursor:pointer;transition:.2s;display:inline-flex;align-items:center;justify-content:center;gap:7px}.btn:hover{transform:translateY(-1px)}.dark{background:var(--ink);color:white}.light{background:var(--surface);color:var(--ink);border:1px solid var(--line)}.grad{background:linear-gradient(135deg,var(--brand),var(--brand2));color:#fff}.danger{color:#b42318;background:#fff;border:1px solid #fecdca}.ey{display:inline-flex;padding:7px 10px;border-radius:999px;background:#eeefff;color:#4c4fd0;font-size:11px;font-weight:800}.landingHero{padding:76px 0 55px;display:grid;grid-template-columns:1.1fr .9fr;gap:44px;align-items:center}.hero h1{font-size:clamp(46px,6vw,82px);line-height:.95;letter-spacing:-5px;margin:18px 0}.hero p{font-size:18px;line-height:1.7;color:var(--muted);max-width:650px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:25px}.cover{min-height:430px;border-radius:34px;background:linear-gradient(145deg,#111326,#2f3270);box-shadow:0 30px 80px rgba(31,35,90,.28);padding:22px;color:white;position:relative;overflow:hidden}.cover:before{content:"";position:absolute;width:270px;height:270px;border-radius:50%;background:#7778ff55;filter:blur(8px);right:-70px;top:-70px}.coverCard{position:relative;background:#ffffff12;border:1px solid #ffffff1f;border-radius:22px;padding:19px;margin-bottom:12px;backdrop-filter:blur(8px)}.coverCard strong{display:block;font-size:18px}.coverCard small{display:block;color:#cfd2e7;margin-top:7px;line-height:1.5}.coverMap{position:absolute;left:22px;right:22px;bottom:22px;height:110px;border-radius:18px;background:linear-gradient(135deg,#34386e,#171a35);border:1px solid #ffffff1f;display:flex;align-items:center;justify-content:center;color:#cfd2e7}.section{padding:54px 0}.section h2{font-size:34px;letter-spacing:-1.5px}.featureGrid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.card{background:rgba(255,255,255,.88);border:1px solid var(--line);border-radius:22px;padding:21px;box-shadow:0 8px 30px rgba(16,24,40,.04)}.muted{color:var(--muted)}.price{font-size:28px;font-weight:800}.app{display:none}.appHead{padding:35px 0 0}.welcome{display:flex;align-items:flex-end;gap:15px;justify-content:space-between}.welcome h1{font-size:42px;letter-spacing:-2px;margin:9px 0}.tabs{display:flex;gap:7px;overflow:auto;padding:22px 0 10px;position:sticky;top:74px;z-index:15;background:linear-gradient(var(--bg) 80%,transparent)}.tab{padding:10px 14px;border-radius:12px;border:1px solid transparent;background:transparent;white-space:nowrap;font:inherit;font-weight:700;color:var(--muted);cursor:pointer}.tab.active{background:white;border-color:var(--line);color:var(--ink);box-shadow:0 5px 20px #1018280b}.panel{display:none;padding:18px 0 60px}.panel.active{display:block}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.stat{padding:20px}.stat .big{font-size:28px;font-weight:800;margin-top:5px}.layout{display:grid;grid-template-columns:1.25fr .75fr;gap:16px}.form{display:grid;gap:11px}.input{width:100%;padding:13px 14px;border:1px solid var(--line);border-radius:13px;background:#fff;font:inherit;outline:none}.input:focus{border-color:#8d8ff7;box-shadow:0 0 0 4px #5b5cf012}.textarea{min-height:110px;resize:vertical}.request{display:flex;gap:14px;align-items:center;padding:16px;border:1px solid var(--line);border-radius:17px;background:#fff;margin:9px 0}.requestmain{flex:1;min-width:0}.badge{padding:6px 9px;border-radius:999px;background:#f2f4f7;font-size:11px;font-weight:800;white-space:nowrap}.badge.ok{background:#ecfdf3;color:#027a48}.badge.warn{background:#fffaeb;color:#b54708}.map{height:460px;border-radius:22px;overflow:hidden;border:1px solid var(--line);background:#eef0f5}.match{padding:16px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px}.avatar{width:42px;height:42px;border-radius:14px;background:linear-gradient(135deg,#ececff,#ddd8ff);display:flex;align-items:center;justify-content:center;font-weight:800}.grow{flex:1;min-width:0}.modal{position:fixed;inset:0;background:#10182899;display:none;align-items:center;justify-content:center;z-index:100;padding:20px}.box{background:#fff;border-radius:26px;padding:26px;width:min(600px,100%);max-height:90vh;overflow:auto;box-shadow:0 30px 100px #10182833}.close{float:right;border:0;background:none;font-size:25px;cursor:pointer}.chat{height:480px;display:flex;flex-direction:column}.messages{flex:1;overflow:auto;padding:12px;background:#f7f8fb;border-radius:17px}.msg{max-width:78%;padding:10px 13px;border-radius:16px;background:#fff;margin:7px 0;border:1px solid var(--line)}.msg.mine{margin-left:auto;background:#eef0ff;border-color:#d9dbff}.msg small{display:block;color:var(--muted);font-size:10px;margin-top:4px}.chatbar{display:flex;gap:8px;margin-top:10px}.empty{padding:32px;text-align:center;color:var(--muted)}.toast{position:fixed;right:20px;bottom:20px;z-index:200;background:#101828;color:#fff;border-radius:14px;padding:13px 16px;box-shadow:var(--shadow);display:none}.verify{background:linear-gradient(135deg,#f0f0ff,#fff);border:1px solid #dfe1ff}.profileGrid{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:900px){.landingHero,.layout,.profileGrid{grid-template-columns:1fr}.featureGrid{grid-template-columns:1fr 1fr}.stats{grid-template-columns:1fr 1fr}}@media(max-width:600px){.in,.wrap{padding:0 15px}.featureGrid,.stats{grid-template-columns:1fr}.hero h1{letter-spacing:-3px}.welcome h1{font-size:32px}.cover{min-height:390px}.request{align-items:flex-start;flex-wrap:wrap}}
#p-billing .layout{grid-template-columns:minmax(0,1.7fr) minmax(280px,.8fr);align-items:start}#appprices{grid-template-columns:repeat(2,minmax(0,1fr))}#appprices>.card{min-width:0;display:flex;flex-direction:column;align-items:flex-start}#appprices>.card h3{min-height:2.8em;margin-bottom:8px}#appprices>.card .muted{min-height:3em}#appprices>.card .price{margin-top:auto;padding:12px 0 16px;white-space:nowrap}#appprices>.card .btn{width:100%}@media(max-width:900px){#p-billing .layout{grid-template-columns:minmax(0,1fr)}#appprices{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:520px){#appprices{grid-template-columns:minmax(0,1fr)}}

/* H·Point visual refresh */
:root{--bg:#f7f8fb;--surface:#fff;--ink:#191b24;--muted:#737887;--line:#e8eaf0;--brand:#5946e8;--brand2:#795cf6;--ok:#15966b;--warn:#b97817;--shadow:0 20px 55px rgba(25,27,36,.08)}
body{background:radial-gradient(ellipse at 77% 4%,rgba(218,214,255,.56),transparent 29%),radial-gradient(ellipse at 0 44%,rgba(231,239,255,.55),transparent 27%),var(--bg);color:var(--ink);font-family:Manrope,Inter,system-ui,-apple-system,sans-serif;letter-spacing:-.01em}
.nav{background:rgba(255,255,255,.88);border-bottom:1px solid rgba(232,234,240,.9);backdrop-filter:blur(20px)}
.in,.wrap{width:min(1280px,100%);padding-left:30px;padding-right:30px}.in{height:78px}.logo{font-size:26px;letter-spacing:-1.5px}.logo b{color:var(--brand)}
.btn{border-radius:13px;padding:13px 19px;font-size:14px;letter-spacing:-.01em;box-shadow:none}.btn:hover{transform:translateY(-2px)}.btn:focus-visible,.tab:focus-visible,.input:focus-visible{outline:3px solid rgba(89,70,232,.28);outline-offset:2px}.dark{background:#20212a;color:white}.dark:hover{background:#30313d}.light{background:#fff;color:#252630;border-color:#e4e6ee}.light:hover{background:#f9f9fc;border-color:#d5d7e2}.grad{background:linear-gradient(120deg,#5946e8,#7659f0);box-shadow:0 8px 20px rgba(89,70,232,.18)}.grad:hover{box-shadow:0 10px 24px rgba(89,70,232,.27)}
.ey{gap:8px;padding:8px 12px;background:#eeecff;color:#5845d6;font-size:10px;letter-spacing:.1em}.eyDot,.coverDemo i{display:inline-block;width:7px;height:7px;border-radius:50%;background:#6856ed;box-shadow:0 0 0 4px rgba(104,86,237,.12)}
.landingHero{padding:91px 0 88px;grid-template-columns:minmax(0,1.05fr) minmax(400px,.95fr);gap:76px;align-items:center}.hero h1{font-size:clamp(52px,6vw,78px);line-height:1.01;letter-spacing:-5.5px;margin:25px 0 18px;font-weight:800}.hero p{max-width:570px;font-size:17px;line-height:1.75;color:#686d7c}.actions{gap:12px;margin-top:29px}.heroMeta{display:flex;gap:23px;flex-wrap:wrap;margin-top:32px;color:#777b89;font-size:12px;font-weight:600}.heroMeta span{display:flex;align-items:center;gap:8px}.heroMeta b{color:#5746d8;font-size:10px;letter-spacing:.08em}
.cover{min-height:486px;padding:25px;border-radius:30px;background:radial-gradient(ellipse at 80% 15%,rgba(114,98,242,.42),transparent 37%),linear-gradient(145deg,#20202b,#2c2a3d 60%,#252434);box-shadow:0 28px 70px rgba(41,36,87,.2);isolation:isolate}.cover:before{width:310px;height:310px;right:-120px;top:-120px;background:#9181ff38;filter:blur(15px)}.cover:after{content:"";position:absolute;z-index:-1;width:280px;height:280px;left:-150px;bottom:-175px;border-radius:50%;background:#4cbbcf22;filter:blur(10px)}
.coverTop{position:relative;display:flex;justify-content:space-between;align-items:center}.coverBrand{font-weight:800;letter-spacing:-1px;font-size:17px}.coverBrand span{color:#a69bff}.coverDemo{display:flex;align-items:center;gap:8px;color:#cbc9dc;font-size:9px;font-weight:800;letter-spacing:.12em}.coverDemo i{background:#b9f37b;box-shadow:0 0 0 4px rgba(185,243,123,.13)}.coverMapLabel{position:relative;margin-top:31px;color:#c6c4d5;font-size:9px;font-weight:800;letter-spacing:.14em}.coverMapArt{position:relative;height:245px;margin:13px -2px 0;border:1px solid rgba(255,255,255,.1);border-radius:20px;overflow:hidden;background:radial-gradient(ellipse at 52% 50%,rgba(131,119,223,.16),transparent 57%),linear-gradient(135deg,#343345,#2c2b3b)}.coverMapArt:before{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.04) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.04) 1px,transparent 1px);background-size:42px 42px;opacity:.45}.mapStreet{position:absolute;height:11px;border:1px solid rgba(212,210,230,.13);border-left:0;border-right:0;background:#ffffff08;border-radius:30px}.streetA{width:120%;left:-5%;top:38%;transform:rotate(-17deg)}.streetB{width:115%;left:-4%;top:70%;transform:rotate(18deg)}.streetC{width:90%;left:20%;top:48%;transform:rotate(66deg)}.streetD{width:75%;left:-15%;top:54%;transform:rotate(72deg)}.coverMapArt svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}.coverMapArt path{fill:none;stroke:#b8abff;stroke-width:3;stroke-dasharray:7 8;stroke-linecap:round;opacity:.8}.coverMapArt circle{fill:#c5f07e;stroke:#fff;stroke-width:3;filter:drop-shadow(0 0 7px #b8ec85)}.mapTag{position:absolute;padding:6px 9px;border:1px solid #ffffff22;border-radius:8px;background:#29283b;color:#f7f6ff;font-size:9px;font-weight:700;box-shadow:0 5px 18px #10101855}.tagA{left:5%;bottom:8%}.tagB{right:6%;top:10%}
.coverTask{position:relative;display:flex;align-items:center;gap:13px;margin-top:-20px;padding:15px;border:1px solid #ffffff20;border-radius:17px;background:rgba(38,37,53,.95);box-shadow:0 15px 30px #14131f55;backdrop-filter:blur(14px)}.taskIcon{width:43px;height:43px;display:grid;place-items:center;border-radius:13px;background:#eeeaff;color:#5b46e8;font-size:25px;font-weight:700}.taskCopy{display:flex;flex:1;min-width:0;flex-direction:column;gap:3px}.taskCopy small{color:#b3a9ff;font-size:8px;letter-spacing:.12em;font-weight:800}.taskCopy strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:white;font-size:12px}.taskCopy span{color:#b6b4c4;font-size:10px}.taskArrow{color:#c4f18e;font-size:19px}.coverBottom{display:flex;align-items:center;gap:11px;margin-top:17px;color:#c6c4d4;font-size:10px}.avatarStack{display:flex;padding-left:2px}.avatarStack i{width:22px;height:22px;margin-left:-3px;display:grid;place-items:center;border:2px solid #2b2939;border-radius:50%;background:#ded9ff;color:#433d6f;font-size:8px;font-style:normal;font-weight:800}.avatarStack i:nth-child(2){background:#c8f1de}.avatarStack i:nth-child(3){background:#ffd9bd}
.section{padding:51px 0}.sectionIntro{margin-bottom:22px}.sectionIntro .ey{margin-bottom:10px}.section h2{font-size:clamp(27px,3vw,36px);line-height:1.15;letter-spacing:-1.7px;margin:8px 0 22px}.steps{grid-template-columns:repeat(3,minmax(0,1fr));gap:15px}.stepCard{position:relative;min-height:190px;padding:24px 23px;background:rgba(255,255,255,.85);border:1px solid #e9e9f0;border-radius:20px;box-shadow:0 7px 22px rgba(28,29,43,.035);transition:transform .2s,box-shadow .2s,border-color .2s}.stepCard:hover{transform:translateY(-4px);border-color:#d9d3ff;box-shadow:0 17px 35px rgba(49,42,103,.08)}.stepNo{display:inline-grid;width:34px;height:34px;place-items:center;border-radius:11px;background:#f0eeff;color:#5a48d9;font-size:11px;font-weight:800;letter-spacing:.04em}.stepCard h3{margin:20px 0 8px;font-size:16px;letter-spacing:-.4px}.stepCard p{max-width:330px;margin:0;font-size:13px;line-height:1.7}.section+.section{padding-top:47px}.featureGrid:not(.steps){gap:14px}
.card{background:rgba(255,255,255,.93);border:1px solid #e9eaf0;border-radius:19px;box-shadow:0 8px 26px rgba(25,27,36,.035)}.muted{color:var(--muted)}.price{letter-spacing:-1px}.appHead{padding-top:42px}.welcome{align-items:center}.welcome h1{font-size:36px;letter-spacing:-1.8px}.tabs{top:78px;gap:5px;margin-top:17px;padding:8px;background:rgba(255,255,255,.7);border:1px solid #ececf2;border-radius:16px;backdrop-filter:blur(14px)}.tab{padding:10px 13px;border-radius:11px;font-size:12px}.tab.active{background:#292a35;border-color:#292a35;color:#fff;box-shadow:0 5px 15px #20212a22}.panel{padding-top:26px}.panel>h2,.panel .layout h2{font-size:27px;letter-spacing:-1.1px}.stats{gap:13px}.stat{min-height:112px;padding:19px 20px}.stat .muted{font-size:12px;font-weight:600}.stat .big{font-size:27px;letter-spacing:-1px}.layout{gap:17px}.request{border:1px solid #e9eaf0;border-radius:15px;padding:15px;background:#fff;transition:border-color .18s,box-shadow .18s,transform .18s}.request:hover{transform:translateY(-1px);border-color:#d8d2ff;box-shadow:0 8px 22px rgba(31,28,74,.06)}.requestmain b{font-size:14px}.requestmain .muted{font-size:12px;line-height:1.55;margin-top:4px}.badge{padding:6px 9px;border-radius:8px;font-size:10px;letter-spacing:.02em}.input{border-color:#e4e6ed;border-radius:12px;padding:13px 14px;font-size:14px;transition:border-color .18s,box-shadow .18s}.input:focus{border-color:#8e80f0;box-shadow:0 0 0 4px rgba(89,70,232,.1)}.map{border-radius:20px;border-color:#e7e8ee;box-shadow:0 8px 24px rgba(25,27,36,.04)}.match{padding:16px;border-color:#eeedf3}.avatar{border-radius:13px;background:linear-gradient(135deg,#e9e5ff,#dcecff);color:#5344ba}.modal{background:rgba(24,24,33,.55);backdrop-filter:blur(8px)}.box{border:1px solid #ffffffb8;border-radius:24px;padding:30px;box-shadow:0 28px 90px rgba(15,16,28,.25)}.toast{border:1px solid #ffffff22;border-radius:13px}.verify{background:linear-gradient(135deg,#f1efff,#fff);border-color:#e3defe}.empty{font-size:13px;line-height:1.6}
@media(max-width:900px){.landingHero{grid-template-columns:1fr;gap:38px;padding-top:70px}.cover{width:min(100%,620px);margin:auto}.steps{grid-template-columns:repeat(3,minmax(0,1fr))}.appHead{padding-top:30px}}
@media(max-width:650px){.in,.wrap{padding-left:18px;padding-right:18px}.in{height:68px}.logo{font-size:23px}.landingHero{padding:55px 0 55px;gap:29px}.hero h1{font-size:clamp(44px,12vw,62px);letter-spacing:-3.6px;margin-top:20px}.hero p{font-size:15px;line-height:1.65}.heroMeta{gap:13px;margin-top:22px;font-size:10px}.cover{min-height:420px;padding:19px;border-radius:24px}.coverMapArt{height:205px}.coverTask{margin-top:-16px;padding:12px}.section{padding:38px 0}.section h2{font-size:27px}.steps{grid-template-columns:1fr;gap:10px}.stepCard{min-height:0;padding:19px}.stepCard h3{margin-top:14px}.welcome{align-items:flex-start}.welcome h1{font-size:27px;letter-spacing:-1.2px}.appHead{padding-top:24px}.tabs{top:68px;margin-left:-2px;margin-right:-2px;overflow-x:auto;scrollbar-width:none}.tabs::-webkit-scrollbar{display:none}.tab{font-size:11px;padding:9px 11px}.panel{padding-top:19px}.stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.stat{min-height:96px;padding:15px}.stat .big{font-size:23px}.layout,.profileGrid{grid-template-columns:1fr;gap:12px}.request{gap:10px;padding:13px}.requestmain{flex-basis:calc(100% - 54px)}.request>.btn{width:100%}.map{height:390px}.box{padding:23px 19px;border-radius:20px}}
@media(max-width:380px){.in,.wrap{padding-left:14px;padding-right:14px}.hero h1{font-size:42px}.actions .btn{padding:12px 13px}.cover{padding:15px}.coverMapArt{height:185px}.coverBottom{font-size:9px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition:none!important;animation:none!important}}
</style></head><body>
<header class="nav"><div class="in"><div class="logo">H·Point<b>.</b></div><div class="sp"></div><div id="nav"></div></div></header>
<main id="landing" class="wrap"><section class="landingHero"><div class="hero"><span class="ey"><span class="eyDot"></span> ПОМОЩЬ РЯДОМ</span><h1>Хорошие дела<br>начинаются рядом.</h1><p>Найдите человека для повседневной задачи или помогите соседу. Заявки, подбор и общение — на сайте и в Telegram.</p><p class="audiencePortrait">H·Point создан для Ильи: он недавно переехал в новый район, работает до вечера и хочет быстро найти надёжного человека рядом, чтобы настроить роутер, донести коробки или решить другую небольшую, но срочную задачу.</p><div class="actions"><button class="btn dark" onclick="authForm(true)">Начать бесплатно <span aria-hidden="true">→</span></button><button class="btn light" onclick="authForm(false)">Войти</button></div><div class="heroMeta"><span><b>01</b> Одна учётная запись</span><span><b>02</b> Сайт и Telegram вместе</span></div></div><div class="cover" aria-label="Пример интерфейса H-Point"><div class="coverTop"><span class="coverBrand">H·Point<span>.</span></span><span class="coverDemo"><i></i> ПРИМЕР</span></div><div class="coverMapLabel">ПОМОЩЬ РЯДОМ</div><div class="coverMapArt" aria-hidden="true"><div class="mapStreet streetA"></div><div class="mapStreet streetB"></div><div class="mapStreet streetC"></div><div class="mapStreet streetD"></div><svg viewBox="0 0 440 250" preserveAspectRatio="none"><path d="M42 194 C95 170 112 119 172 132 S255 188 290 116 356 77 402 46"/><circle cx="42" cy="194" r="8"/><circle cx="172" cy="132" r="7"/><circle cx="290" cy="116" r="7"/><circle cx="402" cy="46" r="8"/></svg><span class="mapTag tagA">Вы</span><span class="mapTag tagB">Помощник</span></div><div class="coverTask"><span class="taskIcon">⌁</span><div class="taskCopy"><small>ПРИМЕР ЗАЯВКИ</small><strong>Помочь настроить технику</strong><span>Сегодня · рядом с вами</span></div><span class="taskArrow">↗</span></div><div class="coverBottom"><span class="avatarStack"><i>А</i><i>М</i><i>И</i></span><span>Подбор по навыкам и расстоянию</span></div></div></section>
<section class="section"><div class="sectionIntro"><span class="ey">ПРОСТО И ПОНЯТНО</span><h2>От запроса до помощи — три шага</h2></div><div class="featureGrid steps"><div class="card stepCard"><span class="stepNo">01</span><h3>Опишите задачу</h3><p class="muted">Укажите, что нужно, где и когда. Точный адрес останется приватным.</p></div><div class="card stepCard"><span class="stepNo">02</span><h3>Найдите подходящего</h3><p class="muted">Smart Match учитывает категорию, опыт, рейтинг и расстояние.</p></div><div class="card stepCard"><span class="stepNo">03</span><h3>Договоритесь и помогите</h3><p class="muted">Общайтесь в чате или продолжайте в Telegram — профиль и заявки общие.</p></div></div></section>
<section class="section"><h2>H·Point+</h2><p class="muted">Оплата в рублях или H-Points.</p><div id="prices" class="featureGrid"></div></section></main>
<main id="app" class="wrap app"><section class="appHead"><div class="welcome"><div><span class="ey">ТВОЙ H·POINT</span><h1 id="welcome"></h1><div id="verifyNotice"></div></div><button class="btn light" onclick="logout()">Выйти</button></div><div class="tabs"><button class="tab active" data-t="home">Главная</button><button class="tab" data-t="requests">Заявки</button><button class="tab" data-t="match">Smart Match</button><button class="tab" data-t="chat">Чаты</button><button class="tab" data-t="map">Карта</button><button class="tab" data-t="history">История</button><button class="tab" data-t="profile">Профиль</button><button class="tab" data-t="billing">H·Point+</button></div></section>
<section id="p-home" class="panel active"><div class="stats"><div class="card stat"><span class="muted">Баланс</span><div class="big" id="bal"></div></div><div class="card stat"><span class="muted">Ваш рейтинг</span><div class="big" id="rate"></div></div><div class="card stat"><span class="muted">Помощей оказано</span><div class="big" id="helped"></div></div><div class="card stat"><span class="muted">Помощей получено</span><div class="big" id="received"></div></div></div><div class="layout" style="margin-top:16px"><div class="card"><span class="ey">БЫСТРЫЙ СТАРТ</span><h2>Что сделаем сейчас?</h2><div class="actions"><button class="btn grad" onclick="requestForm()">🆘 Нужна помощь</button><button class="btn light" onclick="helper()">🤝 Хочу помочь</button><button class="btn light" onclick="go('match')">⚡ Найти человека</button></div></div><div class="card verify"><h3>🔐 Подтверждение личности</h3><p id="verifyText" class="muted"></p><button class="btn light" onclick="go('profile')">Открыть профиль</button></div></div></section>
<section id="p-requests" class="panel"><div class="layout"><div><div style="display:flex;justify-content:space-between;align-items:center"><h2>Заявки</h2><button class="btn grad" onclick="requestForm()">+ Новая</button></div><div id="mine"></div></div><div class="card"><h3>Умный поиск</h3><input id="searchInput" class="input" placeholder="Например: нужна дрель рядом"><select id="searchCategory" class="input"><option value="">Все категории</option><option value="tech">Техника</option><option value="tools">Инструменты</option><option value="carry">Перенос / переезд</option><option value="shopping">Покупки</option><option value="study">Учёба</option><option value="transport">Транспорт</option><option value="snow">Снег / уборка</option></select><button class="btn dark" style="width:100%" onclick="searchOpen()">Найти заявки</button><div id="searchResults" style="margin-top:12px"></div></div></div></section>
<section id="p-match" class="panel"><div class="layout"><div><h2>Smart Match</h2><div class="card form"><select id="rid" class="input"></select><input id="matchQuestion" class="input" placeholder="Уточните: например, нужен человек с опытом техники"><button class="btn grad" onclick="match()">⚡ Найти лучших кандидатов</button><p class="muted">Подбор объясняет, почему кандидат оказался в списке. Персональные данные и точный адрес не показываются.</p></div><div id="matches" class="card" style="padding:0;margin-top:15px"></div></div><div><div id="mapMatch" class="map"></div></div></div></section>
<section id="p-chat" class="panel"><div class="layout"><div class="card"><h2>Чаты</h2><div id="chatList"></div></div><div class="card"><div id="chatWindow" class="empty">Выберите чат с назначенным помощником или заказчиком.</div></div></div></section>
<section id="p-map" class="panel"><h2>Карта</h2><p class="muted">Открытые заявки и найденные Smart Match-кандидаты.</p><div id="bigMap" class="map"></div></section>
<section id="p-history" class="panel"><h2>История</h2><div id="historyList"></div></section>
<section id="p-profile" class="panel"><div class="profileGrid"><div class="card"><h2>Профиль</h2><div class="form"><input id="pn" class="input" placeholder="Имя"><input id="pc" class="input" placeholder="Город"><textarea id="pb" class="input textarea" placeholder="Коротко о себе"></textarea><button class="btn grad" onclick="saveProfile()">Сохранить профиль</button></div><div id="profInfo" style="margin-top:18px"></div></div><div class="card"><h2>Подключить Telegram</h2><p class="muted">После привязки профиль, заявки и история будут общими на сайте и в боте.</p><div id="tgState"></div><button id="tgLinkButton" class="btn light" onclick="linkcode()">Получить код привязки</button><div id="code" class="ey" style="margin-top:12px">—</div><p id="tgGuide" class="muted" style="margin-top:12px">Получите код и отправьте в боте: <b>/link КОД</b>.</p></div></div></section>
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
function authForm(reg){$('modal').style.display='flex';$('modalbody').innerHTML=reg?`<h2>Создать аккаунт</h2><p class="muted">Войдите через Telegram или используйте email. Telegram подтверждает аккаунт и синхронизирует сайт с ботом.</p><div class="form"><button class="btn grad" onclick="telegramLogin()">Продолжить с Telegram</button><div class="muted" style="text-align:center">или</div><input id="an" class="input" placeholder="Имя"><input id="ae" class="input" placeholder="Email"><input id="ap" class="input" type="password" autocomplete="new-password" placeholder="Пароль от 12 символов"><button class="btn light" onclick="register()">Зарегистрироваться по email</button><div id="err" class="muted"></div></div>`:`<h2>Войти</h2><p class="muted">Telegram откроет тот же профиль и историю заявок.</p><div class="form"><button class="btn grad" onclick="telegramLogin()">Войти через Telegram</button><div class="muted" style="text-align:center">или</div><input id="ae" class="input" placeholder="Email" autocomplete="email"><input id="ap" class="input" type="password" autocomplete="current-password" placeholder="Пароль"><button class="btn light" onclick="login()">Войти по email</button><div id="err" class="muted"></div></div>`}
function closeModal(){$('modal').style.display='none'}
async function register(){try{let d=await api('/api/auth/register',{method:'POST',body:JSON.stringify({name:an.value,email:ae.value,password:ap.value})});closeModal();toast('Аккаунт создан');await load();if(d.link_code)go('profile')}catch(e){$('err').textContent=e.message}}
async function login(){try{await api('/api/auth/login',{method:'POST',body:JSON.stringify({email:ae.value,password:ap.value})});closeModal();await load();toast('С возвращением')}catch(e){$('err').textContent=e.message}}
async function telegramLogin(){try{let d=await api('/api/auth/telegram/start',{method:'POST',body:'{}'});window.open(d.bot_url,'hpointTelegramLogin','noopener');$('modalbody').innerHTML=`<h2>Подтвердите вход в Telegram</h2><p class="muted">Открылся бот H·Point. Нажмите «Start» в Telegram — сайт войдёт автоматически.</p><div id="tgLoginStatus" class="ey">Ожидаем подтверждение…</div>`;let tries=0;let poll=setInterval(async()=>{tries++;try{let r=await fetch('/api/auth/telegram/complete?ticket='+encodeURIComponent(d.ticket),{credentials:'same-origin'});if(r.status===202){if(tries>150){clearInterval(poll);$('tgLoginStatus').textContent='Ссылка истекла. Начните вход заново.'}return}let done=await r.json();if(done.ok){clearInterval(poll);closeModal();await load();toast('Вход через Telegram выполнен')}}catch(e){clearInterval(poll);$('tgLoginStatus').textContent='Не удалось подтвердить вход.'}},2000)}catch(e){$('err').textContent=e.message==='telegram_login_unavailable'?'Вход через Telegram пока настраивается.':'Не удалось начать вход через Telegram.'}}
async function logout(){await fetch('/api/auth/logout',{method:'POST'});location.reload()}
function landing(){ $('landing').style.display='block';$('app').style.display='none';$('nav').innerHTML='<button class="btn light" onclick="authForm(false)">Войти</button><button class="btn dark" onclick="authForm(true)">Регистрация</button>';prices('prices',false)}
async function load(){try{let d=await api('/api/dashboard');$('landing').style.display='none';$('app').style.display='block';$('nav').innerHTML='<button class="btn light" onclick="go(\'profile\')">Профиль</button><button class="btn dark" onclick="requestForm()">+ Заявка</button>';$('welcome').textContent='Добро пожаловать, '+d.user.name;$('bal').textContent=d.user.balance+' HP';$('rate').textContent=d.user.stats.helped_avg?'⭐ '+d.user.stats.helped_avg.toFixed(1):'—';$('helped').textContent=d.user.stats.helped;$('received').textContent=d.user.stats.received;$('verifyText').textContent=d.user.verified?'Профиль подтверждён. Можно пользоваться всеми основными функциями.':'Привяжите Telegram в профиле, чтобы подтвердить аккаунт и получить полный доступ к связке сайта и бота.';$('verifyNotice').innerHTML=d.user.verified?'<span class="badge ok">✓ Профиль подтверждён</span>':'<span class="badge warn">Нужно привязать Telegram</span>';await requests();await profile();prices('appprices',true);await billing();startSync()}catch(e){landing()}}
async function syncTick(){try{let d=await api('/api/dashboard');$('welcome').textContent='Добро пожаловать, '+d.user.name;$('bal').textContent=d.user.balance+' HP';$('rate').textContent=d.user.stats.helped_avg?'⭐ '+d.user.stats.helped_avg.toFixed(1):'—';$('helped').textContent=d.user.stats.helped;$('received').textContent=d.user.stats.received;$('verifyText').textContent=d.user.tg_linked?'Telegram привязан: заявки и история доступны в обоих интерфейсах.':'До привязки заявки сайта и Telegram относятся к разным профилям. В профиле получите код и отправьте /link КОД в боте.';$('verifyNotice').innerHTML=d.user.tg_linked?'<span class="badge ok">✓ Telegram привязан</span>':'<span class="badge warn">Нужно привязать Telegram</span>';await requests();let tab=document.querySelector('.tab.active')?.dataset.t;if(tab==='history')await history();if(tab==='profile')await profile();if(tab==='billing')await billing()}catch(e){if(e.message==='auth_required')stopSync()}}
function startSync(){if(syncTimer)return;syncTick();syncTimer=setInterval(()=>{if(document.visibilityState==='visible')syncTick()},5000);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')syncTick()})}
function stopSync(){if(syncTimer){clearInterval(syncTimer);syncTimer=null}}
async function requests(){let d=await api('/api/requests/mine');$('mine').innerHTML=d.requests.length?d.requests.map(r=>`<div class="request"><div class="avatar">${esc((r.what||'?')[0].toUpperCase())}</div><div class="requestmain"><b>#${r.id} · ${esc(r.what)}</b><div class="muted">${esc(r.category_name)} · ${esc(r.place)} · ${esc(r.status_title)}</div></div><span class="badge ${r.status==='done'?'ok':r.status==='in_progress'?'warn':''}">${esc(r.urgency)}</span>${r.status==='in_progress'&&r.helper_id===d.current_user_id?`<button class="btn grad" onclick="finish(${r.id})">Завершить</button>`:''}${r.status==='in_progress'?`<button class="btn light" onclick="openChat(${r.id})">Чат</button>`:''}${r.status==='done'&&r.requester_id===d.current_user_id&&!r.requester_rating?`<button class="btn light" onclick="review(${r.id},'requester')">Оценить</button>`:''}${r.status==='done'&&r.helper_id===d.current_user_id&&!r.helper_rating?`<button class="btn light" onclick="review(${r.id},'helper')">Оценить</button>`:''}</div>`).join(''):'<div class="empty">Здесь появятся ваши заявки.</div>'; $('rid').innerHTML=d.requests.filter(r=>r.status==='open').map(r=>`<option value="${r.id}">#${r.id} — ${esc(r.what)}</option>`).join('')||'<option value="">Нет открытых заявок</option>'}
function requestForm(){ $('modal').style.display='flex';$('modalbody').innerHTML=`<h2>Новая заявка</h2><p class="muted">Опишите задачу понятно. Геопозиция используется только для подбора.</p><div class="form"><input id="qw" class="input" placeholder="Что нужно сделать?"><input id="qp" class="input" placeholder="Район / ориентир"><input id="qt" class="input" placeholder="Когда нужна помощь?"><select id="qc" class="input"><option value="other">Другое</option><option value="carry">Перенос / переезд</option><option value="shopping">Покупки</option><option value="snow">Снег / уборка</option><option value="tools">Инструменты</option><option value="transport">Транспорт</option><option value="tech">Техника</option><option value="study">Учёба</option></select><select id="qu" class="input"><option>🔥 Очень срочно</option><option>⏳ В течение дня</option><option>🕊 Не срочно</option></select><textarea id="qd" class="input textarea" placeholder="Детали"></textarea><button class="btn grad" onclick="createReq()">Создать заявку</button><div id="rqerr" class="muted"></div></div>`}
function createReq(){let submitted=false;const submit=(lat,lon)=>{if(submitted)return;submitted=true;sendReq(lat,lon)};try{if(!navigator.geolocation){submit(null,null);return}navigator.geolocation.getCurrentPosition(p=>submit(p.coords.latitude,p.coords.longitude),()=>submit(null,null),{timeout:2500,maximumAge:60000})}catch(e){submit(null,null)}}
async function sendReq(lat,lon){try{let d=await api('/api/requests',{method:'POST',body:JSON.stringify({what:qw.value,place:qp.value,time_needed:qt.value,urgency:qu.value,details:qd.value,category:qc.value,lat,lon})});closeModal();await requests();toast('Заявка #'+d.request_id+(d.matched?' · помощник уже найден':' создана'));go('match')}catch(e){$('rqerr').textContent=e.message}}
async function helper(){try{let d=await api('/api/helper/queue',{method:'POST'});toast(d.message)}catch(e){toast(e.message)}}
function initMatchMap(){if(!matchMap){matchMap=new ymaps.Map('mapMatch',{center:[55.75,37.62],zoom:10,controls:['zoomControl','searchControl']},{searchControlProvider:'yandex#search'})}setTimeout(()=>matchMap.container.fitToViewport(),100)}
async function match(){if(!rid.value)return;try{let d=await api('/api/assistant/candidates',{method:'POST',body:JSON.stringify({request_id:Number(rid.value),question:$('matchQuestion').value})});$('matches').innerHTML=d.matches.length?d.matches.map(x=>`<div class="match"><div class="avatar">${esc((x.name||'?')[0])}</div><div class="grow"><b>${esc(x.name)} ${x.verified?'✓':''}</b><div class="muted">⭐ ${x.rating||'—'} · ${x.distance_km??'—'} км · ${x.reviews} отзывов · match ${Math.round(x.score)}%</div><div class="muted">${esc((x.reasons||[]).join(' · '))}</div></div><button class="btn grad" onclick="assign(${rid.value},${x.user_id})">Предложить</button></div>`).join(''):'<div class="empty">Пока нет подходящих кандидатов.</div>';initMatchMap();d.matches.filter(x=>x.lat&&x.lon).forEach(x=>{const pm=new ymaps.Placemark([x.lat,x.lon],{balloonContent:esc(x.name)});matchMap.geoObjects.add(pm)});}catch(e){toast(e.message)}}
async function assign(r,h){try{await api('/api/smart-match/assign',{method:'POST',body:JSON.stringify({request_id:r,helper_id:h})});toast('Помощник назначен, чат создан');await requests();openChat(r)}catch(e){toast(e.message)}}
async function finish(id){try{await api('/api/requests/finish',{method:'POST',body:JSON.stringify({request_id:id})});toast('Помощь завершена');await requests()}catch(e){toast(e.message)}}
function review(id,side){$('modal').style.display='flex';$('modalbody').innerHTML=`<h2>Оценить взаимодействие</h2><div class="form"><select id="rv" class="input"><option value="5">5 ⭐</option><option value="4">4 ⭐</option><option value="3">3 ⭐</option><option value="2">2 ⭐</option><option value="1">1 ⭐</option></select><textarea id="rt" class="input textarea" placeholder="Отзыв"></textarea><button class="btn grad" onclick="sendReview(${id},'${side}')">Сохранить</button></div>`}
async function sendReview(id,side){try{await api('/api/reviews',{method:'POST',body:JSON.stringify({request_id:id,side,rating:Number(rv.value),review:rt.value})});closeModal();toast('Спасибо за отзыв');await requests();await load()}catch(e){toast(e.message)}}
async function profile(){let d=await api('/api/me'),u=d.user,linked=Boolean(u.tg_linked);$('pn').value=u.name||'';$('pc').value=u.city||'';$('pb').value=u.bio||'';$('profInfo').innerHTML=`<p><b>${esc(u.name)}</b></p><p class="muted">${esc(u.email||'')}<br>Рейтинг: ${u.stats.helped_avg?u.stats.helped_avg.toFixed(1):'—'} · ${u.stats.helped} помощей</p>`;$('tgState').innerHTML=(linked?'<span class="badge ok">✓ Telegram привязан</span>':'<span class="badge warn">Telegram не привязан</span>')+(u.telegram_url?` <a class="btn light" href="${esc(u.telegram_url)}" target="_blank" rel="noopener">Перейти в Telegram</a>`:'');$('tgLinkButton').style.display=linked?'none':'';$('code').textContent=linked?'Подключено':u.link_code||'Код не создан';$('tgGuide').innerHTML=linked?'Сайт и бот используют один профиль.':'Получите код и отправьте в боте: <b>/link КОД</b>.'}
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

# The page intentionally remains a dependency-free single-file UI.  These
# overrides keep the existing API and markup stable while applying the actual
# H-Point visual language and the live interaction improvements below.
BRAND_CSS=r'''
/* H-Point brand assets */
:root{--brand:#087bff;--brand2:#12cfd0;--brandDeep:#123968;--brandMist:#effbff}
.brandLogo{display:flex;align-items:center;text-decoration:none;line-height:0}.brandLogo img{display:block;width:132px;height:42px;object-fit:contain;object-position:left center}
.authBrand{margin-bottom:18px}.authBrand img{display:block;width:148px;height:47px;object-fit:contain;object-position:left center}
.cover{background:linear-gradient(145deg,rgba(6,82,166,.22),rgba(7,219,208,.08)),url('/assets/hpoint-brand-hero.png') center/cover no-repeat;border:1px solid rgba(20,169,231,.12)}
.cover:before{z-index:0;background:#12d5cf30}.coverTop,.coverMapLabel,.coverMapArt,.coverTask,.coverBottom{z-index:2}.coverMapArt{background:linear-gradient(145deg,rgba(7,42,92,.18),rgba(4,122,187,.22)),url('/assets/hpoint-neighbors-hero.png') center/cover no-repeat;border-color:rgba(255,255,255,.42)}
.coverMapArt:before{background:linear-gradient(90deg,rgba(5,71,133,.16),transparent)}.coverMapArt .mapStreet,.coverMapArt svg,.coverMapArt .mapTag{display:none}.coverTask{background:rgba(10,47,89,.82);border-color:rgba(255,255,255,.32)}.coverBrand span{color:#8efbd8}.coverDemo i{background:#a7ff50}.grad{background:linear-gradient(120deg,#087bff,#12cfd0);box-shadow:0 8px 20px rgba(8,123,255,.2)}.grad:hover{box-shadow:0 11px 26px rgba(8,123,255,.29)}.ey{background:#e8f9ff;color:#0875cf}.eyDot{background:#12cfd0;box-shadow:0 0 0 4px rgba(18,207,208,.14)}.tab.active{background:#0d4078;border-color:#0d4078}.avatar{background:linear-gradient(135deg,#dffbfa,#dceaff);color:#0875cf}.identityCard{background:linear-gradient(145deg,#effcff,#fff 62%);border-color:#cdeefa}.identityCard h2{margin-top:0}.identityCard .identityArt{float:right;width:46px;height:46px;object-fit:contain;margin:-8px 0 8px 12px}.chat{height:520px}.chatHeader{display:flex;align-items:center;gap:10px;padding:3px 2px 13px}.chatHeader .avatar{flex:0 0 auto}.chatHint{font-size:11px;color:var(--muted);margin-top:2px}.messages{background:linear-gradient(180deg,#f2fbff,#f8fbff)}.msg.mine{background:#e5fbfb;border-color:#c5efed}.chatbar textarea{min-height:48px;max-height:110px;resize:vertical}.chatbar .btn{align-self:flex-end}.chatStatus{font-size:10px;color:#168672;font-weight:800;letter-spacing:.08em}
@media(max-width:650px){.brandLogo img{width:116px;height:38px}.chat{height:480px}.chatbar{align-items:flex-end}.chatbar .btn{padding:12px 13px}.identityCard .identityArt{width:38px;height:38px}}
'''

# The landing visual direction deliberately uses the same visual principles as
# the approved reference: one strong dark stage, precise labels and restrained
# colour.  The site's existing data attributes and JavaScript hooks remain
# unchanged, so these are presentation-only changes.
REFERENCE_CSS=r'''
:root{--bg:#10120f;--surface:#171a14;--ink:#edf0e7;--muted:#a9afa1;--line:#3a4035;--brand:#12cfd0;--brand2:#087bff;--ok:#b8f36b;--warn:#f5d96b;--shadow:none}
*{scrollbar-color:#4b5245 #10120f}body{background:radial-gradient(ellipse at 76% 13%,#1d322d 0,transparent 38%),#10120f;color:var(--ink);font-family:Manrope,Arial,sans-serif;letter-spacing:-.012em}.nav{background:rgba(16,18,15,.87);border-bottom:1px solid #30352d;backdrop-filter:blur(18px)}.in,.wrap{width:min(1360px,100%);padding-left:clamp(20px,5vw,80px);padding-right:clamp(20px,5vw,80px)}.in{height:76px}.brandLogo{filter:brightness(1.08) saturate(1.08)}.brandLogo img{width:144px;height:49px}.btn{border-radius:0;font-size:12px;letter-spacing:.015em;padding:14px 19px;transition:transform .18s,background .18s,border-color .18s}.btn:hover{transform:translateY(-2px)}.dark,.grad{background:#b8f36b;color:#10120f;box-shadow:none}.dark:hover,.grad:hover{background:#d3ff74;box-shadow:none}.light{background:transparent;color:#edf0e7;border:1px solid #4a5146}.light:hover{border-color:#b8f36b;background:#1a1d17}.danger{background:transparent;color:#ffc8bf;border-color:#8f4137}.muted{color:#a9afa1}.landingHero{position:relative;min-height:calc(100svh - 76px);padding:clamp(64px,10vh,130px) 0 62px;grid-template-columns:minmax(320px,.84fr) 1.16fr;gap:28px;align-items:center;isolation:isolate}.landingHero:before{content:"";position:absolute;inset:0;z-index:-2;opacity:.13;pointer-events:none;background-image:linear-gradient(#82907e 1px,transparent 1px),linear-gradient(90deg,#82907e 1px,transparent 1px);background-size:72px 72px;mask-image:linear-gradient(90deg,#000 20%,transparent 80%)}.landingHero:after{content:"";position:absolute;z-index:-1;width:390px;height:390px;right:10%;top:14%;border:1px solid #4b5447;border-radius:50%;box-shadow:0 0 0 44px #ffffff05,0 0 0 88px #ffffff03}.hero{position:relative;z-index:2}.ey{padding:0;background:transparent;color:#b8f36b;border-radius:0;font:10px 'Space Mono',monospace;letter-spacing:.17em}.eyDot{width:28px;height:1px;border-radius:0;background:#b8f36b;box-shadow:none}.hero h1{margin:25px 0 20px;max-width:680px;font-size:clamp(52px,6.8vw,104px);line-height:.9;letter-spacing:-.075em;font-weight:600}.hero h1 span{color:#b8f36b;font-family:Georgia,serif;font-style:italic;font-weight:400;letter-spacing:-.09em}.hero p{max-width:435px;color:#c3c9bf;font-size:16px;line-height:1.65}.actions{margin-top:30px}.heroMeta{max-width:430px;margin-top:31px;padding-top:15px;border-top:1px solid #3a4035;color:#a9afa1;font:10px 'Space Mono',monospace;letter-spacing:.015em}.heroMeta b{color:#b8f36b;font-family:'Space Mono',monospace}.cover{width:100%;min-height:clamp(420px,53vw,625px);padding:25px;border:1px solid #3a4035;border-radius:0;background:#10120f;box-shadow:none}.cover:before{inset:0;width:auto;height:auto;border-radius:0;right:auto;top:auto;filter:none;background:linear-gradient(180deg,rgba(16,18,15,.08),rgba(16,18,15,.62));z-index:1}.cover:after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(16,18,15,.45),transparent 55%);z-index:1;filter:none}.coverTop,.coverMapLabel,.coverMapArt,.coverTask,.coverBottom{z-index:2}.coverBrand{font:700 11px 'Space Mono',monospace;letter-spacing:.15em;text-transform:uppercase}.coverBrand span{color:#b8f36b}.coverDemo{font-family:'Space Mono',monospace;color:#a9afa1}.coverDemo i{background:#b8f36b;box-shadow:0 0 0 4px #b8f36b24}.coverMapLabel{margin-top:28px;color:#b8f36b;font:10px 'Space Mono',monospace;letter-spacing:.16em}.coverMapArt{height:clamp(235px,29vw,345px);margin-top:15px;border:1px solid #3d463c;border-radius:0;background:linear-gradient(90deg,#10120f11,#10120f66),url('/assets/hpoint-route-network.png') center/cover no-repeat}.coverMapArt:before{background:linear-gradient(90deg,#10120f55,transparent 60%);opacity:1}.coverTask{margin-top:-18px;border:1px solid #566050;background:rgba(16,18,15,.9);border-radius:0;box-shadow:none;backdrop-filter:blur(10px)}.taskIcon{border-radius:0;background:#b8f36b;color:#10120f}.taskCopy small{color:#b8f36b;font-family:'Space Mono',monospace}.taskArrow{color:#b8f36b}.coverBottom{font:10px 'Space Mono',monospace;letter-spacing:.02em}.avatarStack i{border-color:#10120f;border-radius:50%;background:#12cfd0;color:#10120f}.avatarStack i:nth-child(2){background:#087bff;color:#fff}.avatarStack i:nth-child(3){background:#b8f36b;color:#10120f}.section{padding:82px 0;background:#10120f}.sectionIntro{max-width:650px}.sectionIntro .ey{margin-bottom:18px}.section h2{font-size:clamp(32px,4vw,54px);line-height:.98;letter-spacing:-.06em;font-weight:600}.featureGrid{gap:1px;background:#3a4035;border:1px solid #3a4035}.featureGrid:not(.steps){background:transparent;border:0;gap:14px}.stepCard{min-height:300px;padding:28px;background:#161914;border:0;border-radius:0;box-shadow:none;overflow:hidden;isolation:isolate}.stepCard:after{content:"";position:absolute;inset:0;z-index:-1;opacity:.34;background:linear-gradient(90deg,#161914 5%,transparent 100%),url('/assets/hpoint-match-field.png') right center/cover no-repeat;transition:opacity .2s}.stepCard:nth-child(2):after{background-image:linear-gradient(90deg,#161914 5%,transparent 100%),url('/assets/hpoint-route-network.png')}.stepCard:nth-child(3):after{background-image:linear-gradient(90deg,#161914 5%,transparent 100%),url('/assets/hpoint-brand-hero.png')}.stepCard:hover{transform:none;border:0;box-shadow:none}.stepCard:hover:after{opacity:.55}.stepNo{border-radius:0;background:#b8f36b;color:#10120f;font:700 10px 'Space Mono',monospace}.stepCard h3{max-width:210px;font-size:19px}.stepCard p{max-width:260px;color:#c5cbc0}.price{font-size:32px}.card{background:#171a14;border:1px solid #3a4035;border-radius:0;box-shadow:none}.app{background:#10120f;min-height:100vh}.appHead{padding-top:52px}.welcome h1{font-size:clamp(33px,4vw,52px);font-weight:600;letter-spacing:-.06em}.tabs{top:76px;padding-top:24px;background:linear-gradient(#10120f 80%,transparent)}.tab{border-radius:0;color:#a9afa1;font:10px 'Space Mono',monospace;letter-spacing:.08em}.tab.active{background:#b8f36b;border-color:#b8f36b;color:#10120f;box-shadow:none}.stats,.profileGrid{gap:1px;background:#3a4035;border:1px solid #3a4035}.stat,.profileGrid>.card{border:0;background:#171a14}.layout{gap:1px;background:#3a4035;border:1px solid #3a4035}.layout>.card,.layout>div>.card{border:0}.request{background:#171a14;border-color:#3a4035;border-radius:0}.avatar{border-radius:0;background:#182f30;color:#70f5e9}.badge{border-radius:0;background:#252a22;color:#d4d9d0;font:700 10px 'Space Mono',monospace;letter-spacing:.04em}.badge.ok{background:#27391c;color:#d5ff8a}.badge.warn{background:#443d1c;color:#fff1a8}.input{background:#10120f;border-color:#444b40;border-radius:0;color:#edf0e7}.input:focus{border-color:#b8f36b;box-shadow:0 0 0 3px #b8f36b20}.map,.messages{border-radius:0;border-color:#3a4035;background:#151813}.match{border-color:#3a4035}.modal{background:#070806d9}.box{background:#171a14;border:1px solid #4a5146;border-radius:0;box-shadow:0 28px 80px #0009}.close{color:#edf0e7}.messages{background:#11140f}.msg{border-radius:0;background:#1c211a;border-color:#3a4035;color:#edf0e7}.msg.mine{background:#173c3a;border-color:#2c716b}.chatStatus{color:#b8f36b}.identityCard{background:#171a14;border-color:#3a4035}.toast{border-radius:0;background:#b8f36b;color:#10120f;box-shadow:none}.verify{background:#171a14;border-color:#3a4035}
@media(max-width:900px){.landingHero{grid-template-columns:1fr;padding-top:68px}.cover{max-width:720px}.landingHero:after{right:-120px;top:50%}.section{padding:58px 0}}@media(max-width:650px){.nav .in{height:68px}.brandLogo img{width:120px;height:41px}.landingHero{min-height:auto;padding:54px 0 42px}.hero h1{font-size:clamp(47px,14vw,70px)}.cover{min-height:420px;padding:18px}.coverMapArt{height:230px}.section{padding:48px 0}.stepCard{min-height:240px}.tabs{top:68px}.stats,.profileGrid,.layout{gap:1px}.btn{padding:13px 15px}}
'''

SOFT_CSS=r'''
/* Softer surfaces for the dark H-Point theme. */
.brandLogo img{width:174px;height:48px;object-fit:contain;filter:drop-shadow(0 7px 18px rgba(18,207,208,.16))}.btn,.card,.request,.box,.input,.map,.messages,.msg,.badge,.tab,.cover,.coverMapArt,.coverTask,.stepCard,.stat{border-radius:16px}.featureGrid,.stats,.profileGrid,.layout{background:transparent;border:0;gap:14px}.stepCard,.stat,.profileGrid>.card,.layout>.card,.layout>div>.card{border:1px solid rgba(128,151,126,.28)}.cover{border-radius:28px}.coverMapArt{border-radius:20px}.coverTask{border-radius:17px}.btn{border-radius:999px}.tab{border-radius:999px}.badge{border-radius:999px}.input{border-radius:13px}.modal .box{border-radius:26px}.card,.request{transition:transform .26s ease,box-shadow .26s ease,border-color .26s ease}.card:hover,.request:hover{transform:translateY(-3px);border-color:rgba(184,243,107,.5);box-shadow:0 18px 42px rgba(0,0,0,.18)}.cover{animation:float-cover 7s ease-in-out infinite}.hero,.coverTask,.stepCard{animation:fade-up .65s both}.coverTask{animation-delay:.16s}.stepCard:nth-child(2){animation-delay:.09s}.stepCard:nth-child(3){animation-delay:.18s}.grad,.dark{box-shadow:0 10px 22px rgba(184,243,107,.12)}.grad:hover,.dark:hover{box-shadow:0 14px 28px rgba(184,243,107,.2)}.audiencePortrait{margin:16px 0 0!important;max-width:590px;padding:13px 15px;border-left:2px solid #b8f36b;background:linear-gradient(90deg,rgba(184,243,107,.1),transparent);color:#d7ded2!important;font-size:13px!important;line-height:1.65!important}.profileActions{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-top:14px}.profileSwitch{display:grid;gap:8px;margin-top:12px}.profileSwitch .request{margin:0;padding:11px 13px;cursor:pointer}.productPrices{display:flex;gap:9px;align-items:baseline;flex-wrap:wrap}.productPrices .hp{color:#b8f36b;font:700 13px 'Space Mono',monospace}.purchaseActions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.purchaseActions .btn{padding:11px 14px;font-size:11px}@keyframes float-cover{50%{transform:translateY(-7px)}}@keyframes fade-up{from{opacity:0;transform:translateY(13px)}to{opacity:1;transform:translateY(0)}}@media(prefers-reduced-motion:reduce){.cover,.hero,.coverTask,.stepCard{animation:none}.card,.request,.btn{transition:none}}
@media(max-width:650px){.brandLogo img{width:142px;height:39px}.featureGrid,.stats,.profileGrid,.layout{gap:10px}.card:hover,.request:hover{transform:none}}
'''

ACCOUNT_UI_OVERRIDES=r'''
products.splice(0,products.length,
 ['boost','Продвижение заявки','Приоритет в Smart Match',49,25],['more_responses','Больше откликов','Дополнительный приоритет',79,40],['pro','H·Point PRO','Расширенные возможности на 30 дней',299,180],['verification','Проверка личности','Ручная проверка после привязки Telegram',99,70],['favorites','Избранное+','Пять дополнительных слотов',149,90],['business','H·Point Business','Business-доступ на 30 дней',999,600],['business_pro','Business Pro','Расширенный Business на 30 дней',1499,900],['ad','Локальное объявление','Размещение на 7 дней',199,120]);
function prices(id,paid){$(id).innerHTML=products.map(p=>`<div class="card"><span class="ey">H·POINT+</span><h3>${p[1]}</h3><p class="muted">${p[2]}</p><div class="productPrices"><div class="price">${p[3]} ₽</div><div class="hp">или ${p[4]} HP</div></div>${paid?`<div class="purchaseActions"><button class="btn grad" onclick="buy('${p[0]}','hp')">Оплатить HP</button><button class="btn light" onclick="buy('${p[0]}','rub')">Оплатить ₽</button></div>`:''}</div>`).join('')}
function purchaseMeta(item){let meta={};if(item==='boost'||item==='more_responses'){let id=prompt('ID открытой заявки:');if(!id)return null;meta.request_id=Number(id)}if(item==='ad'){let text=prompt('Текст объявления:');if(!text)return null;meta.ad_text=text}return meta}
async function buy(item,method){let meta=purchaseMeta(item);if(meta===null)return;try{if(method==='hp'){let d=await api('/api/payments/hp',{method:'POST',body:JSON.stringify({item_type:item,metadata:meta,request_id:meta.request_id,ad_text:meta.ad_text,purchase_key:crypto.randomUUID()})});toast(d.created?'Функция подключена · баланс '+d.balance+' HP':'Покупка уже выполнена');await billing();await syncTick();return}let d=await api('/api/payments/create',{method:'POST',body:JSON.stringify({item_type:item,metadata:meta,request_id:meta.request_id,ad_text:meta.ad_text})});location.href=d.confirmation_url}catch(e){toast(e.message)}}
async function openProfiles(){try{let d=await api('/api/profiles');$('modal').style.display='flex';$('modalbody').innerHTML=`<div class="authBrand"><img src="/assets/hpoint-logo-dark.png" alt="H-Point"></div><h2>Профили на этом устройстве</h2><p class="muted">Каждый профиль хранит свои заявки, баланс и подписки.</p><div class="profileSwitch">${d.profiles.map(p=>`<button class="request" onclick="switchProfile(${p.id})"><div class="avatar">${esc((p.name||'?')[0])}</div><div class="requestmain"><b>${esc(p.name)}</b><div class="muted">${esc(p.email||'Telegram')}</div></div><span class="badge ${p.active?'ok':''}">${p.active?'Активен':'Перейти'}</span></button>`).join('')}</div><div class="profileActions"><button class="btn grad" onclick="authForm(false)">+ Добавить профиль</button></div>`}catch(e){toast(e.message)}}
async function switchProfile(id){try{await api('/api/profiles/switch',{method:'POST',body:JSON.stringify({user_id:id})});closeModal();await load();toast('Профиль переключён')}catch(e){toast(e.message)}}
async function unlinkTelegram(){if(!confirm('Отвязать Telegram? Данные останутся на сайте, а у бота начнётся отдельный чистый профиль.'))return;try{await api('/api/profile/telegram/unlink',{method:'POST',body:'{}'});toast('Telegram отвязан');await load();go('profile')}catch(e){toast(e.message)}}
async function profile(providedUser){let u=providedUser||(await api('/api/me')).user,linked=Boolean(u.tg_linked);$('pn').value=u.name||'';$('pc').value=u.city||'';$('pb').value=u.bio||'';$('profInfo').innerHTML=`<p><b>${esc(u.name)}</b></p><p class="muted">${esc(u.email||'')}<br>Рейтинг: ${u.stats.helped_avg?u.stats.helped_avg.toFixed(1):'—'} · ${u.stats.helped} помощей</p>`;$('tgState').innerHTML=linked?'<span class="badge ok">✓ Telegram привязан</span>':'<span class="badge warn">Telegram не привязан</span>';$('tgLinkButton').style.display=linked?'none':'';$('code').textContent=linked?'Подключено':u.link_code||'Код не создан';$('tgGuide').innerHTML=linked?'Сайт и бот используют один профиль. При отвязке данные сайта сохранятся, а бот начнёт отдельный профиль.':'Получите код и отправьте в боте: <b>/link КОД</b>.';let host=$('tgState').parentElement;let actions=$('tgUnlinkButton');if(!actions){actions=document.createElement('div');actions.id='tgUnlinkButton';actions.className='profileActions';host.appendChild(actions)}actions.innerHTML=linked?'<button class="btn danger" onclick="unlinkTelegram()">Отвязать Telegram</button>':'';renderIdentityCard(u)}
async function load(){try{let d=await api('/api/sync');$('landing').style.display='none';$('app').style.display='block';$('nav').innerHTML='<button class="btn light" onclick="openProfiles()">Профили</button><button class="btn light" onclick="go(\'profile\')">Профиль</button><button class="btn dark" onclick="requestForm()">+ Заявка</button>';applySync(d);await profile(d.user);prices('appprices',true);await billing();startSync()}catch(e){landing()}}
async function billing(){let d=await api('/api/billing');$('subs').innerHTML=`<p>Баланс: <b>${d.user.balance} HP</b></p><p>PRO: <b>${d.user.pro_until?new Date(d.user.pro_until).toLocaleDateString('ru-RU'):'нет'}</b></p><p>Проверка личности: <b>${d.user.identity_verified?'подтверждена':d.user.identity_verification?.status==='pending'?'на проверке':'нет'}</b></p><p>Business: <b>${d.user.business_until?new Date(d.user.business_until).toLocaleDateString('ru-RU'):'нет'}</b></p>`;$('payments').innerHTML=d.history.length?d.history.map(x=>`<div class="request"><div class="requestmain"><b>${esc(x.item_type)}</b><div class="muted">${x.amount_rub} ${x.currency==='HP'?'HP':'₽'} · ${x.status}</div></div></div>`).join(''):'<div class="muted">Покупок пока нет.</div>'}
'''

FUNCTIONAL_FIXES=r'''
let telegramLoginTimer=null;
function stopTelegramLoginPolling(){if(telegramLoginTimer){clearInterval(telegramLoginTimer);telegramLoginTimer=null}}
function showTelegramLoginWait(){ $('modal').style.display='flex';$('modalbody').innerHTML=`<div class="authBrand"><img src="/assets/hpoint-logo.png" alt="H-Point"></div><h2>Подтвердите вход в Telegram</h2><p class="muted">Нажмите Start в открывшемся боте. Сайт завершит вход сам, в том числе после возврата из Telegram.</p><div id="tgLoginStatus" class="ey">Ожидаем подтверждение…</div>`}
async function completeTelegramLogin(ticket){stopTelegramLoginPolling();let tries=0,finished=false;let poll=async()=>{if(finished)return;tries++;try{let r=await fetch('/api/auth/telegram/complete?ticket='+encodeURIComponent(ticket),{credentials:'same-origin'});if(r.status===202){if(tries>150){finished=true;stopTelegramLoginPolling();sessionStorage.removeItem('hpointTelegramLoginTicket');let status=$('tgLoginStatus');if(status)status.textContent='Ссылка истекла. Начните вход заново.'}return}let done=await r.json();if(done.ok){finished=true;stopTelegramLoginPolling();sessionStorage.removeItem('hpointTelegramLoginTicket');closeModal();await load();toast('Вход через Telegram выполнен')}}catch(e){finished=true;stopTelegramLoginPolling();let status=$('tgLoginStatus');if(status)status.textContent='Не удалось подтвердить вход. Попробуйте ещё раз.'}};await poll();if(!finished)telegramLoginTimer=setInterval(poll,2000)}
async function telegramLogin(){let popup=window.open('', 'hpointTelegramLogin', 'popup,width=480,height=720');if(popup)popup.opener=null;try{let d=await api('/api/auth/telegram/start',{method:'POST',body:'{}'});sessionStorage.setItem('hpointTelegramLoginTicket',d.ticket);showTelegramLoginWait();if(popup){popup.location.replace(d.bot_url);await completeTelegramLogin(d.ticket)}else window.location.assign(d.bot_url)}catch(e){if(popup)popup.close();let target=$('err');if(target)target.textContent=e.message==='telegram_login_unavailable'?'Вход через Telegram пока не настроен.':e.message||'Не удалось начать вход через Telegram.'}}
function resumeTelegramLogin(){let ticket=sessionStorage.getItem('hpointTelegramLoginTicket');if(ticket){showTelegramLoginWait();completeTelegramLogin(ticket)}}
function openRequestHost(){let host=$('openRequests');if(host)return host;host=document.createElement('div');host.id='openRequests';host.style.marginTop='18px';let anchor=$('searchResults');if(anchor&&anchor.parentElement)anchor.parentElement.appendChild(host);return host}
async function loadOpenRequests(){try{let d=await api('/api/requests?open=1');let host=openRequestHost();host.innerHTML=`<h3>Открытые заявки</h3>${d.requests.length?d.requests.map(r=>`<div class="request"><div class="requestmain"><b>#${r.id} · ${esc(r.what)}</b><div class="muted">${esc(r.category_name)} · ${esc(r.place)} · ${esc(r.urgency)}</div></div><button class="btn grad" onclick="acceptOpenRequest(${r.id})">Помочь</button></div>`).join(''):'<div class="empty">Сейчас нет открытых заявок от других пользователей.</div>'}`}catch(e){let host=openRequestHost();host.innerHTML='<div class="empty">Не удалось загрузить открытые заявки.</div>'}}
async function acceptOpenRequest(id){try{let d=await api('/api/requests/accept',{method:'POST',body:JSON.stringify({request_id:id})});toast('Заявка принята, чат создан');await requests();openChat(d.request_id)}catch(e){toast(e.message);await loadOpenRequests()}}
async function helper(){try{let d=await api('/api/helper/queue',{method:'POST',body:'{}'});toast(d.message);await requests();if(d.matched)openChat(d.request_id);else {go('requests');await loadOpenRequests()}}catch(e){toast(e.message)}}
async function requests(data){renderRequests(data||await api('/api/requests/mine'));if(document.querySelector('.tab.active')?.dataset.t==='requests')await loadOpenRequests()}
function go(t){document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.dataset.t===t));document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('active',x.id==='p-'+t));if(t!=='chat')stopChatPolling();if(t==='requests')requests();if(t==='match'){requests();setTimeout(initMatchMap,50)}if(t==='chat'){loadChats();if(currentChat)startChatPolling()}if(t==='map')setTimeout(loadBigMap,50);if(t==='history')history();if(t==='profile')profile();if(t==='billing'){prices('appprices',true);billing()}}
async function openProfiles(){try{let d=await api('/api/profiles');$('modal').style.display='flex';$('modalbody').innerHTML=`<div class="authBrand"><img src="/assets/hpoint-logo-dark.png" alt="H-Point"></div><h2>Профили на этом устройстве</h2><p class="muted">Каждый профиль хранит свои заявки, баланс и подписки.</p><div class="profileSwitch">${d.profiles.map(p=>`<button class="request" onclick="switchProfile(${p.id})"><div class="avatar">${esc((p.name||'?')[0])}</div><div class="requestmain"><b>${esc(p.name)}</b><div class="muted">${esc(p.email||'Telegram')}</div></div><span class="badge ${p.active?'ok':''}">${p.active?'Активен':'Перейти'}</span></button>`).join('')}</div><div class="profileActions"><button class="btn grad" onclick="closeModal();authForm(true)">+ Создать профиль</button><button class="btn light" onclick="closeModal();authForm(false)">Войти в существующий</button></div>`}catch(e){toast(e.message)}}
'''

UI_OVERRIDES=r'''
products[3]=['verification','Проверка личности','Рассмотрение заявки после привязки Telegram',99];
function authForm(reg){$('modal').style.display='flex';$('modalbody').innerHTML=reg?`<div class="authBrand"><img src="/assets/hpoint-logo.png" alt="H-Point"></div><h2>Создайте общий профиль</h2><p class="muted">Telegram создаёт профиль бесплатно и сразу объединяет сайт с ботом. Email можно добавить для отдельного входа.</p><div class="form"><button class="btn grad" onclick="telegramLogin()">Продолжить бесплатно с Telegram</button><div class="muted" style="text-align:center">или по email</div><input id="an" class="input" placeholder="Имя"><input id="ae" class="input" placeholder="Email"><input id="ap" class="input" type="password" autocomplete="new-password" placeholder="Пароль от 12 символов"><button class="btn light" onclick="register()">Создать аккаунт</button><div id="err" class="muted"></div></div>`:`<div class="authBrand"><img src="/assets/hpoint-logo.png" alt="H-Point"></div><h2>Войти в H·Point</h2><p class="muted">Через Telegram вы попадёте в тот же профиль и историю заявок.</p><div class="form"><button class="btn grad" onclick="telegramLogin()">Войти через Telegram</button><div class="muted" style="text-align:center">или по email</div><input id="ae" class="input" placeholder="Email" autocomplete="email"><input id="ap" class="input" type="password" autocomplete="current-password" placeholder="Пароль"><button class="btn light" onclick="login()">Войти по email</button><div id="err" class="muted"></div></div>`}
async function telegramLogin(){const popup=window.open('', 'hpointTelegramLogin', 'popup,width=480,height=720');if(popup)popup.opener=null;try{let d=await api('/api/auth/telegram/start',{method:'POST',body:'{}'});if(popup)popup.location.replace(d.bot_url);else window.location.assign(d.bot_url);$('modalbody').innerHTML=`<div class="authBrand"><img src="/assets/hpoint-logo.png" alt="H-Point"></div><h2>Подтвердите вход в Telegram</h2><p class="muted">В открывшемся боте нажмите Start. После этого сайт автоматически откроет ваш общий профиль.</p><div id="tgLoginStatus" class="ey">Ожидаем подтверждение…</div>`;let tries=0,poll=setInterval(async()=>{tries++;try{let r=await fetch('/api/auth/telegram/complete?ticket='+encodeURIComponent(d.ticket),{credentials:'same-origin'});if(r.status===202){if(tries>150){clearInterval(poll);$('tgLoginStatus').textContent='Ссылка истекла. Начните вход заново.'}return}let done=await r.json();if(done.ok){clearInterval(poll);closeModal();await load();toast('Вход через Telegram выполнен')}}catch(e){clearInterval(poll);$('tgLoginStatus').textContent='Не удалось подтвердить вход.'}},2000)}catch(e){if(popup)popup.close();let target=$('err');if(target)target.textContent=e.message==='telegram_login_unavailable'?'Вход через Telegram пока настраивается.':'Не удалось начать вход через Telegram.'}}
let chatTimer=null,chatRefreshing=false,chatSending=false;
function renderRequests(d){$('mine').innerHTML=d.requests.length?d.requests.map(r=>`<div class="request"><div class="avatar">${esc((r.what||'?')[0].toUpperCase())}</div><div class="requestmain"><b>#${r.id} · ${esc(r.what)}</b><div class="muted">${esc(r.category_name)} · ${esc(r.place)} · ${esc(r.status_title)}</div></div><span class="badge ${r.status==='done'?'ok':r.status==='in_progress'?'warn':''}">${esc(r.urgency)}</span>${r.status==='in_progress'&&r.helper_id===d.current_user_id?`<button class="btn grad" onclick="finish(${r.id})">Завершить</button>`:''}${r.status==='in_progress'?`<button class="btn light" onclick="openChat(${r.id})">Чат</button>`:''}${r.status==='done'&&r.requester_id===d.current_user_id&&!r.requester_rating?`<button class="btn light" onclick="review(${r.id},'requester')">Оценить</button>`:''}${r.status==='done'&&r.helper_id===d.current_user_id&&!r.helper_rating?`<button class="btn light" onclick="review(${r.id},'helper')">Оценить</button>`:''}</div>`).join(''):'<div class="empty">Здесь появятся ваши заявки.</div>';$('rid').innerHTML=d.requests.filter(r=>r.status==='open').map(r=>`<option value="${r.id}">#${r.id} — ${esc(r.what)}</option>`).join('')||'<option value="">Нет открытых заявок</option>'}
function updateDashboard(u){$('welcome').textContent='Добро пожаловать, '+u.name;$('bal').textContent=u.balance+' HP';$('rate').textContent=u.stats.helped_avg?'⭐ '+u.stats.helped_avg.toFixed(1):'—';$('helped').textContent=u.stats.helped;$('received').textContent=u.stats.received;let state=u.identity_verification?.status||'not_requested';let text=!u.tg_linked?'Привяжите Telegram: сайт и бот будут работать с одной историей заявок.':state==='approved'?'Личность подтверждена вручную. Статус действует 365 дней.':state==='pending'?'Заявка на ручную проверку личности уже принята.':'Telegram привязан. При необходимости отправьте заявку на ручное подтверждение личности.';$('verifyText').textContent=text;$('verifyNotice').innerHTML=u.tg_linked?'<span class="badge ok">✓ Telegram подключён</span>':'<span class="badge warn">Нужно подключить Telegram</span>'}
function applySync(d){updateDashboard(d.user);renderRequests(d)}
function go(t){document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.dataset.t===t));document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('active',x.id==='p-'+t));if(t!=='chat')stopChatPolling();if(t==='requests')requests();if(t==='match'){requests();setTimeout(initMatchMap,50)}if(t==='chat'){loadChats();if(currentChat)startChatPolling()}if(t==='map')setTimeout(loadBigMap,50);if(t==='history')history();if(t==='profile')profile();if(t==='billing'){prices('appprices',true);billing()}}
async function requests(data){renderRequests(data||await api('/api/requests/mine'))}
async function load(){try{let d=await api('/api/sync');$('landing').style.display='none';$('app').style.display='block';$('nav').innerHTML='<button class="btn light" onclick="go(\'profile\')">Профиль</button><button class="btn dark" onclick="requestForm()">+ Заявка</button>';applySync(d);await profile(d.user);prices('appprices',true);await billing();startSync()}catch(e){landing()}}
async function syncTick(){try{let d=await api('/api/sync');applySync(d);let tab=document.querySelector('.tab.active')?.dataset.t;if(tab==='history')await history();if(tab==='profile')await profile(d.user);if(tab==='billing')await billing();if(tab==='chat')loadChats()}catch(e){if(e.message==='auth_required'){stopSync();stopChatPolling()}}}
function startSync(){if(syncTimer)return;syncTimer=setInterval(()=>{if(document.visibilityState==='visible')syncTick()},10000);document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){syncTick();if(currentChat&&document.querySelector('.tab.active')?.dataset.t==='chat')refreshChat()}})}
function stopSync(){if(syncTimer){clearInterval(syncTimer);syncTimer=null}}
function renderIdentityCard(u){let host=document.querySelector('#p-profile .profileGrid'),card=$('identityCard');if(!host)return;if(!card){card=document.createElement('div');card.id='identityCard';card.className='card identityCard';host.appendChild(card)}let state=u.identity_verification?.status||'not_requested',note=u.identity_verification?.note||'',body,action='';if(!u.tg_linked){body='Сначала подключите Telegram. Это подтверждает, что вы управляете аккаунтом, и объединяет сайт с ботом.';action='<button class="btn light" onclick="linkcode()">Подключить Telegram</button>'}else if(state==='approved'){body='Личность подтверждена вручную. Статус действует 365 дней.';action='<span class="badge ok">✓ Личность подтверждена</span>'}else if(state==='pending'){body='Заявка принята и ожидает ручной проверки администратора.';action='<span class="badge warn">На проверке</span>'}else{body=state==='rejected'?(note?'Заявка отклонена: '+esc(note):'Заявка отклонена. Можно отправить новую после уточнения данных.'):'Telegram уже подключён. Отправьте заявку на ручное подтверждение личности.';action='<button class="btn grad" onclick="requestIdentityVerification()">Отправить заявку</button>'}card.innerHTML='<img class="identityArt" src="/assets/hpoint-logo.png" alt=""><h2>Подтверждение личности</h2><p class="muted">'+body+'</p><div>'+action+'</div>'}
async function profile(providedUser){let u=providedUser||(await api('/api/me')).user,linked=Boolean(u.tg_linked);$('pn').value=u.name||'';$('pc').value=u.city||'';$('pb').value=u.bio||'';$('profInfo').innerHTML=`<p><b>${esc(u.name)}</b></p><p class="muted">${esc(u.email||'')}<br>Рейтинг: ${u.stats.helped_avg?u.stats.helped_avg.toFixed(1):'—'} · ${u.stats.helped} помощей</p>`;$('tgState').innerHTML=(linked?'<span class="badge ok">✓ Telegram привязан</span>':'<span class="badge warn">Telegram не привязан</span>')+(u.telegram_url?` <a class="btn light" href="${esc(u.telegram_url)}" target="_blank" rel="noopener">Перейти в Telegram</a>`:'');$('tgLinkButton').style.display=linked?'none':'';$('code').textContent=linked?'Подключено':u.link_code||'Код не создан';$('tgGuide').innerHTML=linked?'Сайт и бот используют один профиль. Входить можно одновременно с нескольких устройств; выход завершает только текущий сеанс.':'Получите код и отправьте в боте: <b>/link КОД</b>.';renderIdentityCard(u)}
async function requestIdentityVerification(){try{let d=await api('/api/identity-verification',{method:'POST',body:'{}'});toast(d.status==='approved'?'Личность уже подтверждена':'Заявка отправлена на проверку');await profile()}catch(e){toast(e.message)}}
async function loadChats(){let d=await api('/api/chats');$('chatList').innerHTML=d.chats.length?d.chats.map(c=>`<button class="request" style="width:100%;text-align:left;border:1px solid var(--line);cursor:pointer" onclick="openChat(${c.request_id})"><div class="avatar">${esc((c.other_name||'?')[0])}</div><div class="requestmain"><b>${esc(c.other_name)}</b><div class="muted">Заявка #${c.request_id} · ${esc(c.last_message||'Новый чат')}</div></div></button>`).join(''):'<div class="empty">Чатов пока нет. Они появятся после назначения помощника.</div>'}
async function openChat(rid){currentChat=Number(rid);go('chat');await refreshChat(true);startChatPolling()}
async function refreshChat(first=false){if(!currentChat||chatRefreshing)return;chatRefreshing=true;try{let d=await api('/api/chats?request_id='+encodeURIComponent(currentChat)),c=d.chats[0];if(!c){if(first)toast('Чат ещё не создан');stopChatPolling();return}if(first||!$('messages')){$('chatWindow').innerHTML=`<div class="chat"><div class="chatHeader"><div class="avatar">${esc((c.other_name||'?')[0])}</div><div><b>${esc(c.other_name)}</b><div class="chatHint">Заявка #${c.request_id} · сообщения синхронизируются с уведомлениями Telegram</div></div><span class="sp"></span><span class="chatStatus">В СЕТИ</span></div><div id="messages" class="messages"></div><div class="chatbar"><textarea id="chatInput" class="input" maxlength="1000" placeholder="Напишите сообщение…"></textarea><button id="sendChatButton" class="btn grad" onclick="sendChat()">Отправить</button></div></div>`;$('chatInput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat()}})}renderMessages(c.messages,first)}catch(e){if(first)toast(e.message)}finally{chatRefreshing=false}}
function renderMessages(ms,forceBottom=false){let box=$('messages');if(!box)return;let atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<64;box.innerHTML=ms.map(m=>`<div class="msg ${m.mine?'mine':''}">${esc(m.text)}<small>${esc(m.author_name)} · ${new Date(m.created_at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}</small></div>`).join('');if(forceBottom||atBottom)box.scrollTop=box.scrollHeight}
function startChatPolling(){if(chatTimer||!currentChat)return;chatTimer=setInterval(()=>{if(document.visibilityState==='visible'&&document.querySelector('.tab.active')?.dataset.t==='chat')refreshChat()},3000)}
function stopChatPolling(){if(chatTimer){clearInterval(chatTimer);chatTimer=null}}
async function sendChat(){let input=$('chatInput'),button=$('sendChatButton'),text=input?.value.trim();if(!text||chatSending)return;chatSending=true;if(button)button.disabled=true;try{let d=await api('/api/chats/send',{method:'POST',body:JSON.stringify({request_id:currentChat,text})});input.value='';renderMessages(d.messages,true);loadChats()}catch(e){toast(e.message)}finally{chatSending=false;if(button)button.disabled=false}}
async function billing(){let d=await api('/api/billing');$('subs').innerHTML=`<p>PRO: <b>${d.user.pro_until?new Date(d.user.pro_until).toLocaleDateString('ru-RU'):'нет'}</b></p><p>Проверка личности: <b>${d.user.identity_verified?'подтверждена':d.user.identity_verification?.status==='pending'?'на проверке':'нет'}</b></p><p>Business: <b>${d.user.business_until?new Date(d.user.business_until).toLocaleDateString('ru-RU'):'нет'}</b></p>`;$('payments').innerHTML=d.history.length?d.history.map(x=>`<div class="request"><div class="requestmain"><b>${esc(x.item_type)}</b><div class="muted">${x.amount_rub} ₽ · ${x.status}</div></div></div>`).join(''):'<div class="muted">Платежей пока нет.</div>'}
'''

CONSENT_MATCH_UI=r'''
async function match(){if(!rid.value)return;try{let d=await api('/api/assistant/candidates',{method:'POST',body:JSON.stringify({request_id:Number(rid.value),question:$('matchQuestion').value})});if(d.offer){$('matches').innerHTML=`<div class="empty">⏳ Ожидаем ответ от <b>${esc(d.offer.name)}</b>. После отказа можно выбрать другого кандидата.</div>`;return}$('matches').innerHTML=d.matches.length?d.matches.map(x=>`<div class="match"><div class="avatar">${esc((x.name||'?')[0])}</div><div class="grow"><b>${esc(x.name)} ${x.verified?'✓':''}</b><div class="muted">⭐ ${x.rating||'—'} · ${x.distance_km??'—'} км · ${x.reviews} отзывов · match ${Math.round(x.score)}%</div><div class="muted">${esc((x.reasons||[]).join(' · '))}</div></div><button class="btn grad" onclick="assign(${rid.value},${x.user_id})">Выбрать</button></div>`).join(''):'<div class="empty">Сейчас в очереди нет подходящих добровольцев.</div>';initMatchMap();d.matches.filter(x=>x.lat&&x.lon).forEach(x=>{const pm=new ymaps.Placemark([x.lat,x.lon],{balloonContent:esc(x.name)});matchMap.geoObjects.add(pm)});}catch(e){toast(e.message)}}
async function assign(requestId,helperId){try{let d=await api('/api/smart-match/assign',{method:'POST',body:JSON.stringify({request_id:requestId,helper_id:helperId})});toast(d.offered?'Предложение отправлено. Ждём ответ помощника.':'Не удалось отправить предложение');await requests();await match()}catch(e){toast(e.message)}}
async function loadOpenRequests(){try{let d=await api('/api/requests?open=1');let host=openRequestHost();host.innerHTML=`<h3>Открытые заявки</h3>${d.requests.length?d.requests.map(r=>`<div class="request"><div class="requestmain"><b>#${r.id} · ${esc(r.what)}</b><div class="muted">${esc(r.category_name)} · ${esc(r.place)} · ${esc(r.urgency)}</div></div><button class="btn grad" onclick="helper()">Готов помочь</button></div>`).join(''):'<div class="empty">Сейчас нет открытых заявок от других пользователей.</div>'}`; }catch(e){let host=openRequestHost();host.innerHTML='<div class="empty">Не удалось загрузить открытые заявки.</div>'}}
async function acceptOpenRequest(id){try{let d=await api('/api/requests/accept',{method:'POST',body:JSON.stringify({request_id:id})});toast(d.message);await requests()}catch(e){toast(e.message);await loadOpenRequests()}}
async function helper(){try{let d=await api('/api/helper/queue',{method:'POST',body:'{}'});toast(d.message);go('requests')}catch(e){toast(e.message)}}
function helperOffersHost(){let host=$('helperOffers');if(host)return host;host=document.createElement('div');host.id='helperOffers';host.style.marginTop='18px';let anchor=openRequestHost();if(anchor&&anchor.parentElement)anchor.parentElement.appendChild(host);return host}
async function loadHelperOffers(){try{let d=await api('/api/helper/offers');let host=helperOffersHost();host.innerHTML=`<h3>Предложения помощи</h3>${d.offers.length?d.offers.map(o=>`<div class="request"><div class="requestmain"><b>Заявка #${o.request_id} · ${esc(o.what)}</b><div class="muted">${esc(o.requester_name)} · ${esc(o.place)} · ${esc(o.time_needed)}</div></div><button class="btn grad" onclick="respondToOffer(${o.request_id},true)">Помогу</button><button class="btn light" onclick="respondToOffer(${o.request_id},false)">Не смогу</button></div>`).join(''):'<div class="empty">Новых предложений нет. Готовность к помощи синхронизирована с ботом.</div>'}`; }catch(e){let host=helperOffersHost();host.innerHTML='<div class="empty">Не удалось загрузить предложения.</div>'}}
async function respondToOffer(id,accept){try{let d=await api('/api/helper/offers/respond',{method:'POST',body:JSON.stringify({request_id:id,accept})});toast(accept?'Помощь подтверждена, чат создан':'Предложение отклонено');await requests();if(d.accepted)openChat(id)}catch(e){toast(e.message);await loadHelperOffers()}}
async function requests(data){renderRequests(data||await api('/api/requests/mine'));if(document.querySelector('.tab.active')?.dataset.t==='requests'){await loadOpenRequests();await loadHelperOffers()}}
async function syncTick(){try{let d=await api('/api/sync');applySync(d);let tab=document.querySelector('.tab.active')?.dataset.t;if(tab==='requests'){await loadOpenRequests();await loadHelperOffers()}if(tab==='history')await history();if(tab==='profile')await profile(d.user);if(tab==='billing')await billing();if(tab==='chat')loadChats()}catch(e){if(e.message==='auth_required'){stopSync();stopChatPolling()}}}
'''

SECURITY_CSS=r'''
/* Clear account verification and small-screen layout. */
html,body{overflow-x:hidden;overflow-x:clip}
@media(max-width:500px){.nav .in{gap:6px}.brandLogo img{width:106px;height:35px}.nav .sp{min-width:0}.nav #nav{display:flex;align-items:center;gap:6px;flex-shrink:0}.nav #nav .btn{padding:9px 10px;font-size:10px;white-space:nowrap}}
.landingMetrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.landingMetric{padding:22px 20px;background:linear-gradient(145deg,#1b2119,#141812);border:1px solid rgba(184,243,107,.24);border-radius:18px}.landingMetric b{display:block;color:#b8f36b;font:700 25px 'Space Mono',monospace}.landingMetric span{display:block;margin-top:7px;color:#c5cbc0;font-size:13px;line-height:1.45}.safetyGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.safetyCard{padding:24px 21px;min-height:188px;background:#171a14;border:1px solid #3a4035;border-radius:18px}.safetyCard .safetyMark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:#27391c;color:#d5ff8a;font-size:18px}.safetyCard h3{margin:17px 0 8px;font-size:17px}.safetyCard p{margin:0;color:#b9c0b3;font-size:13px;line-height:1.6}.landingCta{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:34px;background:linear-gradient(135deg,#1e2b21,#172419);border:1px solid rgba(184,243,107,.34);border-radius:22px}.landingCta h2{margin:0;max-width:620px;font-size:clamp(28px,4vw,48px)}.passwordRules{margin:0;padding:0;display:grid;gap:4px;color:#c5cbc0;font-size:12px;line-height:1.45;list-style:none}.passwordRules li:before{content:'•';color:#b8f36b;margin-right:7px}.passwordHint{font-size:12px;line-height:1.45}.emailVerificationCard{margin-top:14px;padding:17px;border:1px solid #4f7049;background:#1a2118;border-radius:16px}.emailVerificationCard p{margin:7px 0 13px}.emailVerificationCard .form{grid-template-columns:1fr auto;align-items:center}.emailVerificationCard .input{min-width:0;letter-spacing:.15em}.emailVerificationCard .profileActions{margin:0}.emailVerificationCard .badge{display:inline-flex;margin-bottom:8px}.emailVerificationCard.warn{border-color:#70632e;background:#282516}@media(max-width:760px){.landingMetrics,.safetyGrid{grid-template-columns:1fr}.landingMetric{padding:18px}.safetyCard{min-height:0}.landingCta{align-items:flex-start;flex-direction:column;padding:25px 20px}.landingCta .btn{width:100%}.emailVerificationCard .form{grid-template-columns:1fr}.emailVerificationCard .form .btn{width:100%}}@media(max-width:420px){.modal{padding:10px}.box{max-height:calc(100svh - 20px)}.actions .btn{flex:1}.chatbar{align-items:stretch;flex-direction:column}.chatbar .btn{width:100%}.emailVerificationCard{padding:14px}.landingCta{border-radius:18px}}
'''

LANDING_ENHANCEMENTS=r'''
<section class="section"><div class="sectionIntro"><span class="ey">ВСЁ ПОД КОНТРОЛЕМ</span><h2>Понятный путь к реальной помощи</h2><p class="muted">Профиль, заявки, подбор и сообщения работают как единый сервис на сайте и в Telegram.</p></div><div class="landingMetrics"><div class="landingMetric"><b>01</b><span>Создайте заявку и укажите только нужные детали.</span></div><div class="landingMetric"><b>02</b><span>Выберите добровольца из общей живой очереди.</span></div><div class="landingMetric"><b>03</b><span>Помощник сам подтвердит участие до назначения.</span></div></div></section>
<section class="section"><div class="sectionIntro"><span class="ey">БЕЗОПАСНОСТЬ</span><h2>Контакты открываются только после взаимного решения</h2></div><div class="safetyGrid"><article class="safetyCard"><div class="safetyMark">✉</div><h3>Подтверждённый контакт</h3><p>Почтовый аккаунт активируется одноразовым кодом. Telegram-профиль подтверждается через бота.</p></article><article class="safetyCard"><div class="safetyMark">◎</div><h3>Адрес остаётся приватным</h3><p>В общей ленте виден только район. Детали доступны участникам после согласия на помощь.</p></article><article class="safetyCard"><div class="safetyMark">✓</div><h3>Помощь только по согласию</h3><p>Выбранный помощник подтверждает предложение сам. Чат появляется после его согласия.</p></article></div></section>
<section class="section"><div class="landingCta"><div><span class="ey">НАЧНИТЕ СЕЙЧАС</span><h2>Нужна помощь рядом или хотите помочь кому-то?</h2></div><button class="btn grad" onclick="authForm(true)">Создать защищённый профиль</button></div></section>
'''

ACCOUNT_SECURITY_UI=r'''
function passwordClientProblem(password){if(password.length<12||password.length>256)return 'Пароль должен быть от 12 до 256 символов.';if(!/[a-z]/.test(password)||!/[A-Z]/.test(password)||!/\d/.test(password))return 'Нужны строчная и заглавная латинские буквы, а также цифра.';return ''}
function updatePasswordHint(){let hint=$('passwordHint'),problem=passwordClientProblem($('ap')?.value||'');if(hint)hint.textContent=problem||'Пароль соответствует требованиям.'}
function authForm(reg){$('modal').style.display='flex';$('modalbody').innerHTML=reg?`<div class="authBrand"><img src="/assets/hpoint-logo.png" alt="H-Point"></div><h2>Создайте защищённый профиль</h2><p class="muted">Telegram сразу объединяет сайт с ботом. Для входа по email подтвердите почту кодом из письма.</p><div class="form"><button class="btn grad" onclick="telegramLogin()">Продолжить с Telegram</button><div class="muted" style="text-align:center">или по email</div><input id="an" class="input" maxlength="50" autocomplete="name" placeholder="Имя"><input id="ae" class="input" type="email" autocomplete="email" placeholder="Email"><input id="ap" class="input" type="password" autocomplete="new-password" placeholder="Придумайте пароль"><ul class="passwordRules"><li>от 12 до 256 символов</li><li>строчная и заглавная латинские буквы</li><li>хотя бы одна цифра</li></ul><input id="ap2" class="input" type="password" autocomplete="new-password" placeholder="Повторите пароль"><p id="passwordHint" class="muted passwordHint" aria-live="polite"></p><button class="btn light" onclick="register()">Создать аккаунт</button><div id="err" class="muted" aria-live="polite"></div></div>`:`<div class="authBrand"><img src="/assets/hpoint-logo.png" alt="H-Point"></div><h2>Войти в H·Point</h2><p class="muted">Войдите через Telegram или подтверждённый email.</p><div class="form"><button class="btn grad" onclick="telegramLogin()">Войти через Telegram</button><div class="muted" style="text-align:center">или по email</div><input id="ae" class="input" type="email" autocomplete="email" placeholder="Email"><input id="ap" class="input" type="password" autocomplete="current-password" placeholder="Пароль"><button class="btn light" onclick="login()">Войти</button><div id="err" class="muted" aria-live="polite"></div></div>`;if(reg){$('ap').addEventListener('input',updatePasswordHint);$('ap2').addEventListener('input',()=>{let err=$('err');if($('ap2').value&&$('ap').value!==$('ap2').value)err.textContent='Пароли пока не совпадают.';else err.textContent=''})}}
function showEmailVerification(){let modal=$('modal'),body=$('modalbody');modal.style.display='flex';body.innerHTML=`<div class="authBrand"><img src="/assets/hpoint-logo.png" alt="H-Point"></div><h2>Подтвердите email</h2><p class="muted">Мы отправили шестизначный код. Он действует 10 минут и используется один раз.</p><div class="form"><input id="emailCode" class="input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="Код из письма"><button class="btn grad" onclick="verifyEmailCode()">Подтвердить почту</button><button class="btn light" onclick="resendEmailCode()">Отправить новый код</button><div id="err" class="muted" aria-live="polite"></div></div>`}
async function register(){let password=$('ap').value,confirm=$('ap2').value,problem=passwordClientProblem(password);if(problem){$('err').textContent=problem;return}if(password!==confirm){$('err').textContent='Пароли не совпадают.';return}try{let d=await api('/api/auth/register',{method:'POST',body:JSON.stringify({name:$('an').value,email:$('ae').value,password:password,password_confirm:confirm})});await load();if(d.email_verification_sent){showEmailVerification();toast('Аккаунт создан: подтвердите почту кодом')}else{closeModal();toast('Аккаунт создан. Подтвердите email в профиле, когда отправка кодов будет доступна.')}}catch(e){$('err').textContent=e.message}}
async function verifyEmailCode(){try{await api('/api/auth/email/verify',{method:'POST',body:JSON.stringify({code:$('emailCode').value.trim()})});closeModal();toast('Email подтверждён');await syncTick();if(document.querySelector('.tab.active')?.dataset.t==='profile')await profile()}catch(e){$('err').textContent=e.message}}
async function resendEmailCode(){try{await api('/api/auth/email/resend',{method:'POST',body:'{}'});toast('Новый код отправлен')}catch(e){$('err').textContent=e.message}}
function emailVerificationCard(u){let card=$('emailState');if(!card){card=document.createElement('div');card.id='emailState';let anchor=$('profInfo');anchor.parentElement.insertBefore(card,anchor.nextSibling)}if(u.email_verified){card.className='emailVerificationCard';card.innerHTML='<span class="badge ok">✓ Email подтверждён</span><p class="muted">Почта подтверждена одноразовым кодом и может использоваться для входа.</p>';return}card.className='emailVerificationCard warn';let configured=u.email_delivery_configured;card.innerHTML='<span class="badge warn">Требуется подтверждение email</span><p class="muted">'+(configured?'Подтвердите код из письма, чтобы публиковать заявки и отвечать на них.':'Отправка кодов ещё не настроена. Можно сразу подтвердить профиль через Telegram.')+'</p><div class="profileActions">'+(configured?'<button class="btn grad" onclick="showEmailVerification()">Ввести код</button><button class="btn light" onclick="resendEmailCode()">Новый код</button>':'')+'</div>'}
async function profile(providedUser){let u=providedUser||(await api('/api/me')).user,linked=Boolean(u.tg_linked);$('pn').value=u.name||'';$('pc').value=u.city||'';$('pb').value=u.bio||'';$('profInfo').innerHTML=`<p><b>${esc(u.name)}</b></p><p class="muted">${esc(u.email||'')}<br>Рейтинг: ${u.stats.helped_avg?u.stats.helped_avg.toFixed(1):'—'} · ${u.stats.helped} помощей</p>`;emailVerificationCard(u);$('tgState').innerHTML=(linked?'<span class="badge ok">✓ Telegram привязан</span>':'<span class="badge warn">Telegram не привязан</span>')+(u.telegram_url?` <a class="btn light" href="${esc(u.telegram_url)}" target="_blank" rel="noopener">Перейти в Telegram</a>`:'');$('tgLinkButton').style.display=linked?'none':'';$('code').textContent=linked?'Подключено':u.link_code||'Код не создан';$('tgGuide').innerHTML=linked?'Сайт и бот используют один профиль. Входить можно одновременно с нескольких устройств; выход завершает только текущий сеанс.':'Получите код и отправьте в боте: <b>/link КОД</b>.';renderIdentityCard(u)}
'''

PASSWORD_CSS=r'''
.passwordRules li.bad{color:#ff6b6b;text-decoration:underline;text-decoration-color:#ff6b6b;text-decoration-thickness:2px;text-underline-offset:3px}.passwordRules li.bad:before{color:#ff6b6b}.passwordRules li.ok{color:#b8f36b}.passwordHint.bad{color:#ff6b6b!important}.passwordHint.good{color:#b8f36b!important}.passwordField{position:relative}.passwordField .input{padding-right:48px}.passwordToggle{position:absolute;right:8px;top:50%;transform:translateY(-50%);border:0;background:transparent;color:#a9afa1;cursor:pointer;font-size:18px;line-height:1;padding:7px}.passwordToggle:hover{color:#b8f36b}
'''

PASSWORD_UI_ENHANCEMENTS=r'''
function passwordChecks(password){return {length:password.length>=6&&password.length<=256,lower:/[a-z]/.test(password),upper:/[A-Z]/.test(password),digit:/\d/.test(password)}}
function passwordClientProblem(password){let c=passwordChecks(password);if(!c.length)return 'Пароль должен быть от 6 до 256 символов.';if(!c.lower||!c.upper||!c.digit)return 'Нужны строчная и заглавная латинские буквы, а также цифра.';return ''}
function updatePasswordHint(){let password=$('ap')?.value||'',checks=passwordChecks(password),items=document.querySelectorAll('#passwordRules li');items.forEach(item=>{let key=item.dataset.rule;item.classList.toggle('ok',Boolean(checks[key]));item.classList.toggle('bad',Boolean(password)&&!checks[key])});let hint=$('passwordHint');if(hint){let problem=passwordClientProblem(password);hint.textContent=password?(problem||'Пароль соответствует требованиям.'):'Введите пароль по требованиям ниже.';hint.className='passwordHint '+(password&&!problem?'good':password?'bad':'')}}
function togglePassword(id,button){let input=$(id),visible=input.type==='text';input.type=visible?'password':'text';button.textContent=visible?'👁️':'🙈';button.setAttribute('aria-label',visible?'Показать пароль':'Скрыть пароль')}
function decoratePasswordInput(id,autocomplete){let input=$(id);if(!input)return;let wrap=document.createElement('div');wrap.className='passwordField';input.parentNode.insertBefore(wrap,input);wrap.appendChild(input);let button=document.createElement('button');button.type='button';button.className='passwordToggle';button.textContent='👁️';button.setAttribute('aria-label','Показать пароль');button.onclick=()=>togglePassword(id,button);wrap.appendChild(button);input.autocomplete=autocomplete}
function passwordRulesMarkup(){return '<ul id="passwordRules" class="passwordRules"><li data-rule="length">от 6 до 256 символов</li><li data-rule="lower">строчная латинская буква</li><li data-rule="upper">заглавная латинская буква</li><li data-rule="digit">хотя бы одна цифра</li></ul>'}
const originalAuthForm=authForm;
function authForm(reg){originalAuthForm(reg);let body=$('modalbody'),rules=body.querySelector('.passwordRules');if(rules){rules.id='passwordRules';rules.innerHTML='<li data-rule="length">от 6 до 256 символов</li><li data-rule="lower">строчная латинская буква</li><li data-rule="upper">заглавная латинская буква</li><li data-rule="digit">хотя бы одна цифра</li>'}else{let input=$('ap');if(input){input.insertAdjacentHTML('afterend',passwordRulesMarkup());input.insertAdjacentHTML('afterend','<p id="passwordHint" class="muted passwordHint" aria-live="polite">Введите пароль по требованиям ниже.</p>')}}decoratePasswordInput('ap','current-password');if(reg)decoratePasswordInput('ap2','new-password');let input=$('ap');if(input)input.addEventListener('input',updatePasswordHint);updatePasswordHint()}
'''

def _page_replace(needle, replacement):
    global PAGE
    if needle not in PAGE:
        raise RuntimeError("H-Point page template changed; UI override target is missing")
    PAGE=PAGE.replace(needle, replacement, 1)

_page_replace("</style></head>", BRAND_CSS+REFERENCE_CSS+SOFT_CSS+SECURITY_CSS+PASSWORD_CSS+"</style></head>")
_page_replace("<title>H·Point — помощь рядом</title>", '<title>H·Point — помощь рядом</title><link rel="icon" type="image/svg+xml" href="/assets/favicon.svg"><link rel="apple-touch-icon" href="/assets/hpoint-logo.png"><link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700;800&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">')
_page_replace('<div class="logo">H·Point<b>.</b></div>', '<a class="logo brandLogo" href="/" aria-label="H-Point"><img src="/assets/hpoint-logo-dark.png" alt="H-Point"></a>')
_page_replace("<h1>Хорошие дела<br>начинаются рядом.</h1>", "<h1>Хорошие дела<br><span>начинаются рядом.</span></h1>")
_page_replace('</section></main>\n<main id="app"', '</section>'+LANDING_ENHANCEMENTS+'</main>\n<main id="app"')
_page_replace("load();\n</script></body></html>", UI_OVERRIDES+ACCOUNT_UI_OVERRIDES+FUNCTIONAL_FIXES+CONSENT_MATCH_UI+ACCOUNT_SECURITY_UI+PASSWORD_UI_ENHANCEMENTS+"\nresumeTelegramLogin();\nload();\n</script></body></html>")

class Handler(BaseHTTPRequestHandler):
    server_version="HPointWeb/3.0"
    def finish(self):
        try:
            super().finish()
        finally:
            if isinstance(database.db, (database.SQLiteConnection, database.PostgresConnection)):
                database.db.close()
    def log_message(self,f,*a): print(f"[WEB] {self.command} {urlparse(self.path).path} {a[3] if len(a)>3 else '-'}")
    def _text(self,text,status=200):
        b=text.encode("utf-8");self.send_response(status);self.send_header("Content-Type","text/plain;charset=utf-8");self.send_header("X-Content-Type-Options","nosniff");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def asset(self,name):
        item=ASSETS.get(name)
        if not item or not item[0].is_file():
            self.send_error(404);return
        body=item[0].read_bytes()
        self.send_response(200);self.send_header("Content-Type",item[1]);self.send_header("X-Content-Type-Options","nosniff");self.send_header("Cache-Control","public, max-age=604800, immutable");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def html(self):
        b=PAGE.replace("__YANDEX_MAPS_API_KEY__", YANDEX_MAPS_API_KEY).encode();self.send_response(200);self.send_header("Content-Type","text/html;charset=utf-8");self.send_header("X-Content-Type-Options","nosniff");self.send_header("X-Frame-Options","DENY");self.send_header("Referrer-Policy","same-origin");self.send_header("Content-Security-Policy",CSP);self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
    def do_HEAD(self):
        """Serve metadata for public resources without a response body."""
        p = urlparse(self.path)
        if p.path.startswith("/assets/"):
            item = ASSETS.get(p.path.rsplit("/", 1)[-1])
            if not item or not item[0].is_file():
                self.send_error(404)
                return
            self.send_response(200);self.send_header("Content-Type",item[1]);self.send_header("X-Content-Type-Options","nosniff");self.send_header("Cache-Control","public, max-age=604800, immutable");self.send_header("Content-Length",str(item[0].stat().st_size));self.end_headers()
            return
        if p.path in ("/", "/index.html", "/payment/result"):
            size = len(PAGE.replace("__YANDEX_MAPS_API_KEY__", YANDEX_MAPS_API_KEY).encode())
            self.send_response(200);self.send_header("Content-Type","text/html;charset=utf-8");self.send_header("X-Content-Type-Options","nosniff");self.send_header("X-Frame-Options","DENY");self.send_header("Referrer-Policy","same-origin");self.send_header("Content-Security-Policy",CSP);self.send_header("Content-Length",str(size));self.end_headers()
            return
        if p.path == "/api/health":
            b = json.dumps({"ok":True,"database":True}).encode()
            self.send_response(200);self.send_header("Content-Type","application/json;charset=utf-8");self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff");self.send_header("Content-Length",str(len(b)));self.end_headers()
            return
        self.send_response(405);self.send_header("Allow","GET, POST, HEAD");self.send_header("Content-Length","0");self.end_headers()
    def do_GET(self):
        p=urlparse(self.path)
        try:
            if p.path.startswith("/assets/"):
                return self.asset(p.path.rsplit("/",1)[-1])
            if p.path=="/auth/telegram":
                ticket=parse_qs(p.query).get("ticket",[""])[0]
                uid=database.consume_web_login_ticket(ticket)
                if uid is None:return self._text("Ссылка входа недействительна или устарела.",403)
                headers=session_headers(self, uid)
                self.send_response(303);self.send_header("Location","/")
                for cookie in headers["Set-Cookie"]: self.send_header("Set-Cookie",cookie)
                self.send_header("Cache-Control","no-store");self.end_headers()
                return
            if p.path in ("/","/index.html","/payment/result"): return self.html()
            if p.path=="/api/health": return reply(self,{"ok":True,"database":True})
            if p.path=="/api/auth/telegram/complete":
                ticket=parse_qs(p.query).get("ticket",[""])[0]
                uid=database.consume_telegram_auth_ticket(ticket)
                if uid is None:return reply(self,{"ok":False,"pending":True},202)
                return reply(self,{"ok":True},headers=session_headers(self, uid))
            if p.path=="/api/admin/summary":
                if not admin_auth(self): return
                return reply(self,{"ok":True,"summary":admin_summary()})
            if p.path=="/api/me":
                u=auth(self)
                if not u:return
                return reply(self,{"ok":True,"user":user_payload(u)})
            if p.path=="/api/dashboard":
                u=auth(self)
                if not u:return
                return reply(self,{"ok":True,"user":user_payload(u)})
            if p.path=="/api/sync":
                u=auth(self)
                if not u:return
                rs=get_history(u["user_id"],HISTORY_LIMIT)
                return reply(self,{"ok":True,"user":user_payload(u),"current_user_id":u["user_id"],"requests":[request_payload(r) for r in rs]})
            if p.path=="/api/requests/mine":
                u=auth(self)
                if not u:return
                rs=get_history(u["user_id"],HISTORY_LIMIT)
                return reply(self,{"ok":True,"current_user_id":u["user_id"],"requests":[request_payload(r) for r in rs]})
            if p.path=="/api/helper/offers":
                u=auth(self)
                if not u:return
                return reply(self,{"ok":True,"offers":[dict(row) for row in get_helper_offers(u["user_id"])]})
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
                return reply(self,{"ok":True,"requests":[public_request_payload(r) for r in out[:30]]})
            if p.path=="/api/requests":
                u=auth(self)
                if not u:return
                if parse_qs(p.query).get("open",[""])[0]:
                    rs=db.execute("SELECT * FROM requests WHERE status=? AND requester_id!=? ORDER BY priority_boost DESC,created_at DESC LIMIT 100",(STATUS_OPEN,u["user_id"])).fetchall()
                    return reply(self,{"ok":True,"requests":[public_request_payload(r) for r in rs]})
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
                    try:rid=int(q)
                    except (TypeError,ValueError):return reply(self,{"ok":False,"error":"Некорректный request_id"},400)
                    c=db.execute("SELECT * FROM chats WHERE request_id=? AND (user_a_id=? OR user_b_id=?)",(rid,u["user_id"],u["user_id"])).fetchone()
                    if not c:return reply(self,{"ok":True,"chats":[]})
                    msgs=db.execute("SELECT m.*,u.name author_name FROM chat_messages m JOIN users u ON u.user_id=m.user_id WHERE m.chat_id=? ORDER BY m.id DESC LIMIT 100",(c["id"],)).fetchall()[::-1]
                    other=get_user(c["user_b_id"] if c["user_a_id"]==u["user_id"] else c["user_a_id"])
                    return reply(self,{"ok":True,"chats":[{"request_id":rid,"other_name":other["name"] if other else "Пользователь","messages":[{**dict(m),"mine":m["user_id"]==u["user_id"]} for m in msgs]}]})
                cs=db.execute("SELECT c.*,r.what,u.name other_name,(SELECT text FROM chat_messages m WHERE m.chat_id=c.id ORDER BY m.id DESC LIMIT 1) last_message FROM chats c JOIN requests r ON r.id=c.request_id JOIN users u ON u.user_id=CASE WHEN c.user_a_id=? THEN c.user_b_id ELSE c.user_a_id END WHERE c.user_a_id=? OR c.user_b_id=? ORDER BY c.id DESC",(u["user_id"],u["user_id"],u["user_id"])).fetchall()
                return reply(self,{"ok":True,"chats":[dict(c) for c in cs]})
            if p.path=="/api/billing":
                u=auth(self)
                if not u:return
                return reply(self,{"ok":True,"user":user_payload(u),"history":[dict(x) for x in database.get_billing_history(u["user_id"]) ]})
            if p.path=="/api/profiles":
                u=auth(self)
                if not u:return
                device=cookie_value(self,"hpoint_device")
                if not device:return reply(self,{"ok":True,"profiles":[{"id":u["user_id"],"name":u["name"],"active":True}]})
                rows=db.execute("""SELECT s.user_id,u.name,u.email,MAX(s.created_at) created_at
                    FROM sessions s JOIN users u ON u.user_id=s.user_id
                    WHERE s.device_id=? AND s.expires_at>? GROUP BY s.user_id,u.name,u.email ORDER BY created_at DESC""",(device,now().isoformat())).fetchall()
                return reply(self,{"ok":True,"profiles":[{"id":r["user_id"],"name":r["name"],"email":r["email"],"active":r["user_id"]==u["user_id"]} for r in rows]})
            self.send_error(404)
        except Exception:
            logging.exception("Web request failed: %s", p.path)
            reply(self,{"ok":False,"error":"Внутренняя ошибка сервера"},500)
    def do_POST(self):
        p=urlparse(self.path)
        if p.path=="/api/payments/robokassa/result":
            try:
                try:length=int(self.headers.get("Content-Length","0"))
                except ValueError:return self._text("invalid callback body",400)
                if length < 0 or length > MAX_PAYMENT_BODY:return self._text("invalid callback body",413)
                raw=self.rfile.read(length).decode("utf-8")
                fields={k:v[0] for k,v in parse_qs(raw,keep_blank_values=True).items()}
                inv=verify_robokassa_result(fields)
                if not inv: return self._text("bad signature or invoice",400)
                ok,result=fulfill_invoice(inv["id"],str(inv["id"]))
                if not ok: return self._text("invoice not processed",409)
                return self._text("OK"+str(inv["id"]))
            except Exception:
                logging.exception("Payment callback failed")
                return self._text("payment callback failed",500)
        if not valid_origin(self): return reply(self,{"ok":False,"error":"invalid_origin"},403)
        try:d=read(self)
        except:return reply(self,{"ok":False,"error":"Некорректный JSON"},400)
        try:
            if p.path=="/api/auth/telegram/start":
                if not _telegram_username:return reply(self,{"ok":False,"error":"telegram_login_unavailable"},503)
                subject=client_key(self)
                if database.auth_is_rate_limited("telegram_start",subject,AUTH_ATTEMPT_LIMIT):return reply(self,{"ok":False,"error":"too_many_attempts"},429)
                ticket=secrets.token_urlsafe(32)
                database.create_telegram_auth_ticket(ticket)
                database.record_auth_failure("telegram_start",subject)
                return reply(self,{"ok":True,"ticket":ticket,"bot_url":f"https://t.me/{_telegram_username}?start=login_{ticket}"})
            if p.path=="/api/auth/register":
                n=str(d.get("name","")).strip();e=str(d.get("email","")).strip().lower();pw=str(d.get("password",""));confirm=str(d.get("password_confirm",""))
                subject=client_key(self)
                if database.auth_is_rate_limited("register",e,AUTH_ATTEMPT_LIMIT) or database.auth_is_rate_limited("register_ip",subject,AUTH_ATTEMPT_LIMIT):return reply(self,{"ok":False,"error":"too_many_attempts"},429)
                if not 2<=len(n)<=MAX_NAME_LEN:return reply(self,{"ok":False,"error":"Имя должно быть от 2 до 50 символов."},400)
                if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+",e):return reply(self,{"ok":False,"error":"Введите корректный email."},400)
                if pw!=confirm:return reply(self,{"ok":False,"error":"Пароли не совпадают."},400)
                problem=password_error(pw)
                if problem:return reply(self,{"ok":False,"error":problem},400)
                if get_user_by_email(e):
                    database.record_auth_failure("register",e);database.record_auth_failure("register_ip",subject)
                    return reply(self,{"ok":False,"error":"Не удалось создать аккаунт с этим email."},409)
                try:
                    uid=create_web_user(n,e,ph(pw));c=database.create_link_code(uid)
                except Exception:
                    logging.exception("Registration could not be completed")
                    database.record_auth_failure("register",e);database.record_auth_failure("register_ip",subject)
                    return reply(self,{"ok":False,"error":"Не удалось создать аккаунт с этим email."},409)
                sent=False
                if email_delivery_configured():
                    code=database.create_email_verification_code(uid)
                    sent=send_email_verification_code(e,code)
                database.clear_auth_failures("register",e);database.clear_auth_failures("register_ip",subject)
                return reply(self,{"ok":True,"link_code":c,"email_verification_sent":sent,"email_delivery_configured":email_delivery_configured()},headers=session_headers(self,uid))
            if p.path=="/api/auth/login":
                email=str(d.get("email","")).strip().lower()
                subject=client_key(self)
                if database.auth_is_rate_limited("login",email,AUTH_ATTEMPT_LIMIT) or database.auth_is_rate_limited("login_ip",subject,AUTH_ATTEMPT_LIMIT):return reply(self,{"ok":False,"error":"too_many_attempts"},429)
                u=get_user_by_email(email)
                if not u or not u["password_hash"] or not pv(str(d.get("password","")),u["password_hash"]):
                    database.record_auth_failure("login",email);database.record_auth_failure("login_ip",subject)
                    return reply(self,{"ok":False,"error":"Неверный email или пароль."},401)
                if u["is_blocked"]:return reply(self,{"ok":False,"error":"Аккаунт заблокирован."},403)
                database.clear_auth_failures("login",email);database.clear_auth_failures("login_ip",subject)
                if password_needs_upgrade(u["password_hash"]):db.execute("UPDATE users SET password_hash=? WHERE user_id=?",(ph(str(d.get("password",""))),u["user_id"]))
                return reply(self,{"ok":True},headers=session_headers(self,u["user_id"]))
            if p.path=="/api/auth/email/resend":
                u=auth(self)
                if not u:return
                if u["email_verified"]:return reply(self,{"ok":True,"already_verified":True})
                if not u["email"]:return reply(self,{"ok":False,"error":"В профиле нет email для подтверждения."},409)
                if not email_delivery_configured():return reply(self,{"ok":False,"error":"Отправка кодов временно не настроена."},503)
                if database.auth_is_rate_limited("email_resend",str(u["user_id"]),3):return reply(self,{"ok":False,"error":"Слишком много кодов. Повторите позже."},429)
                code=database.create_email_verification_code(u["user_id"])
                if not send_email_verification_code(u["email"],code):return reply(self,{"ok":False,"error":"Не удалось отправить код. Повторите позже."},503)
                database.record_auth_failure("email_resend",str(u["user_id"]))
                return reply(self,{"ok":True,"sent":True})
            if p.path=="/api/auth/email/verify":
                u=auth(self)
                if not u:return
                subject=str(u["user_id"])+":"+client_key(self)
                if database.auth_is_rate_limited("email_verify",subject,5):return reply(self,{"ok":False,"error":"Слишком много попыток. Запросите новый код."},429)
                ok,status=database.verify_email_code(u["user_id"],str(d.get("code","")).strip())
                if not ok:
                    database.record_auth_failure("email_verify",subject)
                    messages={"expired":"Код истёк. Запросите новый.","too_many_attempts":"Слишком много попыток. Запросите новый код.","invalid":"Неверный код."}
                    return reply(self,{"ok":False,"error":messages.get(status,"Не удалось подтвердить email.")},400)
                database.clear_auth_failures("email_verify",subject)
                return reply(self,{"ok":True,"verified":True})
            if p.path=="/api/auth/logout":
                c=self.headers.get("Cookie","");t=next((x.strip().split("=",1)[1] for x in c.split(";") if x.strip().startswith("hpoint_session=")),None)
                if t:db.execute("DELETE FROM sessions WHERE token=?",(t,))
                return reply(self,{"ok":True},headers={"Set-Cookie":session_cookie("", 0)})
            if p.path=="/api/profiles/switch":
                u=auth(self)
                if not u:return
                try: target=int(d.get("user_id"))
                except (TypeError,ValueError):return reply(self,{"ok":False,"error":"Некорректный профиль."},400)
                device=cookie_value(self,"hpoint_device")
                row=db.execute("SELECT 1 FROM sessions WHERE user_id=? AND device_id=? AND expires_at>? LIMIT 1",(target,device,now().isoformat())).fetchone() if device else None
                if not row:return reply(self,{"ok":False,"error":"Этот профиль недоступен на устройстве."},403)
                return reply(self,{"ok":True},headers=session_headers(self,target))
            if p.path=="/api/profile/telegram/unlink":
                u=auth(self)
                if not u:return
                new_id=database.detach_telegram_to_web_profile(u["user_id"])
                if new_id is None:return reply(self,{"ok":False,"error":"Telegram уже не привязан."},409)
                return reply(self,{"ok":True},headers=session_headers(self,new_id))
            if p.path=="/api/auth/link-code":
                u=auth(self)
                if not u:return
                c=database.create_link_code(u["user_id"]);return reply(self,{"ok":True,"code":c})
            if p.path=="/api/profile":
                u=auth(self)
                if not u:return
                n=str(d.get("name",u["name"])).strip()[:MAX_NAME_LEN];city=str(d.get("city","")).strip()[:80];bio=str(d.get("bio","")).strip()[:500]
                if len(n)<2:return reply(self,{"ok":False,"error":"Имя слишком короткое."},400)
                db.execute("UPDATE users SET name=?,city=?,bio=? WHERE user_id=?",(n,city,bio,u["user_id"]));return reply(self,{"ok":True})
            if p.path=="/api/identity-verification":
                u=auth(self)
                if not u:return
                ok,status=database.request_identity_verification(u["user_id"])
                if not ok:
                    return reply(self,{"ok":False,"error":"Сначала привяжите Telegram к профилю."},409)
                return reply(self,{"ok":True,"status":status})
            if p.path=="/api/admin/users/block":
                admin = admin_auth(self)
                if not admin:return
                try: target_id=int(d["user_id"])
                except (KeyError,TypeError,ValueError):return reply(self,{"ok":False,"error":"Некорректный пользователь."},400)
                blocked=bool(d.get("blocked",True))
                if target_id==admin["user_id"]:return reply(self,{"ok":False,"error":"Нельзя изменить свой доступ."},400)
                if not set_user_blocked(admin["user_id"],target_id,blocked,str(d.get("reason", ""))):return reply(self,{"ok":False,"error":"Пользователь не найден."},404)
                return reply(self,{"ok":True})
            if p.path=="/api/requests":
                u=auth(self)
                if not u:return
                if not verified_community_account(self,u):return
                if get_active_own_request(u["user_id"]):return reply(self,{"ok":False,"error":"У вас уже есть активная заявка."},409)
                if u["balance"]<REQUEST_COST:return reply(self,{"ok":False,"error":f"Нужно {REQUEST_COST} HP."},400)
                f={k:str(d.get(k,"" )).strip() for k in ("what","place","time_needed","urgency","details")}
                if not all(f.values()):return reply(self,{"ok":False,"error":"Заполните все поля."},400)
                if any(len(value)>MAX_TEXT_LEN for value in f.values()):return reply(self,{"ok":False,"error":f"Каждое поле должно быть не длиннее {MAX_TEXT_LEN} символов."},400)
                try:lat=float(d["lat"]) if d.get("lat") is not None else None;lon=float(d["lon"]) if d.get("lon") is not None else None
                except:lat=lon=None
                f["category"]=str(d.get("category","other"))
                if f["category"] not in CATEGORIES:return reply(self,{"ok":False,"error":"Некорректная категория."},400)
                if (lat is None) != (lon is None) or (lat is not None and not (-90<=lat<=90 and -180<=lon<=180)):return reply(self,{"ok":False,"error":"Некорректные координаты."},400)
                rid=create_request(u["user_id"],{**f,"lat":lat,"lon":lon})
                req=get_request(rid)
                if u["tg_user_id"]:
                    notify_telegram_user(
                        u["tg_user_id"],
                        f"🆕 На сайте создана заявка №{rid}: {escape(req['what'])}\n"
                        "Откройте в H-Point «⚡ Подобрать кандидатов», выберите человека из очереди — он сам подтвердит согласие.",
                    )
                return reply(self,{"ok":True,"request_id":rid,"matched":False})
            if p.path=="/api/helper/queue":
                u=auth(self)
                if not u:return
                if not verified_community_account(self,u):return
                if get_active_own_request(u["user_id"]):
                    return reply(self,{"ok":False,"error":"Сначала завершите или отмените свою активную заявку."},409)
                if get_active_help(u["user_id"]):
                    return reply(self,{"ok":False,"error":"Сначала завершите текущую помощь."},409)
                add_to_queue(u["user_id"])
                return reply(self,{"ok":True,"matched":False,"message":"Вы в общей очереди помощников. Когда вас выберут, вы сами подтвердите или отклоните предложение."})
            if p.path=="/api/requests/accept":
                u=auth(self)
                if not u:return
                if not verified_community_account(self,u):return
                try: rid=int(d.get("request_id"))
                except (TypeError,ValueError):return reply(self,{"ok":False,"error":"Некорректная заявка."},400)
                request=get_request(rid)
                if not request or request["status"]!=STATUS_OPEN or request["requester_id"]==u["user_id"]:
                    return reply(self,{"ok":False,"error":"Эта заявка недоступна."},409)
                if get_active_own_request(u["user_id"]):
                    return reply(self,{"ok":False,"error":"Сначала завершите или отмените свою активную заявку."},409)
                if get_active_help(u["user_id"]):
                    return reply(self,{"ok":False,"error":"Сначала завершите текущую помощь."},409)
                add_to_queue(u["user_id"])
                return reply(self,{"ok":True,"request_id":rid,"queued":True,"message":"Вы в очереди помощников. Автор заявки сам выберет кандидата."})
            if p.path=="/api/assistant/candidates":
                u=auth(self)
                if not u:return
                if not verified_community_account(self,u):return
                try: rid=int(d["request_id"])
                except (KeyError,TypeError,ValueError):return reply(self,{"ok":False,"error":"Некорректная заявка."},400)
                request=get_request(rid)
                if not request or request["requester_id"]!=u["user_id"] or request["status"]!=STATUS_OPEN:
                    return reply(self,{"ok":False,"error":"Подбор доступен только для вашей открытой заявки."},403)
                question=str(d.get("question", "")).strip()[:MAX_TEXT_LEN]
                offer=get_current_helper_offer(rid)
                return reply(self,{"ok":True,"matches":smart_match(rid,query=question),"offer":dict(offer) if offer else None})
            if p.path=="/api/smart-match/assign":
                u=auth(self)
                if not u:return
                if not verified_community_account(self,u):return
                try:rid=int(d["request_id"]);hid=int(d["helper_id"])
                except (KeyError,TypeError,ValueError):return reply(self,{"ok":False,"error":"Некорректные данные."},400)
                r=get_request(rid)
                if not r or r["requester_id"]!=u["user_id"] or r["status"]!=STATUS_OPEN:return reply(self,{"ok":False,"error":"Недоступно."},403)
                if not offer_helper(rid,hid):return reply(self,{"ok":False,"error":"Кандидат уже занят, вышел из очереди или заявка изменилась."},409)
                candidate=get_user(hid)
                if candidate and candidate["tg_user_id"]:
                    from .keyboards import helper_offer_kb
                    notify_telegram_user(
                        candidate["tg_user_id"],
                        f"🤝 <b>Вас выбрали как помощника</b>\n\n"
                        f"Заявка №{rid}: {escape(r['what'])}\n"
                        f"Где: {escape(r['place'])}\nКогда: {escape(r['time_needed'])}\n\n"
                        "Подтвердите, что готовы помочь. До вашего согласия заявка никому не назначена.",
                        reply_markup=helper_offer_kb(rid),
                    )
                return reply(self,{"ok":True,"offered":True})
            if p.path=="/api/helper/offers/respond":
                u=auth(self)
                if not u:return
                if not verified_community_account(self,u):return
                try:rid=int(d["request_id"])
                except (KeyError,TypeError,ValueError):return reply(self,{"ok":False,"error":"Некорректная заявка."},400)
                accept=d.get("accept")
                if not isinstance(accept,bool):return reply(self,{"ok":False,"error":"Некорректный ответ."},400)
                if not respond_to_helper_offer(rid,u["user_id"],accept):
                    return reply(self,{"ok":False,"error":"Предложение уже неактуально."},409)
                request=get_request(rid)
                if accept:
                    chat_for_request(rid)
                    requester=get_user(request["requester_id"])
                    if requester and requester["tg_user_id"]:
                        notify_telegram_user(requester["tg_user_id"],f"🎉 Помощник подтвердил заявку №{rid}. Чат уже создан.")
                else:
                    requester=get_user(request["requester_id"])
                    if requester and requester["tg_user_id"]:
                        notify_telegram_user(requester["tg_user_id"],f"ℹ️ Помощник отклонил предложение по заявке №{rid}. Выберите другого кандидата.")
                return reply(self,{"ok":True,"accepted":accept,"request_id":rid})
            if p.path=="/api/requests/finish":
                u=auth(self)
                if not u:return
                if not verified_community_account(self,u):return
                try:rid=int(d["request_id"])
                except (KeyError,TypeError,ValueError):return reply(self,{"ok":False,"error":"Некорректная заявка."},400)
                if not complete_request(rid,u["user_id"]):return reply(self,{"ok":False,"error":"Завершить может только назначенный помощник."},409)
                return reply(self,{"ok":True})
            if p.path=="/api/reviews":
                u=auth(self)
                if not u:return
                if not verified_community_account(self,u):return
                try:rid=int(d["request_id"]);rating=int(d["rating"])
                except (KeyError,TypeError,ValueError):return reply(self,{"ok":False,"error":"Некорректная оценка."},400)
                side=str(d.get("side", ""))
                ok=set_rating(rid,u["user_id"],rating) if side=="requester" else set_helper_rating(rid,u["user_id"],rating) if side=="helper" else False
                if not ok:return reply(self,{"ok":False,"error":"Оценка уже поставлена или недоступна."},409)
                review=str(d.get("review","")).strip()[:MAX_TEXT_LEN]
                if review:set_review(rid,u["user_id"],review,side)
                return reply(self,{"ok":True})
            if p.path=="/api/chats/send":
                u=auth(self)
                if not u:return
                if not verified_community_account(self,u):return
                try:rid=int(d["request_id"])
                except (KeyError,TypeError,ValueError):return reply(self,{"ok":False,"error":"Некорректный request_id."},400)
                text=str(d.get("text","")).strip()[:1000]
                if not text:return reply(self,{"ok":False,"error":"Сообщение пустое."},400)
                cid=chat_for_request(rid)
                if not cid:return reply(self,{"ok":False,"error":"Чат доступен после назначения помощника."},409)
                c=db.execute("SELECT * FROM chats WHERE id=? AND (user_a_id=? OR user_b_id=?)",(cid,u["user_id"],u["user_id"])).fetchone()
                if not c:return reply(self,{"ok":False,"error":"Нет доступа к чату."},403)
                db.execute("INSERT INTO chat_messages(chat_id,user_id,text) VALUES(?,?,?)",(cid,u["user_id"],text))
                other=get_user(c["user_b_id"] if c["user_a_id"]==u["user_id"] else c["user_a_id"])
                if other and other["tg_user_id"]:
                    notify_telegram_user(other["tg_user_id"],f"💬 Новое сообщение по заявке №{rid} от {escape(u['name'])}. Откройте сайт H-Point или ответьте в боте: /chat ТЕКСТ")
                msgs=db.execute("SELECT m.*,u.name author_name FROM chat_messages m JOIN users u ON u.user_id=m.user_id WHERE m.chat_id=? ORDER BY m.id DESC LIMIT 100",(cid,)).fetchall()[::-1]
                return reply(self,{"ok":True,"messages":[{**dict(m),"mine":m["user_id"]==u["user_id"]} for m in msgs]})
            if p.path=="/api/payments/create":
                u=auth(self)
                if not u:return
                item=str(d.get("item_type",""));meta=d.get("metadata") or {}
                if item=="verification" and not u["tg_user_id"]:
                    return reply(self,{"ok":False,"error":"Для проверки личности сначала привяжите Telegram."},409)
                if item in ("boost","more_responses"):
                    try:meta["request_id"]=int(d.get("request_id") or meta.get("request_id") or 0)
                    except:meta["request_id"]=0
                    if not meta["request_id"]:return reply(self,{"ok":False,"error":"Для этой функции нужна заявка."},400)
                if item=="ad" and d.get("ad_text"):meta["ad_text"]=str(d["ad_text"])[:MAX_TEXT_LEN]
                try:i,_,_=create_pending_invoice(u["user_id"],item,meta);url,pid=create_payment(i)
                except Exception:
                    logging.exception("Payment initialization failed")
                    return reply(self,{"ok":False,"error":"Платёжный сервис временно недоступен."},503)
                return reply(self,{"ok":True,"invoice_id":i,"confirmation_url":url,"payment_id":pid})
            if p.path=="/api/payments/hp":
                u=auth(self)
                if not u:return
                item=str(d.get("item_type", ""));meta=d.get("metadata") or {}
                if item in ("boost","more_responses"):
                    try: meta["request_id"]=int(d.get("request_id") or meta.get("request_id") or 0)
                    except (TypeError,ValueError): meta["request_id"]=0
                if item=="ad" and d.get("ad_text"): meta["ad_text"]=str(d["ad_text"])[:MAX_TEXT_LEN]
                try:
                    invoice_id,created=purchase_with_points(u["user_id"],item,meta,d.get("purchase_key"))
                except ValueError as exc:
                    errors={"insufficient_points":"Недостаточно H-Points.","request_id required":"Для этой функции нужна открытая заявка.","request is unavailable":"Заявка недоступна для продвижения.","telegram link required":"Сначала привяжите Telegram.","ad_text required":"Введите текст объявления."}
                    return reply(self,{"ok":False,"error":errors.get(str(exc),"Не удалось выполнить покупку.")},409)
                return reply(self,{"ok":True,"invoice_id":invoice_id,"created":created,"balance":get_user(u["user_id"])["balance"]})
            self.send_error(404)
        except Exception:
            logging.exception("Web request failed: %s", p.path)
            reply(self,{"ok":False,"error":"Внутренняя ошибка сервера"},500)

def create_server():
    database.init_db()
    return ThreadingHTTPServer((WEB_HOST, WEB_PORT), Handler)

def run():
    s=create_server();print(f"H-Point website: http://{WEB_HOST}:{WEB_PORT}")
    try:s.serve_forever()
    finally:s.server_close()
if __name__=="__main__":run()
