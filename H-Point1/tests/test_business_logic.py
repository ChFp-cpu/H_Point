import sqlite3
import unittest
import hpoint.database as database
import hpoint.services as services
from hpoint.config import *

class BusinessLogicTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None); self.db.row_factory=sqlite3.Row
        database.db=self.db; services.db=self.db; database.init_db()
    def tearDown(self):
        database.db=None; services.db=None; self.db.close()
    def add_user(self,uid,balance=100,skills='',portfolio=''):
        database.create_user(uid,f'User {uid}',None); self.db.execute('UPDATE users SET balance=?,skills=?,portfolio=? WHERE user_id=?',(balance,skills,portfolio,uid))
    def make_request(self,uid,skills=''):
        return services.create_request(uid,{'what':'Помочь с компьютером','place':'Пушкино','time_needed':'Сегодня','urgency':URGENCY_OPTIONS[1],'details':'Тест','required_skills':skills})
    def test_mutual_selection(self):
        self.add_user(1); self.add_user(2,skills='Python, ремонт ПК',portfolio='github.com/user')
        rid=self.make_request(1,'Python, ремонт ПК'); self.assertTrue(services.apply_to_request(rid,2)); apps=services.get_candidates(rid); self.assertEqual(len(apps),1)
        result=services.decide_application(apps[0]['id'],1,True); self.assertTrue(result['accepted']); self.assertEqual(database.get_request(rid)['helper_id'],2)
    def test_rejection(self):
        self.add_user(1); self.add_user(2); rid=self.make_request(1); services.apply_to_request(rid,2); app=services.get_candidates(rid)[0]; self.assertTrue(services.decide_application(app['id'],1,False)); self.assertEqual(services.get_candidates(rid),[])
    def test_completion_economy(self):
        self.add_user(1); self.add_user(2); rid=self.make_request(1); services.apply_to_request(rid,2); app=services.get_candidates(rid)[0]; services.decide_application(app['id'],1,True); self.assertTrue(services.complete_request(rid,2)); self.assertFalse(services.complete_request(rid,2)); self.assertEqual(database.get_user(1)['balance'],90); self.assertEqual(database.get_user(2)['balance'],120)
    def test_skills_affect_matching(self):
        self.add_user(1); self.add_user(2,skills='Python'); self.add_user(3,skills='снег'); rid=self.make_request(1,'Python'); r=database.get_request(rid); self.assertGreater(services.match_score(r,self.add_user_row(2)),services.match_score(r,self.add_user_row(3)))
    def add_user_row(self,uid): return database.get_user(uid)
    def test_boost_cost(self):
        self.add_user(1); rid=self.make_request(1); ok,_=services.boost_request(rid,1); self.assertTrue(ok); self.assertEqual(database.get_user(1)['balance'],100-BOOST_COST)
    def test_rating_once(self):
        self.add_user(1); self.add_user(2); rid=self.make_request(1); services.apply_to_request(rid,2); app=services.get_candidates(rid)[0]; services.decide_application(app['id'],1,True); services.complete_request(rid,2); self.assertTrue(services.set_rating(rid,1,5,'requester')); self.assertFalse(services.set_rating(rid,1,4,'requester'))
    def test_category_inference(self):
        self.assertEqual(services.infer_category('Помочь расчистить снег'),'snow'); self.assertEqual(services.infer_category('Помочь с компьютером'),'tech'); self.assertEqual(services.infer_category('Что-нибудь сделать'),'other')
    def test_web_telegram_link_keeps_canonical_web_identity(self):
        web_id=database.create_web_user('Web User','web')
        tg_id=database.create_user(9001,'Telegram User','tg')
        rid=self.make_request(tg_id)
        self.assertTrue(database.link_accounts(web_id,9001,'tg'))
        linked=database.get_user(web_id)
        self.assertEqual(linked['telegram_id'],9001)
        self.assertEqual(database.resolve_user_id(9001),web_id)
        self.assertEqual(database.get_request(rid)['requester_id'],web_id)
        self.assertIsNone(database.get_user(tg_id))
        self.assertEqual(database.get_user(web_id)['username'], 'web')
        self.assertEqual(database.get_user(web_id)['telegram_username'], 'tg')
        database.create_user(9001,'Telegram User Renamed','tg_new')
        self.assertEqual(database.get_user(web_id)['username'], 'web')
        self.assertEqual(database.get_user(web_id)['telegram_username'], 'tg_new')


    def test_full_web_telegram_interaction(self):
        web_id=database.create_web_user('Requester','requester','hash')
        helper_id=database.create_user(9002,'Helper','helper')
        database.link_accounts(web_id,9002,'helper')
        self.assertEqual(database.resolve_user_id(9002),web_id)
        # Use a second linked account for the helper side.
        helper_web=database.create_web_user('Helper Web','helperweb','hash2')
        database.link_accounts(helper_web,9003,'helper2')
        rid=services.create_request(web_id,{'what':'Нужна помощь с Python','place':'Пушкино','time_needed':'Сегодня','urgency':URGENCY_OPTIONS[1],'details':'Тест полного сценария','required_skills':'Python'})
        self.assertTrue(services.apply_to_request(rid,helper_web))
        app=services.get_candidates(rid)[0]
        accepted=services.decide_application(app['id'],web_id,True)
        self.assertTrue(accepted['accepted'])
        self.assertEqual(database.get_request(rid)['helper_id'],helper_web)
        self.assertTrue(services.complete_request(rid,helper_web))
        self.assertEqual(database.get_request(rid)['status'],STATUS_DONE)
        self.assertEqual(database.get_user(web_id)['balance'],90)
        self.assertEqual(database.get_user(helper_web)['balance'],120)
        self.assertTrue(services.set_rating(rid,web_id,5,'requester'))
        self.assertTrue(services.set_rating(rid,helper_web,5,'helper'))
        self.assertIsNotNone(database.get_user_by_telegram(9003))

    def test_open_request_does_not_block_new_help(self):
        self.add_user(1); self.add_user(2)
        rid=self.make_request(1)
        self.assertIsNotNone(database.get_request(rid))
        self.assertIsNone(database.get_in_progress_task(1))
        self.assertTrue(services.apply_to_request(rid,2))

if __name__=='__main__': unittest.main()
