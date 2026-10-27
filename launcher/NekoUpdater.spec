from pathlib import Path

launcher_root = Path(SPECPATH)

a = Analysis(
    [str(launcher_root / "src" / "neko_launcher" / "updater" / "main.py")],
    pathex=[str(launcher_root / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The updater self-tests the candidate launcher's Tk runtime out-of-process;
    # bundling a second Tcl/Tk copy here only adds ~8 MiB.
    excludes=["tkinter", "_tkinter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NekoUpdater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
)
