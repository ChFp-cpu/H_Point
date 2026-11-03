"""Prepare a new, isolated, explicitly synthetic pitch demonstration.

Never loads .env, accepts a database URL/path, resets an existing database or
binds an external interface. Every invocation creates a fresh local directory.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
from pathlib import Path
import secrets
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def configure(port):
    if os.environ.get("DATABASE_URL", "").strip() or os.environ.get("APP_ENV", "").strip().lower() in {"prod", "production"}:
        raise ValueError("Демо запрещено при DATABASE_URL или APP_ENV=production. Запустите в отдельном локальном терминале.")
    if not 1024 <= port <= 65535:
        raise ValueError("Порт должен быть от 1024 до 65535.")
    base = ROOT / ".pitch-demo"
    base.mkdir(exist_ok=True)
    # A symlink/junction must not redirect writes outside the repository.
    if base.resolve().parent != ROOT.resolve():
        raise ValueError("Папка демо должна находиться внутри репозитория.")
    folder = base / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:10])
    folder.mkdir(exist_ok=False)
    env = dict(DB_PATH=str(folder / "demo.sqlite3"), DATABASE_URL="", APP_ENV="development",
               WEB_HOST="127.0.0.1", WEB_PORT=str(port), WEB_PUBLIC_URL=f"http://127.0.0.1:{port}",
               BOT_TOKEN="", BOT_USERNAME="", RUN_TELEGRAM_BOT="0", SESSION_COOKIE_SECURE="0",
               SMTP_HOST="", SMTP_USERNAME="", SMTP_PASSWORD="", BREVO_API_KEY="",
               ROBOKASSA_MERCHANT_LOGIN="", ROBOKASSA_PASSWORD_1="", ROBOKASSA_PASSWORD_2="",
               DONATION_URL="", YANDEX_MAPS_API_KEY="", GAMES_ENABLED="0",
               ADMIN_TELEGRAM_IDS="", REGISTRATION_BONUS_RUB="10000", TRUST_PROXY_HEADERS="0")
    os.environ.update(env)
    return folder


def seed(folder):
    from hpoint import commercial as c, commercial_team as team, database, pilot_analytics, services, web, work_inquiries
    database.init_db()
    db = database.db
    password = "Demo-" + secrets.token_urlsafe(12)
    users = {}
    for role, name in (("author", "Анна · демо"), ("helper", "Илья · демо"),
                       ("owner", "Мария · демо"), ("member", "Алексей · демо"), ("admin", "Администратор · демо")):
        email = role + "@example.test"
        uid = database.create_web_user(name, email, web.ph(password))
        db.execute("UPDATE users SET email_verified=1,web_verified=1,city='Демонстрационный район' WHERE user_id=?", (uid,))
        users[role] = {"id": uid, "email": email}
    admin, owner, author, helper, member = (users[k]["id"] for k in ("admin", "owner", "author", "helper", "member"))
    db.execute("UPDATE users SET role='admin' WHERE user_id=?", (admin,))
    for user in users.values():
        pilot_analytics.set_cohort(db, admin, {"user_id": user["id"], "cohort": "demo"})
    now = datetime.now(timezone.utc)
    db.execute("UPDATE users SET pro_until=? WHERE user_id IN (?,?)", ((now + timedelta(days=30)).isoformat(), author, helper))
    c.save_profile(db, owner, {"title": "Мастерская рядом · ДЕМО", "kind": "foreman", "description": "Учебный пример команды бытового ремонта. Все данные вымышлены."})
    invitation = team.invite(db, owner, {"email": users["member"]["email"], "role": "member"})
    team.invitation_action(db, member, {"invitation_id": invitation["id"]}, "accept", owner)
    service = c.save_service(db, owner, {"title": "Сборка мебели", "description": "Соберём небольшой шкаф, проверим крепления и уберём упаковку. Демонстрационная услуга.", "price_rub": 1800, "duration_minutes": 90})["id"]
    team.save_public_profile(db, owner, {"slug": "demo-workshop", "published": True, "description": "Вымышленная мастерская для показа возможностей H-Point.", "contact": "Только локальное демо — контакты вымышлены"})
    team.publish_service(db, owner, {"id": service, "published": True})
    client = c.save_client(db, owner, {"name": "Елена · учебный клиент", "contact": "client@example.test"})["id"]
    obj = team.save_object(db, owner, {"title": "Комната · демонстрационный объект", "client_id": client, "status": "active", "budget_rub": 25000})["id"]
    starts = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    c.save_booking(db, owner, {"client_id": client, "service_id": service, "title": "Сборка стеллажа · демо", "starts_at": starts.isoformat(), "duration_minutes": 90, "price_rub": 1800, "assignee_id": member, "object_id": obj})
    team.save_task(db, owner, {"title": "Уточнить размеры и подготовить инструмент", "object_id": obj, "assignee_id": member, "due_at": starts.isoformat()})
    estimate = team.save_estimate(db, owner, {"title": "Сборка мебели · демонстрационная смета", "object_id": obj, "client_id": client, "items": [
        {"title": "Сборка шкафа", "quantity": 1, "unit": "усл.", "price_rub": 1800, "cost_rub": 900},
        {"title": "Крепления", "kind": "material", "quantity": 2, "unit": "компл.", "price_rub": 150, "cost_rub": 100}]})["id"]
    inquiry = work_inquiries.create(db, author, {"service_id": service, "message": "Нужно собрать шкаф. Можно ли в пятницу после 18:00?", "preferred_time": "В пятницу вечером", "contact": "author@example.test", "request_key": uuid.uuid4().hex})["id"]
    request = services.create_request(author, {"what": "Помочь перенести коробки · демо", "place": "Демонстрационный район", "time_needed": "По договорённости", "urgency": "Не срочно", "details": "Учебный пример: две небольшие коробки.", "category": "carry"})
    info = {"synthetic": True, "database": str(folder / "demo.sqlite3"), "url": os.environ["WEB_PUBLIC_URL"], "organization": "/organizations/demo-workshop", "password": password, "users": users, "service_id": service, "inquiry_id": inquiry, "request_id": request, "estimate_id": estimate}
    (folder / "demo-info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


def install_local_demo_banner():
    from hpoint import organization_page, web
    banner = '<div role="note" style="padding:10px 18px;text-align:center;background:#f6e8b6;color:#423715;font:700 13px Arial">ДЕМО · вымышленные участники · только тестовые средства</div>'
    web.PAGE = re.sub(r"(<body\b[^>]*>)", lambda match: match[1] + banner, web.PAGE, count=1)
    original = organization_page.document
    def document(*args, **kwargs):
        return re.sub(r"(<body\b[^>]*>)", lambda match: match[1] + banner, original(*args, **kwargs), count=1)
    organization_page.document = document
    # Verification/reset is delivered only to a local JSON file. No provider is contacted.
    def mail(address, code):
        if not address.endswith("@example.test"):
            return False
        Path(os.environ["DB_PATH"]).with_name("local-mail.json").write_text(json.dumps({"address": address, "code": code}), encoding="utf-8")
        return True
    web.email_delivery_configured = lambda: True
    web.send_email_verification_code = mail
    web.send_password_reset_code = mail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--serve", action="store_true", help="Запустить новое демо на 127.0.0.1; Ctrl+C завершает сервер")
    args = parser.parse_args()
    try:
        folder = configure(args.port)
    except ValueError as error:
        parser.error(str(error))
    sys.path.insert(0, str(ROOT))
    info = seed(folder)
    print(json.dumps(info, ensure_ascii=False, indent=2), flush=True)
    if args.serve:
        install_local_demo_banner()
        from hpoint import web
        web.run()


if __name__ == "__main__":
    main()
