"""Where the app's files live - from source or as the packaged Windows .exe.

- RESOURCE_ROOT: the read-only files that ship with the app (web/, forms/).
  In the .exe these are unpacked to a temporary folder at start-up.
- data_dir(): where client details are saved.
    * The .exe always uses ONE fixed folder on this computer, for this Windows
      user:  %LOCALAPPDATA%\\IPO Form Filler\\data
      Every copy and every version of the app shares it, wherever the .exe is
      kept - so updating means just running the new .exe; nothing is copied.
    * Run from the source code (python server.py), the project's own data/
      folder is used, as before.
- legacy_data_dirs(): folders older versions (1.1 - 1.2.1) used - a "data"
  folder next to the .exe - so their clients can be brought in once.
"""

from __future__ import annotations

import os
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
SOURCE_ROOT = Path(__file__).resolve().parent.parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)) if FROZEN else SOURCE_ROOT
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else SOURCE_ROOT
APP_DATA_ROOT = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "IPO Form Filler"
APP_DATA_DIR = APP_DATA_ROOT / "data"
FALLBACK_DATA_DIR = APP_DATA_DIR      # name kept for older code paths


def running_from_temp() -> bool:
    """True when the .exe was double-clicked inside the zip without unzipping
    (Windows then runs it from a temporary folder)."""
    if not FROZEN:
        return False
    try:
        APP_DIR.relative_to(Path(tempfile.gettempdir()).resolve())
        return True
    except ValueError:
        return False


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def data_dir() -> Path:
    if FROZEN:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        return APP_DATA_DIR
    preferred = SOURCE_ROOT / "data"
    if _writable(preferred):
        return preferred
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return APP_DATA_DIR


def legacy_data_dirs() -> list[Path]:
    """Where older versions of the .exe (1.1 - 1.2.1) may have saved clients:
    a "data" folder next to that .exe. Checked: next to this .exe, and copies
    of the app unzipped in the usual places - Downloads, Desktop, Documents -
    since a new version is often unzipped to a different folder.
    (Only for the packaged app.)"""
    if not FROZEN:
        return []
    candidates = [APP_DIR / "data"]
    home = Path.home()
    for place in (home / "Downloads", home / "Desktop", home / "Documents"):
        if not place.is_dir():
            continue
        try:   # e.g. Downloads\IPO Form Filler\data, Downloads\IPO-Form-Filler-Windows\IPO Form Filler\data
            for pattern in ("IPO*Form*Filler*/data", "IPO*Form*Filler*/IPO*Form*Filler*/data"):
                candidates.extend(sorted(place.glob(pattern)))
        except OSError:
            continue
    mine = data_dir().resolve()
    found, seen = [], set()
    for folder in candidates:
        try:
            key = os.path.normcase(str(folder.resolve()))
            if key in seen or folder.resolve() == mine or not (folder / "clients.json").is_file():
                continue
        except OSError:
            continue
        seen.add(key)
        found.append(folder)
    return found
