"""Real PostgreSQL tests. Each test owns a separate, disposable schema."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import threading
import unittest
import uuid

from hpoint import database, services, billing, reliability, workflow
from test_reliability import Scenarios


class IsolatedPostgres(database.PostgresConnection):
    def __init__(self, url, schema):
        super().__init__(url)
        self.schema = schema

    def _connection(self):
        conn = super()._connection()
        if getattr(self._local, "configured", None) is not conn:
            # Generated internal identifier, never supplied by a request.
            conn.execute('SET search_path TO "' + self.schema + '"')
            conn.execute("SET statement_timeout TO '10s'")
            conn.execute("SET lock_timeout TO '8s'")
            self._local.configured = conn
        return conn


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"), "requires isolated PostgreSQL test database")
class Postgres(Scenarios, unittest.TestCase):
    def setUp(self):
        self.schema = "hpoint_qa_" + uuid.uuid4().hex
        self.control = database.PostgresConnection(os.environ["HPOINT_TEST_DATABASE_URL"])
        self.control.execute('CREATE SCHEMA "' + self.schema + '"')
        self.prepare(IsolatedPostgres(os.environ["HPOINT_TEST_DATABASE_URL"], self.schema))

    def tearDown(self):
        self.close()
        # This randomly generated schema contains synthetic fixtures only.
        self.control.execute('DROP SCHEMA "' + self.schema + '" CASCADE')
        self.control.close()

    def race(self, *functions):
        gate = threading.Barrier(len(functions))
        def run(function):
            try:
                gate.wait(timeout=5)
                return function()
            finally:
                self.db.close()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            jobs = [pool.submit(run, function) for function in functions]
            return [job.result(timeout=20) for job in jobs]

    def test_race_two_helpers_one_request(self):
        rid = self.request()
        result = self.race(lambda: services.accept_open_request(rid,2), lambda: services.accept_open_request(rid,3))
        self.assertEqual(result.count("created"),1)
        self.assertIn(database.get_request(rid)["helper_id"],(2,3))

    def test_race_one_helper_two_requests(self):
        first, second = self.request(), self.request(owner=3)
        result = self.race(lambda:services.accept_open_request(first,2),lambda:services.accept_open_request(second,2))
        self.assertEqual(result.count("created"),1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests WHERE helper_id=2 AND status='in_progress'").fetchone()["n"],1)

    def test_race_reverse_pair_gets_one_hp_settlement(self):
        first, second = self.request(), self.request(owner=2)
        services.accept_open_request(first,2)
        services.accept_open_request(second,1)
        result = self.race(lambda:services.complete_request(first,2,confirmed_by=1),lambda:services.complete_request(second,1,confirmed_by=2))
        self.assertEqual(result,[True,True])
        self.assertEqual(self.db.execute("SELECT SUM(hp_settled) n FROM requests WHERE status='done'").fetchone()["n"],1)
        self.assertEqual(sum(database.get_user(u)["balance"] for u in (1,2)),2000+services.HELPER_REWARD-services.REQUEST_COST)

    def test_race_complete_and_admin_cancel_settles_once(self):
        rid = self.funded()
        services.accept_open_request(rid,2)
        result = self.race(lambda:services.complete_request(rid,2,confirmed_by=1),lambda:database.admin_cancel_request(4,rid)[0])
        self.assertEqual(sum(result),1)
        self.assertEqual(sum(reliability.wallet_balances(self.db,u)[0] for u in (1,2))+workflow.platform_income(self.db)["earned_test_rub"],500)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions WHERE request_id=? AND kind IN ('reward_refund','reward_earned')",(rid,)).fetchone()["n"],1)

    def test_race_payment_and_cancellation_never_strands_reserve(self):
        rid = self.request(reward=400)
        invoice,_,_=billing.create_request_reward_invoice(1,rid)
        self.race(lambda:billing.fulfill_invoice(invoice),lambda:database.admin_cancel_request(4,rid))
        self.assertEqual(database.get_request(rid)["status"],"cancelled")
        self.assertEqual(database.wallet_summary(1)["balance_rub"],400)
        self.assertNotEqual(database.get_request(rid)["reward_payment_status"],"paid")

    def test_race_duplicate_payment_callback(self):
        rid = self.request(reward=400)
        invoice,_,_=billing.create_request_reward_invoice(1,rid)
        result=self.race(lambda:billing.fulfill_invoice(invoice),lambda:billing.fulfill_invoice(invoice))
        self.assertEqual(sorted(item[1] for item in result),["already_paid","request_reward"])
        self.assertEqual(database.wallet_summary(1)["reserved_rub"],400)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM wallet_transactions").fetchone()["n"],2)

    def test_race_two_pro_payments_extend_instead_of_overwrite(self):
        first,_,_=billing.create_pending_invoice(1,"pro")
        second,_,_=billing.create_pending_invoice(1,"pro")
        self.race(lambda:billing.fulfill_invoice(first),lambda:billing.fulfill_invoice(second))
        until=datetime.fromisoformat(database.get_user(1)["pro_until"])
        if until.tzinfo is None:until=until.replace(tzinfo=timezone.utc)
        self.assertGreater(until,datetime.now(timezone.utc)+timedelta(days=59))

    def test_race_reserves_cannot_overdraw_test_wallet(self):
        database.grant_registration_bonus(1,500)
        first,second=self.request(reward=400),self.request(reward=400)
        def reserve(rid):
            try:return services.reserve_request_reward(rid,1,400)
            except ValueError as error:
                self.assertEqual(str(error),"insufficient wallet")
                return False
        result=self.race(lambda:reserve(first),lambda:reserve(second))
        self.assertEqual(sum(result),1)
        self.assertEqual(reliability.wallet_balances(self.db,1),(100,100))

    def test_race_expiry_and_acceptance_never_refunds_active_help(self):
        rid=self.funded()
        self.db.execute("UPDATE requests SET expires_at='2020-01-01T00:00:00+00:00' WHERE id=?",(rid,))
        self.race(services.expire_open_requests,lambda:services.accept_open_request(rid,2))
        row=database.get_request(rid)
        if row["status"]=="in_progress":
            self.assertEqual(row["reward_payment_status"],"paid")
            self.assertEqual(reliability.wallet_balances(self.db,1),(100,100))
        else:
            self.assertEqual(row["status"],"cancelled")
            self.assertEqual(reliability.wallet_balances(self.db,1),(500,500))

    def test_race_dispute_and_completion_is_atomic(self):
        rid=self.funded()
        services.accept_open_request(rid,2)
        def dispute():
            try:return database.create_request_dispute(rid,2,"Synthetic dispute")
            except ValueError:return None
        self.race(lambda:services.complete_request(rid,2,confirmed_by=1),dispute)
        row=database.get_request(rid)
        if row["dispute_status"]=="open":
            self.assertEqual(row["status"],"in_progress")
            self.assertEqual(reliability.wallet_balances(self.db,2),(0,0))
        else:self.assertEqual(row["status"],"done")
