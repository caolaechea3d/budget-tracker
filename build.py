"""Build Budget Tracker as a Windows app.

    python -m pip install -r requirements-dev.txt     (once: installs PyInstaller)
    python build.py

Creates, in dist/:
  Budget Tracker/                         the app: Budget Tracker.exe and the files it needs
  BudgetTracker-<version>-portable.zip    unzip anywhere and run; data stays inside that folder
  BudgetTracker-<version>-setup.exe       a normal installer (only if Inno Setup 6 is installed)

The version comes from expense_tracker/__init__.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from expense_tracker import APP_NAME, __version__  # noqa: E402
from expense_tracker.paths import PORTABLE_MARKER  # noqa: E402

DIST = ROOT / "dist"
BUILD = ROOT / "build"
ICON = ROOT / "assets" / "app.ico"
INSTALLER_DIR = ROOT / "installer"
EMOJI_FONT = Path(r"C:\Windows\Fonts\seguiemj.ttf")
ICON_COLOR = (67, 170, 139)  # the app's green (#43aa8b)
PORTABLE_NOTE = (
    "This file makes Budget Tracker portable: your data is kept in the 'data' folder next to\n"
    "Budget Tracker.exe instead of in your Windows user folder. Don't delete it.\n"
)


def step(text: str) -> None:
    print(f"\n=== {text}")


def make_icon() -> None:
    """A 💰 on a rounded green square, in all the sizes Windows uses."""
    from PIL import Image, ImageDraw, ImageFont

    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((16, 16, size - 16, size - 16), radius=110, fill=(*ICON_COLOR, 255))
    if EMOJI_FONT.exists():
        glyph = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
        ImageDraw.Draw(glyph).text((150, 150), "💰", font=ImageFont.truetype(str(EMOJI_FONT), 109),
                                   embedded_color=True, anchor="mm")
        glyph = glyph.crop(glyph.getbbox())
        glyph = glyph.resize((330, round(330 * glyph.height / glyph.width)), Image.LANCZOS)  # ~65% of the icon
        img.alpha_composite(glyph, ((size - glyph.width) // 2, (size - glyph.height) // 2))
    ICON.parent.mkdir(exist_ok=True)
    img.save(ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"Icon: {ICON}")


def run_pyinstaller() -> Path:
    for folder in (BUILD, DIST / APP_NAME):
        shutil.rmtree(folder, ignore_errors=True)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--windowed",  # no console window
        "--name", APP_NAME,
        "--icon", str(ICON),
        "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(BUILD),
        str(ROOT / "main.py"),
    ], check=True, cwd=ROOT)
    app_dir = DIST / APP_NAME
    if (app_dir / PORTABLE_MARKER).exists():  # the installed version must keep data in %APPDATA%
        raise SystemExit(f"{PORTABLE_MARKER} must not be in {app_dir}")
    return app_dir


def make_portable_zip(app_dir: Path) -> Path:
    zip_path = DIST / f"BudgetTracker-{__version__}-portable.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for file in sorted(app_dir.rglob("*")):
            if file.is_file():
                z.write(file, Path(APP_NAME) / file.relative_to(app_dir))
        z.writestr(f"{APP_NAME}/{PORTABLE_MARKER}", PORTABLE_NOTE)
        z.write(INSTALLER_DIR / "READ ME FIRST.txt", f"{APP_NAME}/READ ME FIRST.txt")
    return zip_path


def find_inno_setup() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    return next((p for p in candidates if p.exists()), None)


def make_installer(app_dir: Path) -> Path | None:
    iscc = find_inno_setup()
    if iscc is None:
        print("Inno Setup 6 isn't installed, so no installer this time (the portable zip is ready).\n"
              "To also get an installer, install Inno Setup 6 (free): https://jrsoftware.org/isinfo.php\n"
              "and run build.py again.")
        return None
    subprocess.run([str(iscc), f"/DAppVersion={__version__}", f"/DSourceDir={app_dir}", f"/DOutputDir={DIST}",
                    str(INSTALLER_DIR / "budget-tracker.iss")], check=True)
    return DIST / f"BudgetTracker-{__version__}-setup.exe"


def size_mb(path: Path) -> str:
    total = path.stat().st_size if path.is_file() else sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return f"{total / 1_000_000:.1f} MB"


def main() -> None:
    print(f"Building {APP_NAME} {__version__}")
    step("Icon")
    make_icon()
    step("PyInstaller")
    app_dir = run_pyinstaller()
    step("Portable zip")
    zip_path = make_portable_zip(app_dir)
    step("Installer")
    setup = make_installer(app_dir)
    step("Done")
    print(f"App folder:   {app_dir}  ({size_mb(app_dir)})")
    print(f"Portable zip: {zip_path}  ({size_mb(zip_path)})")
    if setup:
        print(f"Installer:    {setup}  ({size_mb(setup)})")


if __name__ == "__main__":
    main()
