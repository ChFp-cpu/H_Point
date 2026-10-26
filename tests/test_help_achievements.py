import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from hpoint import database,services,web,handlers,games,keyboards,help_achievements as awards


class Fixtures:
    def prepare(self,connection=None):
        self.db=connection or sqlite3.connect(":memory:",isolation_level=None,check_same_thread=False)
        if connection is None:self.db.row_factory=sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.patches=[patch.object(module,"db",self.db) for module in (database,services,web,handlers)]
        for item in self.patches:item.start()
        database.init_db()
        for uid in (1,2,3,4,5,6):
            database.create_user(uid,"Synthetic "+str(uid),email=f"awards{uid}@example.test",password_hash="synthetic-unused",tg_user_id=uid,web_verified=True)
            self.db.execute("UPDATE users SET balance=1000,email_verified=1 WHERE user_id=?",(uid,))

    def close(self):
        for item in reversed(self.patches):item.stop()
        self.db.close()

    def completed(self,owner=1,category="tech",rating=None,helper=2):
        rid=services.create_request(owner,dict(what="Synthetic help",place="Test",time_needed="Today",urgency="Normal",details="No real data",category=category))
        self.assertEqual(services.accept_open_request(rid,helper),"created")
        self.assertTrue(services.complete_request(rid,helper,confirmed_by=owner))
        if rating is not None:self.assertTrue(services.set_rating(rid,owner,rating))
        return rid

    def balance(self,uid=2):return database.get_user(uid)["balance"]


