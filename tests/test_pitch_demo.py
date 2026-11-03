"""The pitch fixture cannot target production and never invents real traction."""
import importlib.util
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pitch_demo", ROOT / "scripts/demo_pitch.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class PitchDemoTests(unittest.TestCase):
    def test_refuses_production_before_creating_any_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(demo, "ROOT", Path(folder)):
            for environment in ({"DATABASE_URL": "postgresql://production/database"}, {"APP_ENV": "production"}, {"APP_ENV": " PrOdUcTiOn "}):
                with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(ValueError): demo.configure(8088)
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_new_invocations_keep_previous_data_and_force_loopback_no_delivery(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(demo, "ROOT", Path(folder)), patch.dict(os.environ, {}, clear=True):
            first = demo.configure(8088)
            marker = first / "keep.txt"
            marker.write_text("Existing demo is never reset", encoding="utf-8")
            second = demo.configure(8089)
            self.assertNotEqual(first, second)
            self.assertEqual(marker.read_text(encoding="utf-8"), "Existing demo is never reset")
            self.assertEqual(os.environ["WEB_HOST"], "127.0.0.1")
            for key in ("DATABASE_URL", "BOT_TOKEN", "SMTP_HOST", "SMTP_PASSWORD", "BREVO_API_KEY"):
                self.assertEqual(os.environ[key], "")

    def test_complete_synthetic_fixture_and_banner_are_local_only(self):
        # Keep this test's disposable SQLite outside the actual demo directory.
        with tempfile.TemporaryDirectory() as folder:
            code = '''
import importlib.util,json,os,sys
from pathlib import Path
root=Path(sys.argv[1]);target=Path(sys.argv[2])
spec=importlib.util.spec_from_file_location('pitch_demo',root/'scripts/demo_pitch.py')
demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
demo.ROOT=target
sys.path.insert(0,str(root))
data=demo.seed(demo.configure(8088))
demo.install_local_demo_banner()
from hpoint import database,web,organization_page,commercial_team,pilot_analytics
assert 'ДЕМО · вымышленные участники' in web.PAGE
page=organization_page.document(commercial_team.public_organization(database.db,'demo-workshop'),os.environ['WEB_PUBLIC_URL'])
assert 'ДЕМО · вымышленные участники' in page
assert web.send_email_verification_code('nobody@real.example','123456') is False
assert web.send_email_verification_code('new@example.test','123456') is True
metrics=pilot_analytics.summary(database.db,data['users']['admin']['id'],14,'real')
assert metrics['cohort']=='real'
print(json.dumps(data))
'''
            env = dict(os.environ, DATABASE_URL="", APP_ENV="development", PYTHONIOENCODING="utf-8")
            result = subprocess.run([sys.executable, "-c", code, str(ROOT), folder], cwd=ROOT, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(result.stdout)
            with sqlite3.connect(info["database"]) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE tg_user_id IS NOT NULL").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM pilot_cohorts WHERE cohort='demo'").fetchone()[0], 5)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM commercial_inquiries").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM commercial_estimates").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 1)
            db.close()
            self.assertTrue(info["synthetic"])

    def test_serve_supports_real_email_sessions_and_stops_without_external_data(self):
        # Exercise main(--serve), including its real HTTP server, in a child so
        # imported hpoint configuration cannot reuse another test's database.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            bootstrap = '''
