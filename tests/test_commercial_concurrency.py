from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from hpoint import commercial,database


class RenewalRaces:
    def prepare(self,db):
        self.db=db
        self.patches=[patch.object(database,"db",db),patch.object(database,"REGISTRATION_BONUS_RUB",0)]
        for item in self.patches:item.start()
        database.init_db();commercial.initialize_schema(db)
        database.create_user(1,"Synthetic commercial user")
        db.execute("UPDATE users SET email='commercial@example.test',email_verified=1 WHERE user_id=1")
        commercial.save_profile(db,1,dict(kind="organization",title="Synthetic organisation"))
        database.wallet_add_entry(1,500,"synthetic_test","Synthetic funds","commercial-race-credit",test_amount_rub=500)

    def close(self):
        self.db.close()
        for item in reversed(self.patches):item.stop()

    def race(self,*keys):
        gate=threading.Barrier(len(keys))
        def purchase(key):
            try:
                gate.wait(timeout=5)
                try:return commercial.renew(self.db,1,key)
                except ValueError as error:return str(error)
            finally:self.db.close()
        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            jobs=[pool.submit(purchase,key) for key in keys]
            return [job.result(timeout=20) for job in jobs]

    def assert_single_debit(self):
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_renewals").fetchone()["n"],1)
        row=self.db.execute("SELECT SUM(amount_rub) total,SUM(test_amount_rub) test FROM wallet_transactions WHERE user_id=1").fetchone()
        self.assertEqual((row["total"],row["test"]),(10,10))

    def test_delete_racing_renewal_never_recreates_or_loses_payment_history(self):
        original=commercial.dashboard(self.db,1)["profile"]
        gate=threading.Barrier(2)
        def run(function):
            try:
                gate.wait(timeout=5)
                try:return function()
                except ValueError as error:return str(error)
            finally:self.db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(run,lambda:commercial.renew(self.db,1,"synthetic-delete-race")),pool.submit(run,lambda:commercial.delete_profile(self.db,1,True))]
            results=[job.result(timeout=20) for job in jobs]
        self.assertEqual(results[1],{"deleted":True})
        self.assertIsNone(commercial.dashboard(self.db,1)["profile"])
        self.assertEqual(commercial.summary(self.db,1),{"exists":False})
        renewals=self.db.execute("SELECT COUNT(*) n FROM commercial_renewals").fetchone()["n"]
        amount=self.db.execute("SELECT SUM(test_amount_rub) amount FROM wallet_transactions WHERE user_id=1").fetchone()["amount"]
        self.assertIn((renewals,amount),((0,500),(1,10)))
        self.assertEqual(isinstance(results[0],dict),bool(renewals))
        recreated=commercial.save_profile(self.db,1,dict(kind="organization",title="Recreated organisation"))["profile"]
        self.assertEqual(recreated["trial_until"],original["trial_until"])
        self.assertEqual(bool(recreated["paid_until"]),bool(renewals))

    def test_concurrent_identical_renewal_is_idempotent(self):
        result=self.race("synthetic-race-same-key","synthetic-race-same-key")
        self.assertEqual(sorted(row["created"] for row in result),[False,True])
        self.assert_single_debit()

    def test_concurrent_different_renewals_cannot_overdraw(self):
        result=self.race("synthetic-race-key-one","synthetic-race-key-two")
        self.assertEqual(sum(isinstance(row,dict) for row in result),1)
        self.assert_single_debit()

    def race_actions(self,*functions):
        gate=threading.Barrier(len(functions))
        def run(function):
            try:
                gate.wait(timeout=5)
                try:return function()
                except (ValueError,PermissionError) as error:return str(error)
            finally:self.db.close()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            jobs=[pool.submit(run,function) for function in functions]
            return [job.result(timeout=20) for job in jobs]

    def post(self,uid,suffix,data):
        return commercial.post_action(self.db,uid,"/api/commercial"+suffix,{"owner_id":1,**data})

    def add_member(self):
        database.create_user(-2,"Synthetic member",web_verified=True)
        self.db.execute("UPDATE users SET email='member@example.test',email_verified=1 WHERE user_id=-2")
        return self.post(1,"/team/invite",{"email":"member@example.test"})["id"]

    def test_concurrent_assigned_bookings_cannot_double_book(self):
        client=self.post(1,"/clients",{"name":"Synthetic client"})["id"]
        payload=dict(title="Same assigned interval",client_id=client,assignee_id=1,starts_at="2030-01-01T12:00:00+00:00",duration_minutes=60)
        result=self.race_actions(lambda:self.post(1,"/bookings",payload),lambda:self.post(1,"/bookings",payload))
        self.assertEqual(sum(isinstance(r,dict) for r in result),1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_bookings").fetchone()["n"],1)

    def test_revoke_racing_accept_has_no_access_after_revocation_wins(self):
        item=self.add_member()
        results=self.race_actions(lambda:self.post(1,"/team/revoke",{"invitation_id":item}),lambda:self.post(-2,"/team/accept",{"invitation_id":item}))
        self.assertIsInstance(results[0],dict)
        accepted=isinstance(results[1],dict)
        count=self.db.execute("SELECT COUNT(*) n FROM commercial_members WHERE owner_id=1 AND user_id=-2").fetchone()["n"]
        self.assertEqual(count,int(accepted))
        self.assertIn(self.db.execute("SELECT status FROM commercial_invitations WHERE id=?",(item,)).fetchone()["status"],("accepted","revoked"))

    def test_remove_racing_member_write_cannot_leave_future_access(self):
        item=self.add_member();self.post(-2,"/team/accept",{"invitation_id":item})
        results=self.race_actions(lambda:self.post(1,"/team/remove",{"user_id":-2}),lambda:self.post(-2,"/tasks",{"title":"Concurrent task","assignee_id":-2}))
        self.assertIsInstance(results[0],dict)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_members WHERE user_id=-2").fetchone()["n"],0)
        with self.assertRaises(PermissionError):self.post(-2,"/tasks",{"title":"Write after removal"})
        for row in self.db.execute("SELECT assignee_id FROM commercial_tasks WHERE owner_id=1").fetchall():self.assertIsNone(row["assignee_id"])


class SQLiteRenewalRaces(RenewalRaces,unittest.TestCase):
    def setUp(self):
        temporary_root=None
        if os.name=="nt":
            temporary_root=Path(__file__).resolve().parents[1]/".theme-qa"
            temporary_root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix="commercial-race-",dir=temporary_root)
        self.prepare(database.SQLiteConnection(str(Path(self.temp.name)/"commercial-race.db")))

    def tearDown(self):
        self.close();self.temp.cleanup()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"),"requires isolated PostgreSQL test database")
class PostgreSQLRenewalRaces(RenewalRaces,unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema="commercial_qa_"+uuid.uuid4().hex
        url=os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control=database.PostgresConnection(url)
        self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url,self.schema))

    def tearDown(self):
        self.close()
        self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE')
        self.control.close()
