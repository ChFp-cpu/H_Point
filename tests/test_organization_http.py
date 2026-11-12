"""Public publication and authenticated workspace boundaries, using synthetic data."""
import json
import sqlite3
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hpoint import billing, commercial, database, services, web


class OrganizationHTTP(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.patches = [patch.object(module, "db", self.db) for module in (database, services, billing, web)]
        self.patches += [patch.object(database, "REGISTRATION_BONUS_RUB", 0)]
        for item in self.patches:
            item.start()
        database.init_db()
        self.tokens = {}
        for uid in (-101, -202, -303):
            database.create_user(uid, "Synthetic participant", web_verified=True)
            self.db.execute("UPDATE users SET email=?,email_verified=1 WHERE user_id=?", (f"synthetic{abs(uid)}@example.test", uid))
            self.tokens[uid] = web.new_sess(uid)
        commercial.save_profile(self.db, -101, {"kind":"organization", "title":"Synthetic <studio>", "description":"Private profile", "contact":""})
        self.service = commercial.save_service(self.db, -101, {"title":"Public service", "description":"Consultation", "price_rub":800, "duration_minutes":45})["id"]
        commercial.save_client(self.db, -101, {"name":"Private CRM client", "contact":"secret-client@example.test", "notes":"Private CRM secret"})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=3)
        self.server.server_close()
        for item in reversed(self.patches):
            item.stop()
        self.db.close()

    def fetch(self, path, uid=None, data=None, method=None):
        headers = {"Content-Type":"application/json", "Origin":web.WEB_PUBLIC_URL.rstrip("/")}
        if uid is not None:
            headers["Cookie"] = "hpoint_session=" + self.tokens[uid]
        body = json.dumps(data).encode() if data is not None else None
        try:
            response = urlopen(Request(self.base+path, data=body, headers=headers, method=method), timeout=4)
        except HTTPError as error:
            response = error
        with response:
            return response.status, dict(response.headers), response.read()

    def post(self, path, data, uid=-101):
        status, _, raw = self.fetch(path, uid, data)
        self.assertEqual(status, 200, raw.decode())
        return json.loads(raw)

    def publish(self):
        self.post("/api/commercial/public-profile", {"owner_id":-101, "slug":"synthetic-studio", "published":True, "description":"Public description <script>alert(1)</script>", "contact":"Public contact", "address":"Public district"})
        self.post("/api/commercial/services/publish", {"owner_id":-101, "id":self.service, "published":True})

    def test_publication_is_opt_in_and_never_exports_private_crm(self):
        status, _, raw = self.fetch("/api/organizations/services")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["services"], [])
        self.assertEqual(self.fetch("/organizations/synthetic-studio")[0], 404)
        self.publish()
        for path in ("/api/organizations/services", "/api/organizations/synthetic-studio", "/organizations/synthetic-studio"):
            status, headers, raw = self.fetch(path)
            self.assertEqual(status, 200, raw.decode())
            text = raw.decode()
            self.assertIn("Public service", text)
            for private in ("Private CRM client", "secret-client@example.test", "Private CRM secret", "synthetic101@example.test", "Private profile"):
                self.assertNotIn(private, text)
            self.assertIn("no-store", headers["Cache-Control"])
        status, headers, raw = self.fetch("/organizations/synthetic-studio")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", raw.decode())
        self.assertNotIn("<script>alert(1)</script>", raw.decode())
        self.assertIn("Content-Security-Policy", headers)
        head_status, head_headers, head_body = self.fetch("/organizations/synthetic-studio", method="HEAD")
        self.assertEqual((head_status, head_body), (200, b""))
        self.assertEqual(head_headers["Content-Length"], str(len(raw)))
        self.post("/api/commercial/public-profile", {"owner_id":-101, "slug":"synthetic-studio", "published":False, "description":"Public description", "contact":"", "address":""})
        self.assertEqual(self.fetch("/organizations/synthetic-studio")[0], 404)
        self.assertEqual(json.loads(self.fetch("/api/organizations/services")[2])["services"], [])

    def test_get_and_post_require_organization_membership(self):
        status, _, raw = self.fetch("/api/commercial?owner_id=-101", -303)
        self.assertEqual(status, 403, raw.decode())
        self.assertNotIn(b"Private CRM", raw)
        status, _, raw = self.fetch("/api/commercial/services", -303, {"owner_id":-101, "title":"Forged service"})
        self.assertEqual(status, 403, raw.decode())
        self.assertEqual(self.fetch("/api/commercial?owner_id=invalid", -101)[0], 400)
        self.assertEqual(self.fetch("/api/commercial")[0], 401)
        self.assertEqual(self.fetch("/api/commercial/estimates", data={"notes":"x"*40000})[0], 401)

    def test_billing_reports_real_access_and_user_badge_flag(self):
        database.wallet_add_entry(-101, 500, "synthetic_test", "Synthetic credit", "synthetic-http-credit", test_amount_rub=500)
        status, _, raw = self.fetch("/api/billing", -101)
        self.assertEqual(status, 200, raw.decode())
        self.assertFalse(json.loads(raw)["user"]["pro_active"])
        for path in ("/api/payments/wallet", "/api/payments/hp"):
            bad_status, _, bad_raw = self.fetch(path, -101, {"item_type":"pro", "metadata":["invalid"], "purchase_key":"synthetic-invalid"})
            self.assertEqual(bad_status, 400, bad_raw.decode())
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM billing_invoices").fetchone()["n"], 0)
        self.post("/api/payments/wallet", {"item_type":"pro", "metadata":{}, "purchase_key":"synthetic-http-pro"})
        status, _, raw = self.fetch("/api/billing", -101)
        data = json.loads(raw)
        self.assertTrue(data["user"]["pro_active"])
        self.assertTrue(data["subscription"]["pro"]["active"])
        self.assertGreater(data["subscription"]["pro"]["days_remaining"], 0)
        self.assertIn("pro", data["catalog"])
        status, _, raw = self.fetch("/api/payments/wallet", -101, {"item_type":"pro", "metadata":{}, "purchase_key":"synthetic-http-pro-duplicate"})
        self.assertEqual(status, 409, raw.decode())
        self.assertIn("PRO уже активен", json.loads(raw)["error"])
