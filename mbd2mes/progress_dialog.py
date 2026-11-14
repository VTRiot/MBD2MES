# -*- coding: utf-8 -*-
"""progress_dialog.py -- 変換中に出す、モーダルの進捗ダイアログ（FB03）。一般的な Windows の進捗ダイアログの形。

  タイトル: "Converting..."（固定サイズ・最小化/最大化なし・親窓の中央）
  上: 今の処理の説明（File k/n: ファイル名 / Step k/7: 段の名前）
  中: % 付きのプログレスバー（戻らない）
  下: 経過時間と残りの目安
  右の余白: busy.gif（変換中だけ動く。GIF が無ければ、その分の余白は取らない = 詰める）
  右下: Cancel（× と Esc も同じ）

進みの通知・重み・別スレッド・GIL を譲る処理は FB02 のまま（progress.py・jobs.py）。このダイアログは画面だけで、
変換を止める仕事は on_cancel（旗を立てる）へ渡す。tk 以外に依存しない（変換は知らない）。
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from . import busy_animation
from . import progress as prg

TITLE = "Converting..."
TICK_MS = 500  # 経過時間・残りの目安を更新する間隔
WRAP_PX = 360  # 長いファイル名の折り返し幅
BAR_PX = 360  # バーの長さ
CANCELLING_TEXT = "Cancelling... finishing the step in progress"
GRAB_RETRIES = 20  # 窓が見えるのを待って grab を取り直す回数
GRAB_RETRY_MS = 50


class ProgressDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, on_cancel, gif_path=None, clock=time.monotonic,
                 frame_ms: int = busy_animation.FRAME_MS) -> None:
        super().__init__(parent)
        self.withdraw()  # 位置とサイズが決まるまで出さない
        self.parent = parent
        self._on_cancel = on_cancel
        self._clock = clock
        self._started = clock()
        self._max_value = 0.0
        self._tick_after = None
        self.cancel_requested = False
        self.closed = False
        self.title(TITLE)
        self.resizable(False, False)  # サイズ固定（最大化のボタンも出ない）
        self.transient(parent)  # 最小化のボタンも出ない。親の上に出る
        self.protocol("WM_DELETE_WINDOW", self.request_cancel)  # × は Cancel と同じ
        self.bind("<Escape>", lambda _e: self.request_cancel())

        body = tk.Frame(self, padx=14, pady=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        self.file_var = tk.StringVar(value="Preparing...")
        self.step_var = tk.StringVar(value="")
        self.percent_var = tk.StringVar(value="0%")
        self.time_var = tk.StringVar(value="Elapsed: 0:00")
        tk.Label(body, textvariable=self.file_var, anchor="w", justify="left", wraplength=WRAP_PX).grid(row=0, column=0, sticky="w")
        tk.Label(body, textvariable=self.step_var, anchor="w", justify="left", wraplength=WRAP_PX).grid(row=1, column=0, sticky="w")
        bar_row = tk.Frame(body)
        bar_row.grid(row=2, column=0, sticky="ew", pady=(10, 6))
        self.bar = ttk.Progressbar(bar_row, mode="determinate", maximum=100.0, length=BAR_PX)
        self.bar.pack(side="left", fill="x", expand=True)
        tk.Label(bar_row, textvariable=self.percent_var, width=5, anchor="e").pack(side="left", padx=(6, 0))
        tk.Label(body, textvariable=self.time_var, anchor="w").grid(row=3, column=0, sticky="w")
        # 右の余白に GIF（変換中だけ動く）。GIF が無ければ何も置かない = 余白も取らない
        self.animation = busy_animation.BusyAnimation(
            body, gif_path, frame_ms, attach=lambda lbl: lbl.grid(row=0, column=1, rowspan=4, sticky="ne", padx=(14, 0)))
        ttk.Separator(body, orient="horizontal").grid(row=4, column=0, columnspan=2, sticky="ew", pady=(12, 8))
        self.cancel_button = ttk.Button(body, text="Cancel", width=10, command=self.request_cancel)
        self.cancel_button.grid(row=5, column=0, columnspan=2, sticky="e")  # 右下

        self._center_on_parent()
        self.deiconify()
        self.cancel_button.focus_set()
        self._try_grab(GRAB_RETRIES)  # モーダル（親窓を触れなくする）
        self.animation.start()
        self._tick()

    # ------------------------------------------------------------ 位置と大きさ
    def _center_on_parent(self) -> None:
        """要求された大きさに固定し、親窓の中央（親が見えていなければ画面の中央）へ置く。"""
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        try:
            if self.parent.winfo_viewable() and self.parent.winfo_width() > 1:
                x = self.parent.winfo_rootx() + (self.parent.winfo_width() - w) // 2
                y = self.parent.winfo_rooty() + (self.parent.winfo_height() - h) // 2
            else:
                x = (self.winfo_screenwidth() - w) // 2
                y = (self.winfo_screenheight() - h) // 2
        except tk.TclError:
            x = y = 100
        self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")

    def _try_grab(self, tries: int) -> None:
        """grab は窓が見えるようになってからでないと取れない。見えるまで少し待って取り直す（親が隠れているときは諦める）。"""
        if self.closed:
            return
        try:
            self.grab_set()
        except tk.TclError:
            if tries > 0:
                self.after(GRAB_RETRY_MS, lambda: self._try_grab(tries - 1))

    # ------------------------------------------------------------ 更新
    def update_progress(self, event: "prg.ProgressEvent") -> None:
        """進みの通知（主スレッドで呼ぶ）。バー・% は戻らない。"""
        if self.closed:
            return
        value = max(self._max_value, event.overall * 100.0)
        self._max_value = value
        self.bar["value"] = value
        self.percent_var.set(f"{int(value + 1e-9)}%")
        self.file_var.set(event.file_text())
        if not self.cancel_requested:  # Cancel の案内を上書きしない
            self.step_var.set(event.step_text())

    def _time_text(self) -> str:
        elapsed = self._clock() - self._started
        text = f"Elapsed: {prg.format_clock(elapsed)}"
        if not self.cancel_requested:
            remaining = prg.estimate_remaining(elapsed, self._max_value / 100.0)
            text += ("    Remaining: about " + prg.format_clock(remaining)) if remaining is not None else "    Remaining: calculating..."
        return text

    def _tick(self) -> None:
        if self.closed:
            return
        self.time_var.set(self._time_text())
        self._tick_after = self.after(TICK_MS, self._tick)

    # ------------------------------------------------------------ Cancel・閉じる
    def request_cancel(self) -> None:
        """Cancel ボタン・× ・Esc。1 度だけ有効。ボタンを押せなくし、止まるまで待つ旨を出して、on_cancel（旗を立てる）を呼ぶ。"""
        if self.cancel_requested or self.closed:
            return
        self.cancel_requested = True
        self.cancel_button.state(["disabled"])
        self.step_var.set(CANCELLING_TEXT)
        self.time_var.set(self._time_text())
        self._on_cancel()

    def close(self) -> None:
        """終わったので閉じる（自動）。タイマーと GIF を止め、grab を放す。"""
        if self.closed:
            return
        self.closed = True
        if self._tick_after is not None:
            try:
                self.after_cancel(self._tick_after)
            except tk.TclError:
                pass
            self._tick_after = None
        self.animation.release()
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        # Tk の変数は、主スレッドのうちに手放す（別スレッドで回収されると「main thread is not in main loop」が出うる）
        self.file_var = self.step_var = self.percent_var = self.time_var = None
