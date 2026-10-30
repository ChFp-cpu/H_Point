"""Whole-RUB escrow snapshots, preserved legacy obligations and race safety."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from hpoint import billing, database, personal, reliability, services, workflow


class MoneyScenarios:
    def prepare(self, connection):
        self.db = connection
        self.patches = [patch.object(module, "db", connection) for module in (database, services, billing)]
        self.patches.append(patch.object(database, "REGISTRATION_BONUS_RUB", 0))
        for item in self.patches: item.start()
        database.init_db()
        for uid in range(1, 7):
            database.create_user(uid, "Synthetic pricing participant", web_verified=True)
            self.db.execute("UPDATE users SET balance=1000 WHERE user_id=?", (uid,))
        self.db.execute("UPDATE users SET role='admin' WHERE user_id=4")
        self.pro(1)

    def close(self):
        for item in reversed(self.patches): item.stop()
        self.db.close()

    def pro(self, uid, active=True):
        self.db.execute("UPDATE users SET pro_until=? WHERE user_id=?", ((datetime.now(timezone.utc)+timedelta(days=30 if active else -1)).isoformat(), uid))

    def request(self, reward=1000, owner=1, **extra):
        return services.create_request(owner, dict(what="Synthetic paid help", place="Local fixture", time_needed="Today", urgency="Normal", details="No real data", category="tech", reward_rub=reward, **extra))

    def legacy(self, reward=400, owner=1, **extra):
        # This simulates a pre-upgrade record rather than pretending that new
        # public creation can choose historical pricing.
        rid = database.insert_id("INSERT INTO requests(requester_id,category,what,place,time_needed,urgency,details,status,reward_rub) VALUES(?,'tech','Historical agreement','Fixture','Today','Normal','Fixture','open',?)", (owner, reward))
        for key, value in extra.items():
            assert key in {"helper_id", "status", "requester_rating", "priority_boost", "reward_payment_status", "reward_test_rub", "commission_rub", "helper_reward_rub"}
            self.db.execute("UPDATE requests SET " + key + "=? WHERE id=?", (value, rid))
        return rid

    def funds(self, amount, owner=1, test=True):
        database.wallet_add_entry(owner, amount, "test" if test else "payment", "Synthetic funds", uuid.uuid4().hex, test_amount_rub=amount if test else 0)

    def funded(self, reward=1000, balance=None):
        total = workflow.quote_new_reward(reward)["total_rub"]
        self.funds(total if balance is None else balance)
        rid = self.request(reward)
        self.assertTrue(services.reserve_request_reward(rid, 1, total))
        return rid

    def race(self, *functions):
        gate = threading.Barrier(len(functions))
        def run(function):
            try:
                gate.wait(timeout=5)
                return function()
            finally:
                self.db.close()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            return [future.result(timeout=20) for future in [pool.submit(run, function) for function in functions]]

    def test_quote_rounding_and_validation_are_integer_only(self):
        for reward, fee in ((0, 0), (1, 0), (3, 0), (4, 1), (10, 2), (999, 150), (1000, 150), (100000, 15000)):
            quote = workflow.quote_new_reward(reward)
            self.assertEqual((quote["helper_rub"], quote["commission_rub"], quote["total_rub"]), (reward, fee, reward+fee))
            self.assertEqual(quote["currency"], "TEST_RUB")
        for invalid in (True, False, -1, 100001, 10.0, 0.15, "1.5", "nan", "-1"):
            with self.assertRaises(ValueError): workflow.quote_new_reward(invalid)

    def test_creation_snapshots_terms_but_never_reserves_or_copies_client_pricing(self):
        rid = self.request(1000, reward_pricing_version="legacy_v1", reward_total_rub=1, commission_rub=0, helper_reward_rub=1)
        row = database.get_request(rid)
        self.assertEqual((row["reward_pricing_version"], row["reward_rub"], row["helper_reward_rub"], row["commission_rub"], row["reward_total_rub"]), ("top_up15_v1", 1000, 1000, 150, 1150))
        self.assertEqual(row["reward_payment_status"], "none")
        self.assertEqual(reliability.wallet_balances(self.db, 1), (0, 0))
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions WHERE request_id=?", (rid,)).fetchone()["n"], 0)

    def test_full_total_and_only_test_wallet_are_required(self):
        self.funds(2000, test=False)
        self.funds(1149)
        rid = self.request()
        with self.assertRaisesRegex(ValueError, "reward changed"): services.reserve_request_reward(rid, 1, 1000)
        with self.assertRaisesRegex(ValueError, "insufficient wallet"): services.reserve_request_reward(rid, 1, 1150)
        self.assertEqual(database.get_request(rid)["reward_payment_status"], "none")
        self.funds(1)
        self.assertTrue(services.reserve_request_reward(rid, 1, 1150))
        self.assertFalse(services.reserve_request_reward(rid, 1, 1150))
        self.assertEqual(reliability.wallet_balances(self.db, 1), (2000, 0))
        self.assertEqual(database.get_request(rid)["reward_test_rub"], 1150)
        self.assertEqual(database.wallet_summary(1)["test_reserved_rub"], 1150)

    def test_single_full_payout_commission_and_no_paid_hp(self):
        rid = self.funded()
        self.assertEqual(services.accept_open_request(rid, 2), "created")
        self.assertEqual(workflow.test_wallet_summary(database.wallet_summary(2))["incoming_rub"], 1000)
        self.assertFalse(services.complete_request(rid, 2, confirmed_by=2))
        self.assertTrue(services.complete_request(rid, 2, confirmed_by=1))
        self.assertFalse(services.complete_request(rid, 2, confirmed_by=1))
        self.assertFalse(services.cancel_request(rid, 1))
        self.assertEqual(reliability.wallet_balances(self.db, 2), (1000, 1000))
        self.assertEqual(workflow.platform_income(self.db)["earned_test_rub"], 150)
        self.assertEqual([database.get_user(uid)["balance"] for uid in (1, 2)], [1000, 1000])
        self.assertEqual(database.get_request(rid)["hp_settled"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions WHERE request_id=? AND kind='reward_earned'", (rid,)).fetchone()["n"], 1)
        self.assertEqual(self.db.execute("SELECT gross_test_rub FROM platform_commissions WHERE request_id=?", (rid,)).fetchone()["gross_test_rub"], 1150)
        self.assertIn("1000", services.request_reward_note(database.get_request(rid)))

    def test_cancel_helper_admin_and_expiry_refund_full_escrow(self):
        for path in ("author", "helper", "admin", "expiry"):
            with self.subTest(path=path):
                before = reliability.wallet_balances(self.db, 1)
                self.funds(1150)
                rid = self.request()
                services.reserve_request_reward(rid, 1, 1150)
                if path == "helper": services.accept_open_request(rid, 2)
                if path == "admin": self.assertTrue(database.admin_cancel_request(4, rid)[0])
                elif path == "expiry":
                    self.db.execute("UPDATE requests SET expires_at=? WHERE id=?", ((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(), rid))
                    services.expire_open_requests()
                else: self.assertTrue(services.cancel_request(rid, 2 if path == "helper" else 1))
                self.assertFalse(services.cancel_request(rid, 1))
                self.assertEqual(reliability.wallet_balances(self.db, 1), (before[0]+1150, before[1]+1150))
                self.assertEqual(database.get_request(rid)["reward_payment_status"], "wallet_refunded")
                self.assertEqual(self.db.execute("SELECT amount_rub FROM wallet_transactions WHERE reference=?", (f"request:{rid}:refund",)).fetchone()["amount_rub"], 1150)
        self.assertEqual(workflow.platform_income(self.db)["earned_test_rub"], 0)

    def test_dispute_blocks_payout_until_resolution(self):
        rid = self.funded()
        services.accept_open_request(rid, 2)
        self.assertTrue(database.create_request_dispute(rid, 1, "Synthetic dispute"))
        self.assertFalse(services.complete_request(rid, 2, confirmed_by=1))
        self.assertEqual(reliability.wallet_balances(self.db, 2), (0, 0))
        self.assertTrue(database.resolve_request_dispute(4, rid, "Synthetic resolution"))
        self.assertTrue(services.complete_request(rid, 2, confirmed_by=1))

    def test_failed_payout_rolls_back_completion_and_commission(self):
        rid = self.funded(); services.accept_open_request(rid, 2)
        with patch.object(services, "wallet_add_entry", return_value=False):
            with self.assertRaisesRegex(ValueError, "payout already"): services.complete_request(rid, 2, confirmed_by=1)
        self.assertEqual(database.get_request(rid)["status"], "in_progress")
        self.assertEqual(workflow.platform_income(self.db)["completed_paid_helps"], 0)
        self.assertTrue(services.complete_request(rid, 2, confirmed_by=1))

    def test_failed_refund_rolls_back_cancellation(self):
        rid = self.funded()
        with patch.object(services, "wallet_add_entry", return_value=False):
            with self.assertRaisesRegex(ValueError, "refund snapshot"): services.cancel_request(rid, 1)
        self.assertEqual(database.get_request(rid)["status"], "open")
        self.assertEqual(database.get_request(rid)["reward_payment_status"], "paid")
        self.assertTrue(services.cancel_request(rid, 1))

    def test_legacy_test_deduction_is_not_repriced(self):
        self.funds(400); rid = self.legacy()
        services.reserve_request_reward(rid, 1, 400)
        services.accept_open_request(rid, 2)
        self.assertEqual(workflow.reward_quote(database.get_request(rid))["helper_rub"], 340)
        self.assertTrue(services.complete_request(rid, 2, confirmed_by=1))
        self.assertEqual(reliability.wallet_balances(self.db, 2), (340, 340))
        self.assertEqual(workflow.platform_income(self.db)["earned_test_rub"], 60)

    def test_legacy_real_and_mixed_preserve_original_full_payout(self):
        for test_part in (0, 100):
            with self.subTest(test_part=test_part):
                self.funds(400-test_part, test=False)
                if test_part: self.funds(test_part)
                rid = self.legacy(reward_payment_status="paid", reward_test_rub=test_part)
                database.wallet_add_entry(1, -400, "reward_reserve", "Historical reserve", f"request:{rid}:reserve", rid, test_amount_rub=-test_part)
                services.accept_open_request(rid, 2)
                before = reliability.wallet_balances(self.db, 2)
                self.assertTrue(services.complete_request(rid, 2, confirmed_by=1))
                self.assertEqual(reliability.wallet_balances(self.db, 2), (before[0]+400, before[1]+test_part))
                quote = workflow.reward_quote(database.get_request(rid))
                self.assertEqual((quote["helper_rub"], quote["commission_rub"]), (400, 0))
        self.assertEqual(workflow.platform_income(self.db)["earned_test_rub"], 0)

    def test_legacy_old_completed_amount_and_existing_snapshots_survive_schema_upgrade(self):
        rid = self.legacy(status="done", reward_payment_status="released", reward_test_rub=400)
        self.assertEqual(workflow.reward_quote(database.get_request(rid))["helper_rub"], 400)
        self.db.execute("UPDATE requests SET commission_rub=60,helper_reward_rub=340 WHERE id=?", (rid,))
        workflow.record_commission(self.db, rid, 400)
        old = dict(database.get_request(rid))
        ledger = [dict(row) for row in self.db.execute("SELECT * FROM wallet_transactions ORDER BY id").fetchall()]
        self.db.execute("ALTER TABLE requests DROP COLUMN reward_pricing_version")
        self.db.execute("ALTER TABLE requests DROP COLUMN reward_total_rub")
        workflow.initialize_schema(self.db); workflow.initialize_schema(self.db)
        current = dict(database.get_request(rid))
        self.assertEqual({key: current[key] for key in old}, old)
        self.assertEqual(workflow.reward_quote(current)["helper_rub"], 340)
        self.assertEqual([dict(row) for row in self.db.execute("SELECT * FROM wallet_transactions ORDER BY id").fetchall()], ledger)
        self.assertEqual(workflow.platform_income(self.db)["earned_test_rub"], 60)

    def test_snapshot_is_not_recalculated_when_global_percentage_changes(self):
        rid = self.request()
        with patch.object(workflow, "COMMISSION_PERCENT", 99):
            quote = workflow.reward_quote(database.get_request(rid))
            self.assertEqual((quote["helper_rub"], quote["commission_rub"], quote["total_rub"]), (1000, 150, 1150))

    def test_nested_creation_rolls_back_with_outer_transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        rid = self.request()
        self.db.execute("ROLLBACK")
        self.assertIsNone(database.get_request(rid))
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM request_events WHERE request_id=?", (rid,)).fetchone()["n"], 0)

    def test_own_request_does_not_block_help_but_helper_concurrency_remains_one(self):
        self.request(0, owner=2)
        first = self.request(0)
        self.assertEqual(services.accept_open_request(first, 2), "created")
        other = self.request(0, owner=3)
        self.assertEqual(services.accept_open_request(other, 2), "unavailable")

    def test_pro_helper_bonus_is_live_small_and_never_beats_wrong_category(self):
        rid = self.request(0)
        for uid in (2, 3):
            services.set_helper_categories(uid, ["tech"]); services.add_to_queue(uid)
        self.pro(3)
        ranked = services.smart_match(rid)
        self.assertEqual(ranked[0]["user_id"], 3)
        score = {row["user_id"]: row["score"] for row in ranked}
        self.assertEqual(score[3]-score[2], 8)
        services.apply_to_request(rid, 2); services.apply_to_request(rid, 3)
        self.assertEqual(services.get_request_applications(1)[0]["helper_id"], 3)
        services.set_helper_categories(3, ["study"])
        self.assertEqual(services.get_request_applications(1)[0]["helper_id"], 2)
        services.set_helper_categories(3, ["tech"]); self.pro(3, False)
        rows = services.get_request_applications(1)
        self.assertTrue(all(not row["pro_active"] for row in rows))
        self.assertEqual(rows[0]["score"], rows[1]["score"])

    def test_matching_reputation_and_legacy_request_boost_keep_weight(self):
        rid = self.request(0)
        self.legacy(0, owner=6, status="done", helper_id=2, requester_rating=5)
        for uid in (2, 3): services.set_helper_categories(uid, ["tech"]); services.add_to_queue(uid)
        self.pro(3)
        self.assertEqual(services.smart_match(rid)[0]["user_id"], 2)
        old_boost = self.legacy(0, owner=5, priority_boost=100)
        self.assertEqual(services.smart_requests_for_helper(2)[0]["request"]["id"], old_boost)
        self.assertEqual(database.get_request(old_boost)["priority_boost"], 100)

    def test_pro_bonus_cannot_promote_an_incompatible_application_over_a_suitable_helper(self):
        rid = self.request(0, lat=0, lon=0)
        services.set_helper_categories(2, ["tech"])
        services.set_helper_categories(3, ["study"])
        self.pro(3)
        self.db.execute("UPDATE users SET lat=0,lon=0,verified_until=? WHERE user_id=3", ((datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),))
        self.legacy(0, owner=5, status="done", helper_id=3, requester_rating=4)
        self.legacy(0, owner=6, status="done", helper_id=3, requester_rating=5)
        for uid in (2, 3): self.assertEqual(services.apply_to_request(rid, uid), "created")
        applications = services.get_request_applications(1)
        # Without the suitability guard, the extra eight PRO points alone
        # would turn this wrong-category candidate's 116 into 124 (>120).
        self.assertEqual(applications[0]["helper_id"], 2)
        self.assertEqual(next(row for row in applications if row["helper_id"] == 3)["score"], 116)
        matches = services.smart_match(rid)
        self.assertEqual(matches[0]["user_id"], 2)
        self.assertTrue(next(row for row in matches if row["user_id"] == 3)["pro_active"])

    def test_parallel_reserve_is_single_and_cannot_overdraw(self):
        self.funds(1150); rid = self.request()
        result = self.race(lambda: services.reserve_request_reward(rid, 1, 1150), lambda: services.reserve_request_reward(rid, 1, 1150))
        self.assertEqual(sum(result), 1)
        self.assertEqual(reliability.wallet_balances(self.db, 1), (0, 0))
        other = self.request()
        with self.assertRaisesRegex(ValueError, "insufficient wallet"): services.reserve_request_reward(other, 1, 1150)

    def test_parallel_complete_and_cancel_has_one_conserving_result(self):
        rid = self.funded(); services.accept_open_request(rid, 2)
        result = self.race(lambda: services.complete_request(rid, 2, confirmed_by=1), lambda: services.cancel_request(rid, 1))
        self.assertEqual(sum(result), 1)
        self.assertEqual(sum(reliability.wallet_balances(self.db, uid)[0] for uid in (1, 2))+workflow.platform_income(self.db)["earned_test_rub"], 1150)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions WHERE request_id=? AND kind IN ('reward_earned','reward_refund')", (rid,)).fetchone()["n"], 1)

    def test_parallel_distinct_reserves_cannot_spend_fee_twice(self):
        self.funds(1150)
        first, second = self.request(), self.request()
        def reserve(rid):
            try:
                return services.reserve_request_reward(rid, 1, 1150)
            except ValueError as error:
                self.assertEqual(str(error), "insufficient wallet")
                return False
        self.assertEqual(sum(self.race(lambda: reserve(first), lambda: reserve(second))), 1)
        self.assertEqual(reliability.wallet_balances(self.db, 1), (0, 0))
        self.assertEqual(database.wallet_summary(1)["test_reserved_rub"], 1150)

    def test_parallel_completion_never_duplicates_payout_or_commission(self):
        rid = self.funded(); services.accept_open_request(rid, 2)
        self.assertEqual(sum(self.race(lambda: services.complete_request(rid, 2, confirmed_by=1), lambda: services.complete_request(rid, 2, confirmed_by=1))), 1)
        self.assertEqual(reliability.wallet_balances(self.db, 2), (1000, 1000))
        self.assertEqual(workflow.platform_income(self.db)["earned_test_rub"], 150)

    def test_parallel_reserve_and_cancel_never_strands_fee(self):
        self.funds(1150); rid = self.request()
        def reserve():
            try:
                return services.reserve_request_reward(rid, 1, 1150)
            except ValueError as error:
                self.assertEqual(str(error), "request unavailable")
                return False
        self.race(reserve, lambda: services.cancel_request(rid, 1))
        self.assertEqual(database.get_request(rid)["status"], "cancelled")
        self.assertNotEqual(database.get_request(rid)["reward_payment_status"], "paid")
        self.assertEqual(reliability.wallet_balances(self.db, 1), (1150, 1150))
        self.assertEqual(workflow.platform_income(self.db)["earned_test_rub"], 0)


class SQLiteMoney(MoneyScenarios, unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="hpoint-pricing-")
        self.prepare(database.SQLiteConnection(str(Path(self.folder.name)/"fixture.db")))

    def tearDown(self):
        self.close(); self.folder.cleanup()


class PricingPostgresConnection(database.PostgresConnection):
    def __init__(self, url, schema):
        super().__init__(url); self.schema = schema

    def _connection(self):
        connection = super()._connection()
        if getattr(self._local, "configured", None) is not connection:
            connection.execute('SET search_path TO "'+self.schema+'"')
            connection.execute("SET statement_timeout TO '10s'")
            connection.execute("SET lock_timeout TO '8s'")
            self._local.configured = connection
        return connection


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"), "requires isolated PostgreSQL test database")
class PostgresMoney(MoneyScenarios, unittest.TestCase):
    def setUp(self):
        self.schema = "hpoint_pricing_"+uuid.uuid4().hex
        self.control = database.PostgresConnection(os.environ["HPOINT_TEST_DATABASE_URL"])
        self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(PricingPostgresConnection(os.environ["HPOINT_TEST_DATABASE_URL"], self.schema))

    def tearDown(self):
        self.close()
        self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE')
        self.control.close()


if __name__ == "__main__": unittest.main()
