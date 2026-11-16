"""Build the downloadable zip that others unzip and run.

    python tools/make_release.py 1.0.0

Writes downloads/IPO-Form-Filler.zip containing one folder, IPO-Form-Filler/,
with only the files git tracks - so nothing in data/ (your clients) can ever be
included. Tests and this tools/ folder are left out.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "downloads" / "IPO-Form-Filler.zip"
TOP = "IPO-Form-Filler"
SKIP_PREFIXES = ("tests/", "tools/", "downloads/", ".git")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y.%m.%d")
    files = [f for f in tracked_files() if not f.startswith(SKIP_PREFIXES)]

    # Belt and braces: client data must never be packaged.
    private = [f for f in files if f.startswith("data/") and f != "data/.gitkeep"]
    if private:
        sys.exit(f"Refusing to build: client data is tracked by git: {private}")

    OUT.parent.mkdir(exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in sorted(files):
            data = (ROOT / rel).read_bytes()
            if rel.endswith(".bat"):          # Windows batch files need CRLF
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            elif rel.endswith(".sh"):         # shell scripts need LF
                data = data.replace(b"\r\n", b"\n")
            info = zipfile.ZipInfo(f"{TOP}/{rel}", date_time=datetime.now().timetuple()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if rel.endswith(".sh") else 0o644) << 16
            z.writestr(info, data)
        info = zipfile.ZipInfo(f"{TOP}/VERSION.txt", date_time=datetime.now().timetuple()[:6])
        info.external_attr = 0o644 << 16
        z.writestr(info, f"IPO Form Filler {version}\nBuilt {datetime.now():%Y-%m-%d}\n")
    tmp.replace(OUT)
    print(f"Built {OUT.relative_to(ROOT)}  ({len(files) + 1} files, {OUT.stat().st_size / 1e6:.1f} MB)  version {version}")


if __name__ == "__main__":
    main()
