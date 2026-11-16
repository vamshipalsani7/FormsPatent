"""Start IPO Form Filler: the Windows app (IPO Form Filler.exe is built from
this file) and the double-click starter when running from the source.

Desktop mode (pywebview available - always in the .exe): the tool opens in its
own window using Windows' built-in Edge WebView2. No browser is involved; the
web server inside only listens on this computer, for this window. Downloads
use a normal "Save As" dialog and official PDFs open in a window of their own.
Closing the window stops the tool.

Browser mode (pywebview not installed, or WebView2 missing): the tool opens in
the default browser, with a small "Open in browser / Stop" window.

    python "IPO Form Filler.pyw" --check          # start, self-test, stop (no window)
    python "IPO Form Filler.pyw" --check-desktop  # also load the UI in a hidden window
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# No console (pythonw / the .exe): give anything printed somewhere harmless.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

PREFERRED_PORT = 8765
STARTUP_WAIT = 12   # seconds to wait for another copy that is still starting up


def already_running(port: int) -> bool:
    """Is IPO Form Filler itself serving on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/forms", timeout=2) as r:
            return isinstance(json.load(r), list)
    except Exception:
        return False


def start_server(handler, port: int = PREFERRED_PORT, wait: float = STARTUP_WAIT, server_class=None):
    """Serve on `port`, or find that this tool is already running there.

    Returns (httpd, url) when this copy is now serving, or (None, url) when
    another copy of IPO Form Filler already is - including one double-clicked a
    moment earlier that is still starting. The port is claimed by binding it,
    so two copies can never both serve the same client data. If some other
    program holds the port, the next free port is used instead.
    """
    if server_class is None:
        from server import AppServer as server_class   # holds its port exclusively
    deadline = time.monotonic() + wait
    while True:
        try:
            httpd = server_class(("127.0.0.1", port), handler)
            return httpd, f"http://127.0.0.1:{port}/"
        except OSError:
            if already_running(port):
                return None, f"http://127.0.0.1:{port}/"
            if time.monotonic() >= deadline:
                break
            time.sleep(0.5)   # perhaps another copy is still starting up
    for other in range(port + 1, port + 50):
        try:
            httpd = server_class(("127.0.0.1", other), handler)
            return httpd, f"http://127.0.0.1:{other}/"
        except OSError:
            continue
    raise RuntimeError(f"No free port found between {port} and {port + 49}.")


def show_message(title: str, text: str, warning: bool = False) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        (messagebox.showwarning if warning else messagebox.showinfo)(title, text)
        root.destroy()
    except Exception:
        print(f"{title}: {text}")


def self_test(url: str) -> bool:
    """Used by --check: the page, its scripts, a Word form, a PDF and the country list."""
    ok = already_running(int(url.rsplit(":", 1)[1].strip("/")))
    for path in ("", "app.js", "countries.js", "api/forms/form_01/blank.docx", "official/Form_1.PDF"):
        with urllib.request.urlopen(url + path, timeout=10) as r:
            ok = ok and r.status == 200 and len(r.read()) > 100
    from ipoforms import validation
    return ok and "India" in validation.countries()


# ---------------------------------------------------------------- desktop window

def desktop_available() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


class DesktopApi:
    """Called from the page (window.pywebview.api.*) for things a browser would
    normally do itself: saving downloads, showing PDFs, opening saved files."""

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")
        self._window = None

    def _fetch(self, path: str):
        if not path.startswith("/"):
            raise ValueError("Only the tool's own files can be saved.")
        with urllib.request.urlopen(self._base_url + path, timeout=60) as r:
            return r.read(), r.headers.get("Content-Disposition", "")

    @staticmethod
    def _filename(disposition: str, path: str) -> str:
        from urllib.parse import unquote
        import re
        m = re.search(r"filename\*=UTF-8''([^;]+)", disposition)
        if m:
            return unquote(m.group(1))
        m = re.search(r'filename="([^"]+)"', disposition)
        return m.group(1) if m else unquote(path.rsplit("/", 1)[-1].split("?", 1)[0])

    def save(self, path: str) -> dict:
        """Fetch a download from the tool and ask where to save it."""
        import webview
        try:
            data, disposition = self._fetch(path)
            name = self._filename(disposition, path)
            ext = Path(name).suffix.lower()
            kinds = {".docx": "Word document (*.docx)", ".pdf": "PDF document (*.pdf)"}
            downloads = Path.home() / "Downloads"
            dialog = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
            chosen = self._window.create_file_dialog(
                dialog, directory=str(downloads if downloads.is_dir() else Path.home()),
                save_filename=name, file_types=(kinds.get(ext, "All files (*.*)"), "All files (*.*)"))
            if not chosen:
                return {"cancelled": True}
            target = Path(chosen[0] if isinstance(chosen, (list, tuple)) else chosen)
            if ext and target.suffix.lower() != ext:
                target = target.with_name(target.name + ext)
            target.write_bytes(data)
            return {"saved": str(target), "name": target.name}
        except Exception as exc:  # noqa: BLE001 - reported in the page
            return {"error": str(exc)}

    def open_file(self, file_path: str) -> bool:
        """Open a file the user just saved, with its usual program (e.g. Word)."""
        p = Path(file_path)
        if not p.is_file():
            return False
        if hasattr(os, "startfile"):
            os.startfile(str(p))  # noqa: S606 - the user's own saved file
        else:
            webbrowser.open(p.as_uri())
        return True

    def show_pdf(self, path: str, title: str = "Official form") -> bool:
        """Show an official blank PDF in a window of its own."""
        import webview
        if not path.startswith("/official/"):
            return False
        webview.create_window(title, self._base_url + path, width=900, height=1000)
        return True


