"""Paid priorities change the actual matching results and expire normally."""
import sqlite3
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

from hpoint import billing,database,services


class SubscriptionEffects(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.patches=[patch.object(database,"db",self.db),patch.object(services,"db",self.db),patch.object(billing,"db",self.db),patch.object(database,"REGISTRATION_BONUS_RUB",0)]
        for p in self.patches:p.start()
        database.init_db()
        for uid in (1,2,3,4):
            database.create_user(uid,"Synthetic participant",email=f"synthetic{uid}@example.test",web_verified=True)
            self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
            database.wallet_add_entry(uid,1000,"test","Synthetic test funds",f"effects-seed-{uid}",test_amount_rub=1000)
        for uid in (2,3):
            services.set_helper_categories(uid,["tech"])
            services.add_to_queue(uid)

    def tearDown(self):
        self.db.close()
        for p in reversed(self.patches):p.stop()

    def request(self,owner=1):
        return services.create_request(owner,dict(what="Synthetic technical help",place="Synthetic district",time_needed="today",urgency="Без срочности",details="",category="tech"))

    def test_pro_purchase_promotes_helper_in_real_matching_until_expiry(self):
        rid=self.request()
        before={r["user_id"]:r["score"] for r in services.smart_match(rid)}
        self.assertEqual(before[2],before[3])
        invoice,created=billing.purchase_with_wallet(3,"pro",{},"effects-helper-pro")
        self.assertTrue(created)
        after=services.smart_match(rid)
        self.assertEqual(after[0]["user_id"],3)
        self.assertEqual(after[0]["score"],before[3]+8)
        self.db.execute("UPDATE users SET pro_until='2020-01-01T00:00:00+00:00' WHERE user_id=3")
        expired={r["user_id"]:r["score"] for r in services.smart_match(rid)}
        self.assertEqual(expired,before)

    def test_requester_pro_and_boost_change_helper_request_ranking(self):
        first=self.request(1);second=self.request(4)
        self.assertEqual(services.smart_requests_for_helper(2)[0]["request"]["id"],first)
        billing.purchase_with_wallet(4,"pro",{},"effects-requester-pro")
        self.assertEqual(services.smart_requests_for_helper(2)[0]["request"]["id"],second)
        billing.purchase_with_wallet(1,"boost",{"request_id":first},"effects-request-boost")
        self.assertEqual(services.smart_requests_for_helper(2)[0]["request"]["id"],first)
        self.assertEqual(database.get_request(first)["priority_boost"],100)

    def test_access_status_tracks_purchase_expiry_and_live_effects(self):
        initial=billing.subscription_state(1)
        self.assertEqual(initial["pro"]["status"],"inactive")
        self.assertFalse(initial["pro"]["active"])
        self.assertEqual(initial["pro"]["effects"],{"helper_priority":0,"request_priority":0})
        invoice,_=billing.purchase_with_wallet(1,"pro",{},"status-first-term")
        state=billing.subscription_state(1)
        self.assertTrue(state["pro"]["active"])
        self.assertEqual(state["pro"]["days_remaining"],30)
        self.assertEqual(state["pro"]["effects"],{"helper_priority":8,"request_priority":10})
        self.assertFalse(state["pro"]["auto_renew"])
        self.assertEqual(state["history"][0]["invoice_id"],invoice)
        self.assertEqual(state["history"][0]["provider"],"test_wallet")
        self.db.execute("UPDATE users SET pro_until='2020-01-01T00:00:00+00:00' WHERE user_id=1")
        expired=billing.subscription_state(1)["pro"]
        self.assertEqual(expired["status"],"expired")
        self.assertEqual(expired["days_remaining"],0)
        self.assertFalse(services.is_pro(1))
        self.assertEqual(expired["effects"],{"helper_priority":0,"request_priority":0})

    def test_active_pro_cannot_silently_charge_another_month(self):
        billing.purchase_with_wallet(1,"pro",{},"safe-first-term")
        before=database.wallet_summary(1)["test_balance_rub"]
        until=database.get_user(1)["pro_until"]
        with self.assertRaisesRegex(ValueError,"subscription already active"):
            billing.purchase_with_wallet(1,"pro",{},"silent-next-term")
        with self.assertRaisesRegex(ValueError,"subscription changed"):
            billing.purchase_with_wallet(1,"pro",{"renew":True,"expected_until":"2020-01-01"},"stale-next-term")
        self.assertEqual(database.get_user(1)["pro_until"],until)
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"],before)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM billing_invoices").fetchone()["n"],1)

    def test_explicit_renewal_preserves_days_and_replay_is_idempotent(self):
        billing.purchase_with_wallet(1,"pro",{},"renew-first-term")
        until=database.get_user(1)["pro_until"]
        metadata={"renew":True,"expected_until":until}
        invoice,created=billing.purchase_with_wallet(1,"pro",metadata,"renew-next-term")
        self.assertTrue(created)
        self.assertEqual(datetime.fromisoformat(database.get_user(1)["pro_until"])-datetime.fromisoformat(until),timedelta(days=30))
        self.assertEqual(billing.purchase_with_wallet(1,"pro",metadata,"renew-next-term"),(invoice,False))
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"],1000-298)
        self.assertEqual(billing.subscription_state(1)["pro"]["days_remaining"],60)
        with self.assertRaisesRegex(ValueError,"subscription changed"):
            billing.purchase_with_wallet(1,"pro",metadata,"other-tab-term")
        self.assertEqual(len(billing.subscription_state(1)["history"]),2)
        self.assertEqual(billing.subscription_state(1)["history"][0]["status"],"scheduled")

    def test_purchase_key_cannot_change_the_product_or_request(self):
        self.db.execute("UPDATE users SET balance=1000 WHERE user_id=1")
        first=self.request();second=self.request()
        billing.purchase_with_points(1,"boost",{"request_id":first},"bound-product-key")
        for item,metadata in (("pro",{}),("boost",{"request_id":second})):
            with self.assertRaisesRegex(ValueError,"purchase key already used"):
                billing.purchase_with_points(1,item,metadata,"bound-product-key")
        self.assertEqual(database.get_user(1)["balance"],975)
        self.assertEqual(database.get_request(second)["priority_boost"],0)
        self.assertIsNone(database.get_user(1)["pro_until"])

    def test_purchase_key_cannot_change_wallet_metadata(self):
        first=self.request();second=self.request()
        billing.purchase_with_wallet(1,"boost",{"request_id":first},"wallet-bound-key")
        with self.assertRaisesRegex(ValueError,"purchase key already used"):
            billing.purchase_with_wallet(1,"boost",{"request_id":second},"wallet-bound-key")
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"],951)

    def test_promotion_retry_after_request_closes_returns_original_invoice(self):
        rid=self.request()
        metadata={"request_id":rid}
        invoice,_=billing.purchase_with_wallet(1,"boost",metadata,"closed-request-retry")
        self.db.execute("UPDATE requests SET status='cancelled' WHERE id=?",(rid,))
        self.assertEqual(billing.purchase_with_wallet(1,"boost",metadata,"closed-request-retry"),(invoice,False))
        self.assertEqual(database.wallet_summary(1)["test_balance_rub"],951)

    def test_legacy_response_priority_is_visible_and_expires_with_request(self):
        rid=self.request()
        services.grant_entitlement(1,"more_responses",request_id=rid)
        state=billing.subscription_state(1)
        self.assertFalse(state["legacy_more_responses"]["sold"])
        self.assertEqual(state["promotions"][0]["source"],"more_responses")
        self.assertEqual(state["promotions"][0]["priority"],50)
        self.assertTrue(state["promotions"][0]["active"])
        self.db.execute("UPDATE requests SET status='cancelled' WHERE id=?",(rid,))
        self.assertFalse(billing.subscription_state(1)["promotions"][0]["active"])

    def test_timezone_and_legacy_dates_have_the_same_status_as_matching(self):
        for value in ((datetime.now(timezone.utc)-timedelta(minutes=10)).astimezone(timezone(timedelta(hours=3))).isoformat(),
                      (datetime.now(timezone.utc)+timedelta(days=1)).replace(tzinfo=None).isoformat(),"invalid"):
            self.db.execute("UPDATE users SET pro_until=? WHERE user_id=1",(value,))
            state=billing.subscription_state(1)["pro"]
            self.assertEqual(state["active"],services.is_pro(1))
            if value!="invalid":self.assertEqual(state["renewal_token"],value)

    def test_expired_term_restarts_from_now_without_old_history_loss(self):
        self.db.execute("UPDATE users SET pro_until='2020-01-01T00:00:00' WHERE user_id=1")
        billing.purchase_with_wallet(1,"pro",{},"expired-new-term")
        state=billing.subscription_state(1)
        self.assertTrue(state["pro"]["active"])
        self.assertEqual(state["pro"]["days_remaining"],30)
        self.assertEqual(len(state["history"]),1)


if __name__=="__main__":unittest.main()
