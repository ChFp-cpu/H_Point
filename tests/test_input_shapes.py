"""Malformed JSON roots never reach mutation logic or become server errors."""
import json
import sqlite3
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from hpoint import billing, database, services, web


class InputShapes(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None,check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.patches=[patch.object(module,"db",self.db) for module in (database,services,billing,web)]
        for item in self.patches:item.start()
        database.init_db()
        for uid in (71,72):
            database.create_user(uid,"Synthetic review",email=f"shape{uid}@example.test",web_verified=True)
            self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
        self.token=web.new_sess(71)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),web.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.thread.join(timeout=3);self.server.server_close();self.db.close()
        for item in reversed(self.patches):item.stop()
    def post(self,path,data):
        req=Request(f"http://127.0.0.1:{self.server.server_port}"+path,data=json.dumps(data).encode(),headers={"Content-Type":"application/json","Cookie":"hpoint_session="+self.token,"Origin":web.WEB_PUBLIC_URL.rstrip('/')})
        try:response=urlopen(req,timeout=3)
        except HTTPError as error:response=error
        with response:return response.status,json.load(response)
    def test_all_route_families_reject_non_object_json_without_writes(self):
        paths=("/api/auth/login","/api/auth/register","/api/auth/email/verify","/api/profile","/api/profile/location","/api/support","/api/admin/users/block","/api/events","/api/events/join","/api/requests","/api/requests/cancel","/api/reviews","/api/chats/send","/api/helper/preferences","/api/payments/hp","/api/payments/wallet","/api/commercial/profile","/api/personal/templates","/api/work-inquiries","/api/pilot/activity")
        before={table:self.db.execute("SELECT COUNT(*) n FROM "+table).fetchone()["n"] for table in ("users","requests","wallet_transactions","billing_invoices","support_tickets","community_events")}
        with patch.object(web.logging,"exception") as errors:
            for path in paths:
                for data in ([],[{}],None,True,123,"text"):
                    with self.subTest(path=path,data=data):
                        status,result=self.post(path,data);self.assertEqual(status,400);self.assertFalse(result["ok"])
            errors.assert_not_called()
        self.assertEqual(before,{table:self.db.execute("SELECT COUNT(*) n FROM "+table).fetchone()["n"] for table in before})
    def test_invalid_rating_types_are_rejected_before_any_rating_is_recorded(self):
        request=services.create_request(71,{"what":"Проверить оценку","place":"Тест","time_needed":"сегодня","urgency":"обычная","details":"Тест"})
        self.assertTrue(services.try_assign_helper(request,72));self.assertTrue(services.complete_request(request,72,confirmed_by=71))
        for rating in (True,False,4.5,5.0,"5",[],{},None,0,6):
            with self.subTest(rating=rating):self.assertEqual(self.post("/api/reviews",{"request_id":request,"side":"requester","rating":rating})[0],400)
        self.assertIsNone(database.get_request(request)["requester_rating"])
        self.assertEqual(self.post("/api/reviews",{"request_id":request,"side":"requester","rating":5})[0],200)
        self.assertEqual(database.get_request(request)["requester_rating"],5)


if __name__=="__main__":unittest.main()
