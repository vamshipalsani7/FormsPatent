"""Tests for the Windows app side: start-up, ports and where data is kept.

Run with the rest:  python -m unittest discover -s tests
"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


def load_launcher():
    path = ROOT / "IPO Form Filler.pyw"
    loader = importlib.machinery.SourceFileLoader("ipo_launcher", str(path))
    spec = importlib.util.spec_from_loader("ipo_launcher", loader)
    module = importlib.util.module_from_spec(spec)
    cwd = os.getcwd()
    try:
        loader.exec_module(module)
    finally:
        os.chdir(cwd)   # the launcher changes directory to the app folder
    return module


def free_port() -> int:
    s = server.AppServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = s.server_address[1]
    s.server_close()
    return port


class PortTests(unittest.TestCase):
    def test_a_second_copy_cannot_take_the_same_port(self):
        first = server.AppServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        try:
            with self.assertRaises(OSError):
                server.AppServer(("127.0.0.1", first.server_address[1]), BaseHTTPRequestHandler)
        finally:
            first.server_close()

    def test_launcher_reuses_a_running_copy_instead_of_starting_another(self):
        launcher = load_launcher()
        port = free_port()
        running = server.AppServer(("127.0.0.1", port), server.Handler)
        threading.Thread(target=running.serve_forever, daemon=True).start()
        try:
            httpd, url = launcher.start_server(server.Handler, port, wait=0)
            self.assertIsNone(httpd)                      # -> just opens the browser
            self.assertEqual(url, f"http://127.0.0.1:{port}/")
        finally:
            running.shutdown(); running.server_close()

    def test_launcher_moves_to_another_port_if_a_different_program_has_it(self):
        launcher = load_launcher()
        port = free_port()
        other = server.AppServer(("127.0.0.1", port), BaseHTTPRequestHandler)   # not our tool
        threading.Thread(target=other.serve_forever, daemon=True).start()
        try:
            httpd, url = launcher.start_server(server.Handler, port, wait=0)
            self.assertIsNotNone(httpd)
            self.assertNotEqual(httpd.server_address[1], port)
            httpd.server_close()
        finally:
            other.shutdown(); other.server_close()

    def test_launcher_self_test_passes(self):
        env = dict(os.environ, IPO_FORM_FILLER_PORT=str(free_port()))
        out = subprocess.run([sys.executable, str(ROOT / "IPO Form Filler.pyw"), "--check"],
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("launcher check: OK", out.stdout)


class PackagedPathTests(unittest.TestCase):
    """Imitate the packaged .exe (sys.frozen) in a separate Python process."""

    def run_frozen(self, exe_dir: Path, meipass: Path, localappdata: Path) -> dict:
        code = f"""
import sys, json
sys.frozen = True
sys._MEIPASS = {str(meipass)!r}
sys.executable = {str(exe_dir / 'IPO Form Filler.exe')!r}
sys.path.insert(0, {str(ROOT)!r})
from ipoforms import paths
print(json.dumps({{"resource": str(paths.RESOURCE_ROOT), "data": str(paths.data_dir()),
                  "temp": paths.running_from_temp()}}))
"""
        env = dict(os.environ, LOCALAPPDATA=str(localappdata))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_data_is_saved_next_to_the_exe(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory(dir=ROOT) as app:
            r = self.run_frozen(Path(app), Path(home) / "_MEI1", Path(home) / "local")
            self.assertEqual(Path(r["data"]), Path(app) / "data")
            self.assertEqual(Path(r["resource"]), Path(home) / "_MEI1")
            self.assertFalse(r["temp"])

    def test_exe_opened_inside_the_zip_saves_data_somewhere_permanent(self):
        with tempfile.TemporaryDirectory() as tmp:   # Windows runs it from %TEMP%
            exe_dir = Path(tmp) / "Temp1_IPO-Form-Filler-Windows.zip" / "IPO Form Filler"
            exe_dir.mkdir(parents=True)
            r = self.run_frozen(exe_dir, Path(tmp) / "_MEI2", Path(tmp) / "local")
            self.assertTrue(r["temp"])
            self.assertEqual(Path(r["data"]), Path(tmp) / "local" / "IPO Form Filler" / "data")


if __name__ == "__main__":
    unittest.main()
