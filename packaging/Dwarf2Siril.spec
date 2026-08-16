# PyInstaller spec for Dwarf2Siril.
#
# Build with:   python packaging/build_exe.py
# or directly:  python -m PyInstaller packaging/Dwarf2Siril.spec --noconfirm
#
# Pass ONEDIR=1 in the environment for a one-folder build instead of the
# default single file. See build_exe.py for which to choose and why.
#
# PyInstaller runs this file as a script with its own globals injected, so
# `Analysis`, `PYZ`, `EXE` and `SPECPATH` are not undefined names here.

import os
import sys

ONEDIR = os.environ.get("ONEDIR") == "1"

# Set DEBUG_CONSOLE=1 to build with a console attached. The shipped app is
# windowed, which means a failure before the window opens leaves nothing to
# read; this is how you find out what it was.
DEBUG_CONSOLE = os.environ.get("DEBUG_CONSOLE") == "1"

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

# PySide6 ships the whole of Qt. We use QtCore, QtGui and QtWidgets and
# nothing else, so everything below is dead weight -- and QtWebEngine alone
# is well over 100 MB. Excluding them is the difference between an exe the
# operator can move around and one they cannot.
EXCLUDED_QT = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtLocation",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtNfc",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtPositioning", "PySide6.QtQml",
    "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtSensors", "PySide6.QtSerialBus", "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio", "PySide6.QtSql", "PySide6.QtStateMachine",
    "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtTest",
    "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
]

# The standard library also brings in things a FITS-and-folders tool has no
# use for. tkinter in particular would ship a second GUI toolkit.
EXCLUDED_STDLIB = [
    "tkinter", "unittest", "pydoc", "doctest", "test",
    # Development-only live reload. Excluded so it is not merely inert in a
    # shipped build but absent from it.
    "dwarf2siril.gui.devreload",
    "lib2to3", "distutils", "setuptools", "pip",
    "numpy", "matplotlib", "PIL", "scipy", "pandas",
]

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    # The icon is set on the exe itself for Explorer and the taskbar, and
    # bundled as data so the running app can set it as its window icon too.
    # Without the data copy the exe has an icon on disk but Qt draws its own
    # in the title bar, which is exactly the mismatch this is meant to fix.
    datas=(
        [(os.path.join(SPECPATH, "icon.ico"), ".")]
        if os.path.exists(os.path.join(SPECPATH, "icon.ico"))
        else []
    ),
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDED_QT + EXCLUDED_STDLIB,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

ICON = os.path.join(SPECPATH, "icon.ico")
icon_arg = ICON if os.path.exists(ICON) else None

if ONEDIR:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="Dwarf2Siril",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=DEBUG_CONSOLE,  # windowed by default: no console flashing up
        icon=icon_arg,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="Dwarf2Siril",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="Dwarf2Siril",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        runtime_tmpdir=None,
        console=DEBUG_CONSOLE,
        icon=icon_arg,
    )

