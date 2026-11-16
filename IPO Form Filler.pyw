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


def instance_info(port: int) -> dict | None:
    """What is answering on this port: the running copy's details (its data
    folder, whether it has a window), {"legacy": True} for an older version of
    this tool, or None for nothing / some other program."""
    import urllib.error
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/instance", timeout=2) as r:
            info = json.load(r)
            return info if isinstance(info, dict) and info.get("app") == "ipo-form-filler" else None
    except urllib.error.HTTPError:
        return {"legacy": True} if already_running(port) else None
    except Exception:
        return None


def same_folder(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def start_server(handler, port: int = PREFERRED_PORT, wait: float = STARTUP_WAIT,
                 server_class=None, data_dir: Path | None = None):
    """Serve on `port`, or join the copy of this tool that already serves the
    same clients.

    Returns (httpd, url, None) when this copy is now serving, or
    (None, url, info) when another copy using the *same data folder* is
    already running there - including one double-clicked a moment earlier and
    still starting. The port is claimed by binding it, so two copies never
    serve the same client file. Anything else on the port - another program,
    an older version, or a copy that keeps its clients in a different folder -
    is left alone and the next free port is used.
    """
    if server_class is None:
        from server import AppServer as server_class   # holds its port exclusively
    if data_dir is None:
        from ipoforms.paths import data_dir as _data_dir
        data_dir = _data_dir()
    deadline = time.monotonic() + wait
    while True:
        try:
            httpd = server_class(("127.0.0.1", port), handler)
            return httpd, f"http://127.0.0.1:{port}/", None
        except OSError:
            info = instance_info(port)
            if info and not info.get("legacy") and same_folder(info.get("data_dir", ""), data_dir):
                return None, f"http://127.0.0.1:{port}/", info
            if info is not None or time.monotonic() >= deadline:
                break       # a different copy / version: don't share it, use another port
            time.sleep(0.5)   # perhaps another copy is still starting up
    for other in range(port + 1, port + 50):
        try:
            httpd = server_class(("127.0.0.1", other), handler)
            return httpd, f"http://127.0.0.1:{other}/", None
        except OSError:
            continue
    raise RuntimeError(f"No free port found between {port} and {port + 49}.")


def focus_existing(url: str) -> bool:
    """Ask the running copy to bring its window to the front."""
    try:
        req = urllib.request.Request(url + "api/instance/focus", method="POST", data=b"{}",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return bool(json.load(r).get("focused"))
    except Exception:
        return False


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

    def open_data_folder(self) -> bool:
        """Show the folder where clients are kept (for backups)."""
        from ipoforms.paths import data_dir
        folder = data_dir()
        if hasattr(os, "startfile"):
            os.startfile(str(folder))  # noqa: S606 - the app's own data folder
        else:
            webbrowser.open(folder.as_uri())
        return True

    def show_pdf(self, path: str, title: str = "Official form") -> bool:
        """Show an official blank PDF in a window of its own."""
        import webview
        if not path.startswith("/official/"):
            return False
        webview.create_window(title, self._base_url + path, width=900, height=1000)
        return True


def run_desktop(url: str, check: bool = False, own_server: bool = True) -> bool:
    """Open the tool in its own window. Returns False if that isn't possible
    here (no pywebview / no WebView2), so the caller can use the browser.

    own_server: this process runs the server behind the window, so later
    launches can find this window and bring it to the front."""
    try:
        import webview
    except Exception:
        return False
    from ipoforms import paths
    import server

    api = DesktopApi(url)
    result = {"loaded": False}
    window = webview.create_window(
        "IPO Form Filler", url, js_api=api, width=1280, height=860, min_size=(900, 600),
        hidden=check, text_select=True, background_color="#12161c")
    api._window = window  # private: not exposed to the page
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True

    def bring_to_front() -> None:
        """Called when the app is started again while this window is open."""
        window.restore()
        window.show()
        window.on_top = True     # pop above other windows...
        window.on_top = False    # ...without staying pinned there

    def after_start() -> None:
        if own_server:
            server.INSTANCE.update(window=True, focus=None if check else bring_to_front)
        if not check:
            return
        # --check-desktop: wait until the page has drawn its home screen, then close.
        for _ in range(60):
            try:
                # the home screen has drawn AND the page can reach Save / PDF functions
                if window.evaluate_js("!!document.querySelector('#pick') && "
                                      "typeof window.pywebview?.api?.save === 'function' && "
                                      "typeof window.pywebview?.api?.show_pdf === 'function'"):
                    # ...and a second launch would see that this copy has a window
                    with urllib.request.urlopen(url + "api/instance", timeout=5) as r:
                        result["loaded"] = bool(json.load(r).get("window"))
                    break
            except Exception:
                pass
            time.sleep(0.5)
        window.destroy()

    # Window storage (unsaved-change drafts) is kept between runs.
    storage = paths.APP_DATA_ROOT / "WebView"
    icon = Path(getattr(sys, "_MEIPASS", ROOT)) / "app.ico"
    try:
        webview.start(after_start, gui="edgechromium" if os.name == "nt" else None,
                      private_mode=False, storage_path=str(storage),
                      icon=str(icon) if icon.exists() else None)
    except Exception as exc:  # noqa: BLE001 - e.g. WebView2 runtime missing
        if check:
            print("desktop window failed:", exc)
        return False
    finally:
        if own_server:
            server.INSTANCE.update(window=False, focus=None)
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
    httpd, url, existing = start_server(server.Handler, port, wait=0 if check else STARTUP_WAIT)
    if httpd is None:
        # Another copy already serves these same clients: never start a second
        # server - show that copy instead.
        if check:
            print("launcher check: FAILED - another copy is using", url)
            sys.exit(1)
        if existing.get("window") and focus_existing(url):
            return                                   # its window is now in front
        if run_desktop(url, own_server=False):       # it has no window: open one onto it
            return
        webbrowser.open(url)
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

    # Versions 1.1 - 1.2.1 kept clients in a "data" folder next to the .exe.
    # Bring those in once; from now on every copy uses the one fixed folder.
    for old in paths.legacy_data_dirs():
        added = server.STORE.import_once(old / "clients.json")
        if added:
            show_message("IPO Form Filler - clients moved",
                         f"{added} client{'s' if added != 1 else ''} saved by an earlier version "
                         f"(in {old}) {'have' if added != 1 else 'has'} been brought in.\n\n"
                         "From now on all your clients are kept in one place on this computer:\n"
                         f"{paths.data_dir()}\n\n"
                         "Any copy or newer version of the app uses them automatically - nothing to copy. "
                         "The old folder next to the app is no longer used and can be deleted.")

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