class HelpAwards(Fixtures,unittest.TestCase):
    def setUp(self):self.prepare()
    def tearDown(self):self.close()

    def test_only_author_positive_review_unlocks_first_award_once(self):
        rid=self.completed();before=self.balance()
        self.assertEqual(awards.achievement_state(2)["unlocked_count"],0)
        self.assertFalse(services.set_rating(rid,2,5))
        self.assertFalse(services.set_rating(rid,3,5))
        self.assertTrue(services.set_helper_rating(rid,2,5))
        self.assertEqual(self.balance(),before)
        self.assertTrue(services.set_rating(rid,1,4))
        self.assertEqual(self.balance(),before+10)
        self.assertFalse(services.set_rating(rid,1,5))
        self.assertEqual(awards.claim_earned(2),[])
        self.assertEqual(self.balance(),before+10)
        self.assertIn("+10 HP",awards.reward_notice(2,rid))

    def test_low_review_open_cancelled_and_paid_requests_do_not_grant_awards(self):
        self.completed(rating=3)
        rid=services.create_request(1,dict(what="Synthetic",place="Test",time_needed="Today",urgency="Normal",details="Test"))
        self.assertFalse(services.set_rating(rid,1,5))
        services.cancel_request(rid,1)
        self.assertFalse(services.set_rating(rid,1,5))
        paid=services.create_request(1,dict(what="Paid",place="Test",time_needed="Today",urgency="Normal",details="Test",reward_rub=400))
        self.db.execute("UPDATE requests SET status='done',helper_id=2,reward_payment_status='released' WHERE id=?",(paid,))
        before=self.balance()
        self.assertTrue(services.set_rating(paid,1,5))
        self.assertEqual(awards.claim_earned(2),[])
        self.assertEqual(self.balance(),before)

    def test_five_milestones_have_bounded_unique_rewards(self):
        before=self.balance()
        for index in range(10):
            # Two rounds of legitimate help on separate days.
            if index==5:self.db.execute("UPDATE requests SET completed_at='2020-01-01T00:00:00+00:00'")
            self.completed(owner=(1,3,4,5,6)[index%5],category=("tech","shopping","carry")[index%3],rating=5)
        state=awards.achievement_state(2)
        self.assertEqual((state["unlocked_count"],state["awarded_hp"]),(5,135))
        self.assertEqual(self.balance(),before+10*services.HELPER_REWARD+135)
        self.assertEqual(awards.claim_earned(2),[])
        self.assertEqual(state["claimable_hp"],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM help_achievements WHERE user_id=2").fetchone()["n"],5)

    def test_repeating_one_recipient_cannot_unlock_community_milestones(self):
        for index in range(10):self.completed(category=("tech","shopping","carry")[index%3],rating=5)
        self.assertEqual(awards.achievement_state(2)["awarded_hp"],10)
        self.assertEqual(awards.achievement_state(2)["unlocked_count"],1)

    def test_old_positive_help_can_be_claimed_without_rewriting_history(self):
        rid=self.completed()
        self.db.execute("UPDATE requests SET requester_rating=5,rating=5 WHERE id=?",(rid,))
        before=self.balance()
        self.assertEqual(awards.achievement_state(2)["claimable_hp"],10)
        self.assertEqual(self.balance(),before)
        self.assertEqual(len(awards.claim_earned(2)),1)
        self.assertEqual(self.balance(),before+10)
        self.assertEqual(awards.claim_earned(2),[])

    def test_rating_and_reward_roll_back_together(self):
        rid=self.completed();before=self.balance()
        with patch.object(services,"award_locked",side_effect=RuntimeError("award unavailable")):
            with self.assertRaises(RuntimeError):services.set_rating(rid,1,5)
        self.assertIsNone(database.get_request(rid)["requester_rating"])
        self.assertEqual(self.balance(),before)
        self.assertEqual(awards.achievement_state(2)["unlocked_count"],0)

    def test_awards_survive_stable_unlink_and_relink_without_reissue(self):
        rid=self.completed(rating=5)
        before=self.balance(2)
        self.assertEqual(database.detach_telegram_to_web_profile(2),2)
        self.assertIsNone(database.get_user(2)["tg_user_id"])
        self.assertEqual(awards.achievement_state(2)["awarded_hp"],10)
        self.assertEqual(awards.claim_earned(2),[])
        self.assertEqual(database.link_by_code(database.create_link_code(2),2),(True,"linked"))
        self.assertEqual(self.balance(2),before)
        self.assertEqual(database.get_request(rid)["helper_id"],2)
        self.assertEqual(awards.claim_earned(2),[])
        self.assertEqual(awards.achievement_state(2)["unlocked_count"],1)

    def test_awards_stay_on_email_account_after_first_telegram_link(self):
        uid=database.create_web_user("Synthetic","synthetic@example.test","hash")
        self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
        rid=self.completed(helper=uid,rating=5)
        before=self.balance(uid)
        self.assertEqual(database.link_by_code(database.create_link_code(uid),777),(True,"linked"))
        self.assertEqual(database.get_user(uid)["tg_user_id"],777)
        self.assertIsNone(database.get_user(777))
        self.assertEqual(database.get_request(rid)["helper_id"],uid)
        self.assertEqual(self.balance(uid),before)
        self.assertEqual(awards.claim_earned(uid),[])
        self.assertEqual(awards.achievement_state(uid)["awarded_hp"],10)

    def test_link_cannot_merge_achievements_from_another_email_profile(self):
        self.completed(rating=5)
        uid=database.create_web_user("Other","other@example.test","hash")
        self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
        self.completed(helper=uid,rating=5)
        before=(self.balance(2),self.balance(uid))
        self.assertFalse(database.link_by_code(database.create_link_code(uid),2)[0])
        self.assertEqual((self.balance(2),self.balance(uid)),before)
        self.assertEqual(awards.achievement_state(2)["awarded_hp"],10)
        self.assertEqual(awards.achievement_state(uid)["awarded_hp"],10)

    def test_blocked_helper_cannot_claim_unclaimed_rewards(self):
        rid=self.completed();self.db.execute("UPDATE requests SET requester_rating=5 WHERE id=?",(rid,))
        self.db.execute("UPDATE users SET is_blocked=1 WHERE user_id=2")
        before=self.balance()
        self.assertEqual(awards.claim_earned(2),[])
        self.assertEqual(self.balance(),before)


class AwardRace(Fixtures,unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.prepare(database.SQLiteConnection(str(Path(self.temp.name)/"race.db")))
    def tearDown(self):self.close();self.temp.cleanup()

    def test_simultaneous_claims_credit_only_once(self):
        rid=self.completed();self.db.execute("UPDATE requests SET requester_rating=5 WHERE id=?",(rid,))
        before=self.balance();gate=threading.Barrier(2)
        def claim():
            try:gate.wait(timeout=5);return len(awards.claim_earned(2))
            finally:self.db.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            jobs=[executor.submit(claim) for _ in range(2)]
            results=[job.result(timeout=10) for job in jobs]
        self.assertEqual(sorted(results),[0,1])
        self.assertEqual(self.balance(),before+10)


class PausedGamesAPI(Fixtures,unittest.TestCase):
    def setUp(self):
        self.prepare()
        self.notify_patch=patch.object(web,"notify_telegram_user");self.notify=self.notify_patch.start()
        self.tokens={uid:web.new_sess(uid) for uid in (1,2)}
        self.server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.thread.join(timeout=3);self.server.server_close();self.notify_patch.stop();self.close()
    def request(self,uid,path,payload=None):
        headers={"Content-Type":"application/json"}
        if uid:headers["Cookie"]="hpoint_session="+self.tokens[uid]
        request=urllib.request.Request(f"http://127.0.0.1:{self.server.server_port}"+path,headers=headers,data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with urllib.request.urlopen(request,timeout=3) as response:return response.code,response.read()
        except urllib.error.HTTPError as error:
            with error:return error.code,error.read()

    def test_all_game_mutations_are_paused_and_archive_survives(self):
        with patch.object(games,"GAMES_ENABLED",True):session=games.start_game(2,"crossing")
        snapshot=dict(self.db.execute("SELECT * FROM game_sessions WHERE id=?",(session["id"],)).fetchone());before=self.balance()
        self.assertFalse(web.GAMES_ENABLED)
        self.assertEqual(self.request(None,"/games")[0],503)
        self.assertEqual(self.request(None,"/api/games/state")[0],503)
        for path in ("start","action","abandon","shop/purchase","shop/equip"):
            status,body=self.request(2,"/api/games/"+path,{"game":"crossing","session_id":session["id"],"action":{"type":"finish"},"item_id":"shield","purchase_key":"paused-test"})
            self.assertEqual(status,503);self.assertEqual(json.loads(body)["code"],"games_paused")
        self.assertEqual(dict(self.db.execute("SELECT * FROM game_sessions WHERE id=?",(session["id"],)).fetchone()),snapshot)
        self.assertEqual(self.balance(),before)
        for action in (lambda:games.start_game(2,"crossing"),lambda:games.action_game(2,session["id"],{"type":"finish"}),lambda:games.abandon_game(2,session["id"]),lambda:games.purchase_item(2,"shield","paused"),lambda:games.equip_item(2,"shield")):
            with self.assertRaisesRegex(ValueError,"games_paused"):action()
        with patch.object(games,"GAMES_ENABLED",True):
            self.assertEqual(games.game_session(2,session["id"])["id"],session["id"])

    def test_claim_is_authenticated_and_cannot_forge_reward_or_another_user(self):
        rid=self.completed();self.db.execute("UPDATE requests SET requester_rating=5 WHERE id=?",(rid,))
        before=self.balance()
        self.assertEqual(self.request(None,"/api/help-achievements/claim",{})[0],401)
        status,body=self.request(1,"/api/help-achievements/claim",{"user_id":2,"reward_hp":100000})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)["awarded"],[])
        self.assertEqual(self.balance(),before)
        status,body=self.request(2,"/api/help-achievements/claim",{"reward_hp":100000})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)["balance"],before+10)
        self.assertEqual(json.loads(self.request(2,"/api/help-achievements/claim",{})[1])["awarded"],[])
        sync=json.loads(self.request(2,"/api/sync")[1])
        self.assertEqual(sync["help_achievements"]["unlocked_count"],1)
        self.assertFalse(sync["features"]["games"])

    def test_review_awards_shared_hp_and_notifies_linked_telegram(self):
        rid=self.completed();before=self.balance()
        self.db.execute("UPDATE users SET tg_user_id=2002 WHERE user_id=2")
        self.assertEqual(self.request(1,"/api/reviews",{"request_id":rid,"side":"requester","rating":5})[0],200)
        self.assertEqual(self.balance(),before+10)
        self.assertEqual(self.notify.call_args.args[0],2002)
        self.assertIn("+10 HP",self.notify.call_args.args[1])
        self.assertEqual(self.request(1,"/api/reviews",{"request_id":rid,"side":"requester","rating":5})[0],409)
        self.assertEqual(self.notify.call_count,1)


