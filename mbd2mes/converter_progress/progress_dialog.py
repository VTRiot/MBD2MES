# -*- coding: utf-8 -*-
"""progress_dialog.py -- 変換中に出す、モーダルの進捗ダイアログ。一般的な Windows の進捗ダイアログの形。

  タイトル: "Converting..."（固定サイズ・最小化/最大化なし・親窓の中央）
  上: 今の処理の説明（File k/n: ファイル名 / Step k/N: 段の名前）
  中: % 付きのプログレスバー（戻らない）
  下: 経過時間と残りの目安（Cancel 中・Done では残りを出さない。Done では経過時間を止める）
  右の余白: busy.gif（変換中だけ動く。GIF が無ければ、その分の余白は取らない = 詰める）
  右下: Cancel（× と Esc も同じ。1 度だけ有効）

画面だけを持ち、変換は知らない。変換を止める仕事は on_cancel（旗を立てる関数。JobRunner.request_cancel など）へ渡す。

アプリ側で決めること:
  - on_cancel（旗を立てるだけ。止まるのは変換が段の境目で旗を見たとき）
  - 文言と大きさ（このファイルの先頭の定数。英語の UI のまま使うなら変えなくてよい）
  - GIF の場所（gif_path で直接、または gif_location で env 名・基準フォルダ・exe 同梱名。busy_animation.GifLocation）
  - 仕事が終わったときの閉じ方: 必ず finish_then_close を呼ぶ（成功でも失敗でも Cancel でも。閉じ忘れると親窓が塞がれたままになる）。
    Cancel で止めたときは min_show_s=0 を渡して待たずに閉じる。ダイアログが出せなかった（コンストラクタが例外）ときも変換は続ける

踏んだ地雷:
  - grab_set は窓が見えるようになってからでないと取れない。見えるまで GRAB_RETRY_MS ごとに GRAB_RETRIES 回まで取り直す（親が隠れていれば諦める）
  - Tk の変数と GIF のコマは、閉じるとき主スレッドのうちに手放す（別スレッドの GC で回収されると「main thread is not in main loop」が出うる）
  - close は、どの片付けが失敗しても grab の解除と窓の破棄までは必ず行う（解除し損ねると親窓が塞がれたままになる）
  - コンストラクタが途中で失敗したら、用意した窓・grab・タイマー・GIF を片付けてから例外を出し直す（生成途中の窓を残さない）
  - ダイアログが一瞬で消えると、何が起きたか見えない。閉じる時刻 = max(開いてから MIN_SHOW_S, Done に切り替えてから DONE_HOLD_S)。
    Done にした後は必ずイベントループへ描画を返してから閉じる（Cancel のときは待たない）
  - 終わった（Done）後に遅れて届いた進み・Cancel は無視する（Done の表示を上書きしない）。Done では経過時間を止める
  - 試験・撮影のとき、利用者の画面に窓を出さない: place=(x, y) に画面の外の座標を渡す（出す前に置き場を決めるので一瞬も出ない）。
    負の値は "+-32000" の書き方で渡す（"-32000" は右・下の端からの距離になる）。
    ただし画面の外の窓は Windows が描かないので、PrintWindow で撮ると子の部品（ttk のバー・ボタン）が抜ける。撮影は画面の中に完全に透明な窓を置く
    （scripts/render_dialog_snapshot.py）。試験は親を withdraw したままにするので、何も描かれず、画面の外の座標で足りる
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from . import busy_animation
from . import progress as prg
from .jobs import report_problem

TITLE = "Converting..."
PREPARING_TEXT = "Preparing..."
CANCEL_BUTTON_TEXT = "Cancel"
CANCELLING_TEXT = "Cancelling... finishing the step in progress"
DONE_TEXT = "Done"  # 仕事が終わった状態の段の行
DONE_WITH_ERRORS_TEXT = "Done (with errors)"
CANCELLED_TEXT = "Cancelled"
ELAPSED_PREFIX = "Elapsed: "
REMAINING_PREFIX = "    Remaining: about "
REMAINING_PENDING_TEXT = "    Remaining: calculating..."
MIN_SHOW_S = 1.0  # 【仮置き】ダイアログを開いてからの最低の表示時間（秒）。短い変換でも、開いてからこの間は見せる。見直しの合図: 利用者が短い・長いと言ったとき
DONE_HOLD_S = 0.5  # 【仮置き】Done に切り替えてから閉じるまでの最低の時間（秒）。長い変換でも Done はこの間は見せる。見直しの合図: 利用者が短い・長いと言ったとき
MS_PER_S = 1000  # 秒とミリ秒の換算（単位の定義）
TICK_MS = 500  # 経過時間・残りの目安を更新する間隔
WRAP_PX = 360  # 長いファイル名の折り返し幅
BAR_PX = 360  # バーの長さ
BAR_MAXIMUM = 100.0  # バーの満了（% の定義）
FULL_PERCENT = BAR_MAXIMUM  # Done のときバーを満たす値
GRAB_RETRIES = 20  # 窓が見えるのを待って grab を取り直す回数
GRAB_RETRY_MS = 50
FALLBACK_POS_PX = 100  # 親の位置が取れないときの窓の左上
BODY_PAD_X, BODY_PAD_Y = 14, 12  # 窓の内側の余白
BAR_ROW_PAD = (10, 6)  # バーの行の上下の余白
PERCENT_LABEL_WIDTH = 5  # "100%" が入る幅（文字数）
PERCENT_LABEL_PAD = (6, 0)
GIF_PAD = (14, 0)  # GIF と文字の間の余白
SEPARATOR_PAD = (12, 8)  # 区切り線の上下の余白
CANCEL_BUTTON_WIDTH = 10
TEXT_ROWS = 4  # GIF が縦に並ぶ行数（文字・バー・時間の 4 行）


class ProgressDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, on_cancel, gif_path=None, gif_location: busy_animation.GifLocation | None = None,
                 clock=time.monotonic, frame_ms: int = busy_animation.FRAME_MS, place: tuple[int, int] | None = None) -> None:
        # place: 窓の左上の座標（画面の座標）。None なら親窓の中央。試験・撮影は画面の外の座標を渡す
        super().__init__(parent)
        # 属性は、途中の失敗の後始末（_abort_construction）が見られるよう、先に決めておく
        self.closed = False
        self._tick_after = None
        self.animation = None
        self._finalized = False
        try:
            self.withdraw()  # 位置とサイズが決まるまで出さない
            self.parent = parent
            self._on_cancel = on_cancel
            self._clock = clock
            self._started = clock()
            self._finished_elapsed: float | None = None
            self._max_value = 0.0
            self.cancel_requested = False
            self.finished = False  # 仕事が終わって、最短の表示時間を待っている状態（Cancel は押せない）
            self.title(TITLE)
            self.resizable(False, False)  # サイズ固定（最大化のボタンも出ない）
            self.transient(parent)  # 最小化のボタンも出ない。親の上に出る
            self.protocol("WM_DELETE_WINDOW", self.request_cancel)  # × は Cancel と同じ
            self.bind("<Escape>", lambda _e: self.request_cancel())

            body = tk.Frame(self, padx=BODY_PAD_X, pady=BODY_PAD_Y)
            body.pack(fill="both", expand=True)
            body.columnconfigure(0, weight=1)
            self.file_var = tk.StringVar(master=self, value=PREPARING_TEXT)
            self.step_var = tk.StringVar(master=self, value="")
            self.percent_var = tk.StringVar(master=self, value="0%")
            self.time_var = tk.StringVar(master=self, value=ELAPSED_PREFIX + prg.format_clock(0))
            tk.Label(body, textvariable=self.file_var, anchor="w", justify="left", wraplength=WRAP_PX).grid(row=0, column=0, sticky="w")
            tk.Label(body, textvariable=self.step_var, anchor="w", justify="left", wraplength=WRAP_PX).grid(row=1, column=0, sticky="w")
            bar_row = tk.Frame(body)
            bar_row.grid(row=2, column=0, sticky="ew", pady=BAR_ROW_PAD)
            self.bar = ttk.Progressbar(bar_row, mode="determinate", maximum=BAR_MAXIMUM, length=BAR_PX)
            self.bar.pack(side="left", fill="x", expand=True)
            tk.Label(bar_row, textvariable=self.percent_var, width=PERCENT_LABEL_WIDTH, anchor="e").pack(side="left", padx=PERCENT_LABEL_PAD)
            tk.Label(body, textvariable=self.time_var, anchor="w").grid(row=3, column=0, sticky="w")
            # 右の余白に GIF（変換中だけ動く）。GIF が無ければ何も置かない = 余白も取らない
            self.animation = busy_animation.BusyAnimation(
                body, gif_path, frame_ms, location=gif_location,
                attach=lambda lbl: lbl.grid(row=0, column=1, rowspan=TEXT_ROWS, sticky="ne", padx=GIF_PAD))
            ttk.Separator(body, orient="horizontal").grid(row=TEXT_ROWS, column=0, columnspan=2, sticky="ew", pady=SEPARATOR_PAD)
            self.cancel_button = ttk.Button(body, text=CANCEL_BUTTON_TEXT, width=CANCEL_BUTTON_WIDTH, command=self.request_cancel)
            self.cancel_button.grid(row=TEXT_ROWS + 1, column=0, columnspan=2, sticky="e")  # 右下

            self._center_on_parent(place)
            self.deiconify()
            self.cancel_button.focus_set()
            self._try_grab(GRAB_RETRIES)  # モーダル（親窓を触れなくする）
            self.animation.start()
            self._tick()
        except BaseException:
            # 表示・grab・after の予約の後で失敗したら、用意した物を片付けてから例外を出し直す
            self._abort_construction()
            raise

    def _abort_construction(self) -> None:
        """コンストラクタの途中で失敗したとき: タイマー・GIF・grab・窓を、できる所まで片付ける（各々の失敗は無視して先へ進む）。"""
        self.closed = True
        for step in (self._cancel_tick, self._release_animation, self.grab_release, self.destroy):
            try:
                step()
            except Exception:  # noqa: BLE001 -- 片付けの失敗で、元の例外を隠さない
                pass

    def _cancel_tick(self) -> None:
        if self._tick_after is not None:
            tick, self._tick_after = self._tick_after, None
            self.after_cancel(tick)

    def _release_animation(self) -> None:
        if self.animation is not None:
            self.animation.release()

    # ------------------------------------------------------------ 位置と大きさ
    def _center_on_parent(self, place: tuple[int, int] | None = None) -> None:
        """要求された大きさに固定し、親窓の中央（親が見えていなければ画面の中央）へ置く。place があればその座標（負の値も許す）。"""
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        if place is not None:
            self.geometry(f"{w}x{h}+{place[0]}+{place[1]}")  # 負の値は "+-32000" の書き方（"-32000" は右・下の端からの距離になる）
            return
        try:
            if self.parent.winfo_viewable() and self.parent.winfo_width() > 1:
                x = self.parent.winfo_rootx() + (self.parent.winfo_width() - w) // 2
                y = self.parent.winfo_rooty() + (self.parent.winfo_height() - h) // 2
            else:
                x = (self.winfo_screenwidth() - w) // 2
                y = (self.winfo_screenheight() - h) // 2
        except tk.TclError:
            x = y = FALLBACK_POS_PX
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
        """進みの通知（主スレッドで呼ぶ）。バー・% は戻らない。終わった後・閉じた後の通知は無視する。"""
        if self.closed or self.finished:
            return
        value = max(self._max_value, event.overall * prg.PERCENT_SCALE)
        self._max_value = value
        self.bar["value"] = value
        self.percent_var.set(f"{int(value + prg.PERCENT_EPSILON)}%")
        self.file_var.set(event.file_text())
        if not self.cancel_requested:  # Cancel の案内を上書きしない
            self.step_var.set(event.step_text())

    def elapsed_s(self) -> float:
        """ダイアログを出してからの時間（秒）。Done になった後は、その時点で止まる。"""
        if self._finished_elapsed is not None:
            return self._finished_elapsed
        return self._clock() - self._started

    def _time_text(self) -> str:
        elapsed = self.elapsed_s()
        text = ELAPSED_PREFIX + prg.format_clock(elapsed)
        if not self.cancel_requested and not self.finished:
            remaining = prg.estimate_remaining(elapsed, self._max_value / prg.PERCENT_SCALE)
            text += (REMAINING_PREFIX + prg.format_clock(remaining)) if remaining is not None else REMAINING_PENDING_TEXT
        return text

    def _tick(self) -> None:
        if self.closed or self.finished:
            return
        self.time_var.set(self._time_text())
        self._tick_after = self.after(TICK_MS, self._tick)

    # ------------------------------------------------------------ Cancel・終わり・閉じる
    def request_cancel(self) -> None:
        """Cancel ボタン・× ・Esc。1 度だけ有効。ボタンを押せなくし、止まるまで待つ旨を出して、on_cancel（旗を立てる）を呼ぶ。"""
        if self.cancel_requested or self.closed or self.finished:
            return
        self.cancel_requested = True
        self.cancel_button.state(["disabled"])
        self.step_var.set(CANCELLING_TEXT)
        self.time_var.set(self._time_text())
        self._on_cancel()

    def show_finished(self, text: str, full: bool) -> None:
        """仕事が終わった表示。段の行を text（DONE_TEXT / DONE_WITH_ERRORS_TEXT / CANCELLED_TEXT）にし、Cancel を押せなくし、経過時間を止める。
        full が真ならバーを 100% にする（止めたときは、その時点のまま）。閉じるのは呼び出し側（finish_then_close）。"""
        if self.closed or self.finished:
            return
        self._finished_elapsed = self._clock() - self._started
        self.finished = True
        self.cancel_button.state(["disabled"])
        if full:
            self._max_value = FULL_PERCENT
            self.bar["value"] = FULL_PERCENT
            self.percent_var.set(f"{int(FULL_PERCENT)}%")
        self.step_var.set(text)
        self.time_var.set(self._time_text())

    def finish_then_close(self, text: str, full: bool, on_closed=None, min_show_s: float = MIN_SHOW_S) -> None:
        """仕事が終わったときの定型: Done の表示にし、閉じる時刻 = max(開いてから min_show_s, Done にしてから DONE_HOLD_S) まで待って閉じ、
        on_closed() を 1 度だけ呼ぶ（待つ間にイベントループへ描画を返す）。
        Cancel で止めたときは min_show_s=0 を渡す（待たずに閉じる。DONE_HOLD_S も使わない）。表示の失敗・after の予約の失敗でも、必ず閉じて on_closed へ進む。
        待つ間は root（親）の after を使う（ダイアログ自身の after は、窓が先に壊れると走らない）。"""
        wait_s = 0.0
        try:
            self.show_finished(text, full)
            hold_s = DONE_HOLD_S if min_show_s > 0.0 else 0.0
            wait_s = max(min_show_s - self.elapsed_s(), hold_s, 0.0)
        except Exception as err:  # noqa: BLE001 -- 終わりの表示の失敗でも、必ず閉じる
            report_problem(f"[ERROR] Could not show the finished state: {err!r}")

        def finalize() -> None:
            if self._finalized:
                return
            self._finalized = True
            try:
                self.close()
            finally:
                if on_closed is not None:
                    try:
                        on_closed()
                    except Exception as err:  # noqa: BLE001 -- 後続の失敗を、ダイアログを閉じた後の診断として残す
                        report_problem(f"[ERROR] The after-close handler failed: {err!r}")

        if wait_s > 0.0:
            try:
                self.parent.after(round(wait_s * MS_PER_S), finalize)
                return
            except Exception:  # noqa: BLE001 -- 予約できなければ、待たずにすぐ閉じる
                pass
        finalize()

    def close(self) -> None:
        """終わったので閉じる。タイマーと GIF を止め、grab を放す。どの片付けが失敗しても、grab の解除と窓の破棄までは必ず行う
        （解除し損ねると、親窓が塞がれたままになる）。"""
        if self.closed:
            return
        self.closed = True
        try:
            try:
                self._cancel_tick()
            except tk.TclError:
                pass
            self._release_animation()
        finally:
            try:
                self.grab_release()
            except Exception:  # noqa: BLE001 -- 解除の失敗で、窓の破棄を飛ばさない（destroy は grab も外す）
                pass
            try:
                self.destroy()
            finally:
                # Tk の変数は、主スレッドのうちに手放す（別スレッドで回収されると「main thread is not in main loop」が出うる）
                self.file_var = self.step_var = self.percent_var = self.time_var = None
