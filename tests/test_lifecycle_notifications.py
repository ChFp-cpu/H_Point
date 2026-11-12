"""Expiry notices survive restarts and remain available without PRO."""
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
from hpoint import database, services, lifecycle_notifications as notices, web


class LifecycleCases:
    def prepare(self, connection):
        self.db=connection
        self.patches=[patch.object(module,"db",connection) for module in (database,services,web)]
        self.patches.append(patch.object(database,"REGISTRATION_BONUS_RUB",0))
        for item in self.patches:item.start()
        database.init_db()
        for uid in (1,2,3):
            database.create_user(uid,"Synthetic notice user",email=f"notice{uid}@example.test",web_verified=True,tg_user_id=uid+100)
            self.db.execute("UPDATE users SET email_verified=1,pro_until='2000-01-01T00:00:00+00:00' WHERE user_id=?",(uid,))

    def close(self):
        self.db.close()
        for item in reversed(self.patches):item.stop()

    def expired(self, paid=False):
        rid=services.create_request(1,dict(what="Private <title>",place="PRIVATE ADDRESS",time_needed="Today",urgency="Normal",details="PRIVATE DETAILS",category="tech",reward_rub=1000 if paid else 0))
        services.apply_to_request(rid,2)
        # A previously declined helper must not receive a new lifecycle notice.
        self.db.execute("INSERT INTO request_candidates(request_id,candidate_id,score,status) VALUES(?,?,0,'declined')",(rid,3))
        field="reserve_deadline_at" if paid else "expires_at"
        self.db.execute("UPDATE requests SET "+field+"=? WHERE id=?",((datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat(),rid))
        services.expire_open_requests()
        return rid

    def test_expiry_queues_only_involved_people_once_without_pro_or_private_location(self):
        rid=self.expired()
        rows=self.db.execute("SELECT * FROM request_notification_outbox ORDER BY recipient_id").fetchall()
        self.assertEqual([r["recipient_id"] for r in rows],[1,2])
        self.assertEqual(database.get_request(rid)["status"],"cancelled")
        services.expire_open_requests();database.init_db()
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM request_notification_outbox").fetchone()["n"],2)
        message=notices.message(dict(rows[0]),"https://example.test")
        self.assertIn("&lt;title&gt;",message);self.assertNotIn("PRIVATE ADDRESS",message);self.assertNotIn("PRIVATE DETAILS",message)
        self.assertNotIn("PRO",message)

    def test_unfunded_expiry_records_reason_without_debit(self):
        rid=self.expired(True)
        self.assertEqual(self.db.execute("SELECT event_type FROM request_notification_outbox LIMIT 1").fetchone()["event_type"],"reserve_expired")
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"],0)
        self.assertEqual(database.get_request(rid)["reward_payment_status"],"none")

    def test_large_canonical_identity_is_not_truncated(self):
        uid=9_000_000_123
        database.create_user(uid,"Synthetic large identity",email="large@example.test",web_verified=True,tg_user_id=uid)
        self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
        rid=services.create_request(uid,dict(what="Expiry fixture",place="Local",time_needed="Today",urgency="Normal",details="Fixture",category="tech"))
        self.db.execute("UPDATE requests SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(rid,))
        services.expire_open_requests()
        self.assertEqual(notices.claim(self.db)[0]["recipient_id"],uid)

    def test_failed_refund_rolls_back_notice_and_closure_together(self):
        from hpoint import reliability
        rid=services.create_request(1,dict(what="Refund fixture",place="Local",time_needed="Today",urgency="Normal",details="Fixture",category="tech",reward_rub=1000))
        database.wallet_add_entry(1,1150,"test","Synthetic funds","notice-refund",test_amount_rub=1150)
        services.reserve_request_reward(rid,1,1150)
        self.db.execute("UPDATE requests SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",(rid,))
        with patch.object(reliability,"refund_locked_reserve",side_effect=ValueError("synthetic refund failure")):
            with self.assertRaises(ValueError):services.expire_open_requests()
        self.assertEqual(database.get_request(rid)["status"],"open")
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM request_notification_outbox").fetchone()["n"],0)
        services.expire_open_requests()
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"],1150)
        self.assertEqual(len(notices.claim(self.db)),1)

    def test_concurrent_claims_do_not_send_same_notice(self):
        self.expired();gate=threading.Barrier(2)
        def run():
            try:gate.wait(timeout=5);return notices.claim(self.db)
            finally:self.db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(run) for _ in range(2)];rows=[r for job in jobs for r in job.result(timeout=20)]
        self.assertEqual(len(rows),2);self.assertEqual(len({r["id"] for r in rows}),2)

    def test_restart_reclaims_lease_and_rejects_old_acknowledgement(self):
        self.expired();at=datetime.now(timezone.utc)+timedelta(seconds=1)
        first=notices.claim(self.db,at)
        self.assertEqual(notices.claim(self.db,at),[])
        renewed=notices.claim(self.db,at+timedelta(minutes=6))
        self.assertEqual(len(renewed),2)
        self.assertFalse(notices.finish(self.db,first[0],True))
        self.assertTrue(notices.finish(self.db,renewed[0],True))

    def test_failures_retry_with_backoff_and_stop_after_five_attempts(self):
        self.expired();at=datetime.now(timezone.utc)+timedelta(seconds=1)
        for attempt in range(1,6):
            batch=notices.claim(self.db,at)
            self.assertEqual(len(batch),2)
            for item in batch:self.assertEqual(item["attempts"],attempt);notices.finish(self.db,item,False,at)
            self.assertEqual(notices.claim(self.db,at),[])
            at+=timedelta(hours=2)
        self.assertEqual(notices.claim(self.db,at),[])
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM request_notification_outbox WHERE status='failed'").fetchone()["n"],2)

    def test_worker_delivers_to_current_link_without_subscription_check(self):
        self.expired();future=Future();future.set_result(object())
        with patch.object(web,"_telegram_bot",object()),patch.object(web,"_telegram_loop",object()),patch.object(web,"notify_telegram_user",return_value=future) as send:
            self.assertEqual(web.process_lifecycle_notifications(),2)
            self.assertEqual({call.args[0] for call in send.call_args_list},{101,102})
            self.assertEqual(web.process_lifecycle_notifications(),0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM request_notification_outbox WHERE status='sent'").fetchone()["n"],2)

    def test_disabled_notifier_does_not_consume_queue_and_unlink_prevents_delivery(self):
        self.expired()
        with patch.object(web,"_telegram_bot",None):self.assertEqual(web.process_lifecycle_notifications(),0)
        self.db.execute("UPDATE users SET tg_user_id=NULL WHERE user_id=2")
        future=Future();future.set_result(object())
        with patch.object(web,"_telegram_bot",object()),patch.object(web,"_telegram_loop",object()),patch.object(web,"notify_telegram_user",return_value=future) as send:
            web.process_lifecycle_notifications();self.assertEqual(send.call_count,1);self.assertEqual(send.call_args.args[0],101)


class SQLiteLifecycle(LifecycleCases,unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'.theme-qa';root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=root,prefix='notices-')
        self.prepare(database.SQLiteConnection(str(Path(self.temp.name)/'test.db')))
    def tearDown(self):self.close();self.temp.cleanup()


@unittest.skipUnless(os.environ.get('HPOINT_TEST_DATABASE_URL'),'requires isolated PostgreSQL test database')
class PostgreSQLLifecycle(LifecycleCases,unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema='notices_qa_'+uuid.uuid4().hex;url=os.environ['HPOINT_TEST_DATABASE_URL']
        self.control=database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url,self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE');self.control.close()
