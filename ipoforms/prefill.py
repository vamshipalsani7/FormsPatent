"""Turn (form definition + client profile) into a pre-filled form layout.

The output is a neutral "render model" (sections -> blocks -> rows) that both
the browser preview and the Word (.docx) writer draw from, so what the user sees
on screen is exactly what they download.

Only details stored on the client profile are filled in. Everything
matter-specific (grounds, reasons, fees, dates of signing, ...) is left blank
for the user to complete in the downloaded document.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

ADDRESS_PARTS = ("house_no", "street", "city", "state", "pin_code", "country")
INPUT_KINDS = {"text", "textarea", "date", "number", "dropdown", "radio",
               "checkbox", "checkboxGroup", "strikeoutChoice"}
CHOICE_KINDS = {"dropdown", "radio", "checkbox", "checkboxGroup", "strikeoutChoice"}
# Strike-out pairs printed as "singular / plural" on the forms.
PLURAL_CHOICES = {"iwe", "my_our", "me_us", "am_are", "is_are", "has_have", "i_am_we_are"}
# Particulars of *other* applications (PCT, parent, main patent) are not the
# client's own application and must not be filled from the profile.
EXCLUDED_SECTIONS = {"divisional_particulars", "patent_of_addition_particulars",
                     "pct_particulars", "convention_particulars",
                     # Form 18 s.3 is for a person *other* than the applicant.
                     "interested_person_request",
                     # Form 5: inventors added later sign here - not the known ones.
                     "additional_inventor_statement"}
# Fields that look like the client but are about someone else.
EXCLUDED_FIELDS = {"joint_applicants"}   # Form 3: others the client filed jointly with abroad
SIGNATORY_SECTIONS = {"signatory", "date_and_signature", "final_declaration"}
# Forms filed *against* someone else's patent (opposition, compulsory licence,
# revocation). The client is the opponent / requester here, so the patent being
# acted on is not the client's own and is never filled from the profile.
ADVERSE_FORMS = {"form_07", "form_07a", "form_14", "form_17", "form_19"}
OWN_MATTER_KEYS = ("application.", "patent.", "patentee.", "invention.")
# In those forms the client appears only in these sections (as the opponent,
# representor, or applicant for the licence / revocation).
CLIENT_PARTY_SECTIONS = {"opponent", "representor", "applicant", "evidence",
                         "address_for_service", "declaration_and_service"}
PARTY_PARTICULARS = {"opponent_particulars", "representor_particulars"}

CATEGORY_LABELS = {
    "natural_person": ["natural person"],
    "startup": ["other than natural person", "startup"],
    "small_entity": ["other than natural person", "small entity"],
    "educational_institution": ["other than natural person", "educational institution"],
    "other": ["other than natural person", "others"],
}
CATEGORY_KEYWORDS = {  # Form 28 / Form 18A wording
    "startup": "a startup", "small_entity": "small entity",
    "educational_institution": "educational institution",
}


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def fmt_date(iso: str) -> str:
    if iso and len(iso) == 10 and iso[4] == "-" and iso[7] == "-":
        return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"
    return iso or ""


def fmt_address(addr: dict | None) -> str:
    a = addr or {}
    city_line = a.get("city", "")
    if a.get("state"):
        city_line = f"{city_line}, {a['state']}" if city_line else a["state"]
    if a.get("pin_code"):
        city_line = f"{city_line} - {a['pin_code']}" if city_line else a["pin_code"]
    parts = [a.get("house_no", ""), a.get("street", ""), city_line, a.get("country", "")]
    return ", ".join(p for p in parts if p)


def person_particulars(p: dict) -> str:
    bits = [p["name"]] if p.get("name") else []
    if p.get("nationality"):
        bits.append(f"Nationality: {p['nationality']}")
    addr = fmt_address(p.get("address"))
    if addr:
        bits.append(f"Address: {addr}")
    return ", ".join(bits)


def names(people: list[dict], sep: str) -> str:
    return sep.join(p["name"] for p in people if p.get("name"))


def _numbered(people: list[dict], value) -> str:
    """'1. A' / '2. B' on separate lines so Name / Nationality / Address line up."""
    return "\n".join(f"{i}. {value(p)}" for i, p in enumerate(people, 1) if value(p))


# --------------------------------------------------------------------------
# Value resolution
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Ctx:
    form_id: str
    section_id: str
    item: dict | None = None        # the person/agent a group instance is about
    item_kind: str | None = None    # 'person' | 'agent'
    in_address: bool = False        # inside an address sub-block of `item`
    in_signature: bool = False      # inside a signature block
    numbered: bool = False          # section lists all applicants in single fields


def _key(field: dict) -> str:
    srcs = (field.get("autofill") or {}).get("sources") or []
    return (srcs[0].get("key") or "") if srcs else ""


def _child_keys(field: dict) -> set[str]:
    keys = set()
    for child in field.get("fields") or []:
        k = _key(child)
        if k:
            keys.add(k)
        keys |= _child_keys(child)
    return keys


def _signatory(c: dict) -> str:
    return (c["signatory"].get("name") or c["agent"].get("name")
            or (c["applicants"][0]["name"] if c["applicants"] else ""))


def fmt_address_lines(addr: dict | None) -> str:
    """Postal layout: building/street, city/state/PIN, country on separate lines."""
    a = addr or {}
    first = ", ".join(x for x in (a.get("house_no", ""), a.get("street", "")) if x)
    city = ", ".join(x for x in (a.get("city", ""), a.get("state", "")) if x)
    if a.get("pin_code"):
        city = f"{city} - {a['pin_code']}" if city else a["pin_code"]
    return "\n".join(x for x in (first, city, a.get("country", "")) if x)


def _has_address(addr: dict | None) -> bool:
    return any(v for k, v in (addr or {}).items() if k != "country")


def _service_postal(c: dict) -> str:
    addr = c["service"].get("address")
    return fmt_address_lines(addr) if _has_address(addr) else ""


def _service_block(c: dict) -> str:
    s = c["service"]
    lines = [s.get("name", ""), _service_postal(c)]
    contact = []
    if s.get("telephone"):
        contact.append(f"Tel: {s['telephone']}")
    if s.get("mobile"):
        contact.append(f"Mobile: {s['mobile']}")
    if s.get("fax"):
        contact.append(f"Fax: {s['fax']}")
    if s.get("email"):
        contact.append(f"E-mail: {s['email']}")
    if contact:
        lines.append(", ".join(contact))
    return "\n".join(l for l in lines if l)


def _option_values_matching(field: dict, needles: list[str], exact_first=False) -> list[str]:
    out = []
    for opt in field.get("options") or []:
        label = opt["label"].lower()
        for n in needles:
            if (label == n) if (exact_first and n == "natural person") else (n in label):
                out.append(opt["value"])
                break
    return out


def _person_value(fid: str, field: dict, p: dict, in_address: bool):
    addr = p.get("address") or {}
    if fid in ADDRESS_PARTS:
        return addr.get(fid, "")
    if fid in ("contact_number", "mobile_no", "mobile_phone"):
        return p.get("mobile", "")
    if fid == "telephone_no":
        return p.get("telephone", "")
    if fid == "email":
        return p.get("email", "")
    if in_address:
        return None
    if fid in ("name", "signatory_name"):
        return p.get("name", "")
    if fid in ("nationality", "country_of_residence"):
        return p.get(fid, "")
    if fid == "gender":   # natural persons only
        return [p["gender"]] if p.get("gender") and p.get("kind") != "organisation" else []
    if fid == "age":
        return p.get("age", "") if p.get("kind") != "organisation" else ""
    if fid == "address" and field.get("kind") == "textarea":
        return fmt_address(addr)
    return None


def resolve(field: dict, ctx: Ctx, c: dict):
    """Value for one field: str for scalars, list of option values for choices,
    or None when the profile does not supply it."""
    fid, kind, key = field["id"], field.get("kind"), _key(field)
    label = (field.get("label") or "").lower()
    proj, agent, apps, invs = c["project"], c["agent"], c["applicants"], c["inventors"]

    if key.startswith("assignee") or ctx.section_id in EXCLUDED_SECTIONS \
            or fid in EXCLUDED_FIELDS or "pct" in fid or "deemed" in fid:
        return None
    if ctx.form_id in ADVERSE_FORMS and (key.startswith(OWN_MATTER_KEYS) or (
            key.startswith("applicant.") and ctx.section_id not in CLIENT_PARTY_SECTIONS)):
        return None   # the application/patent being opposed belongs to someone else
    if fid in PARTY_PARTICULARS:
        return "\n".join(person_particulars(p) for p in apps)

    # --- inside a group instance about one person / the agent -------------
    if ctx.item_kind == "person" and ctx.item:
        v = _person_value(fid, field, ctx.item, ctx.in_address)
        if v is not None:
            return v
    if ctx.item_kind == "agent" and ctx.item:
        v = {"name": agent.get("name"), "inpa_no": agent.get("inpa_number"),
             "mobile_no": agent.get("mobile")}.get(fid)
        if v is not None:
            return v

    # --- choices -----------------------------------------------------------
    if kind == "dropdown" and fid == "patent_office":
        return [c["patent_office"]] if c["patent_office"] else []
    if kind == "strikeoutChoice" and fid in PLURAL_CHOICES and apps:
        opts = field.get("options") or []
        if len(opts) >= 2:
            return [opts[0 if len(apps) == 1 else 1]["value"]]
    if kind == "checkboxGroup" and fid == "applicant_category":
        needles = CATEGORY_LABELS.get(c["applicant_category"])
        return _option_values_matching(field, needles, exact_first=True) if needles else []
    if kind == "checkboxGroup" and fid == "application_type":
        valid = {o["value"] for o in field.get("options") or []}
        return [t for t in proj.get("application_type", []) if t in valid]
    if fid in ("status_claimed", "ground") and kind in ("radio", "checkboxGroup"):
        kw = CATEGORY_KEYWORDS.get(c["applicant_category"])
        return _option_values_matching(field, [kw]) if kw else []
    if fid == "inventors_same_as_applicants" and apps and invs:
        same = {p["name"].lower() for p in apps} == {p["name"].lower() for p in invs}
        return ["yes" if same else "no"]

    # --- section-specific --------------------------------------------------
    sec = ctx.section_id
    if sec in ("address_for_service", "declaration_and_service"):
        s = c["service"]
        if fid == "address_for_service":
            return _service_block(c)
        v = {"name": s.get("name"), "postal_address": _service_postal(c),
             "email": s.get("email"), "telephone_no": s.get("telephone"),
             "mobile_no": s.get("mobile"), "fax_no": s.get("fax")}.get(fid)
        if v is not None:
            return v
    if fid == "signatory_name" and key != "inventor.name":
        return _signatory(c)
    if sec in SIGNATORY_SECTIONS and fid == "designation":
        return c["signatory"].get("designation", "")
    if fid == "name" and ctx.in_signature and ctx.item_kind is None and not key.startswith("inventor"):
        return _signatory(c)
    if sec == "licensing" and apps:
        if fid == "contact_email":
            return apps[0].get("email", "")
        if fid == "contact_number":
            return apps[0].get("mobile", "")
    if sec == "matter" and proj.get("application_number"):
        text = f"Patent Application No. {proj['application_number']}"
        if proj.get("invention_title"):
            text += f' titled "{proj["invention_title"]}"'
        return text

    # --- generic vocabulary keys -------------------------------------------
    if key in ("applicant.name", "patentee.name"):
        if kind == "textarea" and "address" in label:
            return "\n".join(person_particulars(p) for p in apps)
        if ctx.numbered:
            return _numbered(apps, lambda p: p.get("name", ""))
        return names(apps, "\n" if kind == "textarea" else ", ")
    if key == "applicant.address":
        if ctx.numbered:
            return _numbered(apps, lambda p: fmt_address(p.get("address")))
        return fmt_address(apps[0]["address"]) if apps else ""
    if key == "applicant.nationality":
        if ctx.numbered:
            return _numbered(apps, lambda p: p.get("nationality", ""))
        return ", ".join(dict.fromkeys(p["nationality"] for p in apps if p.get("nationality")))
    if key == "applicant.country":
        return apps[0].get("country_of_residence", "") if apps else ""
    if key == "inventor.name":
        if kind != "textarea" and len(invs) > 1:
            return None   # single-person field (Forms 8, 8A, 12): which inventor is the user's call
        return names(invs, "\n" if kind == "textarea" else ", ")
    if key == "inventor.nationality":
        return ", ".join(dict.fromkeys(p["nationality"] for p in invs if p.get("nationality")))
    if key == "inventor.address":
        return fmt_address(invs[0]["address"]) if invs else ""
    if key == "agent.name":
        if "address" in label and agent.get("name"):
            bits = [agent["name"]]
            if agent.get("inpa_number"):
                bits.append(f"IN/PA No. {agent['inpa_number']}")
            if _has_address(agent.get("address")):
                bits.append(fmt_address(agent["address"]))
            elif _service_postal(c):
                bits.append(_service_postal(c).replace("\n", ", "))
            return ", ".join(bits)
        return agent.get("name", "")
    if key == "signatory.name":
        return _signatory(c)
    if key == "agent.inpaNumber":
        return agent.get("inpa_number", "")
    if key == "application.number":
        return proj.get("application_number", "")
    if key == "application.filingDate":
        return fmt_date(proj.get("filing_date", ""))
    if key == "patent.number":
        return proj.get("patent_number", "")
    if key == "patent.grantDate":
        return fmt_date(proj.get("grant_date", ""))
    if key == "invention.title":
        return proj.get("invention_title", "")
    return None


# --------------------------------------------------------------------------
# Layout assembly
# --------------------------------------------------------------------------

class _Builder:
    def __init__(self, definition: dict, client: dict):
        self.d = definition
        self.c = client
        self.sections: list[dict] = []
        self.blocks: list[dict] = []
        self.filled = 0
        self.blank = 0

    # block helpers
    def text(self, t: str, style: str = "text"):
        self.blocks.append({"type": style, "text": t})

    def row(self, row: dict):
        if not self.blocks or self.blocks[-1]["type"] != "fields":
            self.blocks.append({"type": "fields", "rows": []})
        self.blocks[-1]["rows"].append(row)

    # field emission
    def emit(self, field: dict, ctx: Ctx, office: bool, prefix: str = ""):
        kind = field.get("kind")
        label = prefix + (field.get("label") or field["id"].replace("_", " ").capitalize())

        if kind == "boilerplate":
            self.text(field.get("text", ""))
            return
        if kind in ("group", "signatureBlock"):
            self.emit_group(field, ctx, office, prefix)
            return
        if kind == "table":
            cols = [col.get("label", col["id"]) for col in field.get("columns") or []]
            self.blocks.append({"type": "table", "label": label, "columns": cols,
                                "rows": [["" for _ in cols] for _ in range(3)]})
            return

        value = None if office or field.get("officeUseOnly") else resolve(field, ctx, self.c)
        row = {"label": label, "kind": kind or "text",
               "multiline": kind == "textarea", "office": office}
        if kind in CHOICE_KINDS:
            opts = field.get("options") or [{"value": "yes", "label": field.get("label", "Yes")}]
            if kind == "checkbox":
                opts = [{"value": "yes", "label": "Yes"}]
            selected = set(value or [])
            row["options"] = [{"label": o["label"], "selected": o["value"] in selected}
                              for o in opts]
            row["value"] = ", ".join(o["label"] for o in opts if o["value"] in selected)
        else:
            row["value"] = value or ""
        row["prefilled"] = bool(row["value"])

        if not office and kind in INPUT_KINDS:
            if row["prefilled"]:
                self.filled += 1
            else:
                self.blank += 1
        self.row(row)

    def emit_group(self, field: dict, ctx: Ctx, office: bool, prefix: str):
        rep = field.get("repeatable")
        children = field.get("fields") or []
        if field.get("kind") == "signatureBlock":
            ctx = replace(ctx, in_signature=True)
        if not rep:
            sub_ctx = ctx
            if field["id"] == "address" and ctx.item_kind == "person":
                sub_ctx = replace(ctx, in_address=True)
            sub_prefix = prefix + (field.get("label") or field["id"]) + " - "
            for ch in children:
                self.emit(ch, sub_ctx, office, sub_prefix)
            return

        items, kind = self.group_items(field, ctx)
        item_label = rep.get("itemLabel") or field.get("label") or "Entry"
        for i, item in enumerate(items or [None], start=1):
            self.text(f"{item_label} {i}", "subheading")
            sub_ctx = replace(ctx, item=item, item_kind=kind if item else None, in_address=False)
            for ch in children:
                self.emit(ch, sub_ctx, office, prefix)

    def group_items(self, field: dict, ctx: Ctx):
        keys = _child_keys(field)
        if any(k.startswith("assignee") for k in keys):
            return [], None
        if field["id"] == "agent":
            return ([self.c["agent"]] if self.c["agent"].get("name") else []), "agent"
        if any(k.startswith("inventor") for k in keys) and \
                ctx.section_id in ("inventors", "declaration_inventors"):
            return self.c["inventors"], "person"
        if field["id"] == "applicant" and ctx.section_id == "applicants":
            return self.c["applicants"], "person"
        return [], None

    def build(self) -> dict:
        for sec in self.d["sections"]:
            self.blocks = []
            office = bool(sec.get("officeUseOnly"))
            # Several applicants in one Name / Nationality / Address block (Forms 6,
            # 18, 18A): number them so each line matches across the fields.
            direct_keys = {_key(f) for f in sec.get("fields") or []}
            numbered = len(self.c["applicants"]) > 1 and bool(
                direct_keys & {"applicant.address", "applicant.nationality"})
            ctx = Ctx(self.d["formId"], sec["id"], numbered=numbered)
            # Single-person sections (Form 30 applicant address, Form 8A inventor
            # identity) are filled only when there is exactly one such person.
            if sec["id"] == "address" and len(self.c["applicants"]) == 1:
                ctx = replace(ctx, item=self.c["applicants"][0], item_kind="person", in_address=True)
            if sec["id"] == "identity" and len(self.c["inventors"]) == 1:
                ctx = replace(ctx, item=self.c["inventors"][0], item_kind="person", in_address=True)
            for f in sec.get("fields") or []:
                self.emit(f, ctx, office)
            self.sections.append({"id": sec["id"], "title": sec.get("title", ""),
                                  "office": office, "blocks": self.blocks})
        legal = self.d.get("legalReference") or {}
        act, rules = legal.get("act") or [], legal.get("rules") or []
        see = [x for x in act[1:] + rules[1:] if x]
        return {
            "form": {
                "id": self.d["formId"], "number": self.d["formNumber"],
                "name": self.d["officialName"],
                "act": act[0] if act else "THE PATENTS ACT, 1970 (39 of 1970)",
                "rules": rules[0] if rules else "THE PATENTS RULES, 2003",
                "see": "; ".join(see),
            },
            "sections": self.sections,
            "stats": {"prefilled": self.filled, "blank": self.blank},
        }


def build_form(definition: dict, client: dict, project: dict | None = None) -> dict:
    """Pre-fill one form for a client, using one of the client's projects.

    Without a project, only client-level details (applicants, agent, address for
    service, signatory, patent office) are filled; invention details and
    inventors stay blank.
    """
    view = dict(client)
    view["project"] = project or {"application_type": []}
    view["inventors"] = (project or {}).get("inventors", [])
    return _Builder(definition, view).build()
