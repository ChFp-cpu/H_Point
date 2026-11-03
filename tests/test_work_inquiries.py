"""Service inquiries: tenant/privacy boundaries, no money, atomic conversion."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from pathlib import Path
import base64
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from hpoint import commercial as c, commercial_team as team, database, work_inquiries as inquiries


class InquiryFixtures:
    def prepare(self, db):
        self.db = db
        self.patches = [patch.object(database, "db", db), patch.object(database, "REGISTRATION_BONUS_RUB", 0)]
        for item in self.patches:
            item.start()
        database.init_db()
        for uid in (-101, -202, -303, -404, -505, 900000000000001):
            database.create_user(uid, "Synthetic user " + str(abs(uid)), email=f"inquiry{abs(uid)}@example.test", web_verified=True)
            db.execute("UPDATE users SET email_verified=1 WHERE user_id=?", (uid,))
        c.save_profile(db, -101, {"title": "Мастерская тестового района", "kind": "repair"})
        c.save_profile(db, -404, {"title": "Другая мастерская", "kind": "organization"})
        for uid, role in ((-202, "member"), (-303, "admin")):
            invite = team.invite(db, -101, {"email": f"inquiry{abs(uid)}@example.test", "role": role})
            team.invitation_action(db, uid, {"invitation_id": invite["id"]}, "accept", -101)
        self.service = c.save_service(db, -101, {"title": "Диагностика техники", "description": "Опубликованная услуга", "price_rub": 1500, "duration_minutes": 60})["id"]
        team.save_public_profile(db, -101, {"slug": "synthetic-repair", "published": True, "description": "Публичное описание", "contact": "PUBLIC CONTACT"})
        team.publish_service(db, -101, {"id": self.service, "published": True})

    def close(self):
        self.db.close()
        for item in reversed(self.patches):
            item.stop()

    def payload(self, **fields):
        return {"service_id": self.service, "message": "Нужно проверить холодильник", "preferred_time": "Завтра после 18:00", "contact": "Контакт, явно введённый автором", "request_key": uuid.uuid4().hex, **fields}

    def create(self, uid=-505, **fields):
        return inquiries.create(self.db, uid, self.payload(**fields))["id"]

    def conversion(self, **fields):
        return {"starts_at": "2030-05-01T12:00:00+03:00", "assignee_id": -202, **fields}

    def photo(self):
        from PIL import Image
        stream = BytesIO();Image.new("RGB", (20, 30), "green").save(stream, format="PNG")
        return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")

class InquiryCases(InquiryFixtures):
    def test_public_service_is_allowlisted_and_only_published_active(self):
        result = inquiries.public_service(self.db, self.service)
        self.assertEqual(result["organization_url"], "/organizations/synthetic-repair")
        self.assertNotIn("owner_id", result)
        self.assertNotIn("inquiry101@example.test", json.dumps(result))
        team.publish_service(self.db, -101, {"id": self.service, "published": False})
        with self.assertRaises(ValueError):inquiries.public_service(self.db, self.service)
        with self.assertRaises(ValueError):self.create()

    def test_create_is_idempotent_snapshots_terms_and_never_spends_money(self):
        before = self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"]
        payload = self.payload()
        first = inquiries.create(self.db, -505, payload)
        second = inquiries.create(self.db, -505, payload)
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(first["created"]);self.assertFalse(second["created"])
        self.assertEqual(len(inquiries.mine(self.db, -505)), 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_clients").fetchone()["n"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_bookings").fetchone()["n"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"], before)
        with self.assertRaises(ValueError):inquiries.create(self.db, -505, {**payload, "message": "Другая задача"})
        c.save_service(self.db, -101, {"id": self.service, "title": "Новая услуга", "price_rub": 9000, "duration_minutes": 120})
        saved = inquiries.detail(self.db, -505, first["id"])
        self.assertEqual((saved["service_title"], saved["price_rub"], saved["duration_minutes"]), ("Диагностика техники", 1500, 60))

    def test_contact_is_explicit_author_dto_omits_crm_notes_and_internal_ids(self):
        item = self.create()
        result = inquiries.convert(self.db, -101, {"inquiry_id": item, **self.conversion()}, -101)
        self.db.execute("UPDATE commercial_clients SET notes='PRIVATE CRM NOTES' WHERE id=?", (result["client_id"],))
        self.db.execute("UPDATE commercial_bookings SET notes='PRIVATE BOOKING NOTES' WHERE id=?", (result["booking_id"],))
        author = inquiries.detail(self.db, -505, item)
        serialized = json.dumps(author)
        for secret in ("inquiry505@example.test", "inquiry202@example.test", "PRIVATE CRM", "PRIVATE BOOKING"):
            self.assertNotIn(secret, serialized)
        self.assertIsNone(author["client_id"]);self.assertIsNone(author["booking_id"])
        self.assertEqual(author["booking"]["starts_at"], "2030-05-01T09:00:00+00:00")
        self.assertEqual(author["contact"], "Контакт, явно введённый автором")

    def test_manager_assignment_employee_visibility_and_no_member_conversion(self):
        item = self.create()
        self.assertEqual(inquiries.dashboard(self.db, -202, -101)["inquiries"], [])
        self.assertEqual(c.summary(self.db, -202, -101)["incoming_count"], 0)
        self.assertEqual(c.summary(self.db, -101)["incoming_count"], 1)
        with self.assertRaises(PermissionError):inquiries.detail(self.db, -202, item, -101)
        inquiries.update(self.db, -303, {"inquiry_id": item, "assignee_id": -202, "status": "in_progress", "reply": "Уточните модель."}, -101)
        employee = inquiries.dashboard(self.db, -202, -101)
        self.assertEqual(employee["incoming_count"], 1)
        self.assertEqual(c.summary(self.db, -202, -101)["incoming_count"], 1)
        self.assertTrue(employee["inquiries"][0]["can_update"])
        self.assertFalse(employee["inquiries"][0]["can_convert"])
        with self.assertRaises(PermissionError):inquiries.convert(self.db, -202, {"inquiry_id": item, **self.conversion()}, -101)
        with self.assertRaises(PermissionError):inquiries.update(self.db, -202, {"inquiry_id": item, "assignee_id": -101}, -101)
        inquiries.update(self.db, -202, {"inquiry_id": item, "reply": "Приеду в согласованное время.", "status": "in_progress"}, -101)
        self.assertEqual(inquiries.detail(self.db, -505, item)["reply"], "Приеду в согласованное время.")
        self.assertEqual(c.dashboard(self.db, -202, -101)["incoming_count"], 1)

    def test_foreign_tenant_references_blocked_accounts_and_author_access(self):
        item = self.create()
        other_client = c.save_client(self.db, -404, {"name": "Чужой клиент"})["id"]
        other_object = team.save_object(self.db, -404, {"title": "Чужой объект"})["id"]
        for uid in (-404, 900000000000001):
            with self.assertRaises(PermissionError):inquiries.detail(self.db, uid, item)
            with self.assertRaises(PermissionError):inquiries.cancel(self.db, uid, {"inquiry_id": item})
        for fields in ({"client_id": other_client}, {"object_id": other_object}, {"assignee_id": -404}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):inquiries.convert(self.db, -101, {"inquiry_id": item, **self.conversion(**fields)}, -101)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_bookings").fetchone()["n"], 0)
        self.db.execute("UPDATE users SET is_blocked=1 WHERE user_id=-505")
        with self.assertRaises(ValueError):inquiries.mine(self.db, -505)
        with self.assertRaises(ValueError):inquiries.convert(self.db, -101, {"inquiry_id": item, **self.conversion()}, -101)

    def test_photos_are_private_validated_and_keep_dimensions_without_public_urls(self):
        item = self.create(photos=[self.photo()])
        author = inquiries.detail(self.db, -505, item)
        photo = author["photos"][0]
        self.assertEqual((photo["width"], photo["height"]), (20, 30))
        self.assertEqual(photo["url"], "/api/work-inquiries/photo?id=" + photo["id"])
        mime, body = inquiries.photo_for_user(self.db, -505, photo["id"])
        self.assertEqual(mime, "image/jpeg");self.assertTrue(body.startswith(b"\xff\xd8"))
        for uid in (-404, -202):
            with self.assertRaises(PermissionError):inquiries.photo_for_user(self.db, uid, photo["id"])
        inquiries.update(self.db, -101, {"inquiry_id": item, "assignee_id": -202}, -101)
        self.assertEqual(inquiries.photo_for_user(self.db, -202, photo["id"])[1], body)
        team.member_action(self.db, -202, {}, "leave", -101)
        with self.assertRaises(PermissionError):inquiries.photo_for_user(self.db, -202, photo["id"])
        for photos in (["not an image"], [self.photo()] * 4):
            with self.assertRaises(ValueError):self.create(photos=photos)

    def test_conversion_is_atomic_idempotent_and_existing_client_can_be_selected(self):
        item = self.create()
        client = c.save_client(self.db, -101, {"name": "Существующий клиент", "contact": "MY CONTACT"})["id"]
        first = inquiries.convert(self.db, -303, {"inquiry_id": item, "client_id": client, **self.conversion()}, -101)
        replay = inquiries.convert(self.db, -101, {"inquiry_id": item}, -101)
        self.assertTrue(first["created"]);self.assertFalse(replay["created"])
        self.assertEqual(first["booking_id"], replay["booking_id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_clients WHERE owner_id=-101").fetchone()["n"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_bookings").fetchone()["n"], 1)
        self.assertEqual(inquiries.detail(self.db, -505, item)["status"], "accepted")
        with self.assertRaises(ValueError):inquiries.cancel(self.db, -505, {"inquiry_id": item})
        with self.assertRaises(ValueError):inquiries.update(self.db, -101, {"inquiry_id": item, "status": "new"}, -101)

    def test_overlap_bad_dates_or_fields_never_create_orphan_clients(self):
        first = self.create()
        inquiries.convert(self.db, -101, {"inquiry_id": first, **self.conversion()}, -101)
        second = self.create()
        for fields in ({}, {"starts_at": "2020-01-01T12:00:00Z"}, {"starts_at": "2030-02-30T12:00:00Z"}, {"duration_minutes": 0}, {"price_rub": -1}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                inquiries.convert(self.db, -101, {"inquiry_id": second, **self.conversion(**fields)}, -101)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_clients").fetchone()["n"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_bookings").fetchone()["n"], 1)
        self.assertEqual(inquiries.detail(self.db, -505, second)["status"], "new")

    def test_expired_read_access_author_cancellation_and_deleted_org_cleanup(self):
        item = self.create(photos=[self.photo()])
        self.db.execute("UPDATE commercial_profiles SET trial_until='2020-01-01T00:00:00Z' WHERE user_id=-101")
        self.assertFalse(inquiries.dashboard(self.db, -101, -101)["inquiries"][0]["can_update"])
        with self.assertRaises(ValueError):self.create()
        with self.assertRaises(ValueError):inquiries.update(self.db, -101, {"inquiry_id": item, "reply": "Нельзя"}, -101)
        with self.assertRaises(ValueError):inquiries.convert(self.db, -101, {"inquiry_id": item, **self.conversion()}, -101)
        inquiries.cancel(self.db, -505, {"inquiry_id": item});inquiries.cancel(self.db, -505, {"inquiry_id": item})
        self.assertEqual(inquiries.detail(self.db, -505, item)["status"], "cancelled")
        c.delete_profile(self.db, -101, True)
        self.assertEqual(inquiries.mine(self.db, -505), [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_inquiry_photos").fetchone()["n"], 0)

    def test_migration_repeated_large_uid_snapshot_and_rejection(self):
        item = self.create(uid=900000000000001)
        c.initialize_schema(self.db);c.initialize_schema(self.db)
        self.assertEqual(inquiries.mine(self.db, 900000000000001)[0]["id"], item)
        inquiries.update(self.db, -101, {"inquiry_id": item, "status": "rejected", "reply": "Нет свободного времени."}, -101)
        self.assertEqual(inquiries.detail(self.db, 900000000000001, item)["status"], "rejected")
        with self.assertRaises(ValueError):inquiries.cancel(self.db, 900000000000001, {"inquiry_id": item})
        with self.assertRaises(ValueError):inquiries.update(self.db, -101, {"inquiry_id": item, "status": "accepted"}, -101)

    def test_withdrawn_service_retains_prior_inquiry_and_retry_without_new_price(self):
        payload = self.payload()
        first = inquiries.create(self.db, -505, payload)
        team.publish_service(self.db, -101, {"id": self.service, "published": False})
        self.assertFalse(inquiries.create(self.db, -505, payload)["created"])
        with self.assertRaises(ValueError):self.create()
        result = inquiries.convert(self.db, -101, {"inquiry_id": first["id"], **self.conversion()}, -101)
        self.assertEqual(result["inquiry"]["booking"]["price_rub"], 1500)

    def test_reassignment_revokes_previous_employee_record_and_photo_access(self):
        item = self.create(photos=[self.photo()])
        inquiries.update(self.db, -101, {"inquiry_id": item, "assignee_id": -202}, -101)
        photo = inquiries.detail(self.db, -202, item, -101)["photos"][0]["id"]
        inquiries.update(self.db, -101, {"inquiry_id": item, "assignee_id": -101}, -101)
        self.assertEqual(inquiries.dashboard(self.db, -202, -101)["incoming_count"], 0)
        with self.assertRaises(PermissionError):inquiries.detail(self.db, -202, item, -101)
        with self.assertRaises(PermissionError):inquiries.photo_for_user(self.db, -202, photo)

    def test_departed_employee_is_unassigned_and_conversion_remains_available(self):
        for action in ("leave", "remove"):
            with self.subTest(action=action):
                member = -202 if action == "leave" else -303
                item = self.create()
                inquiries.update(self.db, -101, {"inquiry_id": item, "assignee_id": member}, -101)
                actor = member if action == "leave" else -101
                team.member_action(self.db, actor, {"user_id": member}, action, -101)
                manager = inquiries.detail(self.db, -101, item, -101)
                self.assertIsNone(manager["assignee_id"])
                self.assertEqual(manager["assignee_name"], "")
                with self.assertRaises(PermissionError):inquiries.detail(self.db, member, item, -101)
                converted = inquiries.convert(self.db, -101, {"inquiry_id": item, "starts_at": "2030-05-01T12:00:00+03:00"}, -101)
                self.assertTrue(converted["created"])
                self.assertIsNone(converted["inquiry"]["assignee_id"])


class SQLiteInquiries(InquiryCases, unittest.TestCase):
    def setUp(self):
        db = sqlite3.connect(":memory:", isolation_level=None);db.row_factory = sqlite3.Row;db.execute("PRAGMA foreign_keys=ON")
        self.prepare(db)
    def tearDown(self):self.close()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"), "requires isolated PostgreSQL test database")
class PostgreSQLInquiries(InquiryCases, unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema = "inquiry_qa_" + uuid.uuid4().hex
        url = os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control = database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "' + self.schema + '"')
        self.prepare(IsolatedPostgres(url, self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "' + self.schema + '" CASCADE');self.control.close()


class InquiryRaces(InquiryFixtures):
    def race(self, *functions):
        gate = threading.Barrier(len(functions))
        def run(function):
            try:
                gate.wait(timeout=5)
                try:return function()
                except (ValueError, PermissionError) as error:return str(error)
            finally:self.db.close()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return [future.result(timeout=30) for future in [pool.submit(run, function) for function in functions]]

    def test_parallel_duplicate_create_has_one_inquiry(self):
        payload = self.payload()
        results = self.race(lambda: inquiries.create(self.db, -505, payload), lambda: inquiries.create(self.db, -505, payload))
        self.assertTrue(all(isinstance(result, dict) for result in results), results)
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_inquiries").fetchone()["n"], 1)

    def test_parallel_convert_has_one_client_and_booking(self):
        item = self.create()
        data = {"inquiry_id": item, **self.conversion()}
        results = self.race(lambda: inquiries.convert(self.db, -101, data, -101), lambda: inquiries.convert(self.db, -303, data, -101))
        self.assertEqual(sorted(result["created"] for result in results), [False, True])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_clients").fetchone()["n"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_bookings").fetchone()["n"], 1)

    def test_cancel_racing_convert_never_leaves_cancelled_booked_inquiry(self):
        item = self.create()
        self.race(lambda: inquiries.cancel(self.db, -505, {"inquiry_id": item}), lambda: inquiries.convert(self.db, -101, {"inquiry_id": item, **self.conversion()}, -101))
        row = inquiries.detail(self.db, -505, item)
        bookings = self.db.execute("SELECT COUNT(*) n FROM commercial_bookings").fetchone()["n"]
        self.assertIn((row["status"], bookings), (("cancelled", 0), ("accepted", 1)))


class SQLiteInquiryRaces(InquiryRaces, unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.prepare(database.SQLiteConnection(str(Path(self.directory.name)/"inquiries.sqlite3")))
    def tearDown(self):self.close();self.directory.cleanup()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"), "requires isolated PostgreSQL test database")
class PostgreSQLInquiryRaces(InquiryRaces, unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema = "inquiry_race_" + uuid.uuid4().hex
        url = os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control = database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "' + self.schema + '"')
        self.prepare(IsolatedPostgres(url, self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "' + self.schema + '" CASCADE');self.control.close()


if __name__ == "__main__":unittest.main()
