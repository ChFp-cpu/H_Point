import sqlite3
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

from hpoint import commercial,database


class Commercial(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.patches=[patch.object(database,"db",self.db),patch.object(database,"REGISTRATION_BONUS_RUB",0)]
        for item in self.patches:item.start()
        database.init_db()
        commercial.initialize_schema(self.db)
        for uid in (1,2):
            database.create_user(uid,"Synthetic",web_verified=True)
            self.db.execute("UPDATE users SET email=?,email_verified=1 WHERE user_id=?",(f"user{uid}@example.test",uid))

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.db.close()

    def profile(self,uid=1,**changes):
        return commercial.save_profile(self.db,uid,dict(kind="trainer",title="Synthetic Studio",description="Test",contact="",**changes))

    def service(self,uid=1):
        return commercial.save_service(self.db,uid,dict(title="Synthetic service",description="Test",price_rub=700,duration_minutes=60))["id"]

    def client(self,uid=1):
        return commercial.save_client(self.db,uid,dict(name="Synthetic client",contact="Contact provided by client",notes="Private note"))["id"]

    def booking(self,uid=1,client=None,service=None):
        return commercial.save_booking(self.db,uid,dict(client_id=client or self.client(uid),service_id=service,title="Synthetic booking",starts_at="2030-01-01T12:00:00+03:00",duration_minutes=60,price_rub=700,notes="Test"))["id"]

    def credit(self,uid=1,amount=500,test=None):
        database.wallet_add_entry(uid,amount,"synthetic_credit","Synthetic test funds",f"synthetic:{uid}:{amount}:{self.db.execute('SELECT COUNT(*) FROM wallet_transactions').fetchone()[0]}",test_amount_rub=amount if test is None else test)

    def expire(self,uid=1):
        self.db.execute("UPDATE commercial_profiles SET trial_until='2020-01-01T00:00:00+00:00' WHERE user_id=?",(uid,))

    def test_profile_trial_is_seven_days_and_survives_edit(self):
        state=self.profile()
        p=state["profile"]
        self.assertTrue(p["active"])
        self.assertEqual(datetime.fromisoformat(p["trial_until"])-datetime.fromisoformat(p["trial_started_at"]),timedelta(days=7))
        self.assertEqual(p["contact"],"")
        changed=commercial.save_profile(self.db,1,dict(kind="foreman",title="Renamed studio",description="",contact=""))["profile"]
        self.assertEqual(changed["trial_started_at"],p["trial_started_at"])
        self.assertEqual(changed["trial_until"],p["trial_until"])
        self.assertEqual(changed["kind"],"foreman")

    def test_email_is_required_and_not_copied_into_contact(self):
        self.db.execute("UPDATE users SET email_verified=0 WHERE user_id=1")
        with self.assertRaisesRegex(ValueError,"email"):self.profile()
        self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=1")
        self.assertEqual(self.profile()["profile"]["contact"],"")

    def test_expired_profile_is_read_only_and_cannot_restart_trial(self):
        self.profile();client=self.client();service=self.service();booking=self.booking(client=client,service=service)
        self.expire()
        state=commercial.dashboard(self.db,1)
        self.assertFalse(state["profile"]["active"])
        self.assertEqual(len(state["clients"]),1)
        for operation in (self.profile,self.client,self.service,lambda:commercial.set_booking_status(self.db,1,booking,"completed"),lambda:self.booking(client=client,service=service)):
            with self.assertRaisesRegex(ValueError,"Пробный период"):operation()

    def test_renewal_uses_only_test_funds_and_preserves_real_balance(self):
        self.profile();self.credit(amount=300,test=0);self.credit(amount=500)
        until=datetime.fromisoformat(commercial.dashboard(self.db,1)["profile"]["access_until"])
        result=commercial.renew(self.db,1,"purchase-synthetic-1")
        self.assertTrue(result["created"])
        self.assertEqual(datetime.fromisoformat(result["ends_at"])-until,timedelta(days=30))
        amounts=self.db.execute("SELECT SUM(amount_rub) total,SUM(test_amount_rub) test FROM wallet_transactions WHERE user_id=1").fetchone()
        self.assertEqual((amounts["total"],amounts["test"]),(310,10))
        duplicate=commercial.renew(self.db,1,"purchase-synthetic-1")
        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["ends_at"],result["ends_at"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM commercial_renewals").fetchone()[0],1)

    def test_real_balance_cannot_fund_renewal(self):
        self.profile();self.credit(amount=1000,test=0)
        with self.assertRaisesRegex(ValueError,"тестовых"):commercial.renew(self.db,1,"synthetic-real-not-allowed")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM commercial_renewals").fetchone()[0],0)

    def test_renewal_after_expiry_starts_now(self):
        self.profile();self.expire();self.credit()
        result=commercial.renew(self.db,1,"synthetic-after-expiry")
        until=datetime.fromisoformat(result["ends_at"])
        self.assertGreater(until,datetime.now(timezone.utc)+timedelta(days=29,hours=23))
        self.assertTrue(commercial.dashboard(self.db,1)["profile"]["active"])

    def test_renewal_rolls_back_when_ledger_fails(self):
        self.profile();self.credit();before=commercial.dashboard(self.db,1)["profile"]["paid_until"]
        def fail(*args,**kwargs):raise RuntimeError("Synthetic ledger unavailable")
        with self.assertRaises(RuntimeError):commercial.renew(self.db,1,"synthetic-failure-key",fail)
        self.assertEqual(commercial.dashboard(self.db,1)["profile"]["paid_until"],before)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM commercial_renewals").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT SUM(test_amount_rub) FROM wallet_transactions WHERE user_id=1").fetchone()[0],500)

    def test_same_purchase_key_cannot_be_used_by_another_account(self):
        self.profile();self.profile(2);self.credit();self.credit(2)
        commercial.renew(self.db,1,"synthetic-global-key")
        with self.assertRaisesRegex(ValueError,"использован"):commercial.renew(self.db,2,"synthetic-global-key")
        self.assertEqual(self.db.execute("SELECT SUM(test_amount_rub) FROM wallet_transactions WHERE user_id=2").fetchone()[0],500)

    def test_clients_services_and_bookings_are_private(self):
        self.profile();self.profile(2);client=self.client();service=self.service();booking=self.booking(client=client,service=service)
        for operation in (lambda:commercial.save_client(self.db,2,dict(id=client,name="Other user")),lambda:commercial.save_service(self.db,2,dict(id=service,title="Other service")),lambda:commercial.set_booking_status(self.db,2,booking,"cancelled"),lambda:self.booking(uid=2,client=client,service=service)):
            with self.assertRaisesRegex(ValueError,"вашем кабинете"):operation()
        other=commercial.dashboard(self.db,2)
        self.assertEqual((other["clients"],other["services"],other["bookings"]),([],[],[]))

    def test_booking_status_and_dashboard_metrics(self):
        self.profile();service=self.service();client=self.client();booking=self.booking(client=client,service=service)
        self.assertEqual(commercial.dashboard(self.db,1)["bookings"][0]["starts_at"],"2030-01-01T09:00:00+00:00")
        before=commercial.dashboard(self.db,1)["metrics"]
        self.assertEqual((before["clients"],before["services"],before["planned"],before["revenue_test_rub"]),(1,1,1,0))
        commercial.set_booking_status(self.db,1,booking,"completed")
        after=commercial.dashboard(self.db,1)["metrics"]
        self.assertEqual((after["completed"],after["planned"],after["revenue_test_rub"]),(1,0,700))
        commercial.set_booking_status(self.db,1,booking,"cancelled")
        self.assertEqual(commercial.dashboard(self.db,1)["metrics"]["revenue_test_rub"],0)
        with self.assertRaises(ValueError):commercial.set_booking_status(self.db,1,booking,"unexpected")

    def test_invalid_fields_do_not_create_records(self):
        self.profile()
        for invalid in (-1,True,1.5,"NaN",1000001):
            with self.assertRaises(ValueError):commercial.save_service(self.db,1,dict(title="Synthetic",price_rub=invalid))
        with self.assertRaises(ValueError):commercial.save_client(self.db,1,dict(name="x"))
        with self.assertRaises(ValueError):commercial.save_booking(self.db,1,dict(client_id=1,title="Synthetic",starts_at="tomorrow"))
        self.assertEqual(commercial.dashboard(self.db,1)["services"],[])

    def test_service_and_client_archiving_preserve_booking_history(self):
        self.profile();service=self.service();client=self.client();self.booking(client=client,service=service)
        commercial.save_service(self.db,1,dict(id=service,title="Archived service",active=False))
        commercial.save_client(self.db,1,dict(id=client,name="Archived client",active=False))
        data=commercial.dashboard(self.db,1)
        self.assertEqual((data["metrics"]["services"],data["metrics"]["clients"]),(0,0))
        self.assertEqual(data["bookings"][0]["client_name"],"Archived client")

    def test_deleting_user_cascades_private_workspace(self):
        self.profile();self.booking(service=self.service())
        self.db.execute("DELETE FROM users WHERE user_id=1")
        for table in ("commercial_profiles","commercial_services","commercial_clients","commercial_bookings","commercial_renewals"):
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],0)

    def test_delete_workspace_erases_private_content_but_keeps_financial_history(self):
        self.profile();self.profile(2);self.booking(service=self.service());other=self.booking(uid=2,service=self.service(2))
        self.credit(amount=1000);commercial.renew(self.db,1,"synthetic-before-delete")
        ledger=[tuple(r) for r in self.db.execute("SELECT * FROM wallet_transactions ORDER BY id")]
        renewals=[tuple(r) for r in self.db.execute("SELECT * FROM commercial_renewals ORDER BY id")]
        self.assertEqual(commercial.delete_profile(self.db,1,True),{"deleted":True})
        self.assertEqual(commercial.summary(self.db,1),{"exists":False})
        data=commercial.dashboard(self.db,1)
        self.assertIsNone(data["profile"]);self.assertFalse(data["trial_available"])
        for key in ("clients","services","bookings","renewals"):self.assertEqual(data[key],[])
        for table in ("commercial_bookings","commercial_clients","commercial_services"):
            self.assertEqual(self.db.execute("SELECT COUNT(*) FROM "+table+" WHERE owner_id=1").fetchone()[0],0)
        row=self.db.execute("SELECT title,description,contact FROM commercial_profiles WHERE user_id=1").fetchone()
        self.assertEqual(tuple(row),("","",""))
        self.assertEqual([tuple(r) for r in self.db.execute("SELECT * FROM wallet_transactions ORDER BY id")],ledger)
        self.assertEqual([tuple(r) for r in self.db.execute("SELECT * FROM commercial_renewals ORDER BY id")],renewals)
        self.assertEqual(commercial.dashboard(self.db,2)["bookings"][0]["id"],other)
        self.assertEqual(commercial.delete_profile(self.db,1,True),{"deleted":False})
        with self.assertRaisesRegex(ValueError,"создайте"):commercial.renew(self.db,1,"synthetic-hidden-renew")
        with self.assertRaisesRegex(ValueError,"создайте"):self.service()

    def test_delete_recreate_keeps_original_trial_and_payment_dates(self):
        original=self.profile()["profile"];self.credit(amount=1000)
        renewal=commercial.renew(self.db,1,"synthetic-recreate-key")
        commercial.delete_profile(self.db,1,True)
        recreated=self.profile()["profile"]
        self.assertEqual(recreated["trial_started_at"],original["trial_started_at"])
        self.assertEqual(recreated["trial_until"],original["trial_until"])
        self.assertEqual(recreated["paid_until"],renewal["ends_at"])
        self.assertFalse(commercial.dashboard(self.db,1)["trial_available"])
        self.assertFalse(commercial.renew(self.db,1,"synthetic-recreate-key")["created"])
        self.assertEqual(self.db.execute("SELECT SUM(test_amount_rub) FROM wallet_transactions WHERE user_id=1").fetchone()[0],510)

    def test_expired_deleted_workspace_can_be_recreated_but_does_not_get_a_new_trial(self):
        self.profile();self.expire();commercial.delete_profile(self.db,1,True)
        recreated=self.profile()["profile"]
        self.assertFalse(recreated["active"])
        self.assertEqual(recreated["trial_until"],"2020-01-01T00:00:00+00:00")
        with self.assertRaisesRegex(ValueError,"Пробный период"):self.service()
        self.credit();commercial.renew(self.db,1,"synthetic-recreated-renewal")
        self.assertTrue(commercial.dashboard(self.db,1)["profile"]["active"])
        self.service()

    def test_delete_requires_explicit_confirmation_and_rolls_back_partial_erasure(self):
        self.profile();self.booking(service=self.service())
        for confirmation in (None,False,1,"true"):
            with self.assertRaisesRegex(ValueError,"Подтвердите"):commercial.delete_profile(self.db,1,confirmation)
        self.db.execute("CREATE TRIGGER synthetic_delete_failure BEFORE DELETE ON commercial_clients BEGIN SELECT RAISE(ABORT,'synthetic delete failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):commercial.delete_profile(self.db,1,True)
        data=commercial.dashboard(self.db,1)
        self.assertIsNotNone(data["profile"]);self.assertEqual(len(data["bookings"]),1)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM commercial_deleted_profiles").fetchone()[0],0)
        self.db.execute("DROP TRIGGER synthetic_delete_failure")
        self.db.execute("UPDATE users SET is_blocked=1 WHERE user_id=1")
        with self.assertRaisesRegex(ValueError,"недоступен"):commercial.delete_profile(self.db,1,True)

    def test_summary_is_empty_until_profile_exists(self):
        self.assertEqual(commercial.summary(self.db,1),{"exists":False})
        self.profile(2)
        self.assertEqual(commercial.summary(self.db,1),{"exists":False})

    def test_summary_only_exposes_own_counts_and_next_three_appointments(self):
        self.profile();self.profile(2)
        client=self.client();service=self.service()
        for index in range(5):
            self.booking(client=client,service=service)
        self.booking(uid=2,client=self.client(2),service=self.service(2))
        data=commercial.summary(self.db,1)
        self.assertTrue(data["exists"])
        self.assertEqual((data["title"],data["kind"]),("Synthetic Studio","trainer"))
        self.assertEqual((data["metrics"]["clients"],data["metrics"]["services"],data["metrics"]["planned"]),(1,1,5))
        self.assertEqual(len(data["next_appointments"]),3)
        self.assertTrue(all(set(row)=={"id","title","starts_at","client_name"} for row in data["next_appointments"]))
        self.assertNotIn("Private note",str(data))
        self.assertNotIn("Contact provided",str(data))
        self.assertNotIn("@example.test",str(data))

    def test_summary_omits_past_and_cancelled_appointments_but_keeps_expired_profile(self):
        self.profile();client=self.client();service=self.service()
        past=self.booking(client=client,service=service)
        self.db.execute("UPDATE commercial_bookings SET starts_at='2020-01-01T00:00:00+00:00' WHERE id=?",(past,))
        cancelled=self.booking(client=client,service=service)
        commercial.set_booking_status(self.db,1,cancelled,"cancelled")
        self.expire()
        data=commercial.summary(self.db,1)
        self.assertTrue(data["exists"])
        self.assertFalse(data["active"])
        self.assertEqual(data["next_appointments"],[])
        self.db.execute("UPDATE users SET email_verified=0 WHERE user_id=1")
        with self.assertRaisesRegex(ValueError,"email"):commercial.summary(self.db,1)


if __name__=="__main__":unittest.main()
