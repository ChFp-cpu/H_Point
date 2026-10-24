"""Run browser QA with a disposable database and synthetic participants only."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / ".theme-qa"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="database-", dir=output) as task_dir:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        env = dict(os.environ, DB_PATH=str(Path(task_dir) / "qa.db"), DATABASE_URL="",
                   WEB_HOST="127.0.0.1", WEB_PORT=str(port), WEB_PUBLIC_URL=base,
                   BOT_TOKEN="", BOT_USERNAME="", RUN_TELEGRAM_BOT="0", SESSION_COOKIE_SECURE="0",
                   SMTP_HOST="", SMTP_PASSWORD="", BREVO_API_KEY="", YANDEX_MAPS_API_KEY="browser-qa-placeholder",
                   HPOINT_QA_URL=base, HPOINT_QA_OUTPUT=str(output), APP_ENV="development",
                   HPOINT_QA_MAIL=str(Path(task_dir) / "mail.json"))
        seed = '''
from hpoint import database, services
database.init_db()
for uid, name in [(901,"Тестовый участник"),(902,"Тестовый помощник"),(903,"Автор заявки"),(904,"Кандидат"),(905,"Новый участник")]:
    database.create_user(uid,name,tg_user_id=uid,web_verified=True)
    database.db.execute("UPDATE users SET email_verified=1,city='Тестовый город' WHERE user_id=?",(uid,))
database.db.execute("UPDATE users SET role='admin' WHERE user_id=901")
payload={"what":"Настроить домашнюю технику","place":"Тестовый район","time_needed":"сегодня","urgency":"В течение дня","details":"Только тестовые данные","category":"tech"}
services.create_request(901,payload)
services.create_request(903,{**payload,"what":"Перенести коробки","category":"carry"})
active=services.create_request(901,{**payload,"what":"Совместная настройка компьютера"})
services.try_assign_helper(active,902)
database.get_or_create_chat_for_request(active)
done=services.create_request(903,{**payload,"what":"Завершённая помощь"})
services.try_assign_helper(done,901)
services.complete_request(done,901)
services.set_rating(done,903,5)
services.add_to_queue(904)
database.create_web_login_ticket(901,"theme-browser-data")
database.create_web_login_ticket(905,"theme-browser-empty")
database.create_web_login_ticket(905,"theme-browser-game-deep")
database.create_web_login_ticket(904,"mobile-helper")
'''
        subprocess.run([sys.executable, "-c", seed], cwd=root, env=env, check=True)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        # Mail is intercepted inside this disposable server; no provider or
        # production setting is modified. Exercise the real verification flow.
        launch = '''
from hpoint import web
import json, os
from pathlib import Path
def record_mail(address, code):
    Path(os.environ["HPOINT_QA_MAIL"]).write_text(json.dumps({"address": address, "code": code}), encoding="utf-8")
    return True
web.email_delivery_configured = lambda: True
web.send_email_verification_code = record_mail
web.send_password_reset_code = record_mail
web.run()
'''
        server = subprocess.Popen([sys.executable, "-c", launch], cwd=root, env=env,
                                  stdout=subprocess.DEVNULL, creationflags=flags)
        try:
            for _ in range(150):
                if server.poll() is not None:
                    raise RuntimeError("Local QA server stopped during startup")
                try:
                    with urlopen(base + "/api/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Local QA server did not become ready")
            script = sys.argv[1] if len(sys.argv) > 1 else "tests/theme_browser.cjs"
            subprocess.run(["node", script], cwd=root, env=env, check=True)
        finally:
            if os.name == "nt":
                # The Windows venv executable is a launcher with a child
                # interpreter. Stop this test's process tree before removing
                # its temporary SQLite file.
                subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