class PausedGamesBot(Fixtures,unittest.IsolatedAsyncioTestCase):
    def setUp(self):self.prepare()
    def tearDown(self):self.close()

    async def test_game_controls_are_absent_and_old_callbacks_are_inert(self):
        self.assertNotIn("Игры",str(keyboards.main_menu_kb()))
        self.assertNotIn("Игры",handlers.BOT_START_OVERVIEW)
        message=SimpleNamespace(from_user=SimpleNamespace(id=2),chat=SimpleNamespace(type="private"),answer=AsyncMock())
        state=SimpleNamespace(clear=AsyncMock())
        await handlers.games_menu(message,state)
        self.assertIn("отключены",message.answer.call_args.args[0])
        callback=SimpleNamespace(from_user=SimpleNamespace(id=2),message=message,answer=AsyncMock(),data="g:start:crossing")
        with patch.object(games,"start_game") as start:
            await handlers.game_callbacks(callback,state);start.assert_not_called()
        self.assertNotIn("/games",str(message.answer.call_args.kwargs["reply_markup"]))

    async def test_achievement_button_claims_for_callback_actor_not_bot_message_author(self):
        rid=self.completed();self.db.execute("UPDATE requests SET requester_rating=5 WHERE id=?",(rid,))
        before=self.balance()
        message=SimpleNamespace(from_user=SimpleNamespace(id=999000),answer=AsyncMock())
        callback=SimpleNamespace(from_user=SimpleNamespace(id=2),message=message,answer=AsyncMock())
        await handlers.help_achievements_callback(callback)
        self.assertEqual(self.balance(),before+10)
        self.assertIn("Достижения за помощь",message.answer.call_args.args[0])
        self.assertIn("+10 HP",message.answer.call_args.args[0])
        await handlers.help_achievements_callback(callback)
        self.assertEqual(self.balance(),before+10)


if __name__=="__main__":unittest.main()
