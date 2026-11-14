# -*- coding: utf-8 -*-
"""進捗ダイアログの見た目を PNG に撮る（FB03。Windows 専用）。利用者の画面には出さない:

  - 窓は画面の外（-32000, -32000 付近）に置く（利用者の目には入らない）。タスクバーにも出ない（tool window）・
    アクティブにしない（WS_EX_NOACTIVATE）。撮った後、前面だった窓へ戻す
  - 撮るのは Win32 の PrintWindow（PW_RENDERFULLCONTENT）。窓が画面の外・他の窓の後ろでも、その窓の中身を描き出せる

  python -I tools/render_dialog_snapshot.py <出力フォルダ> [GIF のパス]

出力: <出力フォルダ>/dialog_with_gif.png（GIF あり・進行中）・dialog_no_gif.png（GIF なし）・dialog_cancelling.png（Cancel を押した後）
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OFFSCREEN = -32000
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0
BI_RGB = 0

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetForegroundWindow.restype = wintypes.HWND
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


def top_hwnd(widget: tk.Misc) -> int:
    """Tk の最上位の窓の HWND（タイトルバーを含む枠）。"""
    widget.update_idletasks()
    frame = widget.wm_frame()
    return int(frame, 16) if frame and int(frame, 16) else widget.winfo_id()


def quiet_style(hwnd: int) -> None:
    """アクティブにならない・タスクバーに出ない窓にする。"""
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)


def capture(hwnd: int, path: Path) -> tuple[int, int]:
    """hwnd の窓を PrintWindow で描き出して PNG に保存する。(幅, 高さ)。"""
    from PIL import Image

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        if not user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT):
            raise OSError("PrintWindow failed")
        gdi32.SelectObject(mem, old)  # GetDIBits は、ビットマップが DC に選ばれていない状態で呼ぶ
        header = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, BI_RGB, 0, 0, 0, 0, 0)  # 上から下へ
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(header), DIB_RGB_COLORS):
            raise OSError("GetDIBits failed")
        Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB").save(path)
    finally:
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(None, screen)
    return w, h


def pump(root: tk.Misc, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.01)


def main() -> int:
    out_dir = Path(sys.argv[1])
    gif = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MBD2MES_SETTINGS_DIR"] = tempfile.mkdtemp(prefix="mbd2mes_snap_")
    from mbd2mes import progress as prg
    from mbd2mes import progress_dialog as pd

    previous = user32.GetForegroundWindow()
    root = tk.Tk()
    root.withdraw()
    root.title("MBD2MES")
    root.geometry(f"900x640+{OFFSCREEN}+{OFFSCREEN}")  # 親窓: 画面の外
    root.attributes("-toolwindow", True)
    root.update_idletasks()
    quiet_style(top_hwnd(root))
    root.deiconify()
    root.update()
    made = []
    try:
        clock = [1000.0]
        cases = [("dialog_with_gif.png", gif, False), ("dialog_no_gif.png", out_dir / "__none__.gif", False),
                 ("dialog_cancelling.png", gif, True)]
        for name, gif_path, cancel in cases:
            clock[0] = 1000.0  # 1 つ目の画面ごとに、経過時間を 0 から数え直す
            d = pd.ProgressDialog(root, on_cancel=lambda: None, gif_path=gif_path, clock=lambda: clock[0])
            d.attributes("-toolwindow", False)  # 本物と同じ見た目（タイトルバーの形）を撮る
            d.update_idletasks()
            hwnd = top_hwnd(d)
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE)  # アクティブにしない（タスクバーの形は本物のまま）
            d.update()
            ev = prg.make_event(2, 5, "26.11.8鈴鹿サンデーR4決勝.MBD", 1, 0.45)
            d.update_progress(ev)
            clock[0] = 1000.0 + 24
            if cancel:
                d.request_cancel()
            else:
                d.update_progress(ev)
            d._tick()
            d.update()
            if d.animation.loaded:
                pump(d, 0.25)  # GIF が動いている途中のコマ
            path = out_dir / name
            w, h = capture(hwnd, path)
            made.append((path, w, h))
            d.close()
    finally:
        root.destroy()
        if previous:
            user32.SetForegroundWindow(previous)  # 前面だった窓へ戻す
    for path, w, h in made:
        print(f"{path} ({w}x{h})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
