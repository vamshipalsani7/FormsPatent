"""Tests for IPO Form Filler.  Run:  python -m unittest discover -s tests"""

import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
import xml.dom.minidom
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from ipoforms import catalog  # noqa: E402
from ipoforms.docx_writer import build_docx  # noqa: E402
from ipoforms.prefill import build_form  # noqa: E402
from ipoforms.store import ClientStore, clean_client  # noqa: E402

ADDR = dict(house_no="12", street="MG Road", city="Bengaluru", state="Karnataka",
            pin_code="560001", country="India")
SAMPLE = dict(
    client_type="organisation", applicant_category="startup",
    applicants=[dict(name="Acme Innovations Pvt Ltd", nationality="Indian",
                     country_of_residence="India", address=ADDR, email="ip@acme.in", mobile="+91 98765 43210")],
    projects=[
        dict(name="Irrigation", invention_title="Smart irrigation controller",
             application_number="202441012345", filing_date="2024-02-20",
             application_type=["ordinary"],
             inventors=[dict(name="Ravi Kumar", nationality="Indian", gender="male", address=ADDR),
                        dict(name="Asha Rao", nationality="Indian", address=ADDR)]),
        dict(name="Drone", invention_title="Crop-spraying drone nozzle",
             application_number="202541099999", inventors=[dict(name="Kiran Das")]),
    ],
    agent=dict(name="S. Mehta", inpa_number="IN/PA-1234",
               address=dict(house_no="7", street="Camac Street", city="Kolkata", state="West Bengal",
                            pin_code="700016", country="India")),
    service=dict(name="Mehta IP", address=dict(house_no="5", street="Park Street", city="Kolkata",
                                                state="West Bengal", pin_code="700016", country="India")),
    signatory=dict(name="S. Mehta", designation="Patent Agent"),
    patent_office="chennai",
)


def rows(model):
    out = {}
    for s in model["sections"]:
        for b in s["blocks"]:
            for r in b.get("rows", []) if b["type"] == "fields" else []:
                out.setdefault((s["id"], r["label"]), []).append(r)
    return out


class CatalogTests(unittest.TestCase):
    def test_all_current_forms_present_in_order(self):
        numbers = [f["number"] for f in catalog.list_forms()]
        expected = [str(n) for n in range(1, 32)]
        for extra, after in (("7A", "7"), ("8A", "8"), ("18A", "18")):
            expected.insert(expected.index(after) + 1, extra)
        self.assertEqual(numbers, expected)

    def test_every_form_has_official_pdf(self):
        self.assertTrue(all(f["official_pdf"] for f in catalog.list_forms()))


