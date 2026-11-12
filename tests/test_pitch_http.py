"""Real HTTP boundaries for private service leads and pilot measurements.

Every account, image and organisation is synthetic and lives in a temporary DB.
"""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hpoint import billing, commercial as c, database, services, web
from test_work_inquiries import InquiryFixtures


class PitchHTTP(InquiryFixtures, unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.prepare(database.SQLiteConnection(str(Path(self.directory.name) / "pitch.sqlite3")))
        for uid, verified, blocked in ((-606, 0, 0), (-707, 1, 1)):
            database.create_user(uid, "Synthetic restricted account", email=f"restricted{abs(uid)}@example.test", web_verified=True)
            self.db.execute("UPDATE users SET email_verified=?,is_blocked=? WHERE user_id=?", (verified, blocked, uid))
        self.db.execute("UPDATE users SET role='admin' WHERE user_id=-303")
        self.patches.extend(patch.object(module, "db", self.db) for module in (billing, services, web))
        for item in self.patches[2:]:
            item.start()
        self.tokens = {uid: web.new_sess(uid) for uid in (-101, -202, -303, -404, -505, -606, -707)}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()
        self.close()
        self.directory.cleanup()

    def fetch(self, path, uid=None, data=None, method=None, origin=None):
        headers = {"Content-Type": "application/json", "Origin": origin or web.WEB_PUBLIC_URL.rstrip("/")}
        if uid is not None:
            headers["Cookie"] = "hpoint_session=" + self.tokens[uid]
        body = json.dumps(data).encode() if data is not None else None
        try:
            response = urlopen(Request(self.base + path, data=body, headers=headers, method=method), timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, dict(response.headers), response.read()

    def json(self, path, uid=None, data=None, expected=200, **kwargs):
        status, headers, raw = self.fetch(path, uid, data, **kwargs)
        self.assertEqual(status, expected, raw.decode(errors="replace"))
        result = json.loads(raw)
        self.assertEqual(result["ok"], expected == 200)
        self.assertIn("no-store", headers["Cache-Control"])
        return result

    def submit(self, **fields):
        return self.json("/api/work-inquiries", -505, self.payload(**fields))["result"]

    def test_public_service_is_safe_but_inbox_and_measurements_need_verified_auth(self):
        service = self.json(f"/api/work-inquiries/service?id={self.service}")["service"]
        self.assertEqual(service["id"], self.service)
        self.assertNotIn("owner_id", service)
        self.assertNotIn("example.test", json.dumps(service))
        self.json("/api/work-inquiries/service?id=invalid", expected=404)
        gets = ("/api/work-inquiries/mine", "/api/work-inquiries?id=1", "/api/commercial/inquiries?owner_id=-101", "/api/work-inquiries/photo?id=invalid", "/api/admin/pilot")
        posts = ("/api/work-inquiries", "/api/work-inquiries/cancel", "/api/commercial/inquiries/update", "/api/commercial/inquiries/convert", "/api/pilot/activity", "/api/pilot/view", "/api/admin/pilot/cohort")
        for path in gets:
            for uid, expected in ((None, 401), (-606, 401), (-707, 403)):
                with self.subTest(path=path, uid=uid):self.json(path, uid, expected=expected)
        for path in posts:
            for uid, expected in ((None, 401), (-606, 401), (-707, 403)):
                with self.subTest(path=path, uid=uid):self.json(path, uid, {}, expected=expected)

    def test_private_inbox_assignment_conversion_and_author_status_without_money(self):
        before = self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"]
        payload = self.payload()
        first = self.json("/api/work-inquiries", -505, payload)["result"]
        replay = self.json("/api/work-inquiries", -505, payload)["result"]
        self.assertTrue(first["created"]);self.assertFalse(replay["created"])
        item = first["id"]
        self.assertEqual(self.json("/api/work-inquiries/mine", -505)["inquiries"][0]["id"], item)
        self.assertEqual(self.json("/api/commercial/inquiries?owner_id=-101", -101)["incoming_count"], 1)
        self.assertEqual(self.json("/api/commercial/inquiries?owner_id=-101", -202)["inquiries"], [])
        for uid in (-202, -404):
            self.json(f"/api/work-inquiries?id={item}&owner_id=-101", uid, expected=403)
        self.json("/api/commercial/inquiries/update", -101, {"owner_id": -101, "inquiry_id": item, "assignee_id": -202, "status": "in_progress", "reply": "Уточнили удобное время."})
        self.assertEqual(self.json("/api/commercial/inquiries?owner_id=-101", -202)["incoming_count"], 1)
        self.json("/api/commercial/inquiries/convert", -202, {"owner_id": -101, "inquiry_id": item, **self.conversion()}, expected=403)
        self.json("/api/work-inquiries/cancel", -404, {"inquiry_id": item}, expected=403)
        conversion = self.json("/api/commercial/inquiries/convert", -101, {"owner_id": -101, "inquiry_id": item, **self.conversion()})["result"]
        again = self.json("/api/commercial/inquiries/convert", -101, {"owner_id": -101, "inquiry_id": item})["result"]
        self.assertTrue(conversion["created"]);self.assertFalse(again["created"])
        self.assertEqual(conversion["booking_id"], again["booking_id"])
        author = self.json(f"/api/work-inquiries?id={item}", -505)["inquiry"]
        self.assertEqual(author["status"], "accepted")
        self.assertIsNone(author["client_id"]);self.assertIsNone(author["booking_id"])
        self.assertEqual(author["booking"]["price_rub"], 1500)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"], before)
        self.json("/api/work-inquiries/cancel", -505, {"inquiry_id": item}, expected=409)

    def test_photo_upload_above_small_body_limit_stays_private_and_sanitized(self):
        from PIL import Image
        stream = BytesIO()
        Image.frombytes("RGB", (160, 160), os.urandom(160 * 160 * 3)).save(stream, format="PNG")
        photo = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()
        self.assertGreater(len(photo), 32 * 1024)
        item = self.submit(photos=[photo])["inquiry"]
        path = item["photos"][0]["url"]
        status, headers, body = self.fetch(path, -505)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/jpeg")
        self.assertEqual(headers["Cache-Control"], "private, no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertTrue(body.startswith(b"\xff\xd8"))
        self.json(path, expected=401)
        self.json(path, -404, expected=403)
        self.json(path, -202, expected=403)
        self.assertEqual(self.fetch(path, -101)[2], body)
        self.json("/api/work-inquiries", -505, self.payload(photos=["not an image"]), expected=409)

    def test_cancellation_retry_and_expired_workspace_preserve_read_access(self):
        item = self.submit()["id"]
        self.db.execute("UPDATE commercial_profiles SET trial_until='2020-01-01T00:00:00Z' WHERE user_id=-101")
        inbox = self.json("/api/commercial/inquiries?owner_id=-101", -101)
        self.assertFalse(inbox["inquiries"][0]["can_update"])
        self.json("/api/commercial/inquiries/update", -101, {"owner_id": -101, "inquiry_id": item, "reply": "Недоступная запись"}, expected=409)
        self.json("/api/work-inquiries/service?id=" + str(self.service), expected=404)
        first = self.json("/api/work-inquiries/cancel", -505, {"inquiry_id": item})["result"]
        again = self.json("/api/work-inquiries/cancel", -505, {"inquiry_id": item})["result"]
        self.assertTrue(first["changed"]);self.assertFalse(again["changed"])
        self.assertEqual(self.json("/api/work-inquiries/mine", -505)["inquiries"][0]["status"], "cancelled")

    def test_analytics_admin_scope_cohorts_and_daily_idempotency(self):
        self.json("/api/admin/pilot", -505, expected=403)
        self.json("/api/admin/pilot/cohort", -505, {"user_id": -505, "cohort": "real"}, expected=403)
        first = self.json("/api/pilot/activity", -505, {})["result"]
        self.assertTrue(first["recorded"])
        self.assertFalse(self.json("/api/pilot/activity", -505, {})["result"]["recorded"])
        view = self.json("/api/pilot/view", -505, {"service_id": self.service})["result"]
        self.assertTrue(view["recorded"])
        self.assertFalse(self.json("/api/pilot/view", -505, {"service_id": self.service})["result"]["recorded"])
        self.assertFalse(self.json("/api/pilot/view", -101, {"service_id": self.service})["result"]["recorded"])
        tagged = self.json("/api/admin/pilot/cohort", -303, {"user_id": -505, "cohort": "demo"})["result"]
        self.assertEqual(tagged["cohort"], "demo")
        summary = self.json("/api/admin/pilot?days=14&cohort=demo", -303)
        self.assertEqual(summary["cohort"], "demo")
        self.assertEqual(summary["cohorts"]["demo"], 1)
        for private in ("Synthetic user", "example.test", "PUBLIC CONTACT"):
            self.assertNotIn(private, json.dumps(summary))
        for query in ("days=91", "days=bad", "cohort=made-up"):
            self.json("/api/admin/pilot?" + query, -303, expected=400)

    def test_typed_json_validation_and_cross_origin_rejection_never_write(self):
        for path in ("/api/work-inquiries", "/api/work-inquiries/cancel", "/api/commercial/inquiries/update", "/api/commercial/inquiries/convert", "/api/pilot/activity", "/api/pilot/view", "/api/admin/pilot/cohort"):
            for body in ([], "bad", 42):
                with self.subTest(path=path, body=body):self.json(path, -303, body, expected=400)
        self.json("/api/work-inquiries", -505, self.payload(), origin="https://foreign.example.test", expected=403)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_inquiries").fetchone()["n"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM pilot_activity_days").fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()
