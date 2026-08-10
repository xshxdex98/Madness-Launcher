# PyInstaller spec for Madness Launcher.
#
# Builds ONE self-contained executable: the launcher, a private copy of Python
# and the Qt libraries it needs, in a single file. Whoever you hand it to
# installs nothing and has nothing to unpack.
#
#     build_exe.bat        ->  dist\MadnessLauncher.exe
#
# Deliberately one file rather than a folder. The folder build produces two
# identically named executables - the real one in dist\, and a non-functional
# stub in build\ - and running the stub fails with "Failed to load Python DLL
# ...\_internal\python310.dll". That is an easy mistake to make and an
# impossible error to interpret. One file cannot be got wrong.
#
# Qt modules are excluded aggressively. PySide6-Addons pulls in WebEngine, 3D,
# Charts, and a browser's worth of dependencies; bundling those would triple the
# download for a launcher that needs none of them. QtMultimedia is kept, since
# the Overview tab's background video and the chat notification sound need it.

from pathlib import Path

block_cipher = None

a = Analysis(
    ["launcher_main.py"],
    pathex=[],
    binaries=[],
    # The window icon is loaded at runtime, so unlike the EXE icon it has to
    # be inside the bundle rather than only stamped onto the file.
    datas=[(str(Path(SPECPATH) / "assets" / "madness_crew.ico"), "assets")],
    hiddenimports=[
        # Reached only through Qt's plugin system, so not found by the
        # import scanner.
        "PySide6.QtNetwork",        # IRC's QSslSocket, and the news fetcher
        "PySide6.QtMultimedia",     # video backdrop + notification tone
    ],
    # News thumbnails come back as JPEG, which Qt decodes through an image
    # format plugin rather than through QtGui itself. PySide6's hook collects
    # the imageformats directory, so nothing extra is needed here — but if a
    # future exclude ever strips plugins, video cards lose their pictures
    # while everything else keeps working, which is a hard symptom to trace.
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
        "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtQuick3D", "PySide6.QtBluetooth", "PySide6.QtNfc",
        "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSerialPort",
        "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest",
        "PySide6.QtSql", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
        "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
        "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
        # Not a GUI app dependency; PyInstaller picks these up by association.
        "tkinter", "unittest", "pydoc", "doctest", "pdb",
        "matplotlib", "numpy", "PIL", "setuptools", "pip",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MadnessLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # A GUI app: no console window. Safe here in a way it is not for run.bat,
    # because everything the launcher needs is inside this file - there is no
    # missing-dependency error left to hide.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Unpacks to a temp folder on each run, which costs a couple of seconds at
    # startup. Worth it for a single file that cannot be mis-distributed.
    runtime_tmpdir=None,
    # Madness Crew artwork, rebuilt from assets/madness_crew.png by
    # tools/make_icon.py. The launcher sets no window icon of its own, so
    # Windows uses this for the titlebar and taskbar as well as for the file.
    icon=str(Path(SPECPATH) / "assets" / "madness_crew.ico"),
)
