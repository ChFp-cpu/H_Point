"""Recommendations, readiness and requester choice share one help lifecycle."""
import sqlite3
import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

from hpoint import chat_threads,database,services


class HelpMatching(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.patches=[patch.object(module,"db",self.db) for module in (database,services)]
        for item in self.patches:item.start()
        database.init_db()
        for uid in range(1,12):database.create_user(uid,f"User {uid}")
        self.db.execute("UPDATE users SET pro_until='2099-01-01T00:00:00+00:00' WHERE user_id=1")

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.db.close()

    def request(self,**extra):
        return services.create_request(1,{"what":"Настроить компьютер","category":"tech","place":"Москва","time_needed":"сегодня","urgency":"обычная","details":"",**extra})

    def ready(self,uid,categories=None,lat=55.75,lon=37.62,**prefs):
        self.db.execute("UPDATE users SET lat=?,lon=? WHERE user_id=?",(lat,lon,uid))
        services.save_helper_preferences(uid,["tech"] if categories is None else categories,ready=True,**prefs)

    def test_filters_category_radius_time_pause_block_busy_and_self(self):
        at=datetime.now(timezone.utc)+timedelta(hours=4)
        rid=self.request(lat=55.75,lon=37.62,scheduled_at=at.isoformat())
        self.ready(1)
        self.ready(2,radius=10)
        self.ready(3,categories=["study"])
        self.ready(4,lat=59.93,lon=30.31,radius=10)
        self.ready(5,available_until=(at-timedelta(hours=1)).isoformat())
        self.ready(6,available_from=(at+timedelta(hours=1)).isoformat())
        self.ready(7);services.save_helper_preferences(7,["tech"],ready=False)
        self.ready(8);self.db.execute("UPDATE users SET is_blocked=1 WHERE user_id=8")
        self.ready(9)
        busy=self.request();services.apply_to_request(busy,9)
        token=services.get_helper_applications(9)[0]["application_token"]
        self.assertEqual(services.accept_open_request(busy,9,1,token),"created")
        self.assertEqual([row["user_id"] for row in services.smart_match(rid)],[2])
        self.assertFalse(services.offer_helper(rid,4))
        self.assertFalse(services.offer_helper(rid,5))
        self.assertFalse(services.offer_helper(rid,9))

    def test_missing_location_is_explicit_and_cannot_bypass_saved_radius(self):
        rid=self.request(lat=55.75,lon=37.62)
        self.ready(2,lat=None,lon=None)
        self.ready(3,lat=None,lon=None,radius=10)
        self.ready(4,lat=55.75,lon=37.62)
        matches=services.smart_match(rid)
        self.assertEqual([row["user_id"] for row in matches],[4,2])
        unknown=matches[1]
        self.assertIsNone(unknown["distance_km"])
        self.assertFalse(unknown["location_known"])
        self.assertIn("расстояние неизвестно: точка не указана",unknown["match_reasons"])
        self.assertNotIn("рядом",unknown["match_reasons"])
        self.assertFalse(services.offer_helper(rid,3))
        self.assertTrue(all(row["lat"] is None and row["lon"] is None for row in matches))

    def test_profile_query_filters_candidates_and_ignores_request_text(self):
        rid=self.request()
        self.ready(2);self.ready(3)
        self.db.execute("UPDATE users SET bio='Компьютерный мастер. Ремонт ноутбуков.' WHERE user_id=2")
        self.assertEqual([row["user_id"] for row in services.smart_match(rid,query="мастер ноутбуков")],[2])
        self.assertEqual(services.smart_match(rid,query="автомеханик"),[])
        self.assertEqual([row["user_id"] for row in services.smart_match(rid,query="компьютер")],[2])

    def test_ready_is_persistent_opt_in_separate_from_current_busy_state(self):
        first=self.request();self.ready(2)
        self.assertEqual(services.apply_to_request(first,2),"created")
        token=services.get_helper_applications(2)[0]["application_token"]
        self.assertEqual(services.accept_open_request(first,2,1,token),"created")
        self.assertTrue(services.is_in_queue(2))
        prefs=services.save_helper_preferences(2,["tech"],ready=True)
        self.assertTrue(prefs["helper_ready"]);self.assertTrue(prefs["helper_busy"])
        second=self.request()
        self.assertEqual(services.smart_match(second),[])
        self.assertTrue(services.complete_request(first,2,confirmed_by=1))
        self.assertEqual([row["user_id"] for row in services.smart_match(second)],[2])
        self.assertEqual(services.apply_to_request(second,2),"created")
        token=services.get_helper_applications(2)[0]["application_token"]
        self.assertEqual(services.accept_open_request(second,2,1,token),"created")
        self.assertTrue(services.cancel_request(second,2))
        self.assertTrue(services.is_in_queue(2))

    def test_explicit_application_survives_pausing_and_preferences_without_auto_enabling(self):
        rid=self.request(lat=55.75,lon=37.62)
        self.assertEqual(services.apply_to_request(rid,2),"created")
        services.save_helper_preferences(2,["study"],ready=False,radius=1)
        match=services.smart_match(rid,query="несуществующий профиль")[0]
        self.assertTrue(match["applied"]);self.assertTrue(match["can_select"])
        self.assertFalse(match["helper_ready"]);self.assertFalse(match["can_invite"])
        self.assertFalse(services.is_in_queue(2))
        self.assertEqual(services.accept_open_request(rid,2,1,match["application_token"]),"created")
        self.assertFalse(services.is_in_queue(2))

    def test_inviting_multiple_helpers_keeps_separate_consent_and_private_chats(self):
        rid=self.request();self.ready(2);self.ready(3)
        self.assertTrue(services.offer_helper(rid,2));self.assertTrue(services.offer_helper(rid,3))
        tokens={row["candidate_id"]:row["offer_token"] for row in services.get_request_helper_offers(rid)}
        self.assertFalse(services.respond_to_helper_offer(rid,2,True,tokens[3]))
        for uid in (2,3):self.assertTrue(services.respond_to_helper_offer(rid,uid,True,tokens[uid]))
        self.assertIsNone(database.get_request(rid)["helper_id"])
        chats={uid:chat_threads.read_chat(self.db,uid,request_id=rid)["id"] for uid in (2,3)}
        self.assertNotEqual(chats[2],chats[3])
        chat_threads.send_message(self.db,2,"Сообщение кандидата",chat_id=chats[2])
        with self.assertRaises(PermissionError):chat_threads.read_chat(self.db,3,chat_id=chats[2])
        self.assertEqual(services.accept_open_request(rid,2,3,tokens[2]),"unavailable")
        self.assertEqual(services.accept_open_request(rid,2,1,"old"),"unavailable")
        self.assertEqual(services.accept_open_request(rid,2,1,tokens[2]),"created")
        self.assertFalse(chat_threads.read_chat(self.db,3,chat_id=chats[3])["can_send"])
        self.assertTrue(chat_threads.read_chat(self.db,2,chat_id=chats[2])["can_send"])
        self.assertFalse(services.complete_request(rid,2,confirmed_by=2))
        self.assertTrue(services.complete_request(rid,2,confirmed_by=1))

    def test_closed_expired_and_unfunded_requests_have_no_recommendations(self):
        self.ready(2)
        expired=self.request()
        self.db.execute("UPDATE requests SET expires_at=? WHERE id=?",((datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),expired))
        unfunded=self.request(reward_rub=100)
        closed=self.request();services.cancel_request(closed,1)
        for rid in (expired,unfunded,closed):
            self.assertEqual(services.smart_match(rid),[])
            self.assertFalse(services.offer_helper(rid,2))


if __name__=="__main__":unittest.main()
