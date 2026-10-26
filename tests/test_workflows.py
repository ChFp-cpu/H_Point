import sqlite3
import unittest
from unittest.mock import patch
from hpoint import database, services, billing, workflow, web


class Workflows(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.patches=[patch.object(m,'db',self.db) for m in (database,services,billing,web)]
        for p in self.patches:p.start()
        database.init_db()
        for uid in (1,2,3):
            database.create_user(uid,'Synthetic '+str(uid),email=f'qa{uid}@example.test')
            self.db.execute('UPDATE users SET email_verified=1,balance=1000 WHERE user_id=?',(uid,))
        database.grant_registration_bonus(1,500)

    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.db.close()

    def request(self,reward=400):
        return services.create_request(1,dict(what='Synthetic help',place='Test address',time_needed='Today',urgency='Normal',details='Synthetic',reward_rub=reward))

    def test_reserve_is_available_before_any_helper_is_selected(self):
        rid=self.request()
        self.assertTrue(services.reserve_request_reward(rid,1,400))
        self.assertIsNone(database.get_request(rid)['helper_id'])
        self.assertEqual(database.get_request(rid)['reward_test_rub'],400)

    def test_unfunded_help_is_cancelled_after_five_minutes(self):
        with patch.object(workflow,'reserve_deadline',return_value='2020-01-01T00:00:00+00:00'):
            rid=self.request()
        with self.assertRaisesRegex(ValueError,'deadline'):services.reserve_request_reward(rid,1,400)
        services.expire_open_requests()
        self.assertEqual(database.get_request(rid)['status'],'cancelled')
        self.assertIn('5 минут',database.get_request(rid)['cancel_reason'])
        self.assertEqual(database.wallet_summary(1)['test_balance_rub'],500)

    def test_funded_help_is_not_cancelled_by_reserve_deadline(self):
        rid=self.request()
        services.reserve_request_reward(rid,1,400)
        self.db.execute("UPDATE requests SET reserve_deadline_at='2020-01-01T00:00:00+00:00' WHERE id=?",(rid,))
        services.expire_open_requests()
        self.assertEqual(database.get_request(rid)['status'],'open')

    def test_commission_is_exactly_once_and_helper_receives_net(self):
        rid=self.request()
        services.reserve_request_reward(rid,1,400)
        services.accept_open_request(rid,2)
        self.assertTrue(services.complete_request(rid,2,confirmed_by=1))
        self.assertFalse(services.complete_request(rid,2,confirmed_by=1))
        self.assertEqual(database.wallet_summary(2)['test_balance_rub'],340)
        self.assertEqual(workflow.platform_income(self.db)['earned_test_rub'],60)
        self.assertEqual(database.get_request(rid)['helper_reward_rub'],340)
        self.assertEqual(sum(database.wallet_summary(uid)['test_balance_rub'] for uid in (1,2))+60,500)

    def test_either_participant_can_cancel_active_help_and_refund_once(self):
        rid=self.request()
        services.reserve_request_reward(rid,1,400)
        services.accept_open_request(rid,2)
        self.assertFalse(services.cancel_request(rid,3))
        self.assertTrue(services.cancel_request(rid,2,'Plans changed'))
        self.assertFalse(services.cancel_request(rid,1))
        self.assertEqual(database.wallet_summary(1)['test_balance_rub'],500)
        self.assertEqual(database.wallet_summary(2)['test_balance_rub'],0)
        self.assertEqual(workflow.platform_income(self.db)['earned_test_rub'],0)

    def test_real_funds_are_hidden_and_cannot_buy_paid_features(self):
        database.wallet_add_entry(2,1000,'payment','Historical real payment','real')
        self.assertEqual(web.public_wallet_summary(2)['balance_rub'],0)
        self.assertEqual(web.public_wallet_summary(2)['transactions'],[])
        with self.assertRaisesRegex(ValueError,'insufficient_wallet'):billing.purchase_with_wallet(2,'pro',{},'cannot-spend-real')
        self.assertEqual(database.wallet_summary(2)['balance_rub'],1000)

    def test_real_checkout_is_disabled(self):
        invoice,_,_=billing.create_pending_invoice(1,'pro')
        with self.assertRaisesRegex(ValueError,'тестовые'):billing.create_payment(invoice)

    def test_helper_without_point_is_not_locked_out_by_radius(self):
        rid=self.request(reward=0)
        self.db.execute("UPDATE users SET helper_radius_km=10,lat=NULL,lon=NULL WHERE user_id=2")
        self.assertIn(rid,[item["request"]["id"] for item in services.smart_requests_for_helper(2)])