def run_desktop(url: str, check: bool = False) -> bool:
    """Open the tool in its own window. Returns False if that isn't possible
    here (no pywebview / no WebView2), so the caller can use the browser."""
    try:
        import webview
    except Exception:
        return False
    from ipoforms import paths

    api = DesktopApi(url)
    result = {"loaded": False}
    window = webview.create_window(
        "IPO Form Filler", url, js_api=api, width=1280, height=860, min_size=(900, 600),
        hidden=check, text_select=True, background_color="#12161c")
    api._window = window  # private: not exposed to the page
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    def after_start() -> None:
        if not check:
            return
        # --check-desktop: wait until the page has drawn its home screen, then close.
        for _ in range(60):
            try:
                # the home screen has drawn AND the page can reach Save / PDF functions
                if window.evaluate_js("!!document.querySelector('#pick') && "
                                      "typeof window.pywebview?.api?.save === 'function' && "
                                      "typeof window.pywebview?.api?.show_pdf === 'function'"):
                    result["loaded"] = True
                    break
            except Exception:
                pass
            time.sleep(0.5)
        window.destroy()

    # Window storage (unsaved-change drafts) is kept between runs.
    storage = paths.FALLBACK_DATA_DIR.parent / "WebView"
    icon = Path(getattr(sys, "_MEIPASS", ROOT)) / "app.ico"
    try:
        webview.start(after_start, gui="edgechromium" if os.name == "nt" else None,
                      private_mode=False, storage_path=str(storage),
                      icon=str(icon) if icon.exists() else None)
    except Exception as exc:  # noqa: BLE001 - e.g. WebView2 runtime missing
        if check:
            print("desktop window failed:", exc)
        return False
    if check:
        print("desktop check:", "OK" if result["loaded"] else "FAILED")
        return result["loaded"]
    return True


# ---------------------------------------------------------------- start-up

def main() -> None:
    check = "--check" in sys.argv or "--check-desktop" in sys.argv
    import server   # imported here so a problem is reported in a message box
    from ipoforms import paths

    port = int(os.environ.get("IPO_FORM_FILLER_PORT", PREFERRED_PORT))
    httpd, url = start_server(server.Handler, port, wait=0 if check else STARTUP_WAIT)
    if httpd is None:
        if check:
            print("launcher check: FAILED - another copy is using", url)
            sys.exit(1)
        if desktop_available():
            show_message("IPO Form Filler", "IPO Form Filler is already open.\n"
                         "Look for its window on the taskbar.")
        else:
            webbrowser.open(url)
            show_message("IPO Form Filler", "IPO Form Filler is already running.\nIt has been opened in your browser.")
        return
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    if check:   # self-test used by the release checks: no browser
        try:
            ok = self_test(url)
        except Exception as exc:  # noqa: BLE001
            print("check failed:", exc)
            ok = False
        if ok and "--check-desktop" in sys.argv:
            ok = run_desktop(url, check=True)
        httpd.shutdown()
        print("launcher check:", "OK" if ok else "FAILED", url, "| data:", paths.data_dir())
        sys.exit(0 if ok else 1)

    if paths.running_from_temp():
        show_message("IPO Form Filler - please unzip first",
                     "It looks like IPO Form Filler was opened from inside the zip file.\n\n"
                     "It will work, but to keep your clients safe they are being saved in:\n"
                     f"{paths.data_dir()}\n\n"
                     "Next time, right-click the zip, choose 'Extract All…', and run "
                     "IPO Form Filler.exe from the extracted folder.", warning=True)

    # Preferred: the tool's own window. Closing it stops the tool.
    if run_desktop(url):
        httpd.shutdown()
        httpd.server_close()
        return

    # Fallback: the default browser plus a small control window.
    webbrowser.open(url)
    try:
        import tkinter as tk
    except ImportError:        # Python without tkinter: keep serving until the process is ended
        threading.Event().wait()
        return

    root = tk.Tk()
    root.title("IPO Form Filler")
    root.resizable(False, False)
    icon = Path(getattr(sys, "_MEIPASS", ROOT)) / "app.ico"
    if icon.exists():
        try:
            root.iconbitmap(default=str(icon))
        except tk.TclError:
            pass
    frame = tk.Frame(root, padx=22, pady=18)
    frame.pack()
    tk.Label(frame, text="IPO Form Filler is running", font=("Segoe UI", 12, "bold")).pack(anchor="w")
    tk.Label(frame, text=f"Open {url} in your browser.\nKeep this window open while you work;\n"
                         "closing it stops the tool.", justify="left", fg="#444").pack(anchor="w", pady=(6, 14))
    buttons = tk.Frame(frame)
    buttons.pack(anchor="e")

    def stop() -> None:
        root.destroy()   # ends mainloop; the server is stopped just below

    tk.Button(buttons, text="Open in browser", width=16, command=lambda: webbrowser.open(url)).pack(side="left", padx=(0, 8))
    tk.Button(buttons, text="Stop", width=10, command=stop).pack(side="left")
    root.protocol("WM_DELETE_WINDOW", stop)
    root.mainloop()
    httpd.shutdown()
    httpd.server_close()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - show the problem instead of failing silently
        show_message("IPO Form Filler could not start", f"{type(exc).__name__}: {exc}", warning=True)
        raise
