"""Administrative test-balance corrections on a disposable database only."""
import sqlite3
import unittest
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from hpoint import database
from scripts.set_test_balances import set_test_balances


class TestBalances(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE users(user_id INTEGER PRIMARY KEY,email_verified INTEGER,is_blocked INTEGER);
            CREATE TABLE requests(id INTEGER PRIMARY KEY,requester_id INTEGER,reward_rub INTEGER,
                reward_test_rub INTEGER,reward_payment_status TEXT,status TEXT);
            CREATE TABLE wallet_transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,
                amount_rub INTEGER,test_amount_rub INTEGER,kind TEXT,description TEXT,request_id INTEGER,
                invoice_id INTEGER,reference TEXT UNIQUE,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE schema_migrations(name TEXT PRIMARY KEY);
            INSERT INTO schema_migrations VALUES('existing-migration');
        """)
        self.patcher = patch.object(database, "db", self.db)
        self.patcher.start()
        for uid, verified, blocked in ((1,1,0),(2,1,0),(3,1,1),(4,0,0),(5,0,1)):
            self.db.execute("INSERT INTO users VALUES(?,?,?)", (uid,verified,blocked))
        self.add(1,500,500); self.add(1,700,0)
        self.add(2,12000,12000); self.add(2,100,0)
        self.add(3,10000,10000); self.add(5,-50,-50)
        self.db.execute("INSERT INTO requests VALUES(8,1,600,400,'paid','in_progress')")

    def tearDown(self):
        self.patcher.stop()
        self.db.close()

    def add(self,uid,total,test):
        index=self.db.execute("SELECT COUNT(*) FROM wallet_transactions").fetchone()[0]
        database.wallet_add_entry(uid,total,"synthetic","Synthetic seed","seed:"+str(index),test_amount_rub=test)

    def apply(self,**kwargs):
        return set_test_balances(self.db,database.wallet_add_entry,batch_key="synthetic-batch",**kwargs)

    def balances(self,uid):
        row=self.db.execute("SELECT COALESCE(SUM(amount_rub),0) total,COALESCE(SUM(test_amount_rub),0) test FROM wallet_transactions WHERE user_id=?",(uid,)).fetchone()
        return row["total"]-row["test"],row["test"]

    def rows(self,table):
        return [tuple(row) for row in self.db.execute("SELECT * FROM "+table+" ORDER BY 1").fetchall()]

    def test_exact_target_for_above_below_equal_blocked_and_unverified(self):
        result=self.apply()
        self.assertTrue(result["applied"])
        self.assertEqual(result["users_count"],5)
        self.assertEqual(result["adjusted_count"],4)
        self.assertEqual(result["credited_rub"],29550)
        self.assertEqual(result["debited_rub"],2000)
        for uid in range(1,6):
            self.assertEqual(self.balances(uid),({1:700,2:100}.get(uid,0),10000))
        corrections=self.db.execute("SELECT amount_rub,test_amount_rub FROM wallet_transactions WHERE kind='test_balance_adjustment'").fetchall()
        self.assertTrue(all(row["amount_rub"]==row["test_amount_rub"] for row in corrections))

    def test_history_real_funds_reserves_and_migration_registry_are_preserved(self):
        history=self.rows("wallet_transactions"); reserves=self.rows("requests"); migrations=self.rows("schema_migrations")
        self.apply()
        self.assertEqual(self.rows("wallet_transactions")[:len(history)],history)
        self.assertEqual(self.rows("requests"),reserves)
        self.assertEqual(self.rows("schema_migrations"),migrations)
        self.assertEqual(self.balances(1),(700,10000))
        self.assertEqual(self.balances(2),(100,10000))

    def test_repeating_batch_does_not_restore_spent_money_or_touch_new_users(self):
        first=self.apply()
        self.add(1,-490,-490)
        self.db.execute("INSERT INTO users VALUES(99,0,1)")
        history=self.rows("wallet_transactions")
        repeated=self.apply()
        self.assertFalse(repeated["applied"])
        self.assertTrue(repeated["already_applied"])
        self.assertEqual(repeated["created_at"],first["created_at"])
        self.assertEqual(self.balances(1),(700,9510))
        self.assertEqual(self.balances(99),(0,0))
        self.assertEqual(self.rows("wallet_transactions"),history)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM test_balance_batches").fetchone()[0],1)

    def test_same_batch_with_different_target_is_rejected(self):
        self.apply()
        history=self.rows("wallet_transactions")
        with self.assertRaisesRegex(ValueError,"different target"):
            self.apply(target=9000)
        self.assertEqual(self.rows("wallet_transactions"),history)

    def test_failure_rolls_back_partial_changes_and_batch_record(self):
        history=self.rows("wallet_transactions")
        calls=[]
        def fail_second(*args,**kwargs):
            calls.append(args[0])
            if len(calls)==2:
                raise RuntimeError("synthetic ledger failure")
            return database.wallet_add_entry(*args,**kwargs)
        with self.assertRaisesRegex(RuntimeError,"synthetic ledger failure"):
            set_test_balances(self.db,fail_second,batch_key="synthetic-failure")
        self.assertEqual(calls,[1,2])
        self.assertEqual(self.rows("wallet_transactions"),history)
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='test_balance_batches'").fetchone())
        self.assertTrue(set_test_balances(self.db,database.wallet_add_entry,batch_key="synthetic-failure")["applied"])

    def test_false_or_incorrect_callback_rolls_back(self):
        history=self.rows("wallet_transactions")
        with self.assertRaisesRegex(RuntimeError,"not inserted"):
            set_test_balances(self.db,lambda *a,**k:False,batch_key="synthetic-false")
        self.assertEqual(self.rows("wallet_transactions"),history)
        def wrong_writer(*args,**kwargs):
            kwargs["test_amount_rub"]=0
            return database.wallet_add_entry(*args,**kwargs)
        with self.assertRaisesRegex(RuntimeError,"verification failed"):
            set_test_balances(self.db,wrong_writer,batch_key="synthetic-wrong")
        self.assertEqual(self.rows("wallet_transactions"),history)

    def test_zero_target_uses_test_only_debits(self):
        self.apply(target=0)
        for uid in range(1,6):
            self.assertEqual(self.balances(uid),({1:700,2:100}.get(uid,0),0))

    def test_invalid_arguments_make_no_changes(self):
        history=self.rows("wallet_transactions")
        for target,key in ((-1,"key"),(True,"key"),(1.5,"key"),(10000,""),(10000,"x"*201)):
            with self.assertRaises(ValueError):
                set_test_balances(self.db,database.wallet_add_entry,target=target,batch_key=key)
        self.assertEqual(self.rows("wallet_transactions"),history)

    def test_postgres_lock_order_precedes_wallet_snapshot(self):
        underlying=self.db
        class RecordingPostgres:
            is_postgres=True
            def __init__(self): self.statements=[]
            def execute(self,sql,params=()):
                self.statements.append(sql)
                if "pg_advisory_xact_lock" in sql or sql.startswith("LOCK TABLE"):
                    return underlying.execute("SELECT 1")
                return underlying.execute(sql.replace(" FOR NO KEY UPDATE",""),params)
        recording=RecordingPostgres()
        with patch.object(database,"db",recording):
            result=set_test_balances(recording,database.wallet_add_entry,batch_key="synthetic-pg-order")
        self.assertTrue(result["applied"])
        statements=recording.statements
        self.assertEqual(statements[0],"BEGIN")
        self.assertIn("pg_advisory_xact_lock",statements[1])
        users=statements.index("SELECT user_id FROM users ORDER BY user_id FOR NO KEY UPDATE")
        wallet=statements.index("LOCK TABLE wallet_transactions IN EXCLUSIVE MODE")
        snapshot=next(i for i,sql in enumerate(statements) if "GROUP BY user_id" in sql)
        self.assertLess(users,wallet)
        self.assertLess(wallet,snapshot)

    def test_regular_script_and_stdin_use_the_same_standalone_implementation(self):
        root=Path(__file__).resolve().parents[1]
        script=root / "scripts" / "set_test_balances.py"
        with tempfile.TemporaryDirectory(prefix=".test-balances-",dir=root) as folder:
            path=Path(folder)/"synthetic.db"
            destination=sqlite3.connect(path)
            self.db.backup(destination)
            destination.close()
            env=dict(os.environ,DB_PATH=str(path),DATABASE_URL="",REGISTRATION_BONUS_RUB="0",PYTHONIOENCODING="utf-8")
            regular=subprocess.run([sys.executable,str(script),"--target","10000","--batch-key","synthetic-cli"],
                cwd=folder,env=env,capture_output=True,text=True,encoding="utf-8",check=True)
            self.assertTrue(json.loads(regular.stdout)["applied"])
            stdin=subprocess.run([sys.executable,"-","--target","10000","--batch-key","synthetic-cli"],
                cwd=root,env=env,input=script.read_text(encoding="utf-8"),capture_output=True,text=True,encoding="utf-8",check=True)
            self.assertTrue(json.loads(stdin.stdout)["already_applied"])


if __name__ == "__main__":
    unittest.main()
