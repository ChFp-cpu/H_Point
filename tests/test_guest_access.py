import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import urlparse

from hpoint import database, guest_access


class GuestAccess(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.database = patch.object(database, "db", self.connection)
        self.database.start()
        database.init_db()
        database.create_user(701, "Посетитель", email="private@example.test")
        database.create_user(702, "Заблокированный")
        self.connection.execute("UPDATE users SET is_blocked=1 WHERE user_id=702")
        self.future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        self.past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()

    def tearDown(self):
        self.database.stop()
        self.connection.close()

    def request(self, title, **values):
        fields = dict(requester_id=701, what=title, place="SECRET HOME ADDRESS",
                      details="PRIVATE PHONE AND DETAILS", time_needed="Сегодня",
                      urgency="Без срочности", category="tech", lat=55.123456,
                      lon=37.123456)
        fields.update(values)
        keys = list(fields)
        self.connection.execute("INSERT INTO requests(" + ",".join(keys) + ") VALUES(" +
                                ",".join("?" for _ in keys) + ")", tuple(fields.values()))

    def test_snapshot_does_not_publish_private_fields_or_unavailable_requests(self):
        self.request("Открытая задача")
        self.request("Резерв создан", reward_rub=500, reward_test_rub=500, reward_payment_status="paid")
        self.request("Нет резерва", reward_rub=500)
        self.request("Срок истёк", expires_at=self.past)
        self.request("Уже договорились", status="in_progress")
        self.request("Закрытая задача", status="done")
        self.request("Автор заблокирован", requester_id=702)
        self.connection.execute("""INSERT INTO community_events
            (creator_id,title,place,description,starts_at,image_data) VALUES(701,?,?,?,?,?)""",
            ("Опубликованное событие", "PRIVATE EVENT ADDRESS", "PRIVATE EVENT TEXT", self.future, "PRIVATE IMAGE"))
        self.connection.execute("""INSERT INTO community_events
            (creator_id,title,place,starts_at,status) VALUES(701,?,?,?,'draft')""",
            ("Черновик", "PRIVATE ADDRESS", self.future))
        public_service = dict(id=10, title="Услуга", description="Публичное описание",
                              price_rub=700, duration_minutes=60, currency="TEST_RUB",
                              organization_title="Компания", organization_url="/organizations/company",
                              owner_id=701, email="PRIVATE SERVICE EMAIL", client_count=42)
        before = self.connection.total_changes
        with patch.object(guest_access.commercial, "public_services", return_value=[public_service]):
            payload = guest_access.public_snapshot(self.connection)
        self.assertEqual(before, self.connection.total_changes, "Public browsing must not write")
        self.assertEqual([row["what"] for row in payload["requests"]], ["Резерв создан", "Открытая задача"])
        self.assertEqual(len(payload["events"]), 1)
        self.assertNotIn("email", payload["services"][0])
        self.assertNotIn("owner_id", payload["services"][0])
        text = json.dumps(payload)
        for secret in ("SECRET HOME ADDRESS", "PRIVATE", "private@example.test", "55.123456", "37.123456"):
            self.assertNotIn(secret, text)
        for forbidden in ("requester_id", "author_profile_id", "photos", "place", "details", "lat", "lon"):
            self.assertNotIn(forbidden, payload["requests"][0])

    def test_filter_is_parameter_safe_and_validated(self):
        self.request("Настроить компьютер")
        with patch.object(guest_access.commercial, "public_services", return_value=[]):
            self.assertEqual(len(guest_access.public_snapshot(self.connection, query="КОМПЬЮТЕР")["requests"]), 1)
            self.assertEqual(guest_access.public_snapshot(self.connection, query="' OR 1=1 --")["requests"], [])
            with self.assertRaises(ValueError):
                guest_access.public_snapshot(self.connection, category="not-a-category")

    def test_public_route_hook_only_handles_guest_discovery(self):
        replies = []
        reply = lambda *args: replies.append(args)
        self.assertFalse(guest_access.handle_public_get(None, urlparse('/api/sync'), self.connection, reply))
        self.assertEqual(replies, [])
        self.assertTrue(guest_access.handle_public_get(None, urlparse('/api/guest?category=invalid'), self.connection, reply))
        self.assertEqual(replies[0][2], 400)

    def test_page_enhancement_runs_after_modules_before_single_boot(self):
        page = '<script src="/assets/current-ui.js"></script><script>window.hpointStart();</script></body>'
        enhanced = guest_access.enhance_page(page)
        self.assertEqual(enhanced.count('window.hpointStart();'), 1)
        self.assertLess(enhanced.index('current-ui.js'), enhanced.index('hpoint-guest.js'))
        self.assertLess(enhanced.index('hpoint-guest.js'), enhanced.index('window.hpointStart();'))


if __name__ == '__main__':
    unittest.main()
