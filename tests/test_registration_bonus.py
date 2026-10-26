import sqlite3
import unittest
from unittest.mock import patch

from hpoint import billing, database


class RegistrationBonus(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.patches = [patch.object(database, "db", self.db), patch.object(billing, "db", self.db),
                        patch.object(database, "REGISTRATION_BONUS_RUB", 500)]
        for item in self.patches:
            item.start()
        database.init_db()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.db.close()

    def balance(self, uid):
        return database.wallet_summary(uid)["test_balance_rub"]

    def test_email_accounts_get_test_rubles_without_changing_hp(self):
        ids=[database.create_web_user("Web", "web@example.test", "hash"),database.create_web_user("Another", "another@example.test", "hash")]
        for user_id in ids:
            self.assertEqual(self.balance(user_id),500)
            self.assertEqual(database.wallet_summary(user_id)["balance_rub"],0)
            self.assertEqual(database.get_user(user_id)["balance"],database.START_BALANCE)
            self.assertFalse(database.grant_registration_bonus(user_id))
            self.assertEqual(self.balance(user_id),500)

    def test_purchase_and_retry_do_not_reissue_credit(self):
        database.create_user(100, "Telegram")
        invoice, created = billing.purchase_with_wallet(100, "pro", {}, "test-bonus-pro")
        self.assertTrue(created)
        self.assertEqual(self.balance(100), 351)
        self.assertFalse(database.grant_registration_bonus(100))
        self.assertEqual(billing.purchase_with_wallet(100, "pro", {}, "test-bonus-pro"), (invoice, False))
        self.assertEqual(self.balance(100), 351)

    def test_existing_balance_is_added_to_and_not_reset(self):
        with patch.object(database, "REGISTRATION_BONUS_RUB", 0):
            database.create_user(100, "Existing")
        database.wallet_add_entry(100, 75, "test", "Existing credit", "existing")
        self.assertTrue(database.grant_registration_bonus(100))
        self.assertFalse(database.grant_registration_bonus(100))
        self.assertEqual(self.balance(100), 575)

    def test_registration_rolls_back_if_credit_fails(self):
        with patch.object(database, "wallet_add_entry", side_effect=RuntimeError("ledger unavailable")):
            with self.assertRaises(RuntimeError):
                database.create_web_user("Web", "web@example.test", "hash")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_bonus_survives_stable_link_and_unlink_without_duplication(self):
        uid=database.create_web_user("Web","web@example.test","hash")
        self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
        code=database.create_link_code(uid)
        self.assertEqual(database.link_by_code(code,100),(True,"linked"))
        self.assertEqual(database.get_user(uid)["tg_user_id"],100)
        self.assertIsNone(database.get_user(100))
        self.assertEqual(self.balance(uid),500)
        self.assertFalse(database.grant_registration_bonus(uid))
        self.assertEqual(database.detach_telegram_to_web_profile(uid),uid)
        self.assertIsNone(database.get_user(uid)["tg_user_id"])
        self.assertEqual(self.balance(uid),500)
        self.assertFalse(database.grant_registration_bonus(uid))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM wallet_transactions WHERE user_id=? AND kind='registration_bonus'",(uid,)).fetchone()[0],1)

    def test_legacy_telegram_ticket_cannot_register_or_grant_bonus(self):
        database.create_telegram_auth_ticket("ticket")
        self.assertFalse(database.complete_telegram_auth_ticket("ticket",100,"Telegram"))
        self.assertIsNone(database.get_user(100))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM wallet_transactions").fetchone()[0],0)

    def test_link_keeps_web_id_and_new_email_account_gets_its_own_credit(self):
        uid=database.create_web_user("First","first@example.test","hash")
        self.db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
        self.assertEqual(database.link_by_code(database.create_link_code(uid),100),(True,"linked"))
        next_uid=database.create_web_user("Next","next@example.test","hash")
        self.assertNotEqual(next_uid,uid)
        self.assertEqual(self.balance(next_uid),500)
        self.assertEqual(self.balance(uid),500)
        self.assertIsNone(database.get_user(100))

    def test_unverified_email_cannot_link_or_receive_another_bonus(self):
        uid=database.create_web_user("Web","web@example.test","hash")
        self.assertFalse(database.link_by_code(database.create_link_code(uid),100)[0])
        self.assertIsNone(database.get_user(uid)["tg_user_id"])
        self.assertEqual(self.balance(uid),500)
        self.assertFalse(database.grant_registration_bonus(uid))

    def test_link_rejects_another_email_profile_instead_of_merging_bonuses(self):
        first=database.create_web_user("First","first@example.test","hash")
        second=database.create_web_user("Second","second@example.test","hash")
        self.db.execute("UPDATE users SET email_verified=1")
        self.assertEqual(database.link_by_code(database.create_link_code(first),100),(True,"linked"))
        self.assertFalse(database.link_by_code(database.create_link_code(second),100)[0])
        self.assertEqual((self.balance(first),self.balance(second)),(500,500))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0],2)


if __name__ == "__main__":
    unittest.main()
