"""Personal PRO parity and owner races, using disposable local databases only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from hpoint import billing, commercial, database, personal, services, workflow


FIELDS = dict(what="Помочь с техникой", place="Тестовый район", time_needed="По договорённости",
              urgency="Обычная", details="Только тестовые условия", category="tech", reward_rub=0)


class PersonalScenarios:
    def prepare(self, connection):
        self.db = connection
        self.patches = [patch.object(database, "db", connection), patch.object(services, "db", connection),
                        patch.object(billing, "db", connection), patch.object(database, "REGISTRATION_BONUS_RUB", 0)]
        for item in self.patches:
            item.start()
        database.init_db()
        for uid in (1, 2, 3):
            database.create_user(uid, "Synthetic personal user", email=f"personal{uid}@example.test", web_verified=True)
            self.db.execute("UPDATE users SET email_verified=1,balance=1000 WHERE user_id=?", (uid,))

    def close(self):
        self.db.close()
        for item in reversed(self.patches):
            item.stop()

    def pro(self, uid=1, active=True):
        self.db.execute("UPDATE users SET pro_until=? WHERE user_id=?", ("2099-01-01T00:00:00+00:00" if active else "2000-01-01T00:00:00+00:00", uid))

    def request(self, uid=1, **fields):
        return services.create_request(uid, {**FIELDS, **fields})

    def event(self, uid=1, title="Synthetic published event"):
        start = (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        return database.create_community_event(uid, title, "Synthetic event details", "Тестовая площадка", start)

    def template(self, uid=1, **fields):
        return personal.save_template(uid, {"name": "Мой шаблон", "fields": {**FIELDS, **fields}})

    def schedule(self, uid=1, **fields):
        template = self.template(uid, **fields)
        return personal.save_schedule(uid, {"template_id": template["id"], "frequency": "daily", "time": "09:00", "timezone": personal.TIMEZONE})

    def due(self, schedule, at=None):
        at = at or datetime.now(timezone.utc)
        self.db.execute("UPDATE personal_schedules SET next_run_at=? WHERE id=?", ((at-timedelta(minutes=1)).isoformat(), schedule["id"]))
        return at

    def race(self, *functions):
        gate = threading.Barrier(len(functions))
        def run(function):
            try:
                gate.wait(timeout=5)
                try:
                    return function()
                except (ValueError, PermissionError) as error:
                    return error
            finally:
                self.db.close()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            jobs = [pool.submit(run, function) for function in functions]
            return [job.result(timeout=30) for job in jobs]

    def test_free_author_limit_counts_both_active_statuses_not_helping(self):
        own = self.request()
        other = self.request(2)
        self.assertTrue(services.try_assign_helper(other, 1))
        with self.assertRaises(personal.PersonalLimitError) as error:
            self.request()
        self.assertEqual(error.exception.code, "active_request_limit")
        self.assertEqual(personal.usage(1)["requests"], {"active": 1, "limit": 1, "remaining": 0})
        self.db.execute("UPDATE requests SET status='cancelled' WHERE id=?", (own,))
        replacement = self.request()
        self.assertNotEqual(replacement, own)
        self.assertEqual(database.get_active_help(1)["id"], other)

    def test_pro_expiry_preserves_ten_requests_and_blocks_only_new_creation(self):
        self.pro()
        ids = [self.request() for _ in range(10)]
        with self.assertRaises(personal.PersonalLimitError):
            self.request()
        self.pro(active=False)
        state = personal.usage(1)
        self.assertEqual(state["requests"], {"active": 10, "limit": 1, "remaining": 0})
        self.assertEqual(len(database.get_history(1)), 10)
        with self.assertRaises(personal.PersonalLimitError):
            self.request()
        for rid in ids:
            self.db.execute("UPDATE requests SET status='done' WHERE id=?", (rid,))
        self.assertIsInstance(self.request(), int)

    def test_owner_lock_serializes_concurrent_requests_and_events(self):
        result = self.race(self.request, self.request, self.event, self.event, self.event)
        self.assertEqual(sum(isinstance(row, int) for row in result[:2]), 1)
        self.assertEqual(sum(isinstance(row, int) for row in result[2:]), 2)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests WHERE requester_id=1").fetchone()["n"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM personal_activity_publications WHERE owner_id=1").fetchone()["n"], 2)

    def test_pro_parallel_creation_is_capped_at_ten(self):
        self.pro()
        result = self.race(*([self.request]*12))
        self.assertEqual(sum(isinstance(row, int) for row in result), 10)
        self.assertEqual(personal.usage(1)["requests"]["active"], 10)

    def test_activity_quota_records_only_successes_and_cancel_does_not_refund(self):
        with self.assertRaises(ValueError):
            self.event(title="x")
        self.assertEqual(personal.usage(1)["activities"]["used"], 0)
        first, second = self.event(), self.event()
        self.db.execute("UPDATE community_events SET status='cancelled' WHERE id=?", (first,))
        with self.assertRaises(personal.PersonalLimitError):
            self.event()
        self.assertEqual(personal.usage(1)["activities"]["used"], 2)
        self.assertIsNotNone(self.db.execute("SELECT id FROM community_events WHERE id=?", (second,)).fetchone())

    def test_pro_event_publications_count_towards_free_limit_after_expiry(self):
        self.pro()
        for _ in range(4):
            self.event()
        self.assertIsNone(personal.usage(1)["activities"]["remaining"])
        self.pro(active=False)
        self.assertEqual(personal.usage(1)["activities"]["remaining"], 0)
        with self.assertRaises(personal.PersonalLimitError):
            self.event()
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM community_events").fetchone()["n"], 4)

    def test_activity_month_is_measured_after_the_owner_lock_wait(self):
        before = datetime(2030, 1, 31, 20, 59, 59, tzinfo=timezone.utc)
        after = datetime(2030, 1, 31, 21, 0, 1, tzinfo=timezone.utc)
        with patch.object(database, "datetime", wraps=datetime) as clock:
            clock.now.side_effect = [before, after]
            event = database.create_community_event(1, "Boundary publication", "Test details", "Test place", "2030-02-02T10:00:00+00:00")
        ledger = self.db.execute("SELECT month_key,published_at FROM personal_activity_publications WHERE event_id=?", (event,)).fetchone()
        self.assertEqual(ledger["month_key"], "2030-02")
        self.assertEqual(personal.usage(1, before)["activities"]["used"], 0)
        self.assertEqual(personal.usage(1, after)["activities"]["used"], 1)

    def test_backfill_includes_cancelled_and_uses_moscow_month_idempotently(self):
        for state, stamp in (("published", "2026-10-31T20:59:59+00:00"), ("cancelled", "2026-10-31T21:00:00+00:00"), ("draft", "2026-10-31T21:00:00+00:00")):
            self.db.execute("INSERT INTO community_events(creator_id,title,place,starts_at,status,created_at) VALUES(1,'Historical event','Synthetic place','2090-01-01',?,?)", (state, stamp))
        before = [dict(row) for row in self.db.execute("SELECT * FROM community_events ORDER BY id").fetchall()]
        personal.initialize_schema(self.db)
        personal.initialize_schema(self.db)
        october = personal.usage(1, "2026-10-31T20:59:59+00:00")["activities"]
        november = personal.usage(1, "2026-10-31T21:00:00+00:00")["activities"]
        self.assertEqual((october["used"], november["used"]), (1, 1))
        self.assertEqual(october["resets_at"], "2026-11-01T00:00:00+03:00")
        self.assertEqual(november["resets_at"], "2026-12-01T00:00:00+03:00")
        self.assertEqual(before, [dict(row) for row in self.db.execute("SELECT * FROM community_events ORDER BY id").fetchall()])

    def test_template_from_request_recovers_duration_without_copying_dates(self):
        self.pro()
        rid=self.request(expires_in_hours=73,reward_rub=1234,details="Original details")
        fields=dict(database.get_request(rid))
        saved=personal.save_template(1,{"name":"From request","fields":fields})
        self.assertEqual(saved["fields"]["expires_in_hours"],73)
        self.assertEqual(saved["fields"]["reward_rub"],1234)
        self.assertEqual(saved["fields"]["details"],"Original details")
        self.assertNotIn("expires_at",saved["fields"])
        self.assertNotIn("created_at",saved["fields"])

    def test_templates_are_private_content_only_and_opening_never_publishes(self):
        self.pro()
        template = self.template(helper_id=2, chat_id=42, requester_rating=5, status="done", reward_payment_status="paid", priority_boost=100,
                                 commission_rub=999, reward_total_rub=9999, photos=[{"id": "private-photo"}], scheduled_at="2000-01-01", reward_rub=1000)
        for key in ("helper_id", "chat_id", "status", "reward_payment_status", "requester_rating", "priority_boost", "commission_rub", "reward_total_rub", "photos", "scheduled_at"):
            self.assertNotIn(key, template["fields"])
        self.assertEqual(template["fields"]["reward_rub"], 1000)
        self.assertEqual(personal.get_template(1, template["id"]), template)
        with self.assertRaises(ValueError):
            personal.get_template(2, template["id"], for_use=False)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"], 0)
        self.assertEqual(personal.usage(1)["requests"]["remaining"], 10)

    def test_expired_templates_remain_listed_and_deletable_but_cannot_be_used(self):
        self.pro()
        schedule = self.schedule()
        self.pro(active=False)
        template = personal.list_templates(1)[0]
        self.assertEqual(template["name"], "Мой шаблон")
        self.assertFalse(template["usable"])
        self.assertIsNone(template["fields"])
        with self.assertRaises(personal.PersonalLimitError):
            personal.get_template(1, template["id"])
        with self.assertRaises(personal.PersonalLimitError):
            personal.save_template(1, {"name": "Blocked change"}, template["id"])
        self.assertTrue(personal.delete_template(1, template["id"]))
        row = personal.get_schedule(1, schedule["id"])
        self.assertEqual((row["status"], row["template_id"], row["last_reason"]), ("disabled", None, "template_deleted"))

    def test_saved_conditions_reject_unpublishable_content_before_a_schedule_exists(self):
        self.pro()
        for changes in ({"what": "x"}, {"place": "x"}, {"reward_rub": 1000.5}, {"reward_rub": True}):
            with self.assertRaises(ValueError):
                self.template(**changes)
        self.assertEqual(personal.list_templates(1), [])
        self.assertEqual(personal.list_schedules(1), [])

    def test_scheduled_conditions_do_not_change_when_the_source_template_is_edited(self):
        self.pro()
        schedule = self.schedule(what="Первоначальные условия", reward_rub=500)
        template = personal.get_template(1, schedule["template_id"])
        personal.save_template(1, {"name": "Обновлённый шаблон", "fields": {**template["fields"], "what": "Новые условия шаблона", "reward_rub": 900}}, template["id"])
        saved = personal.get_schedule(1, schedule["id"])
        self.assertEqual(saved["fields"]["what"], "Первоначальные условия")
        self.assertEqual(saved["fields"]["reward_rub"], 500)
        result = personal.process_due(self.due(schedule))
        request = database.get_request(result["published"][0]["request_id"])
        self.assertEqual(request["what"], "Первоначальные условия")
        self.assertEqual(workflow.reward_quote(request)["total_rub"], 575)

    def test_calendar_next_runs_are_strictly_future_in_explicit_moscow_timezone(self):
        at = "2030-01-31T07:01:00+00:00"
        self.assertEqual(personal.next_run("daily", "10:00", now=at), "2030-02-01T07:00:00+00:00")
        self.assertEqual(personal.next_run("monthly", "10:00", day_of_month=31, now=at), "2030-02-28T07:00:00+00:00")
        self.assertEqual(personal.next_run("monthly", "10:00", day_of_month=31, now="2032-01-31T07:00:00+00:00"), "2032-02-29T07:00:00+00:00")
        self.assertEqual(personal.next_run("weekly", "09:00", weekday=0, now="2030-01-07T06:00:00+00:00"), "2030-01-14T06:00:00+00:00")
        with self.assertRaises(ValueError):
            personal.next_run("daily", "24:01", now=at)

    def test_due_parallel_processes_and_restart_create_one_request(self):
        self.pro()
        schedule = self.schedule()
        at = self.due(schedule)
        result = self.race(lambda: personal.process_due(at), lambda: personal.process_due(at))
        self.assertEqual(sum(len(item["published"]) for item in result), 1)
        self.assertFalse(any(item["errors"] for item in result))
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM personal_schedule_runs").fetchone()["n"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"], 1)
        self.assertEqual(personal.process_due(at)["published"], [])

    def test_failed_process_rolls_back_claim_and_creation_before_safe_retry(self):
        self.pro()
        schedule = self.schedule()
        at = self.due(schedule)
        create = services.create_request
        def fail_after_insert(uid, data):
            create(uid, data)
            raise RuntimeError("Synthetic crash before commit")
        with patch.object(services, "create_request", fail_after_insert):
            result = personal.process_due(at)
        self.assertEqual(result["published"], [])
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM personal_schedule_runs").fetchone()["n"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"], 0)
        self.assertEqual(len(personal.process_due(at)["published"]), 1)

    def test_missed_runs_publish_once_then_previous_active_is_skipped(self):
        self.pro()
        schedule = self.schedule()
        at = datetime.now(timezone.utc)
        self.db.execute("UPDATE personal_schedules SET next_run_at=? WHERE id=?", ((at-timedelta(days=90)).isoformat(), schedule["id"]))
        first = personal.process_due(at)
        self.assertEqual(len(first["published"]), 1)
        future = personal._date(personal.get_schedule(1, schedule["id"])["next_run_at"])
        self.assertGreater(future, at)
        second = personal.process_due(future)
        self.assertEqual(second["published"], [])
        self.assertEqual(second["skipped"][0]["reason"], "previous_active")
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"], 1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM personal_schedule_runs").fetchone()["n"], 2)

    def test_duplicate_ledger_slot_cannot_be_republished_after_clock_or_state_replay(self):
        self.pro()
        schedule = self.schedule()
        at = self.due(schedule)
        stamp = self.db.execute("SELECT next_run_at FROM personal_schedules WHERE id=?", (schedule["id"],)).fetchone()["next_run_at"]
        self.assertEqual(len(personal.process_due(at)["published"]), 1)
        self.db.execute("UPDATE personal_schedules SET next_run_at=?,last_request_id=NULL WHERE id=?", (stamp, schedule["id"]))
        self.assertEqual(personal.process_due(at)["published"], [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"], 1)

    def test_global_limit_skips_with_reason_without_pausing_or_losing_schedule(self):
        self.pro()
        schedule = self.schedule()
        for _ in range(10):
            self.request()
        result = personal.process_due(self.due(schedule))
        self.assertEqual(result["skipped"][0]["reason"], "active_request_limit")
        self.assertEqual(personal.get_schedule(1, schedule["id"])["status"], "active")
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"], 10)

    def test_expiry_pauses_future_schedule_once_and_renewal_never_replays_backlog(self):
        self.pro()
        schedule = self.schedule()
        self.pro(active=False)
        result = personal.process_due()
        self.assertEqual(result["skipped"][0]["reason"], "pro_expired")
        self.assertEqual(personal.get_schedule(1, schedule["id"])["status"], "paused")
        self.assertEqual(personal.process_due()["skipped"], [])
        self.pro()
        self.assertEqual(personal.process_due()["published"], [])
        resumed = personal.set_schedule_status(1, schedule["id"], "active")
        self.assertGreater(personal._date(resumed["next_run_at"]), datetime.now(timezone.utc))

    def test_paid_recurrence_only_creates_fresh_unreserved_request_and_notice(self):
        self.pro()
        schedule = self.schedule(reward_rub=1000)
        database.wallet_add_entry(1, 2000, "test", "Synthetic test balance", "recurrence-wallet", test_amount_rub=2000)
        balance = database.wallet_summary(1)["test_balance_rub"]
        result = personal.process_due(self.due(schedule))
        self.assertEqual(len(result["published"]), 1)
        notice = result["published"][0]
        request = database.get_request(notice["request_id"])
        self.assertTrue(notice["paid"])
        self.assertEqual(request["reward_payment_status"], "none")
        self.assertIsNone(request["helper_id"])
        self.assertEqual(request["priority_boost"], 0)
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"], balance)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM chats").fetchone()["n"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM billing_invoices").fetchone()["n"], 0)
        self.assertEqual(workflow.reward_quote(request)["total_rub"], 1150)
        remaining = personal._date(request["reserve_deadline_at"])-datetime.now(timezone.utc)
        self.assertGreater(remaining.total_seconds(), 270)
        self.assertLessEqual(remaining.total_seconds(), 300)

    def test_renewal_after_expiry_pauses_schedules_before_the_worker_can_observe_expiry(self):
        database.wallet_add_entry(1, 1000, "test", "Synthetic renewal funds", "expiry-renew-wallet", test_amount_rub=1000)
        for uid in (1, 2):
            self.pro(uid)
            future = self.schedule(uid)
            overdue = self.schedule(uid)
            self.due(overdue)
            self.pro(uid, active=False)
            # No process_due call between expiry and purchase: the purchase
            # transaction itself must retain the required explicit-resume step.
            purchase = billing.purchase_with_wallet if uid == 1 else billing.purchase_with_points
            purchase(uid, "pro", {}, "expired-before-worker-"+str(uid))
            self.assertTrue(personal.is_pro(uid))
            for schedule in (future, overdue):
                saved = personal.get_schedule(uid, schedule["id"])
                self.assertEqual((saved["status"], saved["last_reason"]), ("paused", "pro_expired"))
        result = personal.process_due()
        self.assertEqual(result["published"], [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"], 0)
        resumed = personal.set_schedule_status(1, personal.list_schedules(1)[0]["id"], "active")
        self.assertGreater(personal._date(resumed["next_run_at"]), datetime.now(timezone.utc))

    def test_early_renewal_does_not_pause_a_still_active_schedule(self):
        self.pro()
        schedule = self.schedule()
        previous = database.get_user(1)["pro_until"]
        billing.purchase_with_points(1, "pro", {"renew": True, "expected_until": previous}, "early-renew-schedule")
        saved = personal.get_schedule(1, schedule["id"])
        self.assertEqual(saved["status"], "active")
        self.assertIsNone(saved["last_reason"])
        self.assertEqual(saved["next_run_at"], schedule["next_run_at"])

    def test_schedule_pause_edit_resume_and_foreign_access(self):
        self.pro()
        schedule = self.schedule()
        paused = personal.set_schedule_status(1, schedule["id"], "paused")
        self.assertEqual(paused["status"], "paused")
        edited = personal.save_schedule(1, {"frequency": "weekly", "weekday": 4, "time": "18:30"}, schedule["id"])
        self.assertEqual((edited["frequency"], edited["weekday"], edited["time"], edited["status"]), ("weekly", 4, "18:30", "paused"))
        with self.assertRaises(ValueError):
            personal.set_schedule_status(2, schedule["id"], "disabled")
        with self.assertRaises(ValueError):
            personal.save_schedule(1, {"timezone": "UTC"}, schedule["id"])
        self.assertEqual(personal.set_schedule_status(1, schedule["id"], "active")["status"], "active")
        self.assertEqual(personal.set_schedule_status(1, schedule["id"], "disabled")["status"], "disabled")

    def test_pro_price_renewal_and_replayed_purchases_preserve_other_rights(self):
        database.wallet_add_entry(1, 1000, "test", "Synthetic test funds", "pro-wallet", test_amount_rub=1000)
        self.db.execute("UPDATE users SET business_until='2090-01-01T00:00:00+00:00' WHERE user_id=1")
        invoice, created = billing.purchase_with_wallet(1, "pro", {}, "personal-first")
        first = database.get_user(1)["pro_until"]
        self.assertTrue(created)
        self.assertEqual(database.get_invoice(invoice)["amount_rub"], 149)
        self.assertEqual(billing.purchase_with_wallet(1, "pro", {}, "personal-first"), (invoice, False))
        metadata = {"renew": True, "expected_until": first}
        second, _ = billing.purchase_with_points(1, "pro", metadata, "personal-renew")
        self.assertEqual(database.get_invoice(second)["amount_rub"], 90)
        until = personal._date(database.get_user(1)["pro_until"])
        self.assertEqual(until-personal._date(first), timedelta(days=30))
        self.assertEqual(billing.purchase_with_points(1, "pro", metadata, "personal-renew"), (second, False))
        self.assertEqual(database.get_user(1)["business_until"], "2090-01-01T00:00:00+00:00")
        self.assertEqual(database.get_user(1)["balance"], 910)

    def test_concurrent_renewal_token_allows_only_one_extension_and_debit(self):
        database.wallet_add_entry(1, 1000, "test", "Synthetic test funds", "renew-wallet", test_amount_rub=1000)
        self.pro()
        initial = database.get_user(1)["pro_until"]
        metadata = {"renew": True, "expected_until": initial}
        result = self.race(lambda: billing.purchase_with_wallet(1, "pro", metadata, "renew-one"), lambda: billing.purchase_with_wallet(1, "pro", metadata, "renew-two"))
        self.assertEqual(sum(isinstance(row, tuple) for row in result), 1)
        self.assertEqual(personal._date(database.get_user(1)["pro_until"])-personal._date(initial), timedelta(days=30))
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"], 851)

    def test_retired_products_cannot_issue_new_invoices_or_debit_any_currency(self):
        from hpoint.config import LEGACY_MONETIZATION_ITEMS, MONETIZATION_ITEMS
        self.assertEqual(set(MONETIZATION_ITEMS), {"pro"})
        database.wallet_add_entry(1, 5000, "test", "Synthetic funds", "retired-wallet", test_amount_rub=5000)
        for item in LEGACY_MONETIZATION_ITEMS:
            for function in (lambda: billing.create_pending_invoice(1, item), lambda: billing.purchase_with_wallet(1, item, {}, "retired-rub-"+item), lambda: billing.purchase_with_points(1, item, {}, "retired-hp-"+item)):
                with self.assertRaises(ValueError):
                    function()
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM billing_invoices").fetchone()["n"], 0)
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"], 5000)

    def test_legacy_pending_boost_and_real_reward_fulfill_at_original_terms_once(self):
        rid = self.request(reward_rub=1000)
        # A historical legacy row and invoice are not repriced by the migration.
        self.db.execute("UPDATE requests SET reward_pricing_version='legacy_v1',reward_total_rub=0,commission_rub=0,helper_reward_rub=0 WHERE id=?", (rid,))
        self.db.execute("INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata) VALUES(1,'request_reward',1000,'RUB','legacy-real-reward',?)", (json.dumps({"request_id": rid}),))
        invoice = self.db.execute("SELECT * FROM billing_invoices WHERE payload='legacy-real-reward'").fetchone()
        self.assertEqual(billing.fulfill_invoice(invoice["id"]), (True, "request_reward"))
        self.assertEqual(billing.fulfill_invoice(invoice["id"]), (True, "already_paid"))
        quote = workflow.reward_quote(database.get_request(rid))
        self.assertEqual((quote["total_rub"], quote["helper_rub"], quote["commission_rub"]), (1000, 1000, 0))
        self.db.execute("INSERT INTO billing_invoices(user_id,item_type,amount_rub,currency,payload,metadata) VALUES(1,'boost',49,'RUB','legacy-boost',?)", (json.dumps({"request_id": rid}),))
        old = self.db.execute("SELECT * FROM billing_invoices WHERE payload='legacy-boost'").fetchone()
        self.assertTrue(billing.fulfill_invoice(old["id"])[0])
        self.assertTrue(billing.fulfill_invoice(old["id"])[0])
        self.assertEqual(database.get_request(rid)["priority_boost"], 100)
        self.assertEqual(database.get_invoice(old["id"])["amount_rub"], 49)

    def test_reward_invoice_freezes_total_and_unsupported_real_callback_never_makes_test_money(self):
        rid = self.request(reward_rub=1000)
        iid, payload, amount = billing.create_request_reward_invoice(1, rid)
        self.assertEqual(amount, 1150)
        meta = json.loads(database.get_invoice(iid)["metadata"])
        self.assertEqual(meta["reward_quote"]["total_rub"], 1150)
        self.assertEqual(billing.create_request_reward_invoice(1, rid), (iid, payload, amount))
        self.assertEqual(billing.fulfill_invoice(iid), (True, "credited_to_wallet"))
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"], 0)
        self.assertEqual(database.wallet_summary(1)["balance_rub"], 1150)
        self.assertEqual(database.get_request(rid)["reward_payment_status"], "none")


class SQLitePersonal(PersonalScenarios, unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]/".theme-qa"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="personal-tests-", dir=root)
        self.prepare(database.SQLiteConnection(str(Path(self.temp.name)/"personal.db")))

    def tearDown(self):
        self.close()
        self.temp.cleanup()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"), "requires isolated PostgreSQL test database")
class PostgreSQLPersonal(PersonalScenarios, unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema = "personal_qa_"+uuid.uuid4().hex
        url = os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control = database.PostgresConnection(url)
        self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url, self.schema))

    def tearDown(self):
        self.close()
        self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE')
        self.control.close()


if __name__ == "__main__":
    unittest.main()
