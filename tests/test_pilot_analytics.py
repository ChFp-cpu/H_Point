"""Truthful aggregate pilot evidence, privacy, cohorts and mature D7 windows."""
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import unittest
import uuid
from unittest.mock import patch

from hpoint import commercial as c, commercial_team as team, database, pilot_analytics as p


class PilotCases:
    def prepare(self, db):
        self.db = db
        self.now = datetime(2030, 1, 15, 12, tzinfo=timezone.utc)
        self.patches = [patch.object(database, "db", db), patch.object(database, "REGISTRATION_BONUS_RUB", 0),
                        patch.object(p, "_now", return_value=self.now), patch.object(c, "_now", return_value=self.now)]
        for item in self.patches:
            item.start()
        database.init_db()
        for uid in (1, 2, 3, 4, 5, 6):
            database.create_user(uid, "PRIVATE NAME", email=f"private{uid}@example.test", web_verified=True)
            db.execute("UPDATE users SET email_verified=1,created_at=?,role=? WHERE user_id=?",
                       ((self.now-timedelta(days=8)).isoformat(), "admin" if uid == 1 else "user", uid))
        c.save_profile(db, 1, {"title": "PRIVATE ORGANISATION", "kind": "organization"})
        self.service = c.save_service(db, 1, {"title": "PRIVATE SERVICE", "price_rub": 100})["id"]
        team.save_public_profile(db, 1, {"slug": "pilot-test-org", "published": True})
        team.publish_service(db, 1, {"id": self.service, "published": True})

    def close(self):
        self.db.close()
        for item in reversed(self.patches):
            item.stop()

    def moment(self, days=0, seconds=0):
        return (self.now+timedelta(days=days, seconds=seconds)).isoformat()

    def tag(self, uid, cohort):
        return p.set_cohort(self.db, 1, {"user_id": str(uid), "cohort": cohort})

    def request(self, owner=2, status="open", created=None, completed=None, helper=None):
        return c._insert_id(self.db, """INSERT INTO requests(requester_id,helper_id,what,place,time_needed,urgency,details,status,created_at,completed_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", (owner, helper, "PRIVATE REQUEST", "PRIVATE ADDRESS", "Today", "Normal", "PRIVATE NOTES", status,
              created or self.moment(-1), completed))

    def event(self, request, kind, created, actor=3):
        self.db.execute("INSERT INTO request_events(request_id,actor_id,event_type,message,created_at) VALUES(?,?,?,?,?)",
                        (request, actor, kind, "PRIVATE EVENT BODY", created))

    def test_schema_repeated_preserves_start_and_tags(self):
        before=self.db.execute("SELECT value FROM pilot_measurement_settings WHERE key='started_at'").fetchone()["value"]
        self.tag(2,"pilot")
        with patch.object(p,"_now",return_value=self.now+timedelta(days=3)):
            p.initialize_schema(self.db)
        self.assertEqual(self.db.execute("SELECT value FROM pilot_measurement_settings WHERE key='started_at'").fetchone()["value"],before)
        self.assertEqual(p.summary(self.db,1,cohort="pilot")["registrations"]["created"],1)

    def test_admin_only_verified_nonblocked_and_input_validation(self):
        for function in (lambda:p.summary(self.db,2),lambda:self.tag_as_member()):
            with self.assertRaises(PermissionError):function()
        for days in (0,91,True,"1.5"):
            with self.subTest(days=days),self.assertRaises(ValueError):p.summary(self.db,1,days)
        for cohort in ("made-up",[],None):
            with self.subTest(cohort=cohort),self.assertRaises(ValueError):p.summary(self.db,1,cohort=cohort)
        for data in ({"user_id":2,"cohort":[]},{"user_id":True,"cohort":"pilot"},{"user_id":999,"cohort":"pilot"}):
            with self.assertRaises(ValueError):p.set_cohort(self.db,1,data)
        self.db.execute("UPDATE users SET is_blocked=1 WHERE user_id=1")
        with self.assertRaises(ValueError):p.summary(self.db,1)

    def tag_as_member(self):
        return p.set_cohort(self.db,2,{"user_id":3,"cohort":"pilot"})

    def test_existing_accounts_unclassified_and_demo_not_real(self):
        self.assertEqual(p.summary(self.db,1)["cohorts"]["unclassified"],6)
        self.assertEqual(p.summary(self.db,1,cohort="real")["registrations"]["created"],0)
        self.tag(2,"pilot");self.tag(3,"demo");self.tag(4,"real")
        self.request(owner=2);self.request(owner=3);self.request(owner=4)
        for cohort in ("pilot","demo","real"):
            result=p.summary(self.db,1,cohort=cohort)
            self.assertEqual(result["registrations"]["created"],1)
            self.assertEqual(result["help"]["created"],1)
        self.assertEqual(p.summary(self.db,1)["help"]["created"],3)

    def test_response_median_deduplicates_self_future_and_invitation_events(self):
        first=self.request(created=self.moment(-1),helper=3,status="done",completed=self.moment(-1,900))
        second=self.request(created=self.moment(-1,3600))
        self.event(first,"helper_applied",self.moment(-1,1),actor=2)
        self.event(first,"helper_invited",self.moment(-1,60))
        self.event(first,"helper_applied",self.moment(-1,120))
        self.event(first,"helper_applied",self.moment(-1,300))
        self.event(second,"offer_accepted",self.moment(-1,4200))
        self.event(second,"helper_applied",self.moment(1))
        self.request(created=self.moment(1))
        result=p.summary(self.db,1)["help"]
        self.assertEqual((result["created"],result["responded"],result["assigned"],result["completed"]),(2,2,2,1))
        self.assertEqual(result["first_response"],{"sample_size":2,"median_seconds":360.0})
        self.assertEqual(result["completion_conversion"],{"numerator":1,"denominator":2,"percent":50.0})

    def test_legacy_timestamps_and_zero_denominator_are_honest(self):
        result=p.summary(self.db,1)
        self.assertIsNone(result["help"]["completion_conversion"]["percent"])
        self.assertIsNone(result["help"]["first_response"]["median_seconds"])
        self.request(created="2030-01-02 00:00:00")
        self.request(created="2030-01-01T23:59:59Z")
        self.assertEqual(p.summary(self.db,1)["help"]["created"],1)

    def test_explicit_activity_daily_dedup_repeat_and_no_last_seen_backfill(self):
        self.db.execute("UPDATE users SET last_seen_at=?",(self.now.isoformat(),))
        self.assertEqual(p.summary(self.db,1)["activity"]["active_users"],0)
        self.assertTrue(p.record_activity(self.db,2)["recorded"])
        self.assertFalse(p.record_activity(self.db,2)["recorded"])
        with patch.object(p,"_now",return_value=self.now-timedelta(days=1)):
            p.record_activity(self.db,2)
        p.record_activity(self.db,3)
        result=p.summary(self.db,1)["activity"]
        self.assertEqual((result["active_users"],result["users_on_multiple_days"]),(2,1))
        self.assertEqual(result["repeat_conversion"]["percent"],50.0)
        self.db.execute("UPDATE users SET email_verified=0 WHERE user_id=4")
        with self.assertRaises(ValueError):p.record_activity(self.db,4)

    def test_d7_only_mature_new_verified_registration_cohort(self):
        self.db.execute("UPDATE pilot_measurement_settings SET value='2030-01-05T00:00:00Z' WHERE key='started_at'")
        self.tag(2,"pilot");self.tag(3,"pilot");self.tag(4,"pilot");self.tag(5,"pilot")
        self.db.execute("UPDATE users SET created_at='2030-01-07T09:00:00Z' WHERE user_id=2")
        self.db.execute("UPDATE users SET created_at='2030-01-10T09:00:00Z' WHERE user_id=3")
        self.db.execute("UPDATE users SET created_at='2030-01-03T09:00:00Z' WHERE user_id=4")
        self.db.execute("UPDATE users SET created_at='2030-01-07T09:00:00Z' WHERE user_id=5")
        with patch.object(p,"_now",return_value=datetime(2030,1,14,9,tzinfo=timezone.utc)):
            p.record_activity(self.db,2)
        p.record_activity(self.db,5) # Day eight does not masquerade as D7.
        result=p.summary(self.db,1,cohort="pilot")["d7"]
        self.assertEqual(result,{"numerator":1,"denominator":2,"percent":50.0,"not_mature":1,"before_measurement":1})

    def test_service_views_scope_current_publication_owner_and_daily_dedup(self):
        self.assertFalse(p.record_service_view(self.db,1,{"service_id":self.service})["recorded"])
        self.assertTrue(p.record_service_view(self.db,2,{"service_id":self.service})["recorded"])
        self.assertFalse(p.record_service_view(self.db,2,{"service_id":str(self.service)})["recorded"])
        with patch.object(p,"_now",return_value=self.now-timedelta(days=1)):
            p.record_service_view(self.db,2,{"service_id":self.service})
        self.assertEqual(p.summary(self.db,1)["services"]["authenticated_viewer_service_pairs"],1)
        team.publish_service(self.db,1,{"id":self.service,"published":False})
        with self.assertRaises(ValueError):p.record_service_view(self.db,3,{"service_id":self.service})

    def test_d7_current_day_is_not_a_finished_observation_window(self):
        self.db.execute("UPDATE pilot_measurement_settings SET value='2030-01-01T00:00:00Z' WHERE key='started_at'")
        self.tag(2,"pilot")
        self.db.execute("UPDATE users SET created_at='2030-01-08T09:00:00Z' WHERE user_id=2")
        p.record_activity(self.db,2)
        result=p.summary(self.db,1,cohort="pilot")["d7"]
        self.assertEqual((result["denominator"],result["not_mature"]),(0,1))
        self.assertIsNone(result["percent"])
        with patch.object(p,"_now",return_value=self.now+timedelta(days=1)):
            matured=p.summary(self.db,1,cohort="pilot")["d7"]
        self.assertEqual((matured["numerator"],matured["denominator"],matured["percent"]),(1,1,100.0))

    def test_service_conversion_uses_observed_pairs_and_ordered_timestamps(self):
        from hpoint import work_inquiries
        self.tag(2,"pilot");self.tag(3,"demo")
        p.record_service_view(self.db,2,{"service_id":self.service})
        work_inquiries.create(self.db,2,{"service_id":self.service,"message":"PRIVATE NEED","contact":"private@example.test","request_key":"pilot-request-0001"})
        work_inquiries.create(self.db,3,{"service_id":self.service,"message":"PRIVATE DEMO NEED","contact":"demo@example.test","request_key":"demo-request-00001"})
        result=p.summary(self.db,1,cohort="pilot")
        self.assertEqual(result["services"]["view_to_inquiry"],{"numerator":1,"denominator":1,"percent":100.0})
        self.assertEqual(result["inquiries"]["created"],1)
        self.assertEqual(p.summary(self.db,1,cohort="real")["inquiries"]["created"],0)

    def test_work_repeat_uses_actual_record_dates_and_owner_group(self):
        self.tag(1,"pilot")
        c.save_client(self.db,1,{"name":"PRIVATE CLIENT","notes":"PRIVATE CLINICAL NOTES"})
        self.db.execute("UPDATE commercial_clients SET created_at=? WHERE owner_id=1",(self.moment(-2),))
        self.db.execute("UPDATE commercial_services SET created_at=? WHERE owner_id=1",(self.moment(-1),))
        result=p.summary(self.db,1,cohort="pilot")
        self.assertEqual(result["work"]["workspaces_on_multiple_days"],1)
        self.assertEqual(result["work"]["repeat_conversion"]["percent"],100.0)
        payload=json.dumps(result)
        for secret in ("PRIVATE", "example.test", "2030-01-07T09:00:00Z", "PRIVATE CLINICAL NOTES"):
            self.assertNotIn(secret,payload)
        self.assertEqual(result["quality"]["money_mode"],"TEST_ONLY")

    def test_large_canonical_user_id_and_deleted_account_cascade(self):
        uid=5_000_000_000_000_007
        database.create_user(uid,"PRIVATE LARGE ID",email="large@example.test",web_verified=True)
        self.db.execute("UPDATE users SET email_verified=1,created_at=? WHERE user_id=?",(self.now.isoformat(),uid))
        self.assertEqual(self.tag(uid,"demo")["user_id"],uid)
        p.record_activity(self.db,uid)
        self.db.execute("DELETE FROM users WHERE user_id=?",(uid,))
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM pilot_activity_days WHERE user_id=?",(uid,)).fetchone()["n"],0)
        self.assertEqual(p.summary(self.db,1,cohort="demo")["registrations"]["created"],0)


class SQLitePilot(PilotCases, unittest.TestCase):
    def setUp(self):
        db=sqlite3.connect(":memory:",isolation_level=None)
        db.row_factory=sqlite3.Row;db.execute("PRAGMA foreign_keys=ON")
        self.prepare(db)
    def tearDown(self):self.close()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"),"requires isolated PostgreSQL test database")
class PostgreSQLPilot(PilotCases, unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema="pilot_qa_"+uuid.uuid4().hex;url=os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control=database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url,self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE');self.control.close()


if __name__=="__main__":unittest.main()
