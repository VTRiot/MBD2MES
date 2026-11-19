# -*- coding: utf-8 -*-
"""busy_animation.py -- 窓の端に置く、変換中だけ動く小さなアニメーション GIF。tk 以外に依存しない。

アプリ側で決めること（GifLocation で渡す。ProgressDialog の gif_location 引数）:
  - env_var: 絵を試すときの差し替え口にする環境変数の名前（None なら使わない）。設定されていれば、そのファイルを使う（無くても。試験が GIF なしを作るのに使う）
  - base_dir: 開発起動のときの基準フォルダ（Path か、Path を返す関数。None なら起動したスクリプトのあるフォルダ）
  - relative_path: base_dir からの GIF の相対位置（既定 Pic/anim/busy.gif）
  - frozen_name: exe の中（PyInstaller の _MEIPASS 直下）での名前（既定 busy.gif）。exe にこの名前で同梱する（spec の datas）。同梱を確かめる試験をアプリ側に置く
  絵そのものは別に作られる。ここは「置く場所」と「変換中だけ再生して止める仕組み」だけを持つ。

動き:
  - GIF が無い・読めない・コマが 0 のときは、何も出さず、何も起こさない（start/stop は何もしない。attach も呼ばない = 余白を取らない）
  - 大きさは約 1.5 cm 四方（GIF_SIZE_CM。画面の dpi で何 px かは recommended_size_px）。素材の大きさが違っても、長い辺が約 1.5 cm に
    なる整数倍で縮める・拡げる（PhotoImage の zoom・subsample。ちょうどにはならないことがある）。透過は GIF の 1 色。数コマのループ
  - Tk の PhotoImage は GIF のコマごとの待ち時間を読めないので、コマの間隔は FRAME_MS の定数（全コマ同じ）

踏んだ地雷:
  - PhotoImage には必ず master を渡す。渡さないと、最初に作られた別の root に属して、窓が替わると「image doesn't exist」になる
  - コマの後始末（PhotoImage の回収）が別スレッドで走ると「main thread is not in main loop」が出うる。release() は主スレッドで呼んでコマを手放す
  - 壊れた GIF でコマを無限に読まない（MAX_FRAMES）
"""

from __future__ import annotations

import base64
import math
import os
import sys
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Union

DEFAULT_RELATIVE_PATH = ("Pic", "anim", "busy.gif")  # 開発起動の GIF の置き場（base_dir からの相対）
DEFAULT_FROZEN_NAME = "busy.gif"  # exe の中（_MEIPASS 直下）での名前
GIF_SIZE_CM = 1.5  # 画面の端に置く大きさ（約 1.5 cm 四方）
FRAME_MS = 120  # コマの間隔（ミリ秒）
MAX_FRAMES = 200  # 読み込むコマの上限（壊れた GIF で止まらないように）
GIF_SIGNATURE = b"GIF8"  # GIF87a・GIF89a の先頭（GIF の仕様）
MARGIN_PX = 6  # 窓の端からの余白（attach を渡さないときの place の位置）


@dataclass(frozen=True)
class GifLocation:
    """GIF の場所の決め方（アプリが渡す）。"""

    env_var: str | None = None
    base_dir: Union[Path, Callable[[], Path], None] = None
    relative_path: tuple[str, ...] = DEFAULT_RELATIVE_PATH
    frozen_name: str = DEFAULT_FROZEN_NAME


def _default_base_dir() -> Path:
    """起動したスクリプトのあるフォルダ（無ければ作業フォルダ）。"""
    argv0 = sys.argv[0] if sys.argv and sys.argv[0] else ""
    return Path(argv0).resolve().parent if argv0 else Path.cwd()


def resolve_gif_path(location: GifLocation | None = None) -> Path:
    """GIF の場所。環境変数 > exe の中（_MEIPASS 直下の frozen_name）> base_dir/relative_path。ファイルの有無は見ない。"""
    loc = location or GifLocation()
    if loc.env_var:
        override = os.environ.get(loc.env_var)
        if override:
            return Path(override)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / loc.frozen_name
    base = loc.base_dir() if callable(loc.base_dir) else loc.base_dir
    return Path(base if base is not None else _default_base_dir()).joinpath(*loc.relative_path)


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
        # ファイルは 1 度だけ読み、コマはメモリから作る。コマごとにファイルを開くと、途中の 1 回の開き損ね（他のプロセスが一瞬
        # 掴んでいる等）が「コマの終わり」と見分けられず、コマが黙って欠ける（試験の全件の実行でときどき起きた）
        raw = Path(path).read_bytes()
        if not raw.startswith(GIF_SIGNATURE):  # 空・GIF でない（Tk の data は空の文字でも空の画像を作ってしまうので、先に見る）
            return frames
        data = base64.b64encode(raw).decode("ascii")
        for i in range(MAX_FRAMES):
            try:
                frames.append(tk.PhotoImage(master=master, data=data, format=f"gif -index {i}"))
            except tk.TclError:
                break  # コマの終わり（最初のコマで失敗なら frames は空 = 読めない GIF）
    except (OSError, tk.TclError, ValueError):
        return []
    return frames


class BusyAnimation:
    """GIF を master の中に置き、start() の間だけ再生し、stop() で止める（止めたら最初のコマを静止して見せる）。

    attach(label): 置き方を決める関数（進捗ダイアログは右の余白へ grid で置く）。None なら、root の右上の端へ place する。GIF が無ければ label は作らず、attach も呼ばない（余白を取らない）。"""

    def __init__(self, root: tk.Misc, gif_path: Path | None = None, frame_ms: int = FRAME_MS, attach=None,
                 location: GifLocation | None = None) -> None:
        self._root = root
        self._frame_ms = frame_ms
        self._index = 0
        self._after_id = None
        self.running = False
        self.path = Path(gif_path) if gif_path is not None else resolve_gif_path(location)
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
