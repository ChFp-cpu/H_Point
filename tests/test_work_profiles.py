"""Professional workflows, private observations and kind-history preservation."""
import json
import os
import sqlite3
import unittest
import uuid
from unittest.mock import patch

from hpoint import commercial as c, database, work_profiles as profiles


class ProfileCases:
    def prepare(self,db):
        self.db=db
        self.patches=[patch.object(database,"db",db),patch.object(database,"REGISTRATION_BONUS_RUB",0)]
        for p in self.patches:p.start()
        database.init_db()
        for uid in (-1,-2,-3,-4):
            database.create_user(uid,"Synthetic profile user "+str(uid),web_verified=True)
            db.execute("UPDATE users SET email=?,email_verified=1 WHERE user_id=?",("profile"+str(abs(uid))+"@example.test",uid))
        self.kind("trainer")
        c.save_profile(db,-4,dict(kind="trainer",title="Other private organisation"))
        self.client=c.save_client(db,-1,dict(name="Synthetic client",contact="private-contact@example.test"))["id"]
        self.other_client=c.save_client(db,-4,dict(name="Foreign client"))["id"]
        self.obj=c.post_action(db,-1,"/api/commercial/objects",dict(title="Synthetic object"))["id"]
        for uid in (-2,-3):
            item=c.post_action(db,-1,"/api/commercial/team/invite",dict(email="profile"+str(abs(uid))+"@example.test"))["id"]
            c.post_action(db,uid,"/api/commercial/team/accept",dict(invitation_id=item))

    def close(self):
        self.db.close()
        for p in reversed(self.patches):p.stop()

    def kind(self,kind):
        return c.save_profile(self.db,-1,dict(kind=kind,title="Synthetic professional"))

    def post(self,key,data,uid=-1,owner=-1,verb=""):
        return c.post_action(self.db,uid,"/api/commercial/professional/"+key+("/"+verb if verb else ""),dict(owner_id=owner,**data))

    def state(self,uid=-1,owner=-1):return c.dashboard(self.db,uid,owner)["professional"]

    def records(self,key,uid=-1):
        state=self.state(uid)
        return next(m["records"] for m in state["modules"]+state["history"] if m["key"]==key)

    def athlete(self,coach=-2):
        return self.post("athletes",dict(title="PRIVATE ATHLETE",client_id=self.client,assignee_id=coach,discipline="Judo",weight_category="73 kg",goals="Private competition goal"))["id"]

    def test_nine_profile_catalog_and_eighteen_concrete_workflows(self):
        state=self.state()
        self.assertEqual(len(state["catalog"]),9)
        self.assertEqual(set(c.KINDS),{"trainer","tutor","beauty","repair","foreman","events","studio","organization","other"})
        self.assertEqual({m["key"] for m in state["modules"]},{"athletes","training_sessions","health_checks","competitions"})
        self.assertEqual(sum(len(k["modules"]) for k in state["catalog"]),18)
        c.initialize_schema(self.db);self.assertEqual(len(self.state()["catalog"]),9)

    def test_coach_and_tutor_can_start_without_a_duplicate_contact_card(self):
        athlete=self.post("athletes",dict(title="Standalone athlete",assignee_id=-2),uid=-2)["id"]
        self.post("health_checks",dict(title="Standalone measurement",athlete_id=athlete,measured_on="2026-10-28",wellbeing=8,weight_kg="70.5"),uid=-2)
        self.post("athletes",dict(id=athlete,title="Linked athlete",assignee_id=-2,client_id=self.client))
        self.assertEqual(self.records("athletes")[0]["client_id"],self.client)
        self.kind("tutor")
        self.post("students",dict(title="Standalone pupil",subject="Math"))
        self.assertIsNone(self.records("students")[0]["client_id"])

    def test_trainer_diary_measurements_competition_and_private_progress(self):
        athlete=self.athlete()
        measurement=self.post("health_checks",dict(title="PRIVATE MEASUREMENT",athlete_id=athlete,measured_on="2026-10-20",weight_kg="72.35",wellbeing=8,sleep_hours="7.5",resting_pulse=65,discomfort="PRIVATE OBSERVATION"),uid=-2)["id"]
        self.post("training_sessions",dict(title="Preparation",athlete_id=athlete,session_on="2026-10-20",duration_minutes=90,load_intensity="moderate",exercises="Throws",results="Technique improved",status="completed"),uid=-2)
        self.post("competitions",dict(title="Local championship",athlete_id=athlete,competition_date="2030-01-01",weight_category="73 kg",status="registered"),uid=-2)
        state=self.state(-2)
        self.assertEqual(state["progress"]["weight_series"][0]["weight_kg"],"72.35")
        self.assertEqual((state["progress"]["training_completed"],state["progress"]["competitions_upcoming"]),(1,1))
        public_to_colleague=json.dumps(c.dashboard(self.db,-3,-1),ensure_ascii=False)
        for secret in ("PRIVATE ATHLETE","PRIVATE MEASUREMENT","72.35","PRIVATE OBSERVATION"):
            self.assertNotIn(secret,public_to_colleague)
        with self.assertRaises(PermissionError):self.post("health_checks",dict(id=measurement,title="Stolen",athlete_id=athlete,measured_on="2026-10-20",wellbeing=5),uid=-3)
        with self.assertRaises(PermissionError):self.post("health_checks",dict(id=measurement,status="archived"),uid=-3,verb="status")
        with self.assertRaises(PermissionError):self.post("health_checks",dict(id=measurement,confirm=True),uid=-3,verb="delete")

    def test_rejoining_a_team_does_not_restore_old_private_coach_assignments(self):
        athlete=self.athlete(-2)
        self.post("health_checks",dict(title="PRIVATE MEASUREMENT",athlete_id=athlete,measured_on="2026-10-28",wellbeing=8),uid=-2)
        c.post_action(self.db,-1,"/api/commercial/team/remove",dict(user_id=-2))
        invite=c.post_action(self.db,-1,"/api/commercial/team/invite",dict(email="profile2@example.test"))["id"]
        c.post_action(self.db,-2,"/api/commercial/team/accept",dict(invitation_id=invite))
        self.assertEqual(self.records("athletes",uid=-2),[])
        self.assertEqual(self.records("health_checks",uid=-2),[])
        self.assertIsNone(self.records("athletes")[0]["assignee_id"])

    def test_reassigning_coach_changes_visibility_of_all_historical_measurements(self):
        athlete=self.athlete()
        self.post("health_checks",dict(title="Health observation",athlete_id=athlete,measured_on="2026-10-20",wellbeing=8,weight_kg="70"),uid=-2)
        self.post("athletes",dict(id=athlete,title="PRIVATE ATHLETE",client_id=self.client,assignee_id=-3))
        self.assertEqual(self.records("health_checks",-2),[])
        self.assertEqual(len(self.records("health_checks",-3)),1)
        with self.assertRaises(PermissionError):self.post("training_sessions",dict(title="No longer coach",athlete_id=athlete,session_on="2026-10-20",duration_minutes=60),uid=-2)
        with self.assertRaises(PermissionError):self.post("athletes",dict(title="Assign to another",client_id=self.client,assignee_id=-3),uid=-2)
        # A parent with history cannot be relabelled as another person.
        client=c.save_client(self.db,-1,dict(name="Another local client"))["id"]
        with self.assertRaises(ValueError):self.post("athletes",dict(id=athlete,title="Different person",client_id=client,assignee_id=-3))

    def test_unknown_health_fields_are_not_persisted_in_unrelated_records(self):
        self.kind("tutor")
        self.post("students",dict(title="Student",client_id=self.client,subject="Math",weight_kg="PRIVATE NUMBER",diagnosis="UNASKED HEALTH",extra={"secret":"PRIVATE"}))
        record=self.records("students")[0]
        self.assertNotIn("weight_kg",record)
        self.assertNotIn("diagnosis",record)
        self.assertNotIn("UNASKED HEALTH",self.db.execute("SELECT data_json FROM commercial_professional_records").fetchone()["data_json"])

    def test_tutor_workflow_persists_homework_grade_and_subject(self):
        self.kind("tutor")
        student=self.post("students",dict(title="Exam preparation",client_id=self.client,subject="Mathematics",level="Grade 10",goals="Exam target",assignee_id=-2))["id"]
        lesson=self.post("lessons",dict(title="Quadratic equations",student_id=student,lesson_on="2026-10-20",duration_minutes=60,homework="Solve problems",homework_status="checked",grade="88.5",status="completed"))["id"]
        record=self.records("lessons")[0]
        self.assertEqual((record["grade"],record["homework_status"],record["client_id"]),("88.5","checked",self.client))
        self.post("lessons",dict(id=lesson,status="archived"),verb="status")
        self.assertTrue(self.records("lessons")[0]["archived"])

    def test_beauty_materials_and_client_restrictions_are_private_to_assigned_specialist(self):
        self.kind("beauty")
        card=self.post("beauty_cards",dict(title="PRIVATE BEAUTY CARD",client_id=self.client,assignee_id=-2,preferences="Colour",sensitivities="PRIVATE LIMITATION"))["id"]
        procedure=self.post("procedures",dict(title="Colour procedure",card_id=card,procedure_on="2026-10-20",materials="Material A",material_cost_rub="100.345",price_rub="1000.10",status="completed"),uid=-2)["id"]
        record=self.records("procedures",-2)[0]
        self.assertEqual(record["material_cost_rub"],"100.35")
        self.assertEqual(self.records("procedures",-3),[])
        self.assertNotIn("PRIVATE LIMITATION",json.dumps(self.state(-3)))
        self.post("procedures",dict(id=procedure,confirm=True),uid=-2,verb="delete")
        self.assertEqual(self.records("procedures",-2),[])

    def test_repair_equipment_diagnostics_parts_and_due_dates(self):
        self.kind("repair")
        equipment=self.post("equipment",dict(title="Laptop",client_id=self.client,brand="Model X",serial_number="SN-123",condition="Will not turn on"))["id"]
        payload=dict(title="Power repair",equipment_id=equipment,received_on="2026-10-20",due_on="2026-10-23",diagnostics="Power supply",parts="Adapter",parts_cost_rub="500.10",price_rub="1000.20",status="waiting_parts")
        order=self.post("repair_orders",payload)["id"]
        self.post("repair_orders",dict(id=order,status="delivered"),verb="status")
        self.assertEqual(self.records("repair_orders")[0]["status"],"delivered")
        with self.assertRaises(ValueError):self.post("repair_orders",{**payload,"due_on":"2026-10-19"})

    def test_event_checklist_vendor_budget_and_foreman_stages(self):
        self.kind("events")
        event=self.post("event_projects",dict(title="Conference",client_id=self.client,event_on="2030-01-01",venue="Hall",guests=50,vendor="Catering",budget_rub="50000.55"))["id"]
        self.post("event_checklist",dict(title="Order catering",project_id=event,assignee_id=-2,vendor="Supplier",due_on="2029-12-25",cost_rub="10000.10",status="completed"))
        self.assertEqual(self.records("event_checklist")[0]["cost_rub"],"10000.10")
        self.kind("foreman")
        self.post("stages",dict(title="Finish walls",object_id=self.obj,assignee_id=-2,quantity="25.125",unit="m2",progress_percent=50,planned_rub="10000",actual_rub="4000",starts_on="2026-10-20",ends_on="2026-10-25"))
        self.assertEqual(self.records("stages")[0]["quantity"],"25.125")
        self.assertEqual(len(self.records("event_projects")),1)

    def test_studio_attendance_unique_capacity_and_restore_cannot_bypass(self):
        self.kind("studio")
        group=self.post("groups",dict(title="Small group",discipline="Drawing",capacity=1,assignee_id=-2))["id"]
        cls=self.post("group_classes",dict(title="First class",group_id=group,class_on="2026-10-20",duration_minutes=60))["id"]
        payload=dict(title="First visit",class_id=cls,client_id=self.client,mark="present")
        visit=self.post("attendance",payload)["id"]
        with self.assertRaisesRegex(ValueError,"уже отмечено"):self.post("attendance",payload)
        other=c.save_client(self.db,-1,dict(name="Other student"))["id"]
        with self.assertRaisesRegex(ValueError,"вместимость"):self.post("attendance",{**payload,"client_id":other})
        self.post("attendance",dict(id=visit,status="archived"),verb="status")
        self.post("attendance",{**payload,"client_id":other})
        with self.assertRaisesRegex(ValueError,"вместимость"):self.post("attendance",dict(id=visit,status="recorded"),verb="status")

    def test_org_responsibility_and_other_assignment_have_typed_results(self):
        self.kind("organization")
        self.post("responsibilities",dict(title="Delivery responsibility",object_id=self.obj,assignee_id=-2,target="Complete shipment",progress_percent=100,result="Delivered",status="completed"))
        self.assertEqual(self.records("responsibilities")[0]["assignee_id"],-2)
        self.kind("other")
        self.post("assignments",dict(title="Consulting assignment",client_id=self.client,object_id=self.obj,scope="Review process",progress_percent=25,result="Initial report"))
        self.assertEqual(self.records("assignments")[0]["progress_percent"],25)

    def test_kind_switch_preserves_trial_old_records_and_private_history(self):
        athlete=self.athlete()
        self.post("health_checks",dict(title="PRIVATE OLD OBSERVATION",athlete_id=athlete,measured_on="2026-10-20",wellbeing=9),uid=-2)
        before=c.dashboard(self.db,-1)["profile"]
        self.kind("tutor")
        state=self.state()
        self.assertEqual({m["key"] for m in state["modules"]},{"students","lessons"})
        self.assertEqual(len(self.records("health_checks")),1)
        self.assertFalse(next(m for m in state["history"] if m["key"]=="health_checks")["can_write"])
        self.assertNotIn("PRIVATE OLD OBSERVATION",json.dumps(self.state(-3)))
        with self.assertRaises(PermissionError):self.post("health_checks",dict(id=1,status="archived"),verb="status")
        self.kind("trainer")
        after=c.dashboard(self.db,-1)["profile"]
        self.assertEqual((before["trial_started_at"],before["trial_until"]),(after["trial_started_at"],after["trial_until"]))
        self.assertEqual(len(self.records("health_checks")),1)

    def test_tenant_and_foreign_reference_validation_cannot_be_bypassed(self):
        athlete=self.athlete()
        foreign=self.post("athletes",dict(title="Foreign athlete",client_id=self.other_client),uid=-4,owner=-4)["id"]
        with self.assertRaises(ValueError):self.post("athletes",dict(title="Wrong client",client_id=self.other_client))
        with self.assertRaises(ValueError):self.post("health_checks",dict(title="Foreign parent",athlete_id=foreign,measured_on="2026-10-20",wellbeing=8))
        with self.assertRaises(PermissionError):self.post("athletes",dict(id=athlete,title="Hijack",client_id=self.client),uid=-4)
        with self.assertRaises(ValueError):self.post("athletes",dict(id=foreign,title="Hijack",client_id=self.client))
        self.kind("organization")
        with self.assertRaises(ValueError):self.post("responsibilities",dict(title="Wrong assignee",assignee_id=-4,target="Not allowed",progress_percent=0))

    def test_invalid_health_metrics_and_enums_never_partially_save(self):
        athlete=self.athlete()
        payload=dict(title="Valid measure",athlete_id=athlete,measured_on="2026-10-20",wellbeing=8)
        for changes in (dict(weight_kg="NaN"),dict(weight_kg="Infinity"),dict(weight_kg="-1"),dict(weight_kg="1000"),dict(weight_kg="1.00001"),dict(wellbeing=True),dict(wellbeing=11),dict(measured_on="2026-02-30"),dict(status={}),dict(resting_pulse=500)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.post("health_checks",{**payload,**changes})
        self.assertEqual(self.records("health_checks"),[])

    def test_archiving_parent_keeps_diary_and_delete_requires_confirmation(self):
        athlete=self.athlete()
        self.post("health_checks",dict(title="Historical measure",athlete_id=athlete,measured_on="2026-10-20",wellbeing=8),uid=-2)
        with self.assertRaisesRegex(ValueError,"связанные"):self.post("athletes",dict(id=athlete,confirm=True),verb="delete")
        self.post("athletes",dict(id=athlete,status="archived"),verb="status")
        with self.assertRaisesRegex(ValueError,"архива"):self.post("health_checks",dict(title="No new archive entry",athlete_id=athlete,measured_on="2026-10-21",wellbeing=8),uid=-2)
        self.assertEqual(len(self.records("health_checks")),1)

    def test_expiry_is_read_only_publication_omits_records_and_deletion_cleans_all(self):
        athlete=self.athlete();self.post("health_checks",dict(title="PRIVATE HEALTH ENTRY",athlete_id=athlete,measured_on="2026-10-20",wellbeing=8),uid=-2)
        c.post_action(self.db,-1,"/api/commercial/public-profile",dict(slug="test-trainer",published=True,description="Public coaching"))
        public=json.dumps(c.public_organization(self.db,"test-trainer"))
        self.assertNotIn("PRIVATE",public)
        self.db.execute("UPDATE commercial_profiles SET trial_until='2020-01-01T00:00:00+00:00' WHERE user_id=-1")
        self.assertFalse(self.state()["modules"][0]["can_write"])
        with self.assertRaisesRegex(ValueError,"Пробный период"):self.post("athletes",dict(id=athlete,status="paused"),verb="status")
        self.assertEqual(len(self.records("health_checks")),1)
        c.delete_profile(self.db,-1,True)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_professional_records WHERE owner_id=-1").fetchone()["n"],0)
        self.assertFalse(c.dashboard(self.db,-1)["trial_available"])


class SQLiteWorkProfiles(ProfileCases,unittest.TestCase):
    def setUp(self):
        db=sqlite3.connect(":memory:",isolation_level=None);db.row_factory=sqlite3.Row;db.execute("PRAGMA foreign_keys=ON")
        self.prepare(db)
    def tearDown(self):self.close()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"),"requires isolated PostgreSQL test database")
class PostgreSQLWorkProfiles(ProfileCases,unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema="work_profiles_qa_"+uuid.uuid4().hex
        url=os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control=database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url,self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE');self.control.close()


if __name__=="__main__":unittest.main()
