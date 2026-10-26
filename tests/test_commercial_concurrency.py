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

    def test_concurrent_identical_renewal_is_idempotent(self):
        result=self.race("synthetic-race-same-key","synthetic-race-same-key")
        self.assertEqual(sorted(row["created"] for row in result),[False,True])
        self.assert_single_debit()

    def test_concurrent_different_renewals_cannot_overdraw(self):
        result=self.race("synthetic-race-key-one","synthetic-race-key-two")
        self.assertEqual(sum(isinstance(row,dict) for row in result),1)
        self.assert_single_debit()


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