import importlib.util,sys
from pathlib import Path
root=Path(sys.argv[1]);target=Path(sys.argv[2]);port=sys.argv[3]
sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location('pitch_demo',root/'scripts/demo_pitch.py')
demo=importlib.util.module_from_spec(spec);spec.loader.exec_module(demo)
demo.ROOT=target
sys.argv=['demo_pitch.py','--serve','--port',port]
demo.main()
'''
            env = dict(os.environ, DATABASE_URL="", APP_ENV="development", PYTHONIOENCODING="utf-8")
            log_path = target / "serve.log"
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen([sys.executable, "-u", "-c", bootstrap, str(ROOT), str(target), str(port)],
                                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    deadline = time.monotonic() + 40
                    while True:
                        self.assertIsNone(process.poll(), log_path.read_text(encoding="utf-8"))
                        try:
                            with urlopen(base + "/api/health", timeout=0.5) as response:
                                self.assertEqual(json.load(response), {"ok": True, "database": True})
                            break
                        except (URLError, TimeoutError):
                            if time.monotonic() >= deadline:
                                self.fail("Local demo did not start: " + log_path.read_text(encoding="utf-8"))
                            time.sleep(0.1)
                    info_files = list(target.glob(".pitch-demo/*/demo-info.json"))
                    self.assertEqual(len(info_files), 1)
                    info = json.loads(info_files[0].read_text(encoding="utf-8"))
                    self.assertEqual(info["url"], base)
                    self.assertTrue(Path(info["database"]).is_relative_to(target))
                    for path in ("/", "/organizations/demo-workshop"):
                        with urlopen(base + path, timeout=3) as response:
                            self.assertIn("ДЕМО · вымышленные участники", response.read().decode())

                    def session():
                        return build_opener(HTTPCookieProcessor(CookieJar()))

                    def request(client, path, body=None):
                        data = json.dumps(body).encode() if body is not None else None
                        req = Request(base + path, data=data, headers={"Content-Type": "application/json", "Origin": base})
                        with client.open(req, timeout=3) as response:
                            result = json.load(response)
                        self.assertTrue(result["ok"], result)
                        return result

                    author = session()
                    request(author, "/api/auth/login", {"email": info["users"]["author"]["email"], "password": info["password"]})
                    me = request(author, "/api/me")["user"]
                    self.assertEqual(me["email"], "author@example.test")
                    self.assertTrue(me["email_verified"])
                    self.assertEqual(len(request(author, "/api/work-inquiries/mine")["inquiries"]), 1)
                    owner = session()
                    request(owner, "/api/auth/login", {"email": info["users"]["owner"]["email"], "password": info["password"]})
                    inbox = request(owner, "/api/commercial/inquiries?owner_id=" + str(info["users"]["owner"]["id"]))
                    self.assertEqual(inbox["incoming_count"], 1)
                    admin = session()
                    request(admin, "/api/auth/login", {"email": info["users"]["admin"]["email"], "password": info["password"]})
                    self.assertEqual(request(admin, "/api/admin/pilot?cohort=demo")["registrations"]["created"], 5)
                    self.assertEqual(request(admin, "/api/admin/pilot?cohort=real")["registrations"]["created"], 0)

                    # Registration and verification use only the loopback JSON
                    # mailbox, proving the visible email-only flow works too.
                    newcomer = session()
                    password = "Demo-New-Participant-123!"
                    request(newcomer, "/api/auth/register", {"name": "Новый участник демо", "email": "new@example.test", "password": password, "password_confirm": password})
                    local_mail = Path(info["database"]).with_name("local-mail.json")
                    mail = json.loads(local_mail.read_text(encoding="utf-8"))
                    self.assertEqual(mail["address"], "new@example.test")
                    request(newcomer, "/api/auth/email/verify", {"code": mail["code"]})
                    self.assertEqual(request(newcomer, "/api/me")["user"]["email"], "new@example.test")
                    self.assertEqual(request(admin, "/api/admin/pilot?cohort=real")["registrations"]["created"], 0)
                finally:
                    if process.poll() is None:
                        if sys.platform == "win32":
                            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                           capture_output=True, timeout=10)
                        else:
                            process.terminate()
                        try:process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill();process.wait(timeout=5)
                    self.assertIsNotNone(process.poll())
            # The test owns this process/port; nothing remains serving after QA.
            with socket.socket() as probe:
                probe.settimeout(0.5)
                self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)


if __name__ == "__main__":
    unittest.main()
