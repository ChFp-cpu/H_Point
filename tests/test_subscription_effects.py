"""Paid priorities change the actual matching results and expire normally."""
import sqlite3
import unittest
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


if __name__=="__main__":unittest.main()
