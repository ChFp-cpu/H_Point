import base64
from datetime import datetime, timedelta, timezone
from io import BytesIO
import sqlite3
import unittest
from unittest.mock import patch

from PIL import Image
from hpoint import database, services, media


class Photos(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.patches = [patch.object(module, "db", self.db) for module in (database, services)]
        for item in self.patches:item.start()
        database.init_db()
        media.initialize_schema(self.db)
        for uid in (1,2,3):database.create_user(uid, "Synthetic person " + str(uid))
        self.rid = services.create_request(1, dict(what="Synthetic help",place="Private address",time_needed="Today",urgency="Normal",details="Test"))

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.db.close()

    def image(self, format="PNG", size=(48,32), metadata=False):
        image = Image.new("RGB", size, "red")
        output = BytesIO()
        options = {}
        if metadata:
            exif=Image.Exif();exif[270]="Private address and GPS information";exif[42033]="Private camera serial"
            options["exif"]=exif
        image.save(output, format=format, **options)
        return "data:image/" + ("jpeg" if format=="JPEG" else format.lower()) + ";base64," + base64.b64encode(output.getvalue()).decode()

    def attach_request(self):
        return media.attach_request_photos(self.db,self.rid,1,media.prepare_photos([self.image()]))[0]

    def message(self, owner=2):
        self.db.execute("UPDATE requests SET helper_id=2,status='in_progress' WHERE id=?",(self.rid,))
        cid=database.get_or_create_chat_for_request(self.rid)
        return database.insert_id("INSERT INTO chat_messages(chat_id,user_id,text) VALUES(?,?,?)",(cid,owner,""))

    def test_all_supported_formats_are_reencoded_without_metadata(self):
        for format in ("JPEG","PNG","WEBP"):
            prepared=media.prepare_photo(self.image(format,metadata=(format=="JPEG")))
            self.assertEqual(prepared.mime,"image/jpeg")
            self.assertEqual((prepared.width,prepared.height),(48,32))
            self.assertNotIn(b"Private",prepared.content)
            with Image.open(BytesIO(prepared.content)) as image:
                self.assertEqual(image.format,"JPEG")
                self.assertEqual(dict(image.getexif()),{})

    def test_resize_and_transparent_background(self):
        prepared=media.prepare_photo(self.image(size=(2600,1300)))
        self.assertEqual((prepared.width,prepared.height),(1920,960))
        rgba=Image.new("RGBA",(2,2),(0,0,0,0));out=BytesIO();rgba.save(out,format="PNG")
        prepared=media.prepare_photo("data:image/png;base64,"+base64.b64encode(out.getvalue()).decode())
        with Image.open(BytesIO(prepared.content)) as image:self.assertEqual(image.getpixel((0,0)),(255,255,255))

    def test_rejects_disguised_truncated_and_unsupported_files(self):
        for value in (self.image().replace("image/png","image/jpeg"),
                      "data:image/png;base64,"+base64.b64encode(b"\x89PNG\r\n\x1a\nnot a photo").decode(),
                      "data:image/svg+xml;base64,PHN2Zz4=", "https://example.test/photo.jpg", "data:image/png;base64,!!!"):
            with self.assertRaises(ValueError):media.prepare_photo(value)

    def test_rejects_oversize_photos_and_batches(self):
        with patch.object(media,"MAX_IMAGE_PIXELS",10):
            with self.assertRaisesRegex(ValueError,"20 мегапикселей"):media.prepare_photo(self.image())
        with patch.object(media,"MAX_PHOTO_BYTES",30):
            with self.assertRaises(ValueError):media.prepare_photo(self.image())
        for values in ([self.image()]*4,"not a list",{}):
            with self.assertRaises(ValueError):media.prepare_photos(values)
        self.assertEqual(media.prepare_photos(None),[])

    def test_request_photos_visible_to_members_while_open(self):
        photo=self.attach_request()
        self.assertEqual(set(photo),{"id","url","width","height"})
        mime,content=media.photo_for_user(self.db,photo["id"],3)
        self.assertEqual(mime,"image/jpeg");self.assertTrue(content.startswith(b"\xff\xd8"))
        with self.assertRaises(PermissionError):media.photo_for_user(self.db,photo["id"],999)
        with self.assertRaises(LookupError):media.photo_for_user(self.db,"../private",1)

    def test_closed_request_photos_are_only_for_its_participants(self):
        photo=self.attach_request()
        self.db.execute("UPDATE requests SET status='done',helper_id=2 WHERE id=?",(self.rid,))
        for uid in (1,2):self.assertTrue(media.photo_for_user(self.db,photo["id"],uid)[1])
        with self.assertRaises(PermissionError):media.photo_for_user(self.db,photo["id"],3)

    def test_only_request_author_can_attach_and_count_is_capped(self):
        photos=media.prepare_photos([self.image()])
        with self.assertRaises(PermissionError):media.attach_request_photos(self.db,self.rid,2,photos)
        for _ in range(3):media.attach_request_photos(self.db,self.rid,1,photos)
        with self.assertRaises(ValueError):media.attach_request_photos(self.db,self.rid,1,photos)
        self.assertEqual(len(media.request_photo_metadata(self.db,self.rid)),3)

    def test_chat_photo_is_only_for_the_two_chat_members(self):
        message=self.message()
        photo=media.attach_message_photos(self.db,message,2,media.prepare_photos([self.image()]))[0]
        for uid in (1,2):self.assertTrue(media.photo_for_user(self.db,photo["id"],uid)[1])
        with self.assertRaises(PermissionError):media.photo_for_user(self.db,photo["id"],3)
        with self.assertRaises(PermissionError):media.attach_message_photos(self.db,message,1,media.prepare_photos([self.image()]))
        self.db.execute("UPDATE users SET is_blocked=1 WHERE user_id=2")
        with self.assertRaises(PermissionError):media.photo_for_user(self.db,photo["id"],2)

    def test_message_payload_contains_urls_without_image_contents(self):
        first=self.message();second=self.message(owner=1)
        media.attach_message_photos(self.db,first,2,media.prepare_photos([self.image()]))
        messages=media.messages_with_photos(self.db,self.db.execute("SELECT * FROM chat_messages ORDER BY id").fetchall())
        self.assertEqual(len(messages[0]["photos"]),1)
        self.assertEqual(messages[1]["photos"],[])
        self.assertNotIn("content_base64",str(messages))

    def test_photo_insert_rolls_back_with_its_request(self):
        before=self.db.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"]
        self.db.execute("UPDATE users SET pro_until='2099-01-01T00:00:00+00:00' WHERE user_id=1")
        self.db.execute("BEGIN IMMEDIATE")
        rid=services.create_request(1,dict(what="Atomic",place="Private",time_needed="Today",urgency="Normal",details="Test"))
        media.attach_request_photos(self.db,rid,1,media.prepare_photos([self.image()]))
        self.db.execute("ROLLBACK")
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM requests").fetchone()["n"],before)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM photos").fetchone()["n"],0)

    def test_photos_cascade_with_request_and_message(self):
        self.attach_request()
        message=self.message()
        media.attach_message_photos(self.db,message,2,media.prepare_photos([self.image()]))
        self.db.execute("DELETE FROM chat_messages WHERE id=?",(message,))
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM photos").fetchone()["n"],1)
        self.db.execute("DELETE FROM requests WHERE id=?",(self.rid,))
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM photos").fetchone()["n"],0)

    def test_event_participants_only_expose_names_and_public_profile_ids(self):
        future=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        event=database.create_community_event(1,"Synthetic gathering","Test","Public place",future)
        database.join_community_event(event,2)
        self.db.execute("UPDATE users SET email='private@example.test',phone='private phone' WHERE user_id=2")
        result=media.event_participants(self.db,event,3)
        self.assertEqual(result["title"],"Synthetic gathering")
        self.assertTrue(any(person["profile_id"]==2 for person in result["participants"]))
        for person in result["participants"]:self.assertEqual(set(person),{"name","profile_id"})
        self.assertNotIn("private",str(result))
        self.db.execute("UPDATE community_events SET status='cancelled' WHERE id=?",(event,))
        with self.assertRaises(PermissionError):media.event_participants(self.db,event,3)
        self.assertTrue(media.event_participants(self.db,event,1)["participants"])
