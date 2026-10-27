"""Private candidate conversations and independent helper preferences."""
import sqlite3
import base64
from io import BytesIO
from PIL import Image
import unittest
from unittest.mock import patch
from hpoint import database,services,chat_threads,media


class Conversations(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.patches=[patch.object(module,'db',self.db) for module in (database,services)]
        self.patches.append(patch.object(database,'REGISTRATION_BONUS_RUB',0))
        for item in self.patches:item.start()
        database.init_db()
        for uid in (1,2,3,4):database.create_user(uid,'Participant '+str(uid),email='p'+str(uid)+'@example.test',web_verified=True)
        self.rid=self.request()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.db.close()

    def request(self,owner=1):
        return services.create_request(owner,dict(what='Synthetic help',place='Test',time_needed='Today',urgency='Normal',details='Test',category='tech'))

    def apply(self,helper=2,rid=None):
        self.assertEqual(services.apply_to_request(rid or self.rid,helper),'created')
        return chat_threads.list_chats(self.db,helper)[0]['id']

    def test_multiple_responses_have_isolated_conversations_before_selection(self):
        first=self.apply(2);second=self.apply(3)
        self.assertFalse(services.is_in_queue(2));self.assertFalse(services.is_in_queue(3))
        self.assertNotEqual(first,second)
        self.assertEqual(database.get_request(self.rid)['status'],'open')
        self.assertEqual(len(services.get_request_applications(1)),2)
        chat_threads.send_message(self.db,2,'Private A',chat_id=first)
        chat_threads.send_message(self.db,3,'Private B',chat_id=second)
        self.assertEqual([m['text'] for m in chat_threads.read_chat(self.db,1,chat_id=first)['messages']],['Private A'])
        self.assertEqual([m['text'] for m in chat_threads.read_chat(self.db,1,chat_id=second)['messages']],['Private B'])
        with self.assertRaises(PermissionError):chat_threads.read_chat(self.db,2,chat_id=second)
        with self.assertRaises(PermissionError):chat_threads.send_message(self.db,4,'Intrusion',chat_id=first)
        with self.assertRaises(PermissionError):chat_threads.read_chat(self.db,4,request_id=self.rid)
        with self.assertRaises(PermissionError):chat_threads.send_message(self.db,4,'Intrusion',request_id=self.rid)
        with self.assertRaises(ValueError):chat_threads.read_chat(self.db,1,request_id=self.rid)
        self.assertEqual(len(chat_threads.read_chat(self.db,2,request_id=self.rid)['messages']),1)

    def test_selected_conversation_keeps_its_original_history(self):
        first=self.apply(2);second=self.apply(3)
        chat_threads.send_message(self.db,2,'Before assignment',chat_id=first)
        application=next(r for r in services.get_request_applications(1) if r['helper_id']==2)
        self.assertEqual(services.accept_open_request(self.rid,2,1,application['application_token']),'created')
        self.assertEqual(database.get_or_create_chat_for_request(self.rid),first)
        self.assertEqual(chat_threads.read_chat(self.db,1,request_id=self.rid)['id'],first)
        author=chat_threads.read_chat(self.db,1,chat_id=first)
        self.assertTrue(author['can_complete']);self.assertTrue(author['can_cancel']);self.assertTrue(author['can_send'])
        self.assertFalse(chat_threads.read_chat(self.db,2,chat_id=first)['can_complete'])
        self.assertTrue(chat_threads.read_chat(self.db,2,chat_id=first)['can_cancel'])
        self.assertFalse(chat_threads.read_chat(self.db,3,chat_id=second)['can_send'])
        with self.assertRaises(ValueError):chat_threads.send_message(self.db,3,'Late candidate',chat_id=second)
        self.assertTrue(services.complete_request(self.rid,2,confirmed_by=1))
        self.assertFalse(chat_threads.read_chat(self.db,2,chat_id=first)['can_send'])

    def test_archiving_is_private_and_new_message_reopens(self):
        cid=self.apply()
        chat_threads.archive_chat(self.db,1,cid)
        self.assertEqual(chat_threads.list_chats(self.db,1),[])
        self.assertEqual(len(chat_threads.list_chats(self.db,2)),1)
        self.assertEqual(database.get_request(self.rid)['status'],'open')
        archived=chat_threads.list_chats(self.db,1,include_archived=True)
        self.assertEqual(len(archived),1);self.assertTrue(archived[0]['archived'])
        self.assertFalse(chat_threads.list_chats(self.db,2)[0]['archived'])
        with self.assertRaises(PermissionError):chat_threads.archive_chat(self.db,4,cid)
        chat_threads.send_message(self.db,2,'New message',chat_id=cid)
        self.assertEqual(len(chat_threads.list_chats(self.db,1)),1)
        chat_threads.archive_chat(self.db,1,cid)
        chat_threads.archive_chat(self.db,1,cid,False)
        self.assertEqual(len(chat_threads.list_chats(self.db,1)),1)

    def test_pause_and_assignment_do_not_withdraw_other_responses(self):
        self.apply();another=self.request(3)
        self.apply(2,another)
        preferences=services.save_helper_preferences(2,['tech','study'],'Evenings',False,10,'2030-01-01T10:00:00+00:00','2030-01-01T20:00:00+00:00')
        self.assertFalse(preferences['helper_ready'])
        self.assertEqual(len(services.get_helper_applications(2)),2)
        self.assertEqual(services.get_helper_categories(2),['tech','study'])
        self.assertEqual(database.get_user(2)['helper_availability'],'Evenings')
        self.assertEqual(services.accept_open_request(self.rid,2),'created')
        self.assertEqual(len(services.get_helper_applications(2)),1)
        third=self.request(4)
        self.assertEqual(services.apply_to_request(third,2),'created')
        self.assertEqual(len(services.get_helper_applications(2)),2)
        preferences=services.save_helper_preferences(2,['tools'],'Weekends',True)
        self.assertFalse(preferences['helper_ready'])
        self.assertEqual(services.get_helper_categories(2),['tools'])
        self.assertEqual(len(services.get_helper_applications(2)),2)

    def test_withdrawing_own_response_closes_only_its_conversation(self):
        cid=self.apply();self.apply(3)
        item=services.get_helper_applications(2)[0]
        self.assertTrue(services.cancel_request_application(self.rid,2,2,item['application_token']))
        self.assertFalse(chat_threads.read_chat(self.db,2,chat_id=cid)['can_send'])
        self.assertEqual(database.get_request(self.rid)['status'],'open')
        self.assertEqual(len(services.get_request_applications(1)),1)
        self.assertEqual(services.apply_to_request(self.rid,2),'created')
        self.assertEqual(chat_threads.read_chat(self.db,2,request_id=self.rid)['id'],cid)

    def test_candidate_photos_are_private_between_the_two_conversation_members(self):
        first=self.apply(2);second=self.apply(3)
        output=BytesIO();Image.new("RGB",(48,32),"blue").save(output,format="PNG")
        image="data:image/png;base64,"+base64.b64encode(output.getvalue()).decode()
        sent=chat_threads.send_message(self.db,2,"",chat_id=first,photos=[image])
        photo=sent["messages"][0]["photos"][0]
        for uid in (1,2):self.assertTrue(media.photo_for_user(self.db,photo["id"],uid)[1])
        with self.assertRaises(PermissionError):media.photo_for_user(self.db,photo["id"],3)
        self.assertEqual(chat_threads.read_chat(self.db,3,chat_id=second)["messages"],[])
        self.assertEqual(sent["last_message_id"],sent["messages"][0]["id"])

    def test_preferences_do_not_partially_save_when_validation_fails(self):
        services.save_helper_preferences(2,["tech"],"Evenings",True,8)
        with self.assertRaises(ValueError):services.save_helper_preferences(2,["fake"],"Changed",False)
        self.assertEqual(services.get_helper_categories(2),["tech"])
        self.assertEqual(database.get_user(2)["helper_availability"],"Evenings")
        self.assertTrue(services.is_in_queue(2))

    def test_helper_preferences_reject_wrong_types_and_preserve_previous_values(self):
        services.save_helper_preferences(2,["tech"],"Evenings",True,1000)
        invalid=[{"ready":"false"},{"ready":1},{"availability":None},{"availability":["x"]},
            {"availability":"x"*241},{"categories":"tech"},{"categories":[{}]},
            {"radius":True},{"radius":1.5},{"radius":-1},{"radius":1001}]
        for changes in invalid:
            with self.subTest(changes=changes):
                values=dict(categories=["tech"],availability="Evenings",ready=True,radius=1000)
                values.update(changes)
                with self.assertRaises(ValueError):services.save_helper_preferences(2,**values)
                self.assertTrue(services.is_in_queue(2))
                self.assertEqual(services.get_helper_categories(2),["tech"])
                self.assertEqual(database.get_user(2)["helper_radius_km"],1000)
                self.assertEqual(database.get_user(2)["helper_availability"],"Evenings")

    def test_explicit_chat_and_request_must_agree(self):
        cid=self.apply();another=self.request(3)
        with self.assertRaises(ValueError):chat_threads.read_chat(self.db,2,chat_id=cid,request_id=another)
        for bad in (0,-1,False,'bad'):
            with self.assertRaises(ValueError):chat_threads.read_chat(self.db,2,chat_id=bad)


class LegacyConversationMigration(unittest.TestCase):
    def test_old_unique_request_schema_retains_messages_and_photo_references(self):
        db=sqlite3.connect(':memory:',isolation_level=None);db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript('''CREATE TABLE users(user_id INTEGER PRIMARY KEY);
            CREATE TABLE requests(id INTEGER PRIMARY KEY,requester_id INTEGER,helper_id INTEGER);
            CREATE TABLE schema_migrations(version TEXT PRIMARY KEY);
            CREATE TABLE chats(id INTEGER PRIMARY KEY AUTOINCREMENT,request_id INTEGER NOT NULL UNIQUE REFERENCES requests(id) ON DELETE CASCADE,user_a_id INTEGER REFERENCES users(user_id),user_b_id INTEGER REFERENCES users(user_id),created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE chat_messages(id INTEGER PRIMARY KEY,chat_id INTEGER REFERENCES chats(id) ON DELETE CASCADE,text TEXT);
            CREATE TABLE photos(id INTEGER PRIMARY KEY,message_id INTEGER REFERENCES chat_messages(id) ON DELETE CASCADE);
            INSERT INTO users VALUES(1),(2),(3);INSERT INTO requests VALUES(8,1,2);
            INSERT INTO chats(id,request_id,user_a_id,user_b_id) VALUES(9,8,1,2);
            INSERT INTO chat_messages VALUES(11,9,'Historical message');INSERT INTO photos VALUES(13,11);''')
        before=[tuple(row) for row in db.execute('SELECT * FROM chats')]
        chat_threads.initialize_schema(db);chat_threads.initialize_schema(db)
        self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM chats')],before)
        self.assertEqual(tuple(db.execute('SELECT * FROM chat_messages').fetchone()),(11,9,'Historical message'))
        self.assertEqual(tuple(db.execute('SELECT * FROM photos').fetchone()),(13,11))
        self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertNotEqual(chat_threads.ensure_chat(db,8,3),9)
        db.close()


if __name__=='__main__':unittest.main()