class PrefillTests(unittest.TestCase):
    def setUp(self):
        self.client = clean_client(SAMPLE)

    def model(self, form_id, project_index=0):
        project = self.client["projects"][project_index] if project_index is not None else None
        return build_form(catalog.get_definition(form_id), self.client, project)

    def test_form1_core_fields(self):
        r = rows(self.model("form_01"))
        self.assertEqual(r[("applicants", "Name in Full")][0]["value"], "Acme Innovations Pvt Ltd")
        self.assertEqual(r[("title_of_invention", "Title of the invention")][0]["value"],
                         "Smart irrigation controller")
        self.assertEqual(len(r[("inventors", "Name in Full")]), 2)
        self.assertEqual(r[("addressee", "at (Patent Office)")][0]["value"], "Chennai")
        cat = r[("category_of_applicant", "Category of applicant")][0]
        self.assertEqual({o["label"] for o in cat["options"] if o["selected"]},
                         {"Other than Natural Person", "Startup"})

    def test_second_project_uses_its_own_invention_and_inventors(self):
        r = rows(self.model("form_01", 1))
        self.assertEqual(r[("title_of_invention", "Title of the invention")][0]["value"],
                         "Crop-spraying drone nozzle")
        self.assertEqual([x["value"] for x in r[("inventors", "Name in Full")]], ["Kiran Das"])

    def test_without_project_only_client_details_fill(self):
        r = rows(self.model("form_01", None))
        self.assertEqual(r[("title_of_invention", "Title of the invention")][0]["value"], "")
        self.assertEqual(r[("applicants", "Name in Full")][0]["value"], "Acme Innovations Pvt Ltd")

    def test_projects_get_ids_and_old_format_converts(self):
        self.assertTrue(all(p["id"].startswith("p_") for p in self.client["projects"]))
        old = dict(SAMPLE, project=dict(invention_title="Old one"), inventors=[dict(name="X")])
        del old["projects"]
        converted = clean_client(old)
        self.assertEqual(len(converted["projects"]), 1)
        self.assertEqual(converted["projects"][0]["invention_title"], "Old one")
        self.assertEqual(converted["projects"][0]["inventors"][0]["name"], "X")

    def test_service_and_agent_addresses(self):
        r = rows(self.model("form_01"))
        self.assertEqual(r[("address_for_service", "Postal Address")][0]["value"],
                         "5, Park Street\nKolkata, West Bengal - 700016\nIndia")
        r = rows(self.model("form_26"))
        auth = r[("authorised_person", "Name, address and nationality of the authorised person(s)")][0]
        self.assertIn("Camac Street", auth["value"])

    def test_old_free_text_service_address_converts(self):
        c = clean_client(dict(service=dict(postal_address="5 Park St\nKolkata 700016")))
        self.assertEqual(c["service"]["address"]["street"], "5 Park St, Kolkata 700016")
        self.assertNotIn("postal_address", c["service"])

    def test_pasted_control_characters_never_break_the_docx(self):
        c = clean_client({"applicants": [{"name": "A & B", "kind": "organisation"}],
                          "projects": [{"invention_title": "Line one\x0bline two\x0cend\x01"}]})
        self.assertNotRegex(c["projects"][0]["invention_title"], "[\x00-\x08\x0b\x0c]")
        for model_client in (c, dict(c, projects=[dict(c["projects"][0], invention_title="raw\x0btab")])):
            data = build_docx(build_form(catalog.get_definition("form_01"), model_client, model_client["projects"][0]))
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml.dom.minidom.parseString(z.read("word/document.xml"))

    def test_review_fixes_in_form_filling(self):
        two_inv = clean_client(dict(SAMPLE))          # 1 applicant, 2 inventors (project 0)
        r = rows(build_form(catalog.get_definition("form_05"), two_inv, two_inv["projects"][0]))
        self.assertEqual(r[("additional_inventor_statement", "Name of the additional inventor")][0]["value"], "")
        r = rows(build_form(catalog.get_definition("form_18"), two_inv, two_inv["projects"][0]))
        self.assertEqual(r[("interested_person_request", "Application no.")][0]["value"], "")
        self.assertEqual(r[("applicant_request", "Application for patent no.")][0]["value"], "202441012345")
        r = rows(build_form(catalog.get_definition("form_07a"), two_inv, two_inv["projects"][0]))
        self.assertEqual(r[("application", "Made by (applicant)")][0]["value"], "")
        r = rows(build_form(catalog.get_definition("form_08"), two_inv, two_inv["projects"][0]))
        self.assertEqual(r[("declaration", "Person to be mentioned / not to be mentioned as inventor")][0]["value"], "")
        r = rows(build_form(catalog.get_definition("form_08"), two_inv, two_inv["projects"][1]))   # 1 inventor
        self.assertEqual(r[("declaration", "Person to be mentioned / not to be mentioned as inventor")][0]["value"], "Kiran Das")
        r = rows(build_form(catalog.get_definition("form_03"), two_inv, two_inv["projects"][0]))
        self.assertEqual(r[("foreign_filings", "Name(s) of joint applicant(s)")][0]["value"], "")

        two_apps = clean_client(dict(SAMPLE, applicants=SAMPLE["applicants"] + [
            dict(name="Asha Rao", nationality="India", address=dict(ADDR, city="Mysuru"))]))
        r = rows(build_form(catalog.get_definition("form_18"), two_apps, two_apps["projects"][0]))
        self.assertEqual(r[("requester", "NAME")][0]["value"], "1. Acme Innovations Pvt Ltd\n2. Asha Rao")
        self.assertTrue(r[("requester", "ADDRESS")][0]["value"].startswith("1. 12, MG Road, Bengaluru"))
        self.assertIn("\n2. 12, MG Road, Mysuru", r[("requester", "ADDRESS")][0]["value"])
        r = rows(build_form(catalog.get_definition("form_30"), two_apps, two_apps["projects"][0]))
        self.assertEqual(r[("address", "City")][0]["value"], "")   # whose address? left for the user

    def test_project_with_only_application_type_is_kept(self):
        c = clean_client({"projects": [{"application_type": ["ordinary"]}]})
        self.assertEqual(len(c["projects"]), 1)

    def test_matter_specific_fields_stay_blank(self):
        r = rows(self.model("form_01"))
        self.assertEqual(r[("fee", "Total fee (₹)")][0]["value"], "")
        self.assertEqual(r[("pct_particulars", "International application number")][0]["value"], "")

    def test_singular_applicant_picks_i(self):
        r = rows(self.model("form_26"))
        iwe = r[("authorising_party", "I/We")][0]
        self.assertEqual([o["label"] for o in iwe["options"] if o["selected"]], ["I"])

    def test_opposition_does_not_use_clients_own_patent(self):
        r = rows(self.model("form_07"))
        self.assertEqual(r[("patent", "Application No.")][0]["value"], "")
        self.assertIn("Acme", r[("opponent", "Names, address and nationality of the opponent(s)")][0]["value"])

    def test_every_form_builds_valid_docx(self):
        for f in catalog.list_forms():
            data = build_docx(self.model(f["id"]))
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for name in z.namelist():
                    xml.dom.minidom.parseString(z.read(name))


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.STORE = ClientStore(Path(cls.tmp.name) / "clients.json")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.tmp.cleanup()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                return res.status, res.read(), res.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def test_client_lifecycle_and_download(self):
        status, body, _ = self.call("POST", "/api/clients", SAMPLE)
        self.assertEqual(status, 201)
        cid = json.loads(body)["id"]

        saved = json.loads(body)
        projects = saved["projects"]
        projects[0]["patent_number"] = "512345"
        status, body, _ = self.call("PUT", f"/api/clients/{cid}", dict(saved, projects=projects))
        after = json.loads(body)["projects"]
        self.assertEqual(after[0]["patent_number"], "512345")
        self.assertEqual([p["id"] for p in after], [p["id"] for p in projects])  # ids stable

        pid = after[1]["id"]
        status, body, _ = self.call("GET", f"/api/clients/{cid}/forms/form_01?project={pid}")
        r = rows(json.loads(body))
        self.assertEqual(r[("title_of_invention", "Title of the invention")][0]["value"],
                         "Crop-spraying drone nozzle")

        status, body, headers = self.call("GET", f"/api/clients/{cid}/forms/form_18a.docx?project={pid}")
        self.assertEqual(status, 200)
        self.assertIn("Form 18A - Acme Innovations Pvt Ltd - Drone", headers["Content-Disposition"])
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(body)))
        self.assertEqual(self.call("GET", f"/api/clients/{cid}/forms/form_01?project=p_000000")[0], 404)

        self.assertEqual(self.call("DELETE", f"/api/clients/{cid}")[0], 200)
        self.assertEqual(self.call("GET", f"/api/clients/{cid}")[0], 404)

    def test_no_field_is_mandatory(self):
        status, body, _ = self.call("POST", "/api/clients", {})
        self.assertEqual(status, 201)
        status, body, _ = self.call("POST", "/api/clients",
                                    {"applicants": [{"address": {"pin_code": "560001"}}]})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body)["applicants"][0]["address"]["pin_code"], "560001")

    def test_invalid_email_rejected_blank_allowed(self):
        status, body, _ = self.call("POST", "/api/clients",
                                    {"applicants": [{"name": "A", "email": "a@b"}],
                                     "agent": {"email": "agent at mail.com"}})
        self.assertEqual(status, 400)
        self.assertIn("Applicant 1", json.loads(body)["error"])
        self.assertIn("Patent agent", json.loads(body)["error"])
        status, _, _ = self.call("POST", "/api/clients",
                                 {"applicants": [{"name": "A", "email": "a.b@firm.co.in"}]})
        self.assertEqual(status, 201)

    def test_phone_rules(self):
        from ipoforms.store import phone_problem
        ok = [("+91 98765 43210", True), ("+91 080 2345 6789", False), ("+91 8023456789", False),
              ("+91 +91 98765 43210", True), ("+1 416 555 0100", True), ("+44 7700 900123", True), ("", True)]
        bad = [("+91 98765", True), ("+91 12345 67890", True), ("+91 98765 432101", True),
               ("+1 555 0100", True), ("+44 12", True)]
        for v, mobile in ok:
            self.assertEqual(phone_problem(v, mobile), "", v)
        for v, mobile in bad:
            self.assertNotEqual(phone_problem(v, mobile), "", v)

    def test_invalid_phone_rejected(self):
        status, body, _ = self.call("POST", "/api/clients", {"agent": {"mobile": "+91 98765"}})
        self.assertEqual(status, 400)
        self.assertIn("Patent agent mobile needs 10 digits", json.loads(body)["error"])

    def test_postcode_format_rules(self):
        from ipoforms.postcode_format import problem
        for country, code in [("India", "560001"), ("United States", "90210-1234"), ("United Kingdom", "SW1A 1AA"),
                              ("Canada", "K1A 0B1"), ("Japan", "100-0001"), ("Narnia", "AB-12"), ("India", "")]:
            self.assertEqual(problem(country, code), "", (country, code))
        for country, code in [("India", "56001"), ("India", "060001"), ("India", "56000A"),
                              ("United States", "9021"), ("United Kingdom", "12345"), ("Germany", "1011")]:
            self.assertNotEqual(problem(country, code), "", (country, code))

    def test_invalid_pin_rejected(self):
        status, body, _ = self.call("POST", "/api/clients",
                                    {"service": {"address": {"country": "India", "pin_code": "56001"}}})
        self.assertEqual(status, 400)
        self.assertIn("Address for service PIN / postal code", json.loads(body)["error"])

    def test_number_and_text_rules(self):
        from ipoforms import validation as V
        for v in ("202441012345", "IN 2023 3101 2345", "1234/DEL/2006", "567/chenp/2008", ""):
            self.assertEqual(V.appno_problem(v), "", v)
        for v in ("20244101234", "202451012345", "199941012345", "abc", "1234/BLR/2006"):
            self.assertNotEqual(V.appno_problem(v), "", v)
        self.assertEqual(V.tidy_appno("IN 2024-4101-2345"), "202441012345")
        self.assertEqual(V.tidy_patentno("IN 512,345"), "512345")
        self.assertNotEqual(V.patentno_problem("12345678"), "")
        self.assertEqual(V.tidy_inpa("in/pa 1234"), "IN/PA-1234")
        self.assertEqual(V.tidy_inpa("1234"), "IN/PA-1234")
        self.assertNotEqual(V.inpa_problem("PA1234X"), "")
        self.assertNotEqual(V.date_problem("2999-01-01"), "")
        self.assertNotEqual(V.person_name_problem("Ravi 2"), "")
        self.assertNotEqual(V.person_name_problem("Ravi@Kumar"), "")
        self.assertEqual(V.person_name_problem("D'Souza-Rao Jr."), "")
        self.assertEqual(V.org_name_problem("3M India (R&D) Pvt. Ltd."), "")
        self.assertNotEqual(V.place_problem("Bengaluru 1"), "")
        self.assertEqual(V.country_problem("India"), "")
        self.assertNotEqual(V.country_problem("Narnia"), "")
        self.assertEqual(clean_client({"applicants": [{"name": "A", "nationality": "Indian"}]})
                         ["applicants"][0]["nationality"], "India")

    def test_invalid_fields_rejected_with_reasons(self):
        status, body, _ = self.call("POST", "/api/clients", {
            "applicants": [{"name": "Acme", "nationality": "Narnia"}],
            "projects": [{"application_number": "2024", "filing_date": "2024-05-01", "grant_date": "2023-01-01"}],
            "agent": {"name": "Agent 007", "inpa_number": "abc"},
            "patent_office": "pune",
        })
        self.assertEqual(status, 400)
        err = json.loads(body)["error"]
        for bit in ("Applicant 1 nationality", "Project 1 application no.", "grant date is before",
                    "Patent agent name", "IN/PA", "Patent office"):
            self.assertIn(bit, err)

    def test_age_and_gender_rules(self):
        from ipoforms import validation as V
        for v in ("34", "1", "120", ""):
            self.assertEqual(V.age_problem(v), "", v)
        for v in ("0", "121", "3.5", "abc", "-4"):
            self.assertNotEqual(V.age_problem(v), "", v)
        # a company applicant can't carry gender/age; an individual applicant's name can't have digits
        status, body, _ = self.call("POST", "/api/clients", {
            "applicants": [{"kind": "organisation", "name": "Acme Ltd", "gender": "male", "age": "40"},
                           {"kind": "individual", "name": "Ravi 2", "gender": "robot", "age": "200"}],
            "projects": [{"name": "X", "inventors": [{"name": "Asha", "age": "0"}]}],
        })
        self.assertEqual(status, 400)
        err = json.loads(body)["error"]
        for bit in ("Applicant 1 is an organisation", "Applicant 2 name", "Applicant 2 gender",
                    "Applicant 2 age", "Project 1, inventor 1 age"):
            self.assertIn(bit, err)

    def test_age_and_gender_fill_form1_for_individuals_only(self):
        c = clean_client({
            "applicants": [{"kind": "individual", "name": "Ravi Kumar", "gender": "male", "age": "41"},
                           {"kind": "organisation", "name": "Acme Ltd"}],
            "projects": [{"name": "X", "inventors": [{"name": "Asha Rao", "gender": "female", "age": "29"}]}],
        })
        r = rows(build_form(catalog.get_definition("form_01"), c, c["projects"][0]))
        ages = [x["value"] for x in r[("applicants", "Age (optional, for natural persons)")]]
        self.assertEqual(ages, ["41", ""])
        genders = [[o["label"] for o in x["options"] if o["selected"]]
                   for x in r[("applicants", "Gender (optional, for individuals)")]]
        self.assertEqual(genders, [["Male"], []])
        self.assertEqual(r[("inventors", "Age (optional, for natural persons)")][0]["value"], "29")
        self.assertEqual(c["projects"][0]["inventors"][0]["kind"], "individual")

    # ---- regressions from the bug review -------------------------------------
    def test_conflicting_save_from_stale_copy_is_refused(self):
        status, body, _ = self.call("POST", "/api/clients", {"applicants": [{"name": "Acme Ltd", "kind": "organisation"}]})
        first = json.loads(body)
        status, body, _ = self.call("PUT", f"/api/clients/{first['id']}", first)        # tab A saves
        self.assertEqual(status, 200)
        status, body, _ = self.call("PUT", f"/api/clients/{first['id']}", first)        # tab B, stale copy
        self.assertEqual(status, 409)
        self.assertIn("changed elsewhere", json.loads(body)["error"])

    def test_damaged_data_file_gives_a_clear_error(self):
        self.call("POST", "/api/clients", {"applicants": [{"name": "A"}]})
        self.call("POST", "/api/clients", {"applicants": [{"name": "B"}]})   # second write makes a backup
        store = server.STORE
        self.assertTrue(store.backup_path.exists())
        good = store.path.read_text(encoding="utf-8")
        store.path.write_text("{ broken", encoding="utf-8")
        try:
            status, body, _ = self.call("GET", "/api/clients")
            self.assertEqual(status, 500)
            self.assertIn("damaged", json.loads(body)["error"])
            self.assertIn("clients.backup.json", json.loads(body)["error"])
        finally:
            store.path.write_text(good, encoding="utf-8")

    def test_city_may_contain_numbers_state_may_not(self):
        ok = {"applicants": [{"name": "A", "address": {"country": "India", "city": "North 24 Parganas",
                                                       "state": "West Bengal", "pin_code": "700124"}}]}
        self.assertEqual(self.call("POST", "/api/clients", ok)[0], 201)
        bad = {"applicants": [{"name": "A", "address": {"state": "Bengal 2"}}]}
        self.assertEqual(self.call("POST", "/api/clients", bad)[0], 400)

    def test_blank_country_uses_no_country_format(self):
        c = {"applicants": [{"name": "A", "address": {"country": "", "pin_code": "AB12"}}]}
        self.assertEqual(self.call("POST", "/api/clients", c)[0], 201)

    def test_blank_word_and_pdf_downloads(self):
        for f in catalog.list_forms():
            status, body, headers = self.call("GET", f"/api/forms/{f['id']}/blank.docx")
            self.assertEqual(status, 200, f["id"])
            self.assertIn(f"Form {f['number']} - blank.docx", headers["Content-Disposition"])
            with zipfile.ZipFile(io.BytesIO(body)) as z:
                xml.dom.minidom.parseString(z.read("word/document.xml"))
            model = build_form(catalog.get_definition(f["id"]), clean_client({}))
            self.assertEqual(model["stats"]["prefilled"], 0, f["id"])
        self.assertEqual(self.call("GET", "/api/forms/form_99/blank.docx")[0], 404)
        status, body, headers = self.call("GET", "/official/Form_10.PDF?download=1")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("Form 10 - official blank.pdf", headers["Content-Disposition"])
        status, _, headers = self.call("GET", "/official/Form_10.PDF")   # view: opens in the browser
        self.assertIsNone(headers.get("Content-Disposition"))

    def test_postcode_rejects_malformed(self):
        self.assertEqual(self.call("GET", "/api/postcode/IN/12")[0], 400)

    def test_static_paths_cannot_escape(self):
        self.assertEqual(self.call("GET", "/official/..%2F..%2Fserver.py")[0], 404)
        self.assertEqual(self.call("GET", "/api/clients/c_00000000/forms/form_99")[0], 404)


if __name__ == "__main__":
    unittest.main()
