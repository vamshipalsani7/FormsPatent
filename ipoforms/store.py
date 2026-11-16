"""Client (user/customer) storage: one JSON file, written atomically."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
from datetime import datetime
from pathlib import Path

from . import postcode_format, validation as V
from .paths import data_dir


class _DefaultPath(os.PathLike):
    """data/clients.json, resolved only when first used (so importing never
    creates folders)."""
    def __fspath__(self) -> str:
        return str(data_dir() / "clients.json")


DEFAULT_PATH = _DefaultPath()
_ID_RE = re.compile(r"^c_[0-9a-f]{8}$")

PERSON_FIELDS = ("name", "gender", "age", "nationality", "country_of_residence",
                 "email", "mobile", "telephone")
PERSON_KINDS = ("individual", "organisation")
ADDRESS_FIELDS = ("house_no", "street", "city", "state", "pin_code", "country")


# Control characters (other than tab and newline) are not allowed in Word
# documents. They arrive by pasting - e.g. a soft line break copied from Word
# is \x0b - and would make the downloaded .docx unopenable.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")


def _s(v) -> str:
    if not isinstance(v, str):
        return ""
    return _CONTROL_RE.sub(" ", v.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _clean_address(a) -> dict:
    a = a if isinstance(a, dict) else {}
    out = {k: _s(a.get(k)) for k in ADDRESS_FIELDS}
    out["country"] = V.tidy_country(out["country"])
    return out


def _clean_person(p, default_kind: str = "individual", force_individual: bool = False) -> dict:
    """An applicant may be an individual or an organisation; inventors are
    always individuals. Age is kept as entered (validated separately)."""
    p = p if isinstance(p, dict) else {}
    out = {k: _s(p.get(k)) if not isinstance(p.get(k), int) else str(p.get(k)) for k in PERSON_FIELDS}
    kind = _s(p.get("kind")) or default_kind
    out["kind"] = "individual" if force_individual else kind
    out["nationality"] = V.tidy_country(out["nationality"])
    out["country_of_residence"] = V.tidy_country(out["country_of_residence"])
    out["address"] = _clean_address(p.get("address"))
    return out


def _clean_section(d, keys) -> dict:
    d = d if isinstance(d, dict) else {}
    return {k: _s(d.get(k)) for k in keys}


PROJECT_FIELDS = ("name", "invention_title", "application_number", "filing_date",
                  "patent_number", "grant_date")
_PROJECT_ID_RE = re.compile(r"^p_[0-9a-f]{6}$")


def _clean_project(raw, used_ids: set) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    project = _clean_section(raw, PROJECT_FIELDS)
    project["application_number"] = V.tidy_appno(project["application_number"])
    project["patent_number"] = V.tidy_patentno(project["patent_number"])
    pid = raw.get("id") if isinstance(raw.get("id"), str) else ""
    if not _PROJECT_ID_RE.match(pid) or pid in used_ids:
        pid = "p_" + secrets.token_hex(3)
        while pid in used_ids:
            pid = "p_" + secrets.token_hex(3)
    used_ids.add(pid)
    types = raw.get("application_type") or []
    project["application_type"] = [t for t in types if isinstance(t, str)]
    inventors = [_clean_person(p, force_individual=True) for p in (raw.get("inventors") or [])
                 if isinstance(p, dict)]
    project["inventors"] = [p for p in inventors if _person_has_data(p)]
    project["id"] = pid
    return project


def _is_empty_project(p: dict) -> bool:
    return not any(p.get(k) for k in PROJECT_FIELDS) and not p["inventors"] and not p["application_type"]


def _clean_agent(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    agent = _clean_section(raw, ("name", "inpa_number", "mobile", "email"))
    agent["inpa_number"] = V.tidy_inpa(agent["inpa_number"])
    agent["address"] = _clean_address(raw.get("address"))
    return agent


def _clean_service(raw) -> dict:
    """Address for service. Older clients stored it as one free-text
    `postal_address`; that text moves into the structured address."""
    raw = raw if isinstance(raw, dict) else {}
    service = _clean_section(raw, ("name", "telephone", "mobile", "fax", "email"))
    address = _clean_address(raw.get("address"))
    legacy = _s(raw.get("postal_address"))
    if legacy and not any(v for k, v in address.items() if k != "country"):
        address["street"] = ", ".join(l.strip() for l in legacy.splitlines() if l.strip())
    service["address"] = address
    return service


def clean_client(raw: dict) -> dict:
    """Keep only known fields, as trimmed strings. Unknown input is dropped.

    A client has any number of projects (inventions); each project carries its
    own inventors. Clients saved before projects existed (one `project` plus
    top-level `inventors`) are converted to a single project.
    """
    raw = raw if isinstance(raw, dict) else {}
    default_kind = "organisation" if _s(raw.get("client_type")) == "organisation" else "individual"
    applicants = [_clean_person(p, default_kind) for p in (raw.get("applicants") or []) if isinstance(p, dict)]
    applicants = [p for p in applicants if _person_has_data(p)]
    raw_projects = raw.get("projects")
    if raw_projects is None and (raw.get("project") or raw.get("inventors")):
        raw_projects = [dict(raw.get("project") or {}, inventors=raw.get("inventors") or [])]
    used: set = set()
    projects = [_clean_project(p, used) for p in (raw_projects or []) if isinstance(p, dict)]
    projects = [p for p in projects if not _is_empty_project(p)]
    return {
        "client_type": _s(raw.get("client_type")) or "individual",
        "applicant_category": _s(raw.get("applicant_category")),
        "applicants": applicants,
        "projects": projects,
        "agent": _clean_agent(raw.get("agent")),
        "service": _clean_service(raw.get("service")),
        "signatory": _clean_section(raw.get("signatory"), ("name", "designation")),
        "patent_office": _s(raw.get("patent_office")),
        "notes": _s(raw.get("notes")),
    }


class ValidationError(ValueError):
    pass


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@.]+(\.[^\s@.]+)*\.[A-Za-z]{2,}$")


def _emails(client: dict):
    """(where, value) for every e-mail on the client."""
    for i, p in enumerate(client["applicants"], 1):
        yield f"Applicant {i}", p.get("email", "")
    for pi, proj in enumerate(client["projects"], 1):
        for i, p in enumerate(proj["inventors"], 1):
            yield f"Project {pi}, inventor {i}", p.get("email", "")
    yield "Patent agent", client["agent"].get("email", "")
    yield "Address for service", client["service"].get("email", "")


def _phones(client: dict):
    """(where, value, is_mobile) for every phone number on the client."""
    for i, p in enumerate(client["applicants"], 1):
        yield f"Applicant {i} mobile", p.get("mobile", ""), True
        yield f"Applicant {i} telephone", p.get("telephone", ""), False
    for pi, proj in enumerate(client["projects"], 1):
        for i, p in enumerate(proj["inventors"], 1):
            yield f"Project {pi}, inventor {i} mobile", p.get("mobile", ""), True
    yield "Patent agent mobile", client["agent"].get("mobile", ""), True
    s = client["service"]
    yield "Address for service telephone", s.get("telephone", ""), False
    yield "Address for service mobile", s.get("mobile", ""), True
    yield "Address for service fax", s.get("fax", ""), False


def phone_problem(value: str, mobile: bool) -> str:
    """Same rules as the form: +91 -> 10 digits (mobiles start 6-9; a
    landline's STD code drops its 0), +1 -> 10 digits, others 4-14 digits."""
    m = re.match(r"^(\+\d{1,4})\s*(.*)$", value or "")
    code, number = (m.group(1), m.group(2)) if m else ("+91", value or "")
    d = re.sub(r"\D", "", number)
    cc = code[1:]
    if code in ("+91", "+1") and len(d) > 10 and d.startswith(cc):
        d = d[len(cc):]
    if code == "+91" and len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if not d:
        return ""
    if code == "+91":
        if len(d) != 10:
            return "needs 10 digits"
        if mobile and d[0] not in "6789":
            return "must start with 6, 7, 8 or 9"
        return ""
    if code == "+1":
        return "" if len(d) == 10 else "needs 10 digits"
    return "" if 4 <= len(d) <= 14 else "is not a valid number"


def _addresses(client: dict):
    """(where, address) for every address on the client."""
    for i, p in enumerate(client["applicants"], 1):
        yield f"Applicant {i}", p["address"]
    for pi, proj in enumerate(client["projects"], 1):
        for i, p in enumerate(proj["inventors"], 1):
            yield f"Project {pi}, inventor {i}", p["address"]
    yield "Patent agent", client["agent"]["address"]
    yield "Address for service", client["service"]["address"]


def _field_problems(c: dict):
    """(where, problem) for every non-blank field whose format is wrong."""
    def check(where, problem):
        if problem:
            yield f"{where} {problem}"

    if c["client_type"] not in V.CLIENT_TYPES:
        yield "Client type is not one of the choices"
    if c["applicant_category"] not in V.CATEGORIES:
        yield "Category of applicant is not one of the choices"
    if c["patent_office"] not in V.PATENT_OFFICES:
        yield "Patent office is not one of the choices"

    people = [(f"Applicant {i}", p, True) for i, p in enumerate(c["applicants"], 1)]
    for pi, proj in enumerate(c["projects"], 1):
        people += [(f"Project {pi}, inventor {i}", p, False) for i, p in enumerate(proj["inventors"], 1)]
    for where, p, is_applicant in people:
        if p["kind"] not in PERSON_KINDS:
            yield f"{where} type must be individual or organisation"
            continue
        individual = p["kind"] == "individual"
        name_check = V.person_name_problem if individual else V.org_name_problem
        yield from check(f"{where} name", name_check(p["name"]))
        if p["gender"] not in V.GENDERS:
            yield f"{where} gender is not one of the choices"
        yield from check(f"{where} age", V.age_problem(p["age"]))
        if not individual and (p["gender"] or p["age"]):
            yield f"{where} is an organisation, so gender and age don't apply"
        yield from check(f"{where} nationality", V.country_problem(p["nationality"]))
        yield from check(f"{where} country of residence", V.country_problem(p["country_of_residence"]))

    for where, addr in _addresses(c):
        yield from check(f"{where} city", V.city_problem(addr["city"]))
        yield from check(f"{where} area / street", V.length_problem(addr["street"], 150))
        yield from check(f"{where} state", V.place_problem(addr["state"]))
        yield from check(f"{where} country", V.country_problem(addr["country"]))
        yield from check(f"{where} house no.", V.length_problem(addr["house_no"], 100))

    for pi, proj in enumerate(c["projects"], 1):
        where = f"Project {pi}"
        yield from check(f"{where} name", V.length_problem(proj["name"], 100))
        yield from check(f"{where} title", V.length_problem(proj["invention_title"], 500))
        yield from check(f"{where} application no.", V.appno_problem(proj["application_number"]))
        yield from check(f"{where} patent no.", V.patentno_problem(proj["patent_number"]))
        yield from check(f"{where} filing date", V.date_problem(proj["filing_date"]))
        yield from check(f"{where} grant date", V.date_problem(proj["grant_date"]))
        if (proj["filing_date"] and proj["grant_date"] and not V.date_problem(proj["filing_date"])
                and not V.date_problem(proj["grant_date"]) and proj["grant_date"] < proj["filing_date"]):
            yield f"{where} grant date is before the filing date"
        if any(t not in V.APPLICATION_TYPES for t in proj["application_type"]):
            yield f"{where} type of application is not one of the choices"

    yield from check("Patent agent name", V.person_name_problem(c["agent"]["name"]))
    yield from check("Patent agent IN/PA no.", V.inpa_problem(c["agent"]["inpa_number"]))
    yield from check("Address for service name", V.org_name_problem(c["service"]["name"]))
    yield from check("Signatory name", V.person_name_problem(c["signatory"]["name"]))
    yield from check("Signatory designation", V.designation_problem(c["signatory"]["designation"]))
    yield from check("Notes", V.length_problem(c["notes"], 2000))


def validate(client: dict) -> None:
    """No field is mandatory, but e-mails, phone numbers and PIN / postal codes
    that are entered must be valid."""
    problems = [f"{where} (invalid e-mail)" for where, v in _emails(client)
                if v and not _EMAIL_RE.match(v)]
    for where, addr in _addresses(client):
        issue = postcode_format.problem(addr.get("country", ""), addr.get("pin_code", ""))
        if issue:
            problems.append(f"{where} PIN / postal code {issue}")
    for where, v, mobile in _phones(client):
        issue = phone_problem(v, mobile)
        if issue:
            problems.append(f"{where} {issue}")
    problems += list(_field_problems(client))
    if problems:
        raise ValidationError("Please fix: " + "; ".join(problems) + ".")


_DEFAULTED = {"nationality", "country_of_residence", "kind"}


def _person_has_data(p: dict) -> bool:
    """True if anything beyond the pre-set country defaults was entered."""
    if any(v for k, v in p.items() if k not in _DEFAULTED and k != "address"):
        return True
    return any(v for k, v in p["address"].items() if k != "country")


class StoreError(RuntimeError):
    """The data file can't be read."""


class ConflictError(ValueError):
    """The client changed since the caller loaded it."""


def _now() -> str:
    # Microseconds, so two saves within one second still differ (conflict check).
    return datetime.now().isoformat(timespec="microseconds")


def valid_id(client_id: str) -> bool:
    return bool(_ID_RE.match(client_id or ""))


class ClientStore:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(self.path.stem + ".backup.json")

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
        except (ValueError, UnicodeDecodeError) as exc:
            backup = (f" The previous version is saved as {self.backup_path.name} in the same folder - "
                      "copy it over clients.json to restore it.") if self.backup_path.exists() else ""
            raise StoreError(f"The client data file ({self.path.name}) is damaged and can't be read "
                             f"({exc}).{backup}") from exc
        # One-time upgrade of clients saved before multiple projects existed.
        stale = [cid for cid, c in data.items()
                 if "projects" not in c or "address" not in (c.get("service") or {})
                 or "address" not in (c.get("agent") or {})]
        for cid in stale:
            old = data[cid]
            data[cid] = dict(clean_client(old), id=cid, created_at=old.get("created_at", ""),
                             updated_at=old.get("updated_at", ""))
        if stale:
            self._write(data)
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        if self.path.exists():   # keep the last good version for recovery
            shutil.copy2(self.path, self.backup_path)
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        with self._lock:
            items = list(self._read().values())
        items.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
        return items

    def get(self, client_id: str) -> dict | None:
        if not valid_id(client_id):
            return None
        with self._lock:
            return self._read().get(client_id)

    def create(self, raw: dict) -> dict:
        client = clean_client(raw)
        validate(client)
        now = _now()
        with self._lock:
            data = self._read()
            cid = "c_" + secrets.token_hex(4)
            while cid in data:
                cid = "c_" + secrets.token_hex(4)
            client.update(id=cid, created_at=now, updated_at=now)
            data[cid] = client
            self._write(data)
        return client

    def update(self, client_id: str, raw: dict) -> dict | None:
        client = clean_client(raw)
        validate(client)
        with self._lock:
            data = self._read()
            old = data.get(client_id) if valid_id(client_id) else None
            if old is None:
                return None
            # Saved from a copy that is now out of date (e.g. edited in another
            # tab meanwhile)? Refuse rather than silently overwrite those edits.
            seen = raw.get("updated_at") if isinstance(raw, dict) else None
            if seen and seen != old.get("updated_at"):
                raise ConflictError("This client was changed elsewhere (another tab or window) after you "
                                    "opened it. Reload the page to see the latest details, then make "
                                    "your changes again.")
            client.update(id=client_id, created_at=old.get("created_at", ""), updated_at=_now())
            data[client_id] = client
            self._write(data)
        return client

    def delete(self, client_id: str) -> bool:
        with self._lock:
            data = self._read()
            if client_id not in data:
                return False
            del data[client_id]
            self._write(data)
        return True

    # ---- bringing in clients saved by an older version -----------------------
    @property
    def _imports_path(self) -> Path:
        return self.path.with_name("imported-from.json")

    def import_once(self, other_file: Path) -> int | None:
        """Copy in the clients from another clients.json (e.g. the "data"
        folder older versions kept next to the .exe) - once per source folder.

        Clients already here are kept as they are; only missing ones are
        added. The source folder is remembered, so it is never imported again
        (a client deleted later can't come back). The source is not changed.
        Returns how many clients were added, or None if this source was
        already imported or can't be read.
        """
        source = str(Path(other_file).resolve())
        with self._lock:
            done = []
            if self._imports_path.exists():
                try:
                    done = json.loads(self._imports_path.read_text(encoding="utf-8"))
                except ValueError:
                    done = []
            if any(os.path.normcase(source) == os.path.normcase(d) for d in done):
                return None
            try:
                incoming = json.loads(Path(other_file).read_text(encoding="utf-8") or "{}")
                if not isinstance(incoming, dict):
                    return None
            except (OSError, ValueError):
                return None
            data = self._read()
            added = 0
            for cid, c in incoming.items():
                if valid_id(cid) and isinstance(c, dict) and cid not in data:
                    data[cid] = dict(clean_client(c), id=cid, created_at=c.get("created_at", ""),
                                     updated_at=c.get("updated_at", ""))
                    added += 1
            if added:
                self._write(data)
            self._imports_path.parent.mkdir(parents=True, exist_ok=True)
            self._imports_path.write_text(json.dumps(done + [source], indent=2), encoding="utf-8")
            return added


def find_project(client: dict, project_id: str | None) -> dict | None:
    for p in client.get("projects", []):
        if p["id"] == project_id:
            return p
    return None


def project_label(project: dict) -> str:
    return (project.get("name") or project.get("invention_title")
            or project.get("application_number") or "Untitled project")


def display_name(client: dict) -> str:
    names = [a["name"] for a in client.get("applicants", []) if a.get("name")]
    if not names:
        return "Unnamed client"
    return names[0] + (f" + {len(names) - 1} more" if len(names) > 1 else "")
