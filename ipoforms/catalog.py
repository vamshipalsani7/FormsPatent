"""The catalogue of IPO forms (Patents Rules, 2003, First/Second Schedule).

Each form is described by a JSON definition in forms/definitions/. The
definitions list every section and field of the official form in printed order.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFINITIONS_DIR = ROOT / "forms" / "definitions"
OFFICIAL_DIR = ROOT / "forms" / "official"


def _sort_key(form_number: str):
    m = re.match(r"(\d+)([A-Z]*)", form_number)
    return (int(m.group(1)), m.group(2)) if m else (999, form_number)


@lru_cache(maxsize=1)
def _definitions() -> dict:
    out = {}
    for path in DEFINITIONS_DIR.glob("form_*.definition.json"):
        d = json.loads(path.read_text(encoding="utf-8"))
        out[d["formId"]] = d
    return out


def get_definition(form_id: str) -> dict | None:
    return _definitions().get(form_id)


def official_pdf_name(form_number: str) -> str | None:
    name = f"Form_{form_number}.PDF"
    return name if (OFFICIAL_DIR / name).exists() else None


def list_forms() -> list[dict]:
    forms = []
    for d in _definitions().values():
        forms.append({
            "id": d["formId"],
            "number": d["formNumber"],
            "name": d["officialName"],
            "purpose": d.get("purpose", ""),
            "official_pdf": official_pdf_name(d["formNumber"]),
        })
    forms.sort(key=lambda f: _sort_key(f["number"]))
    return forms
