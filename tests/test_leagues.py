"""Help directions and earned leagues over real, isolated completion records."""
from datetime import datetime, timezone
import json
import os
import sqlite3
import unittest
import uuid
from unittest.mock import Mock, patch

from hpoint import database
from hpoint.config import CATEGORIES


class LeagueCases:
    def prepare(self, db):
        self.db = db
        self.patches = [patch.object(database, "db", db), patch.object(database, "REGISTRATION_BONUS_RUB", 0)]
        for item in self.patches:
            item.start()
        database.init_db()
        for uid in range(1, 7):
            self.user(uid)

    def close(self):
        self.db.close()
        for item in reversed(self.patches):
            item.stop()

    def user(self, uid):
        database.create_user(uid, "Synthetic helper " + str(uid), web_verified=True)
        self.db.execute("UPDATE users SET email=?,email_verified=1,city='Synthetic city',bio='PRIVATE BIO',lat=55.123456,lon=37.123456 WHERE user_id=?", (f"private{uid}@example.test", uid))

    def request(self, category="tech", status="done", helper=2, owner=1, rating=None, reward=0, at=None):
        at = at or datetime.now(timezone.utc).isoformat()
        return database.insert_id("""INSERT INTO requests
            (requester_id,helper_id,category,what,place,time_needed,urgency,details,status,
             requester_rating,reward_rub,created_at,completed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            owner, helper, category, "PRIVATE REQUEST TITLE", "PRIVATE ADDRESS", "Today", "Normal",
            "PRIVATE DETAILS", status, rating, reward, at, at if status == "done" else None,
        ))

    def progress(self, category="", user_id=2, days=30):
        return database.community_progress(days=days, category=category, user_id=user_id)

    def test_empty_catalog_has_every_direction_and_a_newcomer_progression(self):
        state = self.progress()
        self.assertEqual(state["summary"], dict(total=0, done=0, active=0, rewards=0))
        self.assertEqual(state["completion_percent"], 0)
        self.assertEqual(state["leaderboard"], [])
        self.assertEqual(state["participants"], 0)
        self.assertEqual({row["key"] for row in state["categories"]}, set(CATEGORIES))
        self.assertTrue(all(row["count"] == row["done"] == row["active"] == 0 for row in state["categories"]))
        self.assertEqual(state["current_user"]["league"]["key"], "newcomer")
        self.assertEqual(state["current_user"]["league"]["remaining"], 1)
        self.assertIsNone(state["current_user"]["position"])
        self.assertEqual([row["min_completed"] for row in state["leagues"]], [0, 1, 5, 15, 40, 100])

    def test_filter_changes_metrics_rankings_and_daily_but_keeps_all_direction_choices(self):
        self.request("tech", rating=5, reward=400)
        self.request("tech", status="in_progress", helper=3)
        self.request("tech", status="open", helper=None)
        self.request("tech", status="cancelled", helper=4, reward=100)
        self.request("shopping", helper=3, rating=4, reward=700)
        self.request("shopping", helper=3, rating=5)
        state = self.progress("tech")
        self.assertEqual(state["summary"], dict(total=4, done=1, active=2, rewards=500))
        self.assertEqual(state["completion_percent"], 25)
        self.assertEqual(sum(row["n"] for row in state["daily"]), 4)
        self.assertEqual(state["selected_category"], "tech")
        self.assertEqual(state["category_title"], CATEGORIES["tech"])
        self.assertEqual([(row["user_id"], row["helped"]) for row in state["leaderboard"]], [(2, 1)])
        self.assertEqual(state["current_user"]["position"], 1)
        categories = {row["key"]: row for row in state["categories"]}
        self.assertEqual((categories["tech"]["count"], categories["tech"]["done"], categories["tech"]["active"]), (4, 1, 2))
        self.assertEqual((categories["shopping"]["count"], categories["shopping"]["done"]), (2, 2))
        self.assertEqual(len(categories), len(CATEGORIES))
        self.assertEqual(self.progress()["leaderboard"][0]["user_id"], 3)
        self.assertEqual(self.progress()["summary"]["total"], 6)

    def test_new_direction_can_immediately_have_its_own_rank_and_league(self):
        category = next(key for key in CATEGORIES if key not in {"carry", "shopping", "snow", "tools", "transport", "tech", "study", "other"})
        self.request(category, rating=5)
        state = self.progress(category)
        self.assertEqual(state["summary"]["done"], 1)
        self.assertEqual(state["leaderboard"][0]["league"]["key"], "bronze")
        self.assertEqual(state["current_user"]["league"]["next_at"], 5)

    def test_rank_position_is_personal_even_after_top_twenty(self):
        for uid in range(2, 27):
            if uid > 6:
                self.user(uid)
            self.request(helper=uid, rating=5)
        state = self.progress(user_id=26)
        self.assertEqual(state["participants"], 25)
        self.assertEqual(len(state["leaderboard"]), 20)
        self.assertEqual(state["leaderboard"][-1]["position"], 20)
        self.assertNotIn(26, [row["user_id"] for row in state["leaderboard"]])
        self.assertEqual(state["current_user"]["position"], 25)
        self.assertEqual(state["current_user"]["helped"], 1)

    def test_email_registered_negative_id_is_retained_in_rank_personal_progress_and_reviews(self):
        uid = database.create_web_user("Synthetic email helper", "negative-league@example.test", "synthetic-unused")
        self.assertLess(uid, 0)
        self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?", (uid,))
        rid = self.request(helper=uid, rating=5)
        state = self.progress(user_id=uid)
        self.assertEqual(state["leaderboard"][0]["user_id"], uid)
        self.assertEqual(state["current_user"]["user_id"], uid)
        self.assertEqual(state["current_user"]["position"], 1)
        self.assertEqual(state["current_user"]["league"]["key"], "bronze")
        self.assertEqual(self.progress("tech", user_id=uid)["current_user"]["user_id"], uid)
        profile = database.community_profile(uid)
        self.assertEqual(profile["id"], uid)
        self.assertEqual(profile["name"], "Synthetic email helper")
        self.assertEqual(profile["reviews"][0]["request_id"], rid)
        self.assertEqual(profile["reviews"][0]["rating"], 5)

    def test_paid_priority_and_wallet_balance_cannot_buy_league_or_place(self):
        for _ in range(5):
            self.request(helper=2, rating=4)
        self.request(helper=3, rating=5, reward=500)
        self.db.execute("UPDATE users SET pro_until='2099-01-01T00:00:00+00:00',balance=999999999 WHERE user_id=3")
        state = self.progress(user_id=3)
        self.assertEqual([(row["user_id"], row["league"]["key"]) for row in state["leaderboard"]], [(2, "silver"), (3, "bronze")])
        self.assertEqual(state["current_user"]["position"], 2)
        self.assertEqual(database.get_user(3)["balance"], 999999999)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"], 0)

    def test_category_progress_is_earned_in_that_direction(self):
        for _ in range(5):
            self.request("tech")
        self.request("shopping")
        self.assertEqual(self.progress()["current_user"]["league"]["key"], "silver")
        self.assertEqual(self.progress("tech")["current_user"]["league"]["key"], "silver")
        self.assertEqual(self.progress("shopping")["current_user"]["league"]["key"], "bronze")
        self.assertEqual(self.progress("other")["current_user"]["league"]["key"], "newcomer")
        self.assertIsNone(self.progress("other")["current_user"]["position"])

    def test_league_thresholds_and_progress_are_bounded(self):
        cases = [(-1, "newcomer", 1, 0), (0, "newcomer", 1, 0), (1, "bronze", 4, 0),
                 (3, "bronze", 2, 50), (4, "bronze", 1, 75), (5, "silver", 10, 0),
                 (14, "silver", 1, 90), (15, "gold", 25, 0), (40, "platinum", 60, 0),
                 (99, "platinum", 1, 98), (100, "diamond", 0, 100), (1000, "diamond", 0, 100)]
        for completed, key, remaining, percent in cases:
            with self.subTest(completed=completed):
                league = database.help_league(completed)
                self.assertEqual((league["key"], league["remaining"], league["progress_percent"]), (key, remaining, percent))
        self.assertIsNone(database.help_league(100)["next_at"])

    def test_only_completed_nonself_help_counts_for_rank_and_blocked_users_disappear(self):
        self.request(helper=2, rating=5)
        self.request(helper=3, rating=5)
        self.request(helper=3, rating=5)
        self.request(helper=4, owner=4, rating=5)
        for status in ("open", "in_progress", "cancelled"):
            self.request(helper=5, status=status, rating=5)
        self.db.execute("UPDATE users SET is_blocked=1 WHERE user_id=3")
        state = self.progress(user_id=3)
        self.assertEqual([row["user_id"] for row in state["leaderboard"]], [2])
        self.assertEqual(state["participants"], 1)
        self.assertIsNone(state["current_user"])
        self.assertEqual(self.progress(user_id=4)["current_user"]["helped"], 0)

    def test_ties_use_review_average_then_stable_id_without_faking_unreviewed_rating(self):
        self.request(helper=2, rating=None)
        self.request(helper=3, rating=5)
        self.request(helper=4, rating=5)
        state = self.progress()
        self.assertEqual([row["user_id"] for row in state["leaderboard"]], [3, 4, 2])
        self.assertEqual(state["current_user"]["position"], 3)
        self.assertIsNone(state["current_user"]["rating"])
        self.assertEqual(state["current_user"]["reviews"], 0)

    def test_activity_window_does_not_expire_all_time_league(self):
        for _ in range(5):
            self.request(at="2020-01-01T00:00:00+00:00")
        for days in (7, 30, 365):
            state = self.progress(days=days)
            self.assertEqual(state["daily"], [])
            self.assertEqual(state["current_user"]["league"]["key"], "silver")
            self.assertEqual(state["summary"]["done"], 5)

    def test_public_output_never_exposes_contacts_request_details_or_exact_location(self):
        self.request(rating=5)
        payload = json.dumps(self.progress(), ensure_ascii=False)
        for secret in ("PRIVATE", "example.test", "55.123456", "37.123456", "password_hash", "helper_categories"):
            self.assertNotIn(secret, payload)
        self.assertIsNone(database.community_progress()["current_user"])
        self.assertIsNone(self.progress(user_id=99999)["current_user"])

    def test_unknown_and_nonstring_categories_rejected_before_query(self):
        for category in ("unknown", "tech' OR 1=1 --", [], None, 1):
            with self.subTest(category=category), self.assertRaises(ValueError):
                self.progress(category)
        self.assertEqual(self.progress("other")["selected_category"], "other")

    def test_number_of_queries_does_not_grow_with_direction_catalog_or_rank_size(self):
        self.request()
        spy = Mock(wraps=self.db)
        with patch.object(database, "db", spy):
            state = self.progress()
        self.assertEqual(state["current_user"]["position"], 1)
        self.assertEqual(spy.execute.call_count, 4)


class SQLiteLeagues(LeagueCases, unittest.TestCase):
    def setUp(self):
        db = sqlite3.connect(":memory:", isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        self.prepare(db)

    def tearDown(self):
        self.close()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"), "requires isolated PostgreSQL test database")
class PostgreSQLLeagues(LeagueCases, unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema = "leagues_qa_" + uuid.uuid4().hex
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
