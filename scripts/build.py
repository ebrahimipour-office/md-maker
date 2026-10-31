"""Build a standalone md-maker folder + zip for the current OS.

    uv run --with pyinstaller python scripts/build.py

Output: dist/md-maker/ (md-maker[.exe] = CLI, md-maker-gui[.exe] = GUI),
dist/md-maker-<os>.zip and, on Linux, dist/md-maker_<version>_amd64.deb.
Persian + English OCR data are bundled in dist/md-maker/tessdata, so OCR
works without installing anything.
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
    gui = exe.with_name(exe.name.replace("md-maker", "md-maker-gui"))
    if not gui.is_file():  # needs a display to run, so only check it was built
        sys.exit(f"build failed: missing {gui}")

    name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    archive = shutil.make_archive(
        str(DIST / f"md-maker-{name}-{platform.machine().lower()}"), "zip", DIST, "md-maker"
    )
    print(f"built {exe} and {gui.name}\npackaged {archive}")
    if sys.platform.startswith("linux") and shutil.which("dpkg-deb"):
        print(f"packaged {build_deb(app)}")


DESKTOP = """[Desktop Entry]
Type=Application
Name=md-maker
Comment=Convert PDF and DOCX files to Markdown
Exec=md-maker-gui
Icon=text-x-generic
Terminal=false
Categories=Office;Utility;
"""


def build_deb(app: Path) -> Path:
    """Wrap the PyInstaller folder in a .deb: /opt/md-maker + /usr/bin links + menu entry."""
    from importlib.metadata import version

    ver = version("md-maker")
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
    root = ROOT / "build" / "deb"
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(app, root / "opt" / "md-maker", symlinks=True)
    (root / "usr" / "bin").mkdir(parents=True)
    for name in ("md-maker", "md-maker-gui"):
        (root / "usr" / "bin" / name).symlink_to(f"/opt/md-maker/{name}")
    apps = root / "usr" / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / "md-maker.desktop").write_text(DESKTOP)
    (root / "DEBIAN").mkdir()
    size_kb = sum(f.stat().st_size for f in root.rglob("*") if f.is_file() and not f.is_symlink()) // 1024
    (root / "DEBIAN" / "control").write_text(
        f"Package: md-maker\nVersion: {ver}\nArchitecture: {arch}\n"
        "Maintainer: ebrahimipour <ebrahimipour@gmail.com>\n"
        f"Installed-Size: {size_kb}\nSection: utils\nPriority: optional\n"
        "Description: Convert PDF and DOCX files to Markdown, with Persian support\n"
        " Standalone build: pandoc and OCR data are bundled. Includes the md-maker\n"
        " command and the md-maker-gui desktop app.\n"
    )
    subprocess.run(["chmod", "-R", "u+rwX,go+rX,go-w", str(root)], check=True)  # don't ship the build umask
    deb = DIST / f"md-maker_{ver}_{arch}.deb"
    subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(root), str(deb)], check=True)
    return deb


if __name__ == "__main__":
    main()
