from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


launcher_root = Path(SPECPATH)
repository_root = launcher_root.parent

datas = [
    (str(repository_root / "Asset" / "setting.png"), "."),
    (str(repository_root / "Asset" / "logo.png"), "."),
    (str(repository_root / "Asset" / "icon_app.ico"), "."),
    (str(repository_root / "Asset" / "computer.png"), "."),
    (str(repository_root / "Asset" / "internet.png"), "."),
    (str(repository_root / "Asset" / "discord-icon-svgrepo-com.png"), "."),
    (str(repository_root / "Asset" / "Sarabun-Regular.ttf"), "."),
    (str(repository_root / "Asset" / "Sarabun-Bold.ttf"), "."),
    (str(repository_root / "Asset" / "Sarabun-OFL.txt"), "."),
]
datas += collect_data_files("customtkinter")



a = Analysis(
    [str(launcher_root / "src" / "neko_launcher" / "main.py")],
    pathex=[str(launcher_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["keyring.backends.Windows"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PIL._avif",
        "PIL._webp",
        "PIL._imagingcms",
        "PIL._imagingmath",
        "httpx._main",
        "rich",
        "pygments",
        "pydoc_data",
        "_pyrepl",
        # Frozen release builds always use the Proxy API + web authentication;
        # the legacy Supabase gateway is source/dev-only and drags in pydantic.
        "supabase",
        "supabase_auth",
        "postgrest",
        "storage3",
        "realtime",
        "gotrue",
        "pydantic",
        "pydantic_core",
    ],
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
    name="NekoLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(repository_root / "Asset" / "icon_app.ico")],
    uac_admin=False,
)
