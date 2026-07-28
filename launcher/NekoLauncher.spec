from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


launcher_root = Path(SPECPATH)
repository_root = launcher_root.parent

datas = [
    (str(repository_root / "image_11.png"), "."),
    (str(repository_root / "icon_app.ico"), "."),
    (str(repository_root / "NotoSansThai-Regular.ttf"), "."),
]
datas += collect_data_files("customtkinter")

proxy_root = repository_root / "ProxyCore"
if proxy_root.is_dir():
    for proxy_file in proxy_root.rglob("*"):
        if proxy_file.is_file():
            datas.append(
                (
                    str(proxy_file),
                    str(Path("ProxyCore") / proxy_file.relative_to(proxy_root).parent),
                )
            )

a = Analysis(
    [str(launcher_root / "src" / "neko_launcher" / "main.py")],
    pathex=[str(launcher_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["keyring.backends.Windows"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(repository_root / "icon_app.ico")],
)
