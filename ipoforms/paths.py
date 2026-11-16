"""Where the app's files live - from source or as a packaged Windows .exe.

- RESOURCE_ROOT: the read-only files that ship with the app (web/, forms/).
  When packaged with PyInstaller these are unpacked to a temporary folder.
- data_dir(): where client details are saved. It must survive restarts, so for
  the .exe it is a "data" folder next to the .exe itself, falling back to
  %LOCALAPPDATA%\\IPO Form Filler\\data if that folder can't be written to
  (e.g. the .exe was put in Program Files).
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
FALLBACK_DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "IPO Form Filler" / "data"


def running_from_temp() -> bool:
    """True when the .exe was double-clicked inside the zip without unzipping:
    Windows then runs it from a temporary folder that is later deleted."""
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
    preferred = APP_DIR / "data"
    if not running_from_temp() and _writable(preferred):
        return preferred
    FALLBACK_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return FALLBACK_DATA_DIR
