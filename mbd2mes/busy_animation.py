# -*- coding: utf-8 -*-
"""busy_animation.py -- 窓の端に置く、変換中だけ動く小さなアニメーション GIF（FB02）。

絵は別に作られ、らいおが選ぶ。ここは「置く場所」と「変換中だけ再生して止める仕組み」だけを持つ。
  - GIF の場所は GIF_RELATIVE_PATH の 1 か所（開発起動: リポ直下からの相対。exe: spec が _MEIPASS 直下へ busy.gif として同梱する）。
    環境変数 MBD2MES_BUSY_GIF があれば、そのファイルを使う（絵を試すときの差し替え口。試験にも使う）
  - GIF が無い・読めない・コマが 0 のときは、何も出さず、何も起こさない（start/stop は何もしない）
  - 大きさは約 1.5 cm 四方（GIF_SIZE_CM。画面の dpi で何 px かは recommended_size_px）。素材の大きさが違っても、長い辺が約 1.5 cm に
    なる整数倍で縮める・拡げる（PhotoImage の zoom・subsample。ちょうどにはならないことがある）。透過は GIF の 1 色。数コマのループ
  - Tk の PhotoImage は GIF のコマごとの待ち時間を読めないので、コマの間隔は FRAME_MS の定数（全コマ同じ）
"""

from __future__ import annotations

import math
import os
import sys
import tkinter as tk
from pathlib import Path

from . import config as cfgmod

GIF_RELATIVE_PATH = ("Pic", "anim", "busy.gif")  # アニメーション GIF の置き場（1 か所。差し替えはこのファイルを置き換える）
GIF_FROZEN_NAME = "busy.gif"  # exe の中（_MEIPASS 直下）での名前。dist_build/mbd2mes.spec が同梱する
GIF_ENV = "MBD2MES_BUSY_GIF"
GIF_SIZE_CM = 1.5  # 画面の端に置く大きさ（約 1.5 cm 四方）
FRAME_MS = 120  # コマの間隔（ミリ秒）
MAX_FRAMES = 200  # 読み込むコマの上限（壊れた GIF で止まらないように）
MARGIN_PX = 6  # 窓の端からの余白


def resolve_gif_path() -> Path:
    """GIF の場所。環境変数 > exe の中 > リポ直下の Pic/anim/busy.gif。ファイルの有無は見ない。"""
    override = os.environ.get(GIF_ENV)
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / GIF_FROZEN_NAME
    return cfgmod.app_base_dir().joinpath(*GIF_RELATIVE_PATH)


def recommended_size_px(root: tk.Misc) -> int:
    """約 1.5 cm 四方に当たる px（この画面の dpi で）。絵を作る側への目安。"""
    return round(root.winfo_fpixels(f"{GIF_SIZE_CM}c"))


def scale_factors(width: int, height: int, target_px: int) -> tuple[int, int]:
    """(拡大の倍率, 縮小の倍率)。PhotoImage の zoom・subsample は整数倍なので、変換後の長い辺が target_px に（絶対差で）最も近くなる
    整数倍を選ぶ（隣り合う 2 つの倍率の変換後の大きさを比べる。どちらか一方が 1。ちょうど近ければ両方 1）。長い辺が 0 以下なら (1, 1)。
    縮小後の大きさは subsample の定義（切り上げ）に合わせる。"""
    longest = max(width, height)
    if longest <= 0 or target_px <= 0:
        return 1, 1
    if longest >= target_px:
        ratio = longest / target_px
        candidates = sorted({max(1, math.floor(ratio)), max(1, math.ceil(ratio))})
        best = min(candidates, key=lambda n: (abs(math.ceil(longest / n) - target_px), n))
        return 1, best
    ratio = target_px / longest
    candidates = sorted({max(1, math.floor(ratio)), max(1, math.ceil(ratio))})
    best = min(candidates, key=lambda n: (abs(longest * n - target_px), n))
    return best, 1


def fit_frames(frames: list[tk.PhotoImage], target_px: int) -> list[tk.PhotoImage]:
    """コマを、長い辺が約 target_px になる整数倍へ縮める・拡げる。透過は保たれる。倍率が 1 ならそのまま。"""
    if not frames:
        return frames
    zoom, sub = scale_factors(frames[0].width(), frames[0].height(), target_px)
    if zoom == 1 and sub == 1:
        return frames
    return [f.zoom(zoom) if zoom > 1 else f.subsample(sub) for f in frames]


def load_frames(path: Path, master: tk.Misc) -> list[tk.PhotoImage]:
    """GIF のコマを全部読む。読めなければ空のリスト（例外にしない）。コマは master（この窓の root）に属させる
    （master を渡さないと、最初に作られた別の root に属して、窓が替わると「image doesn't exist」になる）。"""
    frames: list[tk.PhotoImage] = []
    try:
        if not Path(path).is_file():
            return frames
        for i in range(MAX_FRAMES):
            try:
                frames.append(tk.PhotoImage(master=master, file=str(path), format=f"gif -index {i}"))
            except tk.TclError:
                break  # コマの終わり（最初のコマで失敗なら frames は空 = 読めない GIF）
    except (OSError, tk.TclError, ValueError):
        return []
    return frames


class BusyAnimation:
    """GIF を master の中に置き、start() の間だけ再生し、stop() で止める（止めたら最初のコマを静止して見せる）。

    attach(label): 置き方を決める関数（FB03: 進捗ダイアログの右の余白へ grid で置く）。None なら、master の右上の端へ place する
    （FB02 の窓の端。今のメイン窓は使わない）。GIF が無ければ label は作らず、attach も呼ばない（余白を取らない）。"""

    def __init__(self, root: tk.Misc, gif_path: Path | None = None, frame_ms: int = FRAME_MS, attach=None) -> None:
        self._root = root
        self._frame_ms = frame_ms
        self._index = 0
        self._after_id = None
        self.running = False
        self.path = Path(gif_path) if gif_path is not None else resolve_gif_path()
        self.frames = fit_frames(load_frames(self.path, root), recommended_size_px(root))  # 約 1.5 cm に合わせる（整数倍）
        self.label: tk.Label | None = None
        if self.frames:
            self.label = tk.Label(root, image=self.frames[0], borderwidth=0, highlightthickness=0, bg=root.cget("bg"))
            if attach is not None:
                attach(self.label)
            else:
                self.label.place(relx=1.0, x=-MARGIN_PX, y=MARGIN_PX, anchor="ne")  # 右上の端

    @property
    def loaded(self) -> bool:
        return bool(self.frames)

    def start(self) -> bool:
        """再生を始める。GIF が無ければ何もしない（False）。"""
        if not self.frames or self.label is None or self.running:
            return self.running
        self.running = True
        self._index = 0
        self._step()
        return True

    def _step(self) -> None:
        if not self.running or self.label is None:
            return
        self.label.configure(image=self.frames[self._index])
        self._index = (self._index + 1) % len(self.frames)
        self._after_id = self._root.after(self._frame_ms, self._step)

    def release(self) -> None:
        """止めて、コマを手放す（PhotoImage の後始末を、呼んだスレッド = 主スレッドで済ませるため。別スレッドで回収されると
        「main thread is not in main loop」が出うる）。"""
        self.stop()
        self.frames = []
        self.label = None

    def stop(self) -> None:
        """再生を止める（最初のコマを静止して見せる）。GIF が無ければ何もしない。"""
        self.running = False
        if self._after_id is not None:
            try:
                self._root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self.label is not None and self.frames:
            self.label.configure(image=self.frames[0])
            self._index = 0
