"""Private decimal estimates and actual native exports on SQLite/PostgreSQL."""
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
import re
import sqlite3
import unittest
from unittest.mock import patch
import uuid
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from hpoint import commercial as c, commercial_team as team, database

NS={"s":"http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def workbook(body):
    with ZipFile(BytesIO(body)) as bundle:
        strings=ET.fromstring(bundle.read("xl/sharedStrings.xml"))
        texts=["".join(node.itertext()) for node in strings]
        sheets=[ET.fromstring(bundle.read(name)) for name in sorted(bundle.namelist()) if re.fullmatch(r"xl/worksheets/sheet\d+.xml",name)]
        return texts,sheets,ET.fromstring(bundle.read("xl/workbook.xml"))


def cells(sheet):return {node.attrib["r"]:node for node in sheet.findall(".//s:sheetData/s:row/s:c",NS)}
def value(sheet,address):return cells(sheet)[address].find("s:v",NS).text
def formula(sheet,address):return cells(sheet)[address].find("s:f",NS).text


class EstimateCases:
    def prepare(self,db):
        self.db=db
        self.patches=[patch.object(database,"db",db),patch.object(database,"REGISTRATION_BONUS_RUB",0)]
        for item in self.patches:item.start()
        database.init_db()
        for uid in (1,2,3,4):
            database.create_user(uid,"Synthetic estimate user "+str(uid),email=f"estimate{uid}@example.test",web_verified=True)
            db.execute("UPDATE users SET email_verified=1 WHERE user_id=?",(uid,))
        c.save_profile(db,1,{"kind":"foreman","title":"Пример строительной организации","contact":"business@example.test"})
        c.save_profile(db,4,{"kind":"organization","title":"Другая организация"})
        self.client=c.save_client(db,1,{"name":"Клиент Ирина","contact":"PRIVATE-CLIENT-CONTACT","notes":"PRIVATE-CLIENT-NOTES"})["id"]
        self.obj=team.save_object(db,1,{"title":"Квартира на Лесной","address":"Лесная, 10","client_id":self.client})["id"]
        for uid,role in ((2,"member"),(3,"admin")):
            invite=team.invite(db,1,{"email":f"estimate{uid}@example.test","role":role})
            team.invitation_action(db,uid,{"invitation_id":invite["id"]},"accept",1)

    def close(self):
        self.db.close()
        for item in reversed(self.patches):item.stop()

    def data(self,**fields):
        return {"title":"Смета ремонта комнаты","client_id":self.client,"object_id":self.obj,"number":"РМ-2026/07",
                "issued_on":"2026-10-30","valid_until":"2026-11-10","notes":"Работы выполняются по согласованию.","markup_percent":"10","discount_percent":"5",
                "items":[{"title":"Подготовка поверхности","kind":"work","quantity":"2.5","unit":"м²","price_rub":"100.125","cost_rub":"60"},
                         {"title":"Грунтовка","kind":"material","quantity":"3","unit":"л","price_rub":"50.20","cost_rub":"30.10"}],**fields}

    def save(self,**fields):return team.save_estimate(self.db,1,self.data(**fields))["id"]
    def row(self,item):return team.shape_estimate(c._owned(self.db,"commercial_estimates",1,item))

    def test_decimal_preview_save_discount_and_reload_share_one_calculation(self):
        before=self.db.execute("SELECT COUNT(*) n FROM commercial_estimates").fetchone()["n"]
        quote=team.quote_estimate(self.db,1,self.data())["quote"]
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_estimates").fetchone()["n"],before)
        self.assertEqual((quote["subtotal_rub"],quote["markup_rub"],quote["discount_rub"],quote["total_rub"]),("400.93","40.09","22.05","418.97"))
        self.assertEqual(quote["groups"],{"work":"250.33","material":"150.60","other":"0.00"})
        item=self.save();saved=self.row(item)
        for key in ("items","subtotal_rub","markup_rub","discount_rub","total_rub","cost_rub","profit_rub"):
            self.assertEqual(saved[key],quote[key],key)
        team.save_estimate(self.db,1,{**saved,"id":item})
        self.assertEqual(self.row(item)["total_rub"],"418.97")

    def test_zero_price_and_full_discount_are_valid_without_negative_total(self):
        item=self.save(discount_percent="100")
        self.assertEqual(self.row(item)["total_rub"],"0.00")
        self.assertEqual(self.row(item)["profit_rub"],"-240.30")
        zero=self.save(markup_percent="0",items=[{"title":"Бесплатная консультация","quantity":"1","price_rub":"0","cost_rub":"0"}])
        self.assertEqual(self.row(zero)["total_rub"],"0.00")

    def test_invalid_fields_do_not_partially_replace_existing_estimate(self):
        item=self.save();before=dict(c._owned(self.db,"commercial_estimates",1,item))
        cases=[{"discount_percent":"100.01"},{"discount_percent":"NaN"},{"discount_percent":True},{"markup_percent":"1001"},
               {"valid_until":"2026-10-29"},{"issued_on":"2026-02-30"},{"number":"x"*41},{"notes":"x"*4001},
               {"items":[{"title":"Недопустимая строка","kind":"invalid","quantity":"1","price_rub":"10"}]},
               {"items":[{"title":"Недопустимая строка","quantity":"0","price_rub":"10"}]}]
        for fields in cases:
            with self.subTest(fields=fields),self.assertRaises(ValueError):team.save_estimate(self.db,1,self.data(id=item,**fields))
            self.assertEqual(dict(c._owned(self.db,"commercial_estimates",1,item)),before)

    def test_new_metadata_references_are_tenant_scoped(self):
        other=c.save_client(self.db,4,{"name":"Другой клиент"})["id"]
        obj=team.save_object(self.db,4,{"title":"Чужой объект"})["id"]
        for fields in ({"client_id":other},{"object_id":obj}):
            with self.assertRaises(ValueError):self.save(**fields)
        self.assertEqual(self.db.execute("SELECT COUNT(*) n FROM commercial_estimates").fetchone()["n"],0)

    def test_repeat_schema_preserves_all_historical_estimate_values(self):
        item=self.save();before=dict(c._owned(self.db,"commercial_estimates",1,item))
        # A legacy persisted item has no kind and still renders without writes.
        legacy=json.loads(before["items_json"])
        for line in legacy:line.pop("kind",None)
        self.db.execute("UPDATE commercial_estimates SET items_json=? WHERE id=?",(json.dumps(legacy),item))
        before=dict(c._owned(self.db,"commercial_estimates",1,item))
        c.initialize_schema(self.db);c.initialize_schema(self.db)
        self.assertEqual(dict(c._owned(self.db,"commercial_estimates",1,item)),before)
        self.assertEqual(self.row(item)["items"][0]["kind"],"work")

    def test_duplicate_is_independent_draft_and_status_update_preserves_content(self):
        item=self.save(status="approved");before=dict(c._owned(self.db,"commercial_estimates",1,item))
        duplicate=team.duplicate_estimate(self.db,3,{"id":item},1)["id"]
        row=self.row(duplicate)
        self.assertNotEqual(duplicate,item);self.assertEqual(row["status"],"draft");self.assertEqual(row["number"],"")
        self.assertEqual(row["issued_on"],"");self.assertEqual(row["valid_until"],"")
        self.assertEqual(row["total_rub"],self.row(item)["total_rub"])
        team.estimate_status(self.db,3,{"id":duplicate,"status":"completed"},1)
        self.assertEqual(self.row(duplicate)["items"],self.row(item)["items"])
        self.assertEqual(dict(c._owned(self.db,"commercial_estimates",1,item)),before)

    def test_delete_requires_confirmation_and_manage_permission(self):
        item=self.save()
        with self.assertRaises(ValueError):team.delete_estimate(self.db,1,{"id":item})
        with self.assertRaises(PermissionError):team.delete_estimate(self.db,2,{"id":item,"confirm":True},1)
        self.assertTrue(team.delete_estimate(self.db,3,{"id":item,"confirm":True},1)["deleted"])
        with self.assertRaises(ValueError):self.row(item)

    def test_quote_and_finance_management_cannot_be_used_by_regular_member(self):
        item=self.save()
        for action,payload in ((team.quote_estimate,self.data()),(team.save_estimate,self.data()),(team.duplicate_estimate,{"id":item}),
                               (team.estimate_status,{"id":item,"status":"approved"})):
            with self.subTest(action=action.__name__),self.assertRaises(PermissionError):action(self.db,2,payload,1)

    def test_client_xlsx_has_numeric_cells_formulas_cached_totals_and_no_private_finance(self):
        item=self.save();result=team.export_estimate(self.db,2,item,1,"xlsx","client")
        self.assertTrue(result["filename"].endswith(".xlsx"));self.assertNotIn("/",result["filename"])
        self.assertIn("spreadsheetml",result["content_type"]);self.assertTrue(result["body"].startswith(b"PK"))
        texts,sheets,book=workbook(result["body"])
        self.assertEqual(len(sheets),1)
        combined=" ".join(texts)
        for private in ("PRIVATE-CLIENT-CONTACT","PRIVATE-CLIENT-NOTES","Себестоимость","прибыль"):
            self.assertNotIn(private,combined)
        self.assertIn("Клиент Ирина",combined);self.assertIn("Квартира на Лесной · Лесная, 10",combined)
        main=sheets[0];self.assertEqual(value(main,"E10"),"2.5");self.assertEqual(value(main,"F10"),"100.13")
        self.assertEqual(formula(main,"G10"),"ROUND(E10*F10,2)");self.assertEqual(value(main,"G10"),"250.33")
        self.assertEqual(formula(main,"G18"),"G13+G15-G17");self.assertEqual(Decimal(value(main,"G18")),Decimal("418.97"))
        self.assertEqual(cells(main)["F5"].get("t"),None,"Issue date is a native numeric Excel date")
        self.assertIsNotNone(main.find("s:sheetViews/s:sheetView/s:pane",NS));self.assertIsNotNone(main.find("s:autoFilter",NS))
        self.assertIn("_xlnm.Print_Area",ET.tostring(book,encoding="unicode"))

    def test_internal_workbook_links_inputs_and_calculates_cost_and_profit(self):
        item=self.save();result=team.export_estimate(self.db,3,item,1,"xlsx","internal")
        texts,sheets,_=workbook(result["body"]);self.assertEqual(len(sheets),2)
        internal=sheets[1]
        self.assertEqual(formula(internal,"C10"),"'Смета'!E10");self.assertEqual(formula(internal,"D10"),"'Смета'!F10")
        self.assertEqual(formula(internal,"F10"),"ROUND(C10*E10,2)")
        self.assertEqual(formula(internal,"G13"),"'Смета'!G18")
        self.assertEqual(formula(internal,"G14"),"SUM(F10:F11)")
        self.assertEqual(formula(internal,"G15"),"G13-G14")
        self.assertEqual(Decimal(value(internal,"G15")),Decimal("178.67"))
        self.assertNotIn("PRIVATE-CLIENT-NOTES"," ".join(texts))

    def test_all_user_text_remains_text_and_never_creates_links_or_formulas(self):
        item=self.save(title='=HYPERLINK("https://example.test","open")',notes="@malicious text",number="+1+1",
                       items=[{"title":"=2+2","quantity":"1","price_rub":"10","unit":"@unit"}])
        result=team.export_estimate(self.db,1,item,1,"xlsx")
        texts,sheets,_=workbook(result["body"])
        self.assertIn("=2+2",texts);self.assertIn("+1+1",texts);self.assertIn("@malicious text",texts)
        sheet=sheets[0]
        self.assertEqual(cells(sheet)["B10"].get("t"),"s")
        self.assertIsNone(sheet.find("s:hyperlinks",NS))
        for node in sheet.findall(".//s:f",NS):self.assertNotIn("HYPERLINK",node.text)

    def test_pdf_is_real_embedded_cyrillic_document_and_handles_long_multipage_estimate(self):
        lines=[{"title":"Длинное описание отделочных работ и материалов "+str(i)+" "+"я"*100,"quantity":"1234.5678","price_rub":"123.45","cost_rub":"50.20","kind":"material"} for i in range(100)]
        item=self.save(items=lines,notes="Подробное описание условий.\n"+"Длинная фраза для проверки переноса. "*90)
        result=team.export_estimate(self.db,1,item,1,"pdf")
        self.assertEqual(result["content_type"],"application/pdf");self.assertTrue(result["body"].startswith(b"%PDF-"))
        self.assertTrue(result["body"].rstrip().endswith(b"%%EOF"));self.assertIn(b"/ToUnicode",result["body"])
        self.assertGreaterEqual(len(re.findall(rb"/Type\s*/Page\b",result["body"])),3)
        self.assertNotIn(b"PRIVATE-CLIENT",result["body"])

    def test_export_tenant_role_membership_and_expired_subscription_guards(self):
        item=self.save()
        with self.assertRaises(PermissionError):team.export_estimate(self.db,2,item,1,"xlsx","internal")
        with self.assertRaises(PermissionError):team.export_estimate(self.db,4,item,1,"pdf")
        with self.assertRaises(ValueError):team.export_estimate(self.db,4,item,4,"pdf")
        for kind,audience in (("csv","client"),("pdf","public")):
            with self.assertRaises(ValueError):team.export_estimate(self.db,1,item,1,kind,audience)
        team.member_action(self.db,1,{"user_id":2},"remove",1)
        with self.assertRaises(PermissionError):team.export_estimate(self.db,2,item,1,"pdf")
        self.db.execute("UPDATE commercial_profiles SET trial_until='2000-01-01T00:00:00+00:00' WHERE user_id=1")
        with self.assertRaises(ValueError):team.export_estimate(self.db,1,item,1,"pdf")
        self.assertEqual(self.row(item)["total_rub"],"418.97")

    def test_parallel_pdf_documents_do_not_share_dynamic_font_subsets(self):
        from hpoint import estimate_exports
        item=self.save()
        document={**self.row(item),"organization_title":"Synthetic PDF organisation","audience":"client"}
        with ThreadPoolExecutor(max_workers=4) as pool:
            bodies=list(pool.map(lambda index:estimate_exports.pdf({**document,"title":"Concurrent estimate "+str(index)}),range(4)))
        self.assertEqual(len(set(bodies)),4)
        for body in bodies:
            self.assertTrue(body.startswith(b"%PDF-"));self.assertTrue(body.rstrip().endswith(b"%%EOF"));self.assertIn(b"/ToUnicode",body)


class SQLiteEstimates(EstimateCases,unittest.TestCase):
    def setUp(self):
        connection=sqlite3.connect(":memory:",isolation_level=None);connection.row_factory=sqlite3.Row;connection.execute("PRAGMA foreign_keys=ON")
        self.prepare(connection)
    def tearDown(self):self.close()


@unittest.skipUnless(os.environ.get("HPOINT_TEST_DATABASE_URL"),"requires isolated PostgreSQL test database")
class PostgreSQLEstimates(EstimateCases,unittest.TestCase):
    def setUp(self):
        from test_postgres import IsolatedPostgres
        self.schema="estimate_qa_"+uuid.uuid4().hex;url=os.environ["HPOINT_TEST_DATABASE_URL"]
        self.control=database.PostgresConnection(url);self.control.execute('CREATE SCHEMA "'+self.schema+'"')
        self.prepare(IsolatedPostgres(url,self.schema))
    def tearDown(self):
        self.close();self.control.execute('DROP SCHEMA "'+self.schema+'" CASCADE');self.control.close()


if __name__=="__main__":unittest.main()
