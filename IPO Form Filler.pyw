"""Double-click to start IPO Form Filler.

A .pyw file is run by Python itself (pythonw), so Windows doesn't treat it as a
downloaded program the way it treats .bat files, and no black console window
appears. A small window shows that the tool is running, with buttons to open it
in the browser or stop it. Closing that window stops the tool.

    python "IPO Form Filler.pyw" --check     # start, self-test, stop (no window)
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# pythonw has no console: give the server somewhere harmless to write.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import server  # noqa: E402  (needs the path set up above)

PREFERRED_PORT = 8765


def already_running(port: int) -> bool:
    """Is IPO Form Filler itself already serving on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/forms", timeout=2) as r:
            return isinstance(json.load(r), list)
    except Exception:
        return False


def free_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port found between 8765 and 8814.")


def show_message(title: str, text: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo(title, text)
        root.destroy()
    except Exception:
        print(f"{title}: {text}")


def main() -> None:
    check = "--check" in sys.argv

    if not check and already_running(PREFERRED_PORT):
        webbrowser.open(f"http://127.0.0.1:{PREFERRED_PORT}/")
        show_message("IPO Form Filler", "IPO Form Filler is already running.\n"
                     "It has been opened in your browser.")
        return

    port = free_port(PREFERRED_PORT)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), server.Handler)
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    if check:   # self-test used by the release checks: no window, no browser
        ok = already_running(port)
        httpd.shutdown()
        print("launcher check:", "OK" if ok else "FAILED", url)
        sys.exit(0 if ok else 1)

    webbrowser.open(url)
    try:
        import tkinter as tk
    except ImportError:        # Python without tkinter: keep serving until killed
        httpd.serve_forever()
        return

    root = tk.Tk()
    root.title("IPO Form Filler")
    root.resizable(False, False)
    frame = tk.Frame(root, padx=22, pady=18)
    frame.pack()
    tk.Label(frame, text="IPO Form Filler is running", font=("Segoe UI", 12, "bold")).pack(anchor="w")
    tk.Label(frame, text=f"Open {url} in your browser.\nKeep this window open while you work;\n"
                         "closing it stops the tool.", justify="left", fg="#444").pack(anchor="w", pady=(6, 14))
    buttons = tk.Frame(frame)
    buttons.pack(anchor="e")

    def stop() -> None:
        httpd.shutdown()
        root.destroy()

    tk.Button(buttons, text="Open in browser", width=16, command=lambda: webbrowser.open(url)).pack(side="left", padx=(0, 8))
    tk.Button(buttons, text="Stop", width=10, command=stop).pack(side="left")
    root.protocol("WM_DELETE_WINDOW", stop)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - show the problem instead of failing silently
        show_message("IPO Form Filler could not start", str(exc))
        raise
