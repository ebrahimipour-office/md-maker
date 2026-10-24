"""Build a standalone md-maker folder + zip for the current OS.

    uv run --with pyinstaller python scripts/build.py

Output: dist/md-maker/ (run md-maker[.exe] inside it) and
dist/md-maker-<os>.zip. Persian + English OCR data are bundled in
dist/md-maker/tessdata, so OCR works without installing anything.
PyInstaller can't cross-compile: build the Windows version on Windows
(scripts/build-windows.ps1).
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def main():
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(DIST), "--workpath", str(ROOT / "build"),
         str(ROOT / "packaging" / "md-maker.spec")],
        check=True,
    )
    app = DIST / "md-maker"

    from md_maker import ocr

    ocr.install(dest=app / "tessdata")

    exe = app / ("md-maker.exe" if sys.platform == "win32" else "md-maker")
    subprocess.run([str(exe), "--help"], check=True, stdout=subprocess.DEVNULL)

    name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    archive = shutil.make_archive(
        str(DIST / f"md-maker-{name}-{platform.machine().lower()}"), "zip", DIST, "md-maker"
    )
    print(f"built {exe}\npackaged {archive}")


if __name__ == "__main__":
    main()
