"""Start IPO Form Filler: the Windows app (IPO Form Filler.exe is built from
this file) and the double-click starter when running from the source.

Starts the local server, opens the browser and shows a small window with
"Open in browser" and "Stop"; closing the window stops the tool. Starting it
again while it is already running just opens the browser.

    python "IPO Form Filler.pyw" --check     # start, self-test, stop (no window)
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


def main() -> None:
    check = "--check" in sys.argv
    import server   # imported here so a problem is reported in a message box
    from ipoforms import paths

    port = int(os.environ.get("IPO_FORM_FILLER_PORT", PREFERRED_PORT))
    httpd, url = start_server(server.Handler, port, wait=0 if check else STARTUP_WAIT)
    if httpd is None:
        if check:
            print("launcher check: FAILED - another copy is using", url)
            sys.exit(1)
        webbrowser.open(url)
        show_message("IPO Form Filler", "IPO Form Filler is already running.\nIt has been opened in your browser.")
        return
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    if check:   # self-test used by the release checks: no window, no browser
        try:
            ok = self_test(url)
        except Exception as exc:  # noqa: BLE001
            print("check failed:", exc)
            ok = False
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
