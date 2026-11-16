"""PIN / postal code format rules - the same rules the form applies.

Keyed by country *name* as stored on the client (names come from the
country picker). Countries not listed accept 2-10 letters or digits.
"""

from __future__ import annotations

import re

_4 = (r"\d{4}", "4 digits")
_5 = (r"\d{5}", "5 digits")
_6 = (r"\d{6}", "6 digits")

RULES = {
    "India": (r"[1-9]\d{5}", "6 digits, not starting with 0"),
    "United States": (r"\d{5}(-\d{4})?", "5 digits, or ZIP+4"),
    "United Kingdom": (r"[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}", "a UK postcode"),
    "Canada": (r"[A-Z]\d[A-Z] \d[A-Z]\d", "letter-digit-letter digit-letter-digit"),
    "Ireland": (r"[A-Z]\d[\dW] [A-Z\d]{4}", "an Eircode"),
    "Netherlands": (r"[1-9]\d{3} [A-Z]{2}", "4 digits and 2 letters"),
    "Japan": (r"\d{3}-\d{4}", "7 digits"),
    "Brazil": (r"\d{5}-\d{3}", "8 digits"),
    "Sweden": (r"\d{3} \d{2}", "5 digits"),
    "Portugal": (r"\d{4}-\d{3}", "7 digits"),
    "Poland": (r"\d{2}-\d{3}", "5 digits"),
    "Israel": (r"\d{7}", "7 digits"),
    **{n: _4 for n in ("Australia", "New Zealand", "South Africa", "Switzerland", "Austria", "Belgium",
                       "Denmark", "Norway", "Bangladesh", "Philippines")},
    **{n: _5 for n in ("Germany", "France", "Italy", "Spain", "Finland", "Mexico", "Malaysia", "Thailand",
                       "Sri Lanka", "Nepal", "Pakistan", "South Korea", "Turkey", "Saudi Arabia", "Indonesia")},
    **{n: _6 for n in ("Singapore", "China", "Russia", "Vietnam")},
}
GENERIC = (r"[A-Z0-9][A-Z0-9 -]{1,9}", "2-10 letters or digits")


def problem(country: str, code: str) -> str:
    """'' if the code is blank or valid for the country, else what it should be."""
    code = re.sub(r"\s+", " ", (code or "").upper()).strip()
    if not code:
        return ""
    # No country chosen: no country-specific format is assumed.
    pattern, what = RULES.get((country or "").strip(), GENERIC)
    return "" if re.fullmatch(pattern, code) else f"should be {what}"
