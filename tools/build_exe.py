"""Build the Windows application: downloads/IPO Form Filler.exe (+ a zip of it).

Needs PyInstaller, pywebview (the app's own window) and Pillow (icon), ideally
in a separate venv:

    python -m venv buildenv
    buildenv\\Scripts\\python -m pip install pyinstaller pywebview pillow
    buildenv\\Scripts\\python tools\\build_exe.py 1.1.0

The .exe contains Python, the web pages, the form definitions and the official
PDFs, so the person running it needs nothing else installed. Client details
are saved in a "data" folder next to the .exe (never inside it).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DOWNLOADS = ROOT / "downloads"
NAME = "IPO Form Filler"
ICON = ROOT / "tools" / "app.ico"

README_TXT = """IPO Form Filler {version}
=========================

Fills in Indian Patent Office forms (Form 1 to 31, incl. 7A, 8A, 18A) from
saved client details and downloads them as editable Word documents.

To start: double-click "IPO Form Filler.exe". It opens in its own window -
no browser needed, and it works without internet (only the automatic PIN code
look-up needs a connection). Closing the window stops the tool.
Nothing needs installing (it uses Microsoft Edge WebView2, built into Windows 10/11).

Your client details are saved on this computer only, in one fixed place:
  %LOCALAPPDATA%\\IPO Form Filler\\data
Every copy and every new version of the app uses them automatically - to
update, just run the new .exe; there is nothing to copy. (The Home screen
shows this folder and has an "Open folder" button for backups.)

If Windows shows "Windows protected your PC": click "More info", then
"Run anyway". (The app is not code-signed, so Windows doesn't recognise it yet.)

https://github.com/vamshipalsani7/FormsPatent
"""


def version_file(version: str) -> Path:
    parts = [int(p) for p in (version.split(".") + ["0", "0", "0"])[:4]]
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(parts)}, prodvers={tuple(parts)}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'IPO Form Filler'),
      StringStruct('FileDescription', 'IPO Form Filler - Indian Patent Office forms'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'IPO Form Filler'),
      StringStruct('OriginalFilename', 'IPO Form Filler.exe'),
      StringStruct('ProductName', 'IPO Form Filler'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    path = BUILD / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y.%m.%d")
    if not ICON.exists():
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_icon.py")], check=True)
    BUILD.mkdir(exist_ok=True)
    try:
        import webview  # noqa: F401  - the .exe must include its own window
    except ImportError:
        sys.exit("pywebview is not installed in this Python: pip install pywebview")
    sep = ";"   # PyInstaller --add-data separator on Windows
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME,
        "--icon", str(ICON),
        "--version-file", str(version_file(version)),
        "--add-data", f"{ROOT / 'web'}{sep}web",
        "--add-data", f"{ROOT / 'forms'}{sep}forms",
        "--add-data", f"{ICON}{sep}.",
        "--paths", str(ROOT),
        "--distpath", str(BUILD / "dist"),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        str(ROOT / f"{NAME}.pyw"),
    ]
    subprocess.run(cmd, check=True, cwd=ROOT)

    exe = BUILD / "dist" / f"{NAME}.exe"
    DOWNLOADS.mkdir(exist_ok=True)
    shutil.copy2(exe, DOWNLOADS / f"{NAME}.exe")
    zip_path = DOWNLOADS / "IPO-Form-Filler-Windows.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(exe, f"{NAME}/{NAME}.exe")
        z.writestr(f"{NAME}/Read me.txt", README_TXT.format(version=version).replace("\n", "\r\n"))
    print(f"Built {exe.name} ({exe.stat().st_size / 1e6:.1f} MB) and {zip_path.name} "
          f"({zip_path.stat().st_size / 1e6:.1f} MB), version {version}")


if __name__ == "__main__":
    main()
