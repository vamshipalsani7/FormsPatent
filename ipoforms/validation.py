"""Format rules for client fields - the blocking rules the form applies
(web/app.js, CHECKS), enforced again here so bad data can't be saved another way.

Every function takes a value and returns '' when it's blank or valid, else a
short description of what's wrong. `tidy_*` functions return the stored form.
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

from .catalog import ROOT

OFFICE_CODES = {"11": "Delhi", "21": "Mumbai", "31": "Chennai", "41": "Kolkata"}
PATENT_OFFICES = {"", "delhi", "mumbai", "chennai", "kolkata"}
CATEGORIES = {"", "natural_person", "startup", "small_entity", "educational_institution", "other"}
CLIENT_TYPES = {"individual", "organisation"}
GENDERS = {"", "male", "female", "others", "not_disclosed"}
APPLICATION_TYPES = {"ordinary", "convention", "pct_np", "pph", "divisional", "patent_of_addition"}
# Values saved before the country picker existed.
DEMONYMS = {"indian": "India", "american": "United States", "british": "United Kingdom"}


@lru_cache(maxsize=1)
def countries() -> frozenset:
    """Country names offered by the picker (web/countries.js is the one list)."""
    text = (ROOT / "web" / "countries.js").read_text(encoding="utf-8")
    return frozenset(re.findall(r'\["([^"]+)", "[A-Z]{2}", "\+\d+"\]', text))


def tidy_country(v: str) -> str:
    v = (v or "").strip()
    return DEMONYMS.get(v.lower(), v)


def country_problem(v: str) -> str:
    return "" if not v or v in countries() else f'"{v}" is not a country in the list'


# --- numbers --------------------------------------------------------------

def tidy_appno(v: str) -> str:
    s = re.sub(r"[\s-]", "", (v or "").upper())
    return s[2:] if re.fullmatch(r"IN\d+", s) else s


def appno_problem(v: str) -> str:
    s = tidy_appno(v)
    if not s:
        return ""
    if s.isdigit():
        if len(s) != 12:
            return f"needs 12 digits (has {len(s)})"
        year = int(s[:4])
        if not 2005 <= year <= date.today().year:
            return "must start with the filing year"
        if s[4:6] not in OFFICE_CODES:
            return "digits 5-6 must be an office code (11, 21, 31 or 41)"
        return ""
    if re.fullmatch(r"\d{1,5}/(DEL|MUM|CHE|KOL)(NP)?/(19|20)\d{2}", s):
        return ""
    return "is not a valid application number"


def tidy_patentno(v: str) -> str:
    s = re.sub(r"[\s,.-]", "", (v or "").upper())
    return s[2:] if s.startswith("IN") else s


def patentno_problem(v: str) -> str:
    s = tidy_patentno(v)
    if not s:
        return ""
    return "" if re.fullmatch(r"\d{1,7}", s) else "must be up to 7 digits"


def tidy_inpa(v: str) -> str:
    s = re.sub(r"\s+", "", (v or "").upper())
    m = re.fullmatch(r"(?:IN/?PA[-/]?)?(\d{1,5})", s)
    return f"IN/PA-{m.group(1)}" if m else (v or "").strip()


def inpa_problem(v: str) -> str:
    s = tidy_inpa(v)
    return "" if not s or re.fullmatch(r"IN/PA-\d{1,5}", s) else "must look like IN/PA-1234"


def age_problem(v: str) -> str:
    """Whole years, 1-120 (blank is fine)."""
    s = (v or "").strip()
    if not s:
        return ""
    if not s.isdigit():
        return "must be a whole number of years"
    return "" if 1 <= int(s) <= 120 else "must be between 1 and 120"


# --- dates ----------------------------------------------------------------

def date_problem(v: str) -> str:
    if not v:
        return ""
    try:
        d = date.fromisoformat(v)
    except ValueError:
        return "is not a valid date"
    if d > date.today():
        return "can't be in the future"
    if d.year < 1970:
        return "can't be before 1970"
    return ""


# --- text -----------------------------------------------------------------

def _text_problem(v: str, max_len: int, digits: bool, symbols: str) -> str:
    s = re.sub(r"\s+", " ", v or "").strip()
    if not s:
        return ""
    if len(s) > max_len:
        return f"is longer than {max_len} characters"
    if not digits and re.search(r"\d", s):
        return "shouldn't contain numbers"
    bad = {ch for ch in s if not (ch.isalpha() or ch.isspace() or (digits and ch.isdigit())
                                 or ch in symbols or _is_mark(ch))}
    if bad:
        return "can't contain " + " ".join(sorted(bad))
    if not any(ch.isalpha() for ch in s):
        return "needs at least one letter"
    return ""


def _is_mark(ch: str) -> bool:
    import unicodedata
    return unicodedata.category(ch).startswith("M")


def person_name_problem(v):
    return _text_problem(v, 100, False, ".'’-")


def org_name_problem(v):
    return _text_problem(v, 200, True, ".,'’-&()/+:")


def place_problem(v):
    """States: letters only."""
    return _text_problem(v, 60, False, ".'’-()&")


def city_problem(v):
    """Cities / districts may contain numbers, e.g. 'North 24 Parganas', 'Sector 62'."""
    return _text_problem(v, 60, True, ".'’-()&,")


def designation_problem(v):
    return _text_problem(v, 80, False, ".,'’-&()/")


def length_problem(v, max_len):
    return f"is longer than {max_len} characters" if len((v or "").strip()) > max_len else ""
