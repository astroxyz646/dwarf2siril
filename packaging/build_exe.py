"""Build the standalone Dwarf2Siril executable.

    python packaging/build_exe.py            one file  (default)
    python packaging/build_exe.py --onedir   one folder
    python packaging/build_exe.py --both     both, and time each

The default is one file because that is what "just send me the app" means.
A one-file build unpacks itself to a temp folder on every launch, which costs
a few seconds of startup with Qt bundled; the one-folder build starts almost
instantly but is a folder the user has to keep together. Measure with
``--both`` on the machine that matters and pick from the numbers.

PyInstaller is a BUILD-time dependency only. Nothing in dwarf2siril imports
it, and the built app does not need it, Python, or pip.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PACKAGING = Path(__file__).resolve().parent
ROOT = PACKAGING.parent
SPEC = PACKAGING / "Dwarf2Siril.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def run_pyinstaller(onedir: bool) -> Path:
    label = "one-folder" if onedir else "one-file"
    print(f"\n=== Building the {label} version ===")

    env = dict(os.environ)
    env["ONEDIR"] = "1" if onedir else "0"

    # Separate work directories so the two builds cannot contaminate each
    # other's caches when both are built in one go.
    workpath = BUILD / ("onedir" if onedir else "onefile")

    started = time.monotonic()
    result = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            str(SPEC),
            "--noconfirm",
            "--distpath", str(DIST / ("onedir" if onedir else "onefile")),
            "--workpath", str(workpath),
        ],
        cwd=str(ROOT),
        env=env,
    )
    if result.returncode != 0:
        raise SystemExit(f"PyInstaller failed with exit code {result.returncode}")

    target = DIST / ("onedir" if onedir else "onefile")
    exe = (
        target / "Dwarf2Siril" / "Dwarf2Siril.exe"
        if onedir
        else target / "Dwarf2Siril.exe"
    )
    if not exe.exists():   # non-Windows produces no .exe suffix
        alternative = exe.with_suffix("")
        if alternative.exists():
            exe = alternative

    took = time.monotonic() - started
    measured = exe.parent if onedir else exe
    print(f"\n{label}: {exe}")
    print(f"  size  : {human(tree_size(measured))}")
    print(f"  built : {took:.0f}s")
    return exe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onedir", action="store_true", help="one-folder build")
    parser.add_argument("--both", action="store_true", help="build both and compare")
    parser.add_argument(
        "--clean", action="store_true", help="delete dist/ and build/ first"
    )
    args = parser.parse_args()

    if not SPEC.is_file():
        raise SystemExit(f"spec not found: {SPEC}")

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit(
            "PyInstaller is not installed. It is only needed to build:\n"
            "    pip install pyinstaller"
        )

    if args.clean:
        for folder in (DIST, BUILD):
            if folder.exists():
                shutil.rmtree(folder)
                print(f"removed {folder}")

    if args.both:
        run_pyinstaller(onedir=False)
        run_pyinstaller(onedir=True)
    else:
        run_pyinstaller(onedir=args.onedir)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
