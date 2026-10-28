"""Tenant boundaries and persisted organisation workflows on SQLite/PostgreSQL."""
import json
import os
import sqlite3
import unittest
import uuid
from datetime import timedelta
from unittest.mock import patch

from hpoint import commercial as c, commercial_team as team, database


class OrganizationCases:
    def prepare(self,db):
        self.db=db
        self.patches=[patch.object(database,"db",db),patch.object(database,"REGISTRATION_BONUS_RUB",0)]
        for p in self.patches:p.start()
        database.init_db()
        for uid in (-101,-202,-303,-404,-505):
            database.create_user(uid,"Synthetic "+str(uid),web_verified=True)
            db.execute("UPDATE users SET email=?,email_verified=1 WHERE user_id=?",("user"+str(abs(uid))+"@example.test",uid))
        c.save_profile(db,-101,dict(kind="organization",title="First private studio"))
        c.save_profile(db,-404,dict(kind="foreman",title="Other private organisation"))

    def close(self):
        self.db.close()
        for p in reversed(self.patches):p.stop()

    def post(self,suffix,data=None,uid=-101,owner=-101):
        return c.post_action(self.db,uid,"/api/commercial"+suffix,{"owner_id":owner,**(data or {})})

    def join(self,uid=-202,role="member",owner=-101):
        invite=self.post("/team/invite",dict(email="user"+str(abs(uid))+"@example.test",role=role),uid=owner,owner=owner)
        return self.post("/team/accept",dict(invitation_id=invite["id"]),uid=uid,owner=owner)

    def client(self,owner=-101):
        return c.save_client(self.db,owner,dict(name="Synthetic private client",contact="secret@example.test",notes="CONFIDENTIAL CRM NOTES"))["id"]

    def obj(self,owner=-101,**kwargs):
        return self.post("/objects",dict(title="Test construction object",**kwargs),uid=owner,owner=owner)["id"]

    def estimate(self,**kwargs):
        return dict(title="Decimal estimate",items=[dict(title="Work line",quantity="3",price_rub="0.335",cost_rub="0.10",unit="hr")],**kwargs)

    def test_migration_repeated_preserves_existing_crm(self):
        client=self.client();obj=self.obj(client_id=client)
        c.initialize_schema(self.db);c.initialize_schema(self.db)
        state=c.dashboard(self.db,-101)
        self.assertEqual(state["clients"][0]["id"],client)
        self.assertEqual(state["objects"][0]["id"],obj)
        self.assertEqual(state["role"],"owner")

    def test_negative_ids_invite_accept_multiorganisation_and_leave(self):
        self.join();self.join(owner=-404)
        state=c.dashboard(self.db,-202,owner_id="-101")
        self.assertEqual({r["owner_id"] for r in state["organizations"]},{-101,-404})
        self.assertEqual(state["role"],"member")
        self.assertTrue(c.summary(self.db,-202)["exists"])
        self.post("/team/leave",uid=-202)
        with self.assertRaises(PermissionError):c.dashboard(self.db,-202,-101)
        self.assertEqual(c.dashboard(self.db,-202)["selected_owner_id"],-404)
        with self.assertRaisesRegex(ValueError,"Владелец"):self.post("/team/leave")

    def test_invite_is_private_email_bound_expiring_revocable_and_idempotent(self):
        item=self.post("/team/invite",dict(email="USER202@example.test",role="member"))["id"]
        self.assertEqual(c.dashboard(self.db,-202)["incoming_invitations"][0]["id"],item)
        self.assertEqual(c.dashboard(self.db,-303)["incoming_invitations"],[])
        with self.assertRaises(PermissionError):self.post("/team/accept",dict(invitation_id=item),uid=-303)
        self.db.execute("UPDATE commercial_invitations SET expires_at='2020-01-01T00:00:00+00:00' WHERE id=?",(item,))
        with self.assertRaisesRegex(ValueError,"истёк"):self.post("/team/accept",dict(invitation_id=item),uid=-202)
        self.post("/team/invite",dict(email="user202@example.test"))
        self.post("/team/revoke",dict(invitation_id=item))
        with self.assertRaises(ValueError):self.post("/team/accept",dict(invitation_id=item),uid=-202)
        self.post("/team/invite",dict(email="user202@example.test"))
        self.post("/team/decline",dict(invitation_id=item),uid=-202)
        self.assertEqual(c.dashboard(self.db,-202)["incoming_invitations"],[])
        self.join();self.post("/team/accept",dict(invitation_id=item),uid=-202)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_members WHERE owner_id=-101 AND user_id=-202").fetchone()["n"],1)

    def test_roles_cannot_escalate_and_members_cannot_change_finance_catalog_or_publication(self):
        self.join();self.join(-303,"admin")
        for suffix,payload in (
            ("/services",dict(title="Forbidden service")),("/clients",dict(name="Forbidden client")),
            ("/estimates",self.estimate()),("/team/invite",dict(email="user505@example.test")),
            ("/public-profile",dict(slug="forbidden-page",published=True)),
            ("/profile",dict(title="Forbidden rename",kind="organization")),
        ):
            with self.subTest(suffix=suffix),self.assertRaises(PermissionError):self.post(suffix,payload,uid=-202)
        with self.assertRaises(PermissionError):self.post("/team/role",dict(user_id=-202,role="admin"),uid=-303)
        with self.assertRaises(PermissionError):self.post("/team/invite",dict(email="user505@example.test",role="admin"),uid=-303)
        with self.assertRaises(PermissionError):self.post("/team/remove",dict(user_id=-303),uid=-202)
        self.post("/team/role",dict(user_id=-202,role="admin"))
        self.assertEqual(c.dashboard(self.db,-202,-101)["role"],"admin")
        with self.assertRaises(PermissionError):self.post("/delete",dict(confirm=True),uid=-202)
        with self.assertRaises(PermissionError):self.post("/renew",dict(purchase_key="synthetic-renew-unauthorised"),uid=-202)

    def test_foreign_references_and_uninvited_users_are_rejected(self):
        self.join()
        otherclient=self.client(-404);otherobject=self.obj(-404)
        service=c.save_service(self.db,-404,dict(title="Foreign service"))["id"]
        for payload in (dict(client_id=otherclient),dict(assignee_id=-303)):
            with self.assertRaises(ValueError):self.post("/objects",dict(title="Own object",**payload))
        with self.assertRaises(ValueError):self.post("/tasks",dict(title="Foreign object task",object_id=otherobject),uid=-202)
        with self.assertRaises(ValueError):self.post("/estimates",self.estimate(object_id=otherobject))
        with self.assertRaises(ValueError):self.post("/objects",dict(id=otherobject,title="Hijacked object"))
        with self.assertRaises(PermissionError):c.dashboard(self.db,-303,-101)
        with self.assertRaises(PermissionError):self.post("/objects",dict(title="Hijacked tenant"),uid=-303)
        with self.assertRaises(ValueError):c.save_booking(self.db,-101,dict(client_id=self.client(),service_id=service,title="Foreign service booking",starts_at="2030-01-01T12:00:00+00:00"))

    def test_schedule_conflicts_are_atomic_and_scoped_to_assigned_person(self):
        self.join();client=self.client();obj=self.obj()
        booking=dict(title="Work booking",client_id=client,object_id=obj,assignee_id=-202,starts_at="2030-01-01T10:00:00+00:00",duration_minutes=60,price_rub=500)
        item=self.post("/bookings",booking,uid=-202)["id"]
        # Offset represents the same instant, so canonical strings cannot hide conflicts.
        with self.assertRaisesRegex(ValueError,"уже есть запись"):self.post("/bookings",{**booking,"starts_at":"2030-01-01T13:30:00+03:00"})
        self.post("/bookings",{**booking,"starts_at":"2030-01-01T11:00:00+00:00"})
        self.post("/bookings",{**booking,"assignee_id":-101})
        self.post("/bookings/status",dict(id=item,status="cancelled"))
        self.post("/bookings",booking)
        with self.assertRaises(ValueError):self.post("/bookings/status",dict(id=item,status="planned"))
        shift=dict(title="Morning shift",assignee_id=-202,starts_at="2030-01-01T08:00:00+00:00",ends_at="2030-01-01T17:00:00+00:00")
        sid=self.post("/shifts",shift)["id"]
        with self.assertRaisesRegex(ValueError,"пересекаются"):self.post("/shifts",{**shift,"starts_at":"2030-01-01T09:00:00+00:00"})
        self.post("/shifts/delete",dict(id=sid));self.assertEqual(c.dashboard(self.db,-101)["shifts"],[])

    def test_decimal_estimate_matches_saved_lines_and_round_trips_without_drift(self):
        item=self.post("/estimates",self.estimate(markup_percent="10",status="approved"))["id"]
        estimate=c.dashboard(self.db,-101)["estimates"][0]
        self.assertEqual((estimate["items"][0]["price_rub"],estimate["subtotal_rub"],estimate["total_rub"],estimate["cost_rub"],estimate["profit_rub"]),("0.34","1.02","1.12","0.30","0.82"))
        self.post("/estimates",{**estimate,"id":item})
        reloaded=c.dashboard(self.db,-101)["estimates"][0]
        self.assertEqual(reloaded["total_rub"],estimate["total_rub"])
        self.assertEqual(reloaded["items"],estimate["items"])
        p=c.dashboard(self.db,-101)["performance"]
        self.assertEqual((p["estimate_total_rub"],p["cost_total_rub"],p["profit_total_rub"]),("1.12","0.30","0.82"))

    def test_invalid_estimate_does_not_partially_save_and_100_rows_are_bounded(self):
        original=self.post("/estimates",self.estimate())["id"]
        for value in ("NaN","Infinity","-1","1e100","0.00001",True,{},"x"*100):
            with self.subTest(value=value),self.assertRaises(ValueError):
                self.post("/estimates",dict(id=original,title="Invalid",items=[dict(title="Bad line",quantity=value,price_rub="20")]))
        self.assertEqual(c.dashboard(self.db,-101)["estimates"][0]["title"],"Decimal estimate")
        lines=[dict(title="Valid line "+str(i),quantity="1.5",price_rub="20.10",cost_rub="1.05") for i in range(100)]
        self.post("/estimates",dict(title="Long valid estimate",items=lines))
        self.assertEqual(c.dashboard(self.db,-101)["estimates"][0]["total_rub"],"3015.00")
        with self.assertRaises(ValueError):self.post("/estimates",dict(title="Too many lines",items=lines+[lines[0]]))

    def test_removed_member_loses_access_and_assignments_are_released(self):
        self.join();obj=self.obj(assignee_id=-202)
        self.post("/tasks",dict(title="Task with member",assignee_id=-202,object_id=obj),uid=-202)
        self.post("/team/remove",dict(user_id=-202))
        data=c.dashboard(self.db,-101)
        self.assertIsNone(data["objects"][0]["assignee_id"]);self.assertIsNone(data["tasks"][0]["assignee_id"])
        with self.assertRaises(PermissionError):self.post("/tasks",dict(title="No longer allowed"),uid=-202)

    def test_expired_organization_is_read_only_but_leave_and_revoke_still_work(self):
        self.join()
        invite=self.post("/team/invite",dict(email="user505@example.test"))["id"]
        self.db.execute("UPDATE commercial_profiles SET trial_until='2020-01-01T00:00:00+00:00' WHERE user_id=-101")
        self.assertFalse(c.dashboard(self.db,-202)["profile"]["active"])
        with self.assertRaisesRegex(ValueError,"Пробный период"):self.post("/tasks",dict(title="No active access"),uid=-202)
        self.post("/team/revoke",dict(invitation_id=invite))
        self.post("/team/leave",uid=-202)
        self.assertEqual(c.summary(self.db,-202),{"exists":False})

    def test_public_optin_subscription_and_private_allowlist(self):
        client=self.client();self.obj(client_id=client,notes="PRIVATE OBJECT NOTES")
        service=c.save_service(self.db,-101,dict(title="Public service",description="Public service details",price_rub=300))["id"]
        self.assertEqual(c.public_services(self.db),[])
        self.post("/public-profile",dict(slug="my-public-studio",published=True,description="Public story",contact="Public phone",address="Public place"))
        self.post("/services/publish",dict(id=service,published=True))
        public=c.public_organization(self.db,"my-public-studio")
        text=json.dumps(public)
        for private in ("secret@example.test","CONFIDENTIAL CRM NOTES","PRIVATE OBJECT NOTES","user101@example.test","Synthetic private client"):
            self.assertNotIn(private,text)
        self.assertEqual(c.public_services(self.db)[0]["organization_url"],"/organizations/my-public-studio")
        self.assertEqual(public["currency"],"TEST_RUB")
        with self.assertRaises(ValueError):self.post("/public-profile",dict(slug="my-public-studio",published=True),uid=-404,owner=-404)
        self.db.execute("UPDATE commercial_profiles SET trial_until='2020-01-01T00:00:00+00:00' WHERE user_id=-101")
        self.assertEqual(c.public_services(self.db),[])
        with self.assertRaises(ValueError):c.public_organization(self.db,"my-public-studio")
        self.post("/public-profile",dict(slug="my-public-studio",published=False))

    def test_organisation_delete_erases_extended_crm_and_memberships(self):
        self.join();obj=self.obj();self.post("/tasks",dict(title="Private task",object_id=obj));self.post("/estimates",self.estimate(object_id=obj))
        self.post("/public-profile",dict(slug="deleted-studio",published=True))
        self.post("/delete",dict(confirm=True))
        for table in ("commercial_members","commercial_invitations","commercial_objects","commercial_tasks","commercial_estimates","commercial_shifts","commercial_public_profiles"):
            self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM "+table+" WHERE owner_id=-101").fetchone()["n"],0)
        self.assertEqual(c.summary(self.db,-202),{"exists":False})
        self.assertFalse(c.dashboard(self.db,-101)["trial_available"])

    def test_performance_uses_real_completion_and_dates_not_created_count(self):
        self.join();client=self.client();now=c._now()
        for status,days,amount in (("completed",0,700),("planned",0,900),("cancelled",0,500),("completed",60,4000)):
            self.post("/bookings",dict(title="Performance record",client_id=client,assignee_id=-202,starts_at=(now-timedelta(days=days)).isoformat(),status=status,price_rub=amount))
        self.post("/tasks",dict(title="Completed task",status="done",assignee_id=-202))
        self.post("/tasks",dict(title="Overdue task",due_at=(now-timedelta(days=1)).isoformat()))
        p=c.dashboard(self.db,-101)["performance"]
        self.assertEqual((p["completed"],p["planned"],p["cancelled"],p["revenue_test_rub"],p["completion_percent"]),(1,1,1,700,33))
        self.assertEqual((p["tasks_done"],p["tasks_overdue"]),(1,1))
        self.assertEqual(sum(r["revenue_test_rub"] for r in p["series"]),700)
        self.assertEqual(len(p["series"]),30)
        self.assertEqual(next(r for r in p["by_member"] if r["user_id"]==-202)["bookings_completed"],1)


class SQLiteOrganizations(OrganizationCases,unittest.TestCase):
    def setUp(self):
        db=sqlite3.connect(":memory:",isolation_level=None);db.row_factory=sqlite3.Row;db.execute("PRAGMA foreign_keys=ON")
        self.prepare(db)
    def tearDown(self):self.close()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"),"requires isolated PostgreSQL test database")
class PostgreSQLOrganizations(OrganizationCases,unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema="org_qa_"+uuid.uuid4().hex
        url=os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control=database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url,self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE');self.control.close()


if __name__=="__main__":unittest.main()
