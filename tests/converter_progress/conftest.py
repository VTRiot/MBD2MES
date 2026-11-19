# -*- coding: utf-8 -*-
"""テンプレート自体の試験の共通部品。アプリに依存しない。

窓は利用者の画面に出さない: ダイアログの親は withdraw したままにし、ダイアログを出すときは画面の外の座標（OFFSCREEN）を渡す。
フォーカスを奪う操作（focus_force 等）は使わない。
"""

from __future__ import annotations

import gc
import struct
import sys
import time
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent  # リポのルート（mbd2mes の入っているフォルダ）
if str(TEMPLATES_DIR) not in sys.path:
    sys.path.insert(0, str(TEMPLATES_DIR))

PACKAGE = "mbd2mes.converter_progress"  # 完全な import 名（アプリの中に入れ子で写したら "myapp.converter_progress" の形）
PACKAGE_DIR = TEMPLATES_DIR.joinpath(*PACKAGE.split("."))  # パッケージの実ディレクトリ
OFFSCREEN = (-32000, -32000)  # ダイアログを置く画面の外の座標（試験は親が withdraw のままで何も描かれない。撮影は画面の外では描かれない: scripts/render_dialog_snapshot.py）
TK_RETRIES = 5  # Tk の初期化が数回に 1 回失敗する環境がある。やり直す回数
TK_RETRY_WAIT_S = 0.3
PUMP_STEP_S = 0.005
# 試験用 GIF の組み立て（GIF89a の仕様の値）
GIF_PALETTE = [(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)]  # 0 番を透過に使う
GIF_GLOBAL_PALETTE_FLAGS = 0x81  # グローバルパレットあり・4 色
GIF_DELAY_CS = 12  # コマの待ち時間（1/100 秒）
GIF_GCE_FLAGS = 0x09  # 透過あり・後始末 2
GIF_MIN_CODE_SIZE = 2
GIF_CODE_BITS = 3  # 最小符号長 2 + 1
GIF_CLEAR, GIF_END = 4, 5
GIF_BLOCK_MAX = 255


def make_tk_root():
    tk = pytest.importorskip("tkinter")
    last = None
    for _ in range(TK_RETRIES):
        try:
            root = tk.Tk()
            root.withdraw()
            return root
        except tk.TclError as exc:
            last = exc
            time.sleep(TK_RETRY_WAIT_S)
    pytest.skip(f"Tk unavailable: {last}")


@pytest.fixture()
def root():
    r = make_tk_root()
    yield r
    r.destroy()


def pump(root, seconds: float) -> None:
    """主ループの代わりに、指定の時間 update を回す。"""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(PUMP_STEP_S)


def make_gif(path: Path, frames: int = 3, size: int = 4) -> Path:
    """試験用の小さなアニメーション GIF（透過 1 色・数コマのループ）を手で組む。LZW は 2 画素ごとに clear して符号長を増やさない形。"""
    out = bytearray(b"GIF89a" + struct.pack("<HHBBB", size, size, GIF_GLOBAL_PALETTE_FLAGS, 0, 0))
    for r, g, b in GIF_PALETTE:
        out += bytes((r, g, b))
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"  # ループ
    for f in range(frames):
        out += b"\x21\xf9\x04" + bytes((GIF_GCE_FLAGS, GIF_DELAY_CS, 0, 0)) + b"\x00"
        out += b"," + struct.pack("<HHHHB", 0, 0, size, size, 0)
        pixels = [1 + (f % 3) if (x + y) % 2 == 0 else 0 for y in range(size) for x in range(size)]
        codes = []
        for i in range(0, len(pixels), 2):
            codes += [GIF_CLEAR, *pixels[i:i + 2]]
        codes.append(GIF_END)
        bits, nbits, data = 0, 0, bytearray()
        for c in codes:
            bits |= c << nbits
            nbits += GIF_CODE_BITS
            while nbits >= 8:
                data.append(bits & 0xFF)
                bits >>= 8
                nbits -= 8
        if nbits:
            data.append(bits & 0xFF)
        out += bytes((GIF_MIN_CODE_SIZE,))
        for i in range(0, len(data), GIF_BLOCK_MAX):
            chunk = data[i:i + GIF_BLOCK_MAX]
            out += bytes((len(chunk),)) + bytes(chunk)
        out += b"\x00"
    out += b";"
    path.write_bytes(bytes(out))
    return path


@pytest.fixture(autouse=True)
def gc_guard():
    """どの試験も、GC の状態と JobRunner の参照数を元に戻して終わること（戻っていなければ、その試験を失敗にする）。"""
    jobs = __import__("importlib").import_module(f"{PACKAGE}.jobs")
    before = gc.isenabled()
    yield
    leaked, after = jobs._GC_JOBS, gc.isenabled()
    gc.enable() if before else gc.disable()  # 失敗した試験が、後の試験へ状態を残さない
    jobs._GC_JOBS = 0
    assert leaked == 0, "a JobRunner left the GC held"
    assert after == before, "the GC state was not restored"
