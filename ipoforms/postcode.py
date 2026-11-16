"""Postal code -> city / state / localities.

India uses the India Post PIN directory (api.postalpincode.in); other countries
use Zippopotam (api.zippopotam.us). Only the postal code and country are sent.
If the service can't be reached, an Indian PIN still resolves to its state from
the first two digits (the postal circle), so the form stays usable offline.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request

TIMEOUT = 6
_HEADERS = {"User-Agent": "IPOFormFiller/1.0", "Accept": "application/json"}
_cache: dict = {}
_lock = threading.Lock()

# First two digits of an Indian PIN -> state, where those digits belong to a
# single state. Ambiguous prefixes (shared between states/UTs) are left out.
_IN_PREFIX_STATE = {
    "11": "Delhi", "12": "Haryana", "13": "Haryana", "14": "Punjab", "15": "Punjab",
    "17": "Himachal Pradesh", "18": "Jammu and Kashmir",
    "20": "Uttar Pradesh", "21": "Uttar Pradesh", "22": "Uttar Pradesh", "23": "Uttar Pradesh",
    "25": "Uttar Pradesh", "27": "Uttar Pradesh", "28": "Uttar Pradesh",
    "30": "Rajasthan", "31": "Rajasthan", "32": "Rajasthan", "33": "Rajasthan", "34": "Rajasthan",
    "36": "Gujarat", "37": "Gujarat", "38": "Gujarat",
    "41": "Maharashtra", "42": "Maharashtra", "43": "Maharashtra", "44": "Maharashtra",
    "45": "Madhya Pradesh", "46": "Madhya Pradesh", "47": "Madhya Pradesh", "48": "Madhya Pradesh",
    "49": "Chhattisgarh", "50": "Telangana",
    "51": "Andhra Pradesh", "52": "Andhra Pradesh", "53": "Andhra Pradesh",
    "56": "Karnataka", "57": "Karnataka", "58": "Karnataka", "59": "Karnataka",
    "61": "Tamil Nadu", "62": "Tamil Nadu", "63": "Tamil Nadu", "64": "Tamil Nadu",
    "67": "Kerala", "69": "Kerala",
    "70": "West Bengal", "71": "West Bengal", "72": "West Bengal",
    "75": "Odisha", "76": "Odisha", "77": "Odisha", "78": "Assam",
    "80": "Bihar", "81": "Bihar", "82": "Jharkhand", "83": "Jharkhand", "84": "Bihar", "85": "Bihar",
}

_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-]{1,9}$")


class PostcodeError(ValueError):
    """The lookup service could not be reached."""
    status = 503


class InvalidPostcode(PostcodeError):
    """The code itself is malformed."""
    status = 400


def _fetch(url: str):
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return json.loads(res.read().decode("utf-8"))


def _title(s: str) -> str:
    s = (s or "").strip()
    return s if not s.isupper() else s.title()


def _india(pin: str) -> dict:
    if not re.fullmatch(r"[1-9]\d{5}", pin):
        raise InvalidPostcode("An Indian PIN code has 6 digits.")
    try:
        data = _fetch(f"https://api.postalpincode.in/pincode/{pin}")
        offices = (data[0].get("PostOffice") or []) if data else []
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        state = _IN_PREFIX_STATE.get(pin[:2], "")
        return {"found": bool(state), "offline": True, "city": "", "state": state,
                "country": "India", "localities": []}
    if not offices:
        return {"found": False, "city": "", "state": "", "country": "India", "localities": []}
    first = offices[0]
    # Delivery offices first: they are the localities people actually write.
    offices.sort(key=lambda o: o.get("DeliveryStatus") != "Delivery")
    localities = list(dict.fromkeys(_title(o.get("Name", "")) for o in offices if o.get("Name")))
    return {"found": True, "city": _title(first.get("District", "")),
            "state": _title(first.get("State", "")), "country": "India",
            "localities": localities}


def _lookup_form(iso2: str, code: str) -> str:
    """The part of a full postcode that Zippopotam indexes."""
    code = code.upper().strip()
    if iso2 in ("GB", "CA"):
        compact = code.replace(" ", "")
        return compact[:-3] if iso2 == "GB" and len(compact) >= 5 else (compact[:3] if iso2 == "CA" else code)
    if iso2 == "NL":
        return code[:4]
    if iso2 == "US":
        return code[:5]
    if iso2 == "SE":
        return code.replace(" ", "")
    return code


def _world(iso2: str, code: str) -> dict:
    code = _lookup_form(iso2, code)
    try:
        data = _fetch(f"https://api.zippopotam.us/{iso2.lower()}/{urllib.request.quote(code)}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"found": False, "city": "", "state": "", "localities": []}
        raise PostcodeError("The postcode service is not responding.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PostcodeError("No internet connection for postcode lookup.") from exc
    places = data.get("places") or []
    if not places:
        return {"found": False, "city": "", "state": "", "localities": []}
    names = list(dict.fromkeys(p.get("place name", "") for p in places if p.get("place name")))
    return {"found": True, "city": names[0] if len(names) == 1 else "",
            "state": places[0].get("state", ""), "localities": names}


def lookup(iso2: str, code: str) -> dict:
    iso2 = (iso2 or "").upper()
    code = (code or "").strip()
    if not re.fullmatch(r"[A-Z]{2}", iso2) or not _CODE_RE.match(code):
        raise InvalidPostcode("Enter a valid postal code.")
    key = (iso2, code.upper())
    with _lock:
        if key in _cache:
            return _cache[key]
    result = _india(code) if iso2 == "IN" else _world(iso2, code)
    if not result.get("offline"):
        with _lock:
            _cache[key] = result
    return result
