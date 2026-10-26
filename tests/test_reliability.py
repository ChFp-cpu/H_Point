"""Settlement invariants, also exercised against PostgreSQL by test_postgres."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs

from hpoint import database, services, billing, reliability, web


class Scenarios:
    def prepare(self, db):
        self.db = db
        self.patches = [patch.object(m, "db", db) for m in (database, services, billing, web)]
        self.patches.append(patch.object(database, "REGISTRATION_BONUS_RUB", 0))
        for item in self.patches:
            item.start()
        database.init_db()
        for uid in (1, 2, 3, 4):
            database.create_user(uid, "Synthetic participant", web_verified=True)
            db.execute("UPDATE users SET balance=1000 WHERE user_id=?", (uid,))
        db.execute("UPDATE users SET role='admin' WHERE user_id=4")

    def close(self):
        for item in reversed(self.patches):
            item.stop()
        self.db.close()

    def request(self, owner=1, reward=0, **options):
        return services.create_request(owner, dict(what="Synthetic request", place="Test", time_needed="Today",
            urgency="Normal", details="No real data", category="tech", reward_rub=reward, **options))

    def funded(self, amount=400):
        database.grant_registration_bonus(1, 500)
        rid = self.request(reward=amount)
        self.assertTrue(services.reserve_request_reward(rid, 1, amount))
        return rid

    def finish(self, owner=1, helper=2):
        rid = self.request(owner)
        self.assertEqual(services.accept_open_request(rid, helper), "created")
        self.assertTrue(services.complete_request(rid, helper, confirmed_by=owner))
        return rid

    def test_test_reward_stays_test_and_is_paid_once(self):
        rid = self.funded()
        self.assertEqual(database.wallet_summary(1)["test_reserved_rub"], 400)
        self.assertEqual(services.accept_open_request(rid, 2), "created")
        self.assertEqual(database.wallet_summary(2)["test_incoming_rub"], 400)
        self.assertFalse(services.complete_request(rid, 2, confirmed_by=2))
        self.assertTrue(services.complete_request(rid, 2, confirmed_by=1))
        self.assertFalse(services.complete_request(rid, 2, confirmed_by=1))
        self.assertEqual(reliability.wallet_balances(self.db, 2), (340, 340))
        self.assertEqual(database.wallet_summary(2)["balance_rub"], 0)

    def test_real_funds_are_not_spent_in_test_mode(self):
        database.wallet_add_entry(1,300,"payment","Historical real","real-credit")
        database.grant_registration_bonus(1,500)
        too_large=self.request(reward=700)
        with self.assertRaisesRegex(ValueError,"insufficient wallet"):services.reserve_request_reward(too_large,1,700)
        rid=self.request(reward=400)
        services.reserve_request_reward(rid,1,400)
        self.assertEqual(reliability.wallet_balances(self.db,1),(400,100))
        self.assertTrue(services.cancel_request(rid,1))
        self.assertFalse(services.cancel_request(rid,1))
        self.assertEqual(reliability.wallet_balances(self.db,1),(800,500))
        self.assertEqual(database.wallet_summary(1)["balance_rub"],300)

    def test_migration_replays_transfers_without_changing_totals(self):
        rid = self.funded()
        services.accept_open_request(rid, 2)
        services.complete_request(rid, 2, confirmed_by=1)
        billing.purchase_with_wallet(2, "pro", {}, "synthetic-pro")
        self.db.execute("UPDATE wallet_transactions SET test_amount_rub=0")
        self.db.execute("UPDATE requests SET reward_test_rub=0")
        self.db.execute("DELETE FROM schema_migrations WHERE version='006_wallet_sources'")
        before = [reliability.wallet_balances(self.db, u)[0] for u in (1, 2)]
        reliability.migrate_wallet_sources(self.db)
        self.assertEqual([reliability.wallet_balances(self.db, u) for u in (1, 2)], [(100, 100), (191, 191)])
        self.assertEqual(before, [100, 191])
        reliability.migrate_wallet_sources(self.db)
        self.assertEqual(database.get_request(rid)["reward_test_rub"], 400)
        self.assertEqual(reliability.wallet_balances(self.db, 2), (191, 191))

    def test_real_payment_reserve_does_not_spend_test_balance(self):
        database.grant_registration_bonus(1, 500)
        rid = self.request(reward=400)
        invoice, _, _ = billing.create_request_reward_invoice(1, rid)
        self.assertEqual(billing.fulfill_invoice(invoice), (True, "request_reward"))
        self.assertEqual(reliability.wallet_balances(self.db, 1), (500, 500))
        self.assertEqual(database.get_request(rid)["reward_test_rub"], 0)
        services.cancel_request(rid, 1)
        self.assertEqual(reliability.wallet_balances(self.db, 1), (900, 500))

    def test_historical_card_payment_stays_real_after_source_migration(self):
        database.grant_registration_bonus(1,500)
        rid=self.request(reward=400)
        invoice,_,_=billing.create_request_reward_invoice(1,rid)
        billing.fulfill_invoice(invoice)
        services.accept_open_request(rid,2)
        services.complete_request(rid,2,confirmed_by=1)
        self.db.execute("UPDATE wallet_transactions SET test_amount_rub=0")
        self.db.execute("DELETE FROM schema_migrations WHERE version='006_wallet_sources'")
        reliability.migrate_wallet_sources(self.db)
        self.assertEqual(reliability.wallet_balances(self.db,1),(500,500))
        self.assertEqual(reliability.wallet_balances(self.db,2),(400,0))

    def test_historical_cancelled_reserve_is_recovered_once(self):
        rid=self.funded()
        self.db.execute("UPDATE requests SET status='cancelled' WHERE id=?",(rid,))
        self.db.execute("DELETE FROM schema_migrations WHERE version='007_closed_reserves'")
        reliability.reconcile_closed_reserves(self.db,database.wallet_add_entry)
        reliability.reconcile_closed_reserves(self.db,database.wallet_add_entry)
        self.assertEqual(reliability.wallet_balances(self.db,1),(500,500))
        self.assertEqual(database.get_request(rid)["reward_payment_status"],"wallet_refunded")

    def test_late_reward_is_available_real_credit_once(self):
        rid = self.request(reward=400)
        invoice, _, _ = billing.create_request_reward_invoice(1, rid)
        services.cancel_request(rid, 1)
        self.assertEqual(billing.fulfill_invoice(invoice), (True, "credited_to_wallet"))
        self.assertEqual(billing.fulfill_invoice(invoice), (True, "already_paid"))
        self.assertEqual(database.wallet_summary(1)["balance_rub"], 400)
        self.assertEqual(database.get_request(rid)["reward_payment_status"], "none")

    def test_late_promotion_is_available_real_credit(self):
        rid = self.request()
        invoice, _, amount = billing.create_pending_invoice(1, "boost", {"request_id": rid})
        services.cancel_request(rid, 1)
        self.assertEqual(billing.fulfill_invoice(invoice), (True, "credited_to_wallet"))
        billing.fulfill_invoice(invoice)
        self.assertEqual(database.wallet_summary(1)["balance_rub"], amount)
        self.assertEqual(database.get_request(rid)["priority_boost"], 0)

    def test_expired_invoice_credits_wallet_without_reserving(self):
        rid = self.request(reward=400)
        invoice, _, _ = billing.create_request_reward_invoice(1, rid)
        self.db.execute("UPDATE requests SET expires_at='2020-01-01T00:00:00+00:00' WHERE id=?", (rid,))
        self.assertEqual(billing.fulfill_invoice(invoice), (True, "credited_to_wallet"))
        services.expire_open_requests()
        self.assertEqual(database.wallet_summary(1)["balance_rub"], 400)

    def test_invoice_matching_uses_exact_request_id(self):
        ids = [self.request(reward=400) for _ in range(12)]
        last, _, _ = billing.create_request_reward_invoice(1, ids[-1])
        first, _, _ = billing.create_request_reward_invoice(1, ids[0])
        self.assertNotEqual(first, last)
        self.assertEqual(billing.create_request_reward_invoice(1, ids[0])[0], first)

    def test_provider_signatures_amount_and_currency(self):
        invoice, _, amount = billing.create_pending_invoice(1, "pro")
        with patch.multiple(billing, ROBOKASSA_MERCHANT_LOGIN="SyntheticShop", ROBOKASSA_PASSWORD_1="test1",
                            ROBOKASSA_PASSWORD_2="test2", ROBOKASSA_HASH_ALGORITHM="md5",TEST_MONEY_ONLY=False):
            url, _ = billing.create_payment(invoice)
            fields = parse_qs(urlparse(url).query)
            expected = hashlib.md5(f"SyntheticShop:{amount:.2f}:{invoice}:test1".encode()).hexdigest().upper()
            self.assertEqual(fields["SignatureValue"], [expected])
            for raw in (str(amount), f"{amount:.6f}"):
                callback = {"OutSum": raw, "InvId": str(invoice), "SignatureValue": billing._signature(f"{raw}:{invoice}", "test2")}
                self.assertIsNotNone(billing.verify_robokassa_result(callback))
            for raw in ("NaN", "Infinity", "0", "-1", f"{amount}.001"):
                callback = {"OutSum": raw, "InvId": str(invoice), "SignatureValue": billing._signature(f"{raw}:{invoice}", "test2")}
                self.assertIsNone(billing.verify_robokassa_result(callback))
            self.db.execute("UPDATE billing_invoices SET currency='HP' WHERE id=?", (invoice,))
            self.assertIsNone(billing.verify_robokassa_result({"OutSum":str(amount), "InvId":str(invoice), "SignatureValue":billing._signature(f"{amount}:{invoice}","test2")}))

    def test_free_help_reward_is_limited_in_both_directions(self):
        first = self.finish()
        before = [database.get_user(uid)["balance"] for uid in (1, 2)]
        second = self.finish(owner=2, helper=1)
        third = self.finish()
        self.assertEqual([database.get_user(uid)["balance"] for uid in (1, 2)], before)
        self.assertEqual(database.get_request(second)["hp_settled"], 0)
        self.assertEqual(database.get_request(third)["hp_settled"], 0)
        self.assertTrue(services.set_rating(third, 1, 5))
        self.assertTrue(services.set_helper_rating(third, 2, 5))
        old = (datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()
        self.db.execute("UPDATE requests SET completed_at=? WHERE id=?", (old, first))
        later = self.finish()
        self.assertEqual(database.get_request(later)["hp_settled"], 1)

    def test_repeat_help_can_finish_with_zero_points(self):
        self.finish()
        self.db.execute("UPDATE users SET balance=0 WHERE user_id=1")
        rid = self.finish()
        self.assertEqual(database.get_request(rid)["hp_settled"], 0)
        self.assertEqual(database.get_user(1)["balance"], 0)

    def test_different_pair_still_earns_points(self):
        self.finish()
        rid = self.finish(owner=3)
        self.assertEqual(database.get_request(rid)["hp_settled"], 1)

    def test_dispute_freezes_completion_until_admin_resolution(self):
        rid = self.funded()
        services.accept_open_request(rid, 2)
        with self.assertRaises(ValueError):database.create_request_dispute(rid, 3, "Not a participant")
        ticket = database.create_request_dispute(rid, 2, "Synthetic problem")
        self.db.execute("UPDATE support_tickets SET status='answered' WHERE id=?", (ticket,))
        self.assertEqual(database.create_request_dispute(rid, 1, "Same problem"), ticket)
        self.assertFalse(services.complete_request(rid, 2, confirmed_by=1))
        self.assertFalse(database.resolve_request_dispute(3, rid, "Not admin"))
        self.assertTrue(database.resolve_request_dispute(4, rid, "Both participants agreed"))
        self.assertTrue(services.complete_request(rid, 2, confirmed_by=1))
        self.assertEqual(reliability.wallet_balances(self.db, 2), (340, 340))

    def test_admin_can_cancel_dispute_and_return_test_funds(self):
        rid = self.funded()
        services.accept_open_request(rid, 2)
        ticket = database.create_request_dispute(rid, 1, "Synthetic problem")
        self.assertTrue(database.admin_cancel_request(4, rid, "Cancelled by agreement")[0])
        self.assertFalse(database.admin_cancel_request(4, rid)[0])
        self.assertFalse(services.complete_request(rid, 2, confirmed_by=1))
        self.assertEqual(reliability.wallet_balances(self.db, 1), (500, 500))
        self.assertEqual(self.db.execute("SELECT status FROM support_tickets WHERE id=?", (ticket,)).fetchone()["status"], "resolved")

    def test_expiry_refund_is_atomic_and_retryable(self):
        rid = self.funded()
        self.db.execute("UPDATE requests SET expires_at='2020-01-01T00:00:00+00:00' WHERE id=?", (rid,))
        with patch.object(services, "wallet_add_entry", side_effect=RuntimeError("Synthetic ledger failure")):
            with self.assertRaises(RuntimeError):services.expire_open_requests()
        self.assertEqual(database.get_request(rid)["status"], "open")
        services.expire_open_requests()
        services.expire_open_requests()
        self.assertEqual(database.get_request(rid)["status"], "cancelled")
        self.assertEqual(reliability.wallet_balances(self.db, 1), (500, 500))

    def test_admin_cancel_rolls_back_when_refund_fails(self):
        rid = self.funded()
        with patch.object(database, "wallet_add_entry", side_effect=RuntimeError("Synthetic ledger failure")):
            with self.assertRaises(RuntimeError):database.admin_cancel_request(4, rid)
        self.assertEqual(database.get_request(rid)["status"], "open")
        self.assertEqual(reliability.wallet_balances(self.db, 1), (100, 100))

    def test_matching_searches_beyond_first_hundred_and_checks_preferences(self):
        target = self.request(lat=55.75, lon=37.62, scheduled_at="2030-01-01T12:00:00+03:00")
        for _ in range(105):self.request(lat=59.93, lon=30.31)
        self.db.execute("UPDATE users SET lat=55.751,lon=37.621,helper_radius_km=10,helper_available_from='2030-01-01T08:00:00+00:00',helper_available_until='2030-01-01T10:00:00+00:00' WHERE user_id=2")
        self.assertEqual([r["request"]["id"] for r in services.smart_requests_for_helper(2)], [target])
        services.add_to_queue(2)
        self.assertIn(2, [r["user_id"] for r in services.smart_match(target)])
        self.db.execute("UPDATE users SET helper_available_until='2030-01-01T08:30:00+00:00' WHERE user_id=2")
        self.assertNotIn(2, [r["user_id"] for r in services.smart_match(target)])

    def test_schedule_requires_timezone_and_normalizes(self):
        self.assertEqual(services.normalize_schedule("2030-01-01T12:00:00+03:00"), "2030-01-01T09:00:00+00:00")
        for value in ("tomorrow", "2030-01-01T12:00:00"):
            with self.assertRaises(ValueError):services.normalize_schedule(value)

    def test_funnel_counts_acceptance_completion_and_repeat_requesters(self):
        self.finish()
        self.request()
        self.request(owner=3)
        metrics = reliability.funnel_metrics(self.db, 14)
        self.assertEqual(metrics["requests"], 3)
        self.assertEqual(metrics["accepted"], 1)
        self.assertEqual(metrics["completion_percent"], 33.3)
        self.assertEqual(metrics["repeat_requester_percent"], 50)

    def test_health_checks_database(self):
        self.assertEqual(web.health_status()[1], 200)
        with patch.object(database, "db") as failed:
            failed.execute.side_effect=RuntimeError("Synthetic database outage")
            payload, status=web.health_status()
            self.assertEqual(status, 503)
            self.assertFalse(payload["database"])


class Reliability(Scenarios, unittest.TestCase):
    def setUp(self):
        db = sqlite3.connect(":memory:", isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        self.prepare(db)

    def tearDown(self):
        self.close()
