"""Stale help actions cannot revive expired requests or distort ratings."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import os
import threading
import unittest
from unittest.mock import patch
import uuid

from hpoint import database, services
from test_invitations import InvitationData


class HelpLifecycleBoundaries(InvitationData, unittest.TestCase):
    def setUp(self):self.prepare()
    def tearDown(self):self.close()

    def expire(self, rid=None):
        self.db.execute("UPDATE requests SET expires_at=? WHERE id=?", ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), rid or self.rid))

    def test_stale_application_direct_accept_invitation_and_internal_match_cannot_revive_expired_help(self):
        self.expire()
        self.assertEqual(services.apply_to_request(self.rid, 2), "unavailable")
        self.assertEqual(services.accept_open_request(self.rid, 2), "unavailable")
        self.assertFalse(services.offer_helper(self.rid, 2))
        self.assertFalse(services.try_assign_helper(self.rid, 2))
        self.assertIsNone(database.get_request(self.rid)["helper_id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM request_candidates").fetchone()["n"], 0)

    def test_stale_author_selection_after_an_application_does_not_assign(self):
        self.assertEqual(services.apply_to_request(self.rid, 2), "created")
        token = self.db.execute("SELECT offer_token FROM request_candidates WHERE request_id=? AND candidate_id=2", (self.rid,)).fetchone()["offer_token"]
        self.expire()
        self.assertEqual(services.accept_open_request(self.rid, 2, author_id=1, application_token=token), "unavailable")
        self.assertEqual(database.get_request(self.rid)["status"], "open")
        self.assertIsNone(database.get_request(self.rid)["helper_id"])

    def test_stale_invitation_acceptance_does_not_assign_but_decline_stays_available(self):
        self.assertTrue(services.offer_helper(self.rid, 2))
        token = self.current()["offer_token"]
        self.expire()
        self.assertFalse(services.respond_to_helper_offer(self.rid, 2, True, token))
        self.assertIsNone(database.get_request(self.rid)["helper_id"])
        self.assertTrue(services.respond_to_helper_offer(self.rid, 2, False, token))

    def test_unreserved_help_stops_accepting_new_interest_at_five_minute_deadline(self):
        self.db.execute("UPDATE requests SET reward_rub=100,reserve_deadline_at=? WHERE id=?", ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), self.rid))
        self.assertEqual(services.apply_to_request(self.rid, 2), "unavailable")
        self.assertFalse(services.offer_helper(self.rid, 2))
        self.assertEqual(services.accept_open_request(self.rid, 2), "unavailable")
        self.assertIsNone(database.get_request(self.rid)["helper_id"])

    def test_running_help_may_finish_after_publication_expiry_and_repeated_accept_is_safe(self):
        self.assertEqual(services.accept_open_request(self.rid, 2), "created")
        self.expire()
        self.assertEqual(services.accept_open_request(self.rid, 2), "existing")
        self.assertTrue(services.complete_request(self.rid, 2, confirmed_by=1))
        self.assertEqual(database.get_request(self.rid)["status"], "done")

    def test_only_integer_star_ratings_are_persisted(self):
        self.assertEqual(services.accept_open_request(self.rid, 2), "created")
        self.assertTrue(services.complete_request(self.rid, 2, confirmed_by=1))
        for value in (True, False, 4.9, 5.0, "5", None, [], {}, 0, 6):
            with self.subTest(value=value):
                self.assertFalse(services.set_rating(self.rid, 1, value))
                self.assertFalse(services.set_helper_rating(self.rid, 2, value))
        row = database.get_request(self.rid)
        self.assertIsNone(row["requester_rating"]);self.assertIsNone(row["helper_rating"])
        self.assertTrue(services.set_rating(self.rid, 1, 5))
        self.assertTrue(services.set_helper_rating(self.rid, 2, 4))

    def test_timezone_overflow_in_helper_preferences_is_a_validation_error(self):
        for value in ("0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-12:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                services.save_helper_preferences(2, ["tech"], ready=True, available_from=value)
        self.assertIsNone(database.get_user(2)["helper_available_from"])


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"), "requires isolated PostgreSQL test database")
class PostgreSQLHelpLifecycleBoundaries(HelpLifecycleBoundaries):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema = "help_boundaries_" + uuid.uuid4().hex
        url = os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control = database.PostgresConnection(url)
        self.control.execute('CREATE SCHEMA "' + self.schema + '"')
        self.db = IsolatedPostgres(url, self.schema)
        self.patches = [patch.object(module, "db", self.db) for module in (database, services)]
        self.patches.append(patch.object(database, "REGISTRATION_BONUS_RUB", 0))
        for item in self.patches:item.start()
        database.init_db()
        for uid in (1, 2, 3, 4):
            database.create_user(uid, f"Synthetic boundary user {uid}", tg_user_id=uid, web_verified=True)
            self.db.execute("UPDATE users SET email=?,email_verified=1 WHERE user_id=?", (f"boundary{uid}@example.test", uid))
            if uid != 1:services.add_to_queue(uid)
        self.db.execute("UPDATE users SET pro_until='2099-01-01T00:00:00+00:00' WHERE user_id=1")
        self.rid = services.create_request(1, {"what": "Synthetic boundary help", "category": "tech", "place": "Synthetic place", "time_needed": "Today", "urgency": "Normal", "details": "Synthetic fixture"})

    def tearDown(self):
        self.close()
        self.control.execute('DROP SCHEMA "' + self.schema + '" CASCADE')
        self.control.close()

    def test_publication_deadline_is_measured_after_waiting_for_request_lock(self):
        at = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)
        clock = [at]
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock[0].astimezone(tz) if tz else clock[0].replace(tzinfo=None)
        self.db.execute("UPDATE requests SET expires_at=? WHERE id=?", ((at+timedelta(seconds=1)).isoformat(), self.rid))
        # Hold the real row lock while an independent thread enters acceptance.
        # Advance a deterministic clock before releasing it; no timing sleeps.
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute("SELECT id FROM requests WHERE id=? FOR UPDATE", (self.rid,)).fetchone()
        attempting = threading.Event()
        original = self.db.execute
        main_thread = threading.get_ident()
        def observed(sql, params=None):
            if threading.get_ident() != main_thread and "SELECT * FROM requests WHERE id=? FOR UPDATE" in sql:
                attempting.set()
            return original(sql, params)
        def accept():
            try:return services.accept_open_request(self.rid, 2)
            finally:self.db.close()
        with patch.object(services, "datetime", Clock), patch.object(self.db, "execute", side_effect=observed), ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(accept)
            try:
                self.assertTrue(attempting.wait(timeout=5), "Acceptance did not reach the held request lock")
                self.assertFalse(pending.done())
                clock[0] = at+timedelta(seconds=2)
            finally:
                self.db.execute("COMMIT")
            self.assertEqual(pending.result(timeout=10), "unavailable")
        self.assertIsNone(database.get_request(self.rid)["helper_id"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"], 0)


if __name__ == "__main__":unittest.main()
