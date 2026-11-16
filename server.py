"""IPO Form Filler - local web server (Python standard library only).

Run:  python server.py        then open http://127.0.0.1:8765

API
  GET    /api/forms                              catalogue of IPO forms
  GET    /api/clients                            all saved clients
  POST   /api/clients                            create a client
  GET    /api/clients/{id}                       one client
  PUT    /api/clients/{id}                       update a client
  DELETE /api/clients/{id}                       delete a client
  GET    /api/clients/{id}/forms/{form_id}       pre-filled form (preview model)
  GET    /api/clients/{id}/forms/{form_id}.docx  pre-filled form as Word document
         both take ?project={project_id}; without it only client details fill
  GET    /api/postcode/{iso2}/{code}             city / state / localities for a postal code
  GET    /api/forms/{form_id}/blank.docx         the form as an empty, editable Word document
  GET    /official/{file}                        official blank IPO PDF (?download=1 to save it)
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import sys
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from ipoforms import catalog, postcode
from ipoforms.docx_writer import build_docx
from ipoforms.prefill import build_form
from ipoforms.store import (ClientStore, ConflictError, StoreError, ValidationError,
                            clean_client, display_name, find_project, project_label)

ROOT = Path(__file__).resolve().parent
WEB_DIR = ROOT / "web"
MAX_BODY = 1_000_000

STORE = ClientStore()

_FORM_RE = re.compile(r"^/api/clients/(c_[0-9a-f]{8})/forms/(form_[0-9a-z]+)(\.docx)?$")
_CLIENT_RE = re.compile(r"^/api/clients/(c_[0-9a-f]{8})$")
_POSTCODE_RE = re.compile(r"^/api/postcode/([A-Za-z]{2})/([^/]{1,12})$")
_BLANK_RE = re.compile(r"^/api/forms/(form_[0-9a-z]+)/blank\.docx$")


def _attachment(name: str) -> str:
    """Content-Disposition for a download, safe for non-ASCII names."""
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def _safe_filename(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", text)
    return re.sub(r"\s+", " ", text).strip()[:120] or "form"


class Handler(BaseHTTPRequestHandler):
    server_version = "IPOFormFiller/1.0"

    def log_message(self, fmt, *args):  # quieter console
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("%s  %s\n" % (self.log_date_time_string(), fmt % args))

    # ---------------- responses ----------------
    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _error(self, status: int, message: str):
        self._json({"error": message}, status)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0:
            raise ValueError("Invalid request.")
        if length > MAX_BODY:
            raise ValueError("Request too large.")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _static(self, base: Path, rel: str, download_name: str | None = None):
        target = (base / rel).resolve()
        if base.resolve() not in target.parents and target != base.resolve() or not target.is_file():
            return self._error(404, "Not found.")
        if download_name:   # ?download=1: save to disk instead of opening in the browser
            return self._send(200, target.read_bytes(), "application/pdf",
                              {"Content-Disposition": _attachment(download_name)})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix.lower() == ".pdf":
            ctype = "application/pdf"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    # ---------------- routing ----------------
    # Every request goes through _safely: an unexpected failure becomes a JSON
    # error the page can show, instead of a dropped connection.
    def _safely(self, handler):
        try:
            handler()
        except StoreError as exc:
            self._error(500, str(exc))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - last-resort guard
            print(f"Unexpected error on {self.command} {self.path}: {exc!r}", file=sys.stderr)
            try:
                self._error(500, f"Something went wrong: {exc}")
            except OSError:
                pass

    def do_GET(self):
        self._safely(self._get)

    def do_POST(self):
        self._safely(self._post)

    def do_PUT(self):
        self._safely(self._put)

    def do_DELETE(self):
        self._safely(self._delete)

    do_HEAD = do_GET

    def _get(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/forms":
            return self._json(catalog.list_forms())
        if path == "/api/clients":
            return self._json(STORE.list())
        m = _POSTCODE_RE.match(path)
        if m:
            try:
                return self._json(postcode.lookup(m.group(1), m.group(2)))
            except postcode.PostcodeError as exc:
                return self._error(exc.status, str(exc))
        m = _CLIENT_RE.match(path)
        if m:
            c = STORE.get(m.group(1))
            return self._json(c) if c else self._error(404, "Client not found.")
        m = _FORM_RE.match(path)
        if m:
            project_id = parse_qs(urlparse(self.path).query).get("project", [""])[0]
            return self._form(m.group(1), m.group(2), bool(m.group(3)), project_id)
        m = _BLANK_RE.match(path)
        if m:
            return self._blank_docx(m.group(1))
        if path.startswith("/official/"):
            rel = path[len("/official/"):]
            download = parse_qs(urlparse(self.path).query).get("download") == ["1"]
            name = None
            if download:
                number = re.sub(r"^Form_|\.pdf$", "", rel, flags=re.I)
                name = f"Form {number} - official blank.pdf"
            return self._static(catalog.OFFICIAL_DIR, rel, name)
        if path.startswith("/api/"):
            return self._error(404, "Unknown endpoint.")
        rel = path.lstrip("/") or "index.html"
        if not (WEB_DIR / rel).is_file():
            rel = "index.html"
        return self._static(WEB_DIR, rel)

    def _post(self):
        if urlparse(self.path).path != "/api/clients":
            return self._error(404, "Unknown endpoint.")
        try:
            client = STORE.create(self._body())
        except (ValueError, ValidationError) as exc:
            return self._error(400, str(exc))
        self._json(client, 201)

    def _put(self):
        m = _CLIENT_RE.match(urlparse(self.path).path)
        if not m:
            return self._error(404, "Unknown endpoint.")
        try:
            client = STORE.update(m.group(1), self._body())
        except ConflictError as exc:
            return self._error(409, str(exc))
        except (ValueError, ValidationError) as exc:
            return self._error(400, str(exc))
        return self._json(client) if client else self._error(404, "Client not found.")

    def _delete(self):
        m = _CLIENT_RE.match(urlparse(self.path).path)
        if not m:
            return self._error(404, "Unknown endpoint.")
        if STORE.delete(m.group(1)):
            return self._json({"deleted": m.group(1)})
        return self._error(404, "Client not found.")

    # ---------------- forms ----------------
    def _blank_docx(self, form_id: str):
        """The form as an editable Word document with nothing filled in."""
        definition = catalog.get_definition(form_id)
        if not definition:
            return self._error(404, "Form not found.")
        model = build_form(definition, clean_client({}))
        self._send(200, build_docx(model),
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                   {"Content-Disposition": _attachment(f"Form {definition['formNumber']} - blank.docx")})

    def _form(self, client_id: str, form_id: str, as_docx: bool, project_id: str = ""):
        client = STORE.get(client_id)
        if not client:
            return self._error(404, "Client not found.")
        definition = catalog.get_definition(form_id)
        if not definition:
            return self._error(404, "Form not found.")
        project = None
        if project_id:
            project = find_project(client, project_id)
            if project is None:
                return self._error(404, "Project not found.")
        model = build_form(definition, client, project)
        if not as_docx:
            model["official_pdf"] = catalog.official_pdf_name(definition["formNumber"])
            return self._json(model)
        data = build_docx(model)
        stem = f"Form {definition['formNumber']} - {display_name(client)}"
        if project:
            stem += f" - {project_label(project)}"
        name = _safe_filename(stem) + ".docx"
        ascii_name = name.encode("ascii", "replace").decode().replace("?", "_")
        self._send(200, data,
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                   {"Content-Disposition":
                    f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})


def main():
    ap = argparse.ArgumentParser(description="IPO Form Filler")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"IPO Form Filler running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
