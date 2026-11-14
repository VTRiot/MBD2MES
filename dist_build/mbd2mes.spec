# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for mbd2mes_app.py（MBD2MES）。

RCZ2MES の dist_build\\rcz2mes.spec（commit 5b31da8。元は LD2MES の ld2mes.spec）からの写し。改変の要点:
入口を mbd2mes_app.py に、同梱を mbd2mes_config.seed.json・channel_map.seed.json・アイコンに（マニュアル・rc_channel_names は無い）。
アイコンの正本は Pic\\ICON\\MBD2MES.ico。**無ければビルドを止める**（既定のアイコンで黙って作らない）。

onefile / console=False（windowed）/ UPX 無効。seed 2 つとアイコンは sys._MEIPASS 直下へ同梱する
（config.seed_path()・channel_map.seed_path()・gui.resolve_icon_path() が frozen 時に _MEIPASS 配下を見るため）。
GUI 起動時（引数なし）はコンソール関連 API を一切呼ばない。CLI/D&D 起動時（引数あり）は console_io.ensure_console_for_cli() が確保する。
`icon=` は exe ファイル自体（Explorer 上の見た目）、窓のタイトルバー・タスクバーは gui.py が iconbitmap(default=...) で適用する。

使い方（リポのルートで）:
    dist_build\\build_exe.bat
（PyInstaller は .spec 内の相対パスを spec 自身のディレクトリ基準で解決する。ここでは SPECPATH 基準で組む。）
"""

import os

block_cipher = None

ROOT_DIR = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON_PATH = os.path.join(ROOT_DIR, "Pic", "ICON", "MBD2MES.ico")
if not os.path.isfile(ICON_PATH):
    raise SystemExit(f"[mbd2mes.spec] icon not found: {ICON_PATH} (the source of truth is Pic\\ICON\\MBD2MES.ico; build stopped)")

# 変換中に窓の端で動く GIF（FB02）。あれば busy.gif として _MEIPASS 直下へ同梱する（mbd2mes/busy_animation.py が読む）。
# 無ければ同梱せず、アプリは GIF なしで動く（絵はあとで置く）
GIF_PATH = os.path.join(ROOT_DIR, "Pic", "anim", "busy.gif")
GIF_DATAS = [(GIF_PATH, ".")] if os.path.isfile(GIF_PATH) else []
if GIF_DATAS:
    # PyInstaller は同梱の名前を元のファイル名のまま _MEIPASS 直下に置く。busy_animation の GIF_FROZEN_NAME と同じ名前（busy.gif）
    assert os.path.basename(GIF_PATH) == "busy.gif"

a = Analysis(
    [os.path.join(ROOT_DIR, "mbd2mes_app.py")],
    # _gen: tools/write_build_info.py が書く _build_info.py（開発起動の sys.path には無い）
    pathex=[ROOT_DIR, os.path.join(SPECPATH, "_gen")],
    binaries=[],
    datas=[
        (os.path.join(ROOT_DIR, "mbd2mes_config.seed.json"), "."),
        (os.path.join(ROOT_DIR, "channel_map.seed.json"), "."),
        (ICON_PATH, "."),
    ] + GIF_DATAS,
    hiddenimports=["mbd2mes.gui", "mbd2mes.__main__", "_build_info"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="mbd2mes",
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
    icon=ICON_PATH,
)
