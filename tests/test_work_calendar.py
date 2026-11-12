"""Actual private iCalendar output, UTC boundaries and tenant permissions."""
from datetime import datetime, timedelta, timezone
import os
import sqlite3
import unittest
import uuid
from unittest.mock import patch

from hpoint import commercial as c, commercial_team as team, database, work_calendar


def unfold(body):
    return body.decode("utf-8").replace("\r\n ", "")


class CalendarCases:
    def prepare(self, db):
        self.db = db
        self.patches = [patch.object(database, "db", db), patch.object(database, "REGISTRATION_BONUS_RUB", 0)]
        for item in self.patches:
            item.start()
        database.init_db()
        for uid in (-101, -202, -303):
            database.create_user(uid, "Synthetic calendar user", email=f"calendar{abs(uid)}@example.test", web_verified=True)
            db.execute("UPDATE users SET email_verified=1 WHERE user_id=?", (uid,))
        c.save_profile(db, -101, {"title": "Мастерская календаря", "kind": "organization"})
        c.save_profile(db, -303, {"title": "Foreign organisation", "kind": "organization"})
        invitation = team.invite(db, -101, {"email": "calendar202@example.test"})
        team.invitation_action(db, -202, {"invitation_id": invitation["id"]}, "accept", -101)
        self.client = c.save_client(db, -101, {"name": "PRIVATE CLIENT NAME", "contact": "PRIVATE CONTACT", "notes": "PRIVATE CRM"})["id"]

    def close(self):
        self.db.close()
        for item in reversed(self.patches):
            item.stop()

    def booking(self, **fields):
        return c.save_booking(self.db, -101, {"title": "Обсудить проект", "client_id": self.client,
            "starts_at": "2030-02-01T12:00:00+03:00", "notes": "PRIVATE BOOKING NOTE", **fields})["id"]

    def export(self, **fields):
        return work_calendar.export_calendar(self.db, -101, owner_id=-101,
            **{"starts_on": "2030-02-01", "ends_on": "2030-02-01", **fields})

    def test_native_calendar_has_utc_end_stable_uid_and_no_private_crm(self):
        item = self.booking(duration_minutes=75, price_rub=333)
        result = self.export()
        text = unfold(result["body"])
        self.assertEqual(result["content_type"], "text/calendar; charset=utf-8")
        self.assertTrue(result["filename"].endswith(".ics"))
        for expected in ("BEGIN:VCALENDAR", "VERSION:2.0", "CLASS:PRIVATE", "DTSTART:20300201T090000Z", "DTEND:20300201T101500Z", f"UID:hpoint--101-bookings-{item}@gethpoint.ru"):
            self.assertIn(expected, text)
        for secret in ("PRIVATE CLIENT", "PRIVATE CONTACT", "PRIVATE CRM", "PRIVATE BOOKING", "333", "ATTENDEE", "VALARM"):
            self.assertNotIn(secret, text)
        self.assertIn(f"UID:hpoint--101-bookings-{item}@gethpoint.ru", unfold(self.export()["body"]))
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_bookings").fetchone()["n"], 1)

    def test_local_midnight_overlapping_previous_day_and_end_exclusion(self):
        self.booking(title="Previous evening", starts_at="2030-01-31T20:30:00Z", duration_minutes=120)
        self.booking(title="Local late evening", starts_at="2030-02-01T20:30:00Z")
        self.booking(title="Next local day", starts_at="2030-02-01T21:00:00Z")
        text = unfold(self.export(timezone_minutes="180")["body"])
        self.assertIn("SUMMARY:Previous evening", text)
        self.assertIn("SUMMARY:Local late evening", text)
        self.assertNotIn("SUMMARY:Next local day", text)

    def test_only_planned_and_selected_person_and_kind(self):
        self.booking(title="Assigned booking", assignee_id=-202)
        self.booking(title="Other booking", assignee_id=-101)
        self.booking(title="Cancelled booking", status="cancelled")
        self.booking(title="Completed booking", status="completed")
        team.save_shift(self.db, -101, {"title": "Assigned shift", "assignee_id": -202,
            "starts_at": "2030-02-01T08:00:00Z", "ends_at": "2030-02-01T16:00:00Z", "notes": "PRIVATE SHIFT"})
        text = unfold(self.export(person="-202")["body"])
        self.assertIn("Assigned booking", text)
        self.assertIn("Assigned shift", text)
        for hidden in ("Other booking", "Cancelled booking", "Completed booking", "PRIVATE SHIFT"):
            self.assertNotIn(hidden, text)
        self.assertNotIn("Assigned shift", unfold(self.export(kind="bookings")["body"]))
        self.assertNotIn("Assigned booking", unfold(self.export(kind="shifts")["body"]))
        with self.assertRaises(ValueError):
            self.export(person="-303")

    def test_escape_injection_multibyte_folding_and_empty_calendar(self):
        self.assertNotIn("BEGIN:VEVENT", unfold(self.export()["body"]))
        title = "Занятие; путь, \\ и\nEND:VEVENT\nBEGIN:VEVENT " + "я🙂" * 20
        self.booking(title=title)
        body = self.export()["body"]
        for line in body.split(b"\r\n"):
            self.assertLessEqual(len(line), 75)
            line.decode("utf-8")
        text = unfold(body)
        self.assertEqual(text.count("\r\nBEGIN:VEVENT\r\n"), 1)
        self.assertIn("Занятие\\; путь\\, \\\\ и\\nEND:VEVENT\\nBEGIN:VEVENT", text)
        self.assertNotIn(b"\n", body.replace(b"\r\n", b""))

    def test_expired_read_access_membership_revocation_and_blocked_guards(self):
        self.booking()
        self.db.execute("UPDATE commercial_profiles SET trial_until='2020-01-01T00:00:00Z' WHERE user_id=-101")
        fields = {"owner_id": -101, "starts_on": "2030-02-01", "ends_on": "2030-02-01"}
        self.assertIn("BEGIN:VEVENT", unfold(work_calendar.export_calendar(self.db, -202, **fields)["body"]))
        with self.assertRaises(PermissionError):
            work_calendar.export_calendar(self.db, -303, **fields)
        self.db.execute("DELETE FROM commercial_members WHERE owner_id=-101 AND user_id=-202")
        with self.assertRaises(PermissionError):
            work_calendar.export_calendar(self.db, -202, **fields)
        self.db.execute("UPDATE users SET is_blocked=1 WHERE user_id=-101")
        with self.assertRaises(ValueError):
            self.export()

    def test_invalid_dates_types_ranges_and_timezones(self):
        for fields in ({"starts_on": "2030-02-30"}, {"ends_on": "2030-01-30"},
                       {"ends_on": "2032-02-01"}, {"starts_on": "9999-12-31", "ends_on": "9999-12-31"},
                       {"kind": "health"}, {"timezone_minutes": "841"}, {"timezone_minutes": True},
                       {"timezone_minutes": "1.5"}, {"person": "bad"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.export(**fields)

    def test_default_local_period_and_full_export_beyond_dashboard_limit(self):
        fixed = datetime(2030, 2, 1, 0, 30, tzinfo=timezone.utc)
        with patch.object(c, "_now", return_value=fixed):
            result = work_calendar.export_calendar(self.db, -101, timezone_minutes="-180")
        self.assertEqual(result["filename"], "hpoint-calendar-2030-01-31-2030-03-02.ics")
        for index in range(305):
            self.booking(title=f"Record {index}")
        self.assertEqual(unfold(self.export()["body"]).count("BEGIN:VEVENT"), 305)

    def test_dashboard_keeps_next_appointment_over_far_future_history(self):
        now = c._now()
        nearby = self.booking(title="Nearest appointment", starts_at=(now + timedelta(hours=1)).isoformat())
        for index in range(302):
            self.booking(title=f"Future {index}", starts_at=(now + timedelta(days=index + 2)).isoformat())
        data = c.dashboard(self.db, -101)
        self.assertEqual(data["bookings"][0]["id"], nearby)
        self.assertEqual(len(data["bookings"]), 300)
        self.assertEqual(data["record_counts"]["bookings"], 303)
        self.assertTrue(data["search_limited"])

    def test_dashboard_keeps_current_shift_and_pending_task_over_completed_history(self):
        now = c._now()
        shift = team.save_shift(self.db, -101, {"title":"Current overnight shift", "assignee_id":-101,
            "starts_at":(now-timedelta(hours=4)).isoformat(), "ends_at":(now+timedelta(hours=4)).isoformat()})["id"]
        task = team.save_task(self.db, -101, {"title":"Unfinished priority task", "due_at":(now-timedelta(days=2)).isoformat()})["id"]
        for index in range(1001):
            team.save_shift(self.db, -101, {"title":f"Future shift {index}", "assignee_id":-101,
                "starts_at":(now+timedelta(days=index+1)).isoformat(), "ends_at":(now+timedelta(days=index+1,hours=1)).isoformat()})
            team.save_task(self.db, -101, {"title":f"Completed task {index}", "status":"done"})
        data=c.dashboard(self.db,-101)
        self.assertEqual(data["shifts"][0]["id"],shift)
        self.assertEqual(data["tasks"][0]["id"],task)
        self.assertEqual(data["record_counts"]["shifts"],1002)
        self.assertEqual(data["record_counts"]["tasks"],1002)
        self.assertTrue(data["search_limited"])

    def test_booking_end_overflow_is_rejected_and_legacy_outside_period_cannot_break_export(self):
        with self.assertRaisesRegex(ValueError,"длительность"):
            self.booking(starts_at="9999-12-31T23:59:00Z",duration_minutes=60)
        self.booking(title="Valid appointment")
        item=self.booking(title="Legacy broken distant date")
        self.db.execute("UPDATE commercial_bookings SET starts_at='9999-12-31T23:59:00Z' WHERE id=?",(item,))
        self.assertEqual(unfold(self.export()["body"]).count("BEGIN:VEVENT"),1)


class SQLiteCalendar(CalendarCases, unittest.TestCase):
    def setUp(self):
        db = sqlite3.connect(":memory:", isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        self.prepare(db)

    def tearDown(self):
        self.close()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"), "requires isolated PostgreSQL test database")
class PostgreSQLCalendar(CalendarCases, unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema = "calendar_qa_" + uuid.uuid4().hex
        url = os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control = database.PostgresConnection(url)
        self.control.execute('CREATE SCHEMA "' + self.schema + '"')
        self.prepare(IsolatedPostgres(url, self.schema))

    def tearDown(self):
        self.close()
        self.control.execute('DROP SCHEMA "' + self.schema + '" CASCADE')
        self.control.close()


if __name__ == "__main__":
    unittest.main()
