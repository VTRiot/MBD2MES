# -*- coding: utf-8 -*-
"""jobs.py -- 変換を別スレッドで回し、画面（Tk の主ループ）を止めないための小さな道具。tk は import しない（root は after() を持つ物なら何でもよい）。

仕事（work）は別スレッドで走り、進み具合（progress）とログ（log）をキューへ置く。画面側は root.after で一定間隔にキューを読み、
主スレッドの中で画面を更新する（Tk の部品は主スレッドからしか触らない）。仕事が終わると、結果か例外が on_done へ渡る（主スレッド）。

アプリ側で決めること:
  - work(emitter) の中身（変換）。emitter.progress(event) で進みを、emitter.log(text) でログを知らせ、emitter.cancel（threading.Event）を
    段の境目で見て止まる。work の中で Tk の部品に触らない（値は主スレッドで取り出してから渡す）
  - on_progress・on_log（主スレッドで呼ばれる画面の更新）と on_done(結果, 例外, 例外の文面)
  - スレッド名（thread_name。試験が「別スレッドで走ったか」を見分けるのに使う）

踏んだ地雷:
  - 別スレッドで GC が走ると、主スレッドの Tk の変数・画像（循環の中にある物）がそのスレッドで片付けられ、Tcl が「別のスレッドで消された」と
    落ちる（Windows fatal exception 0x80000003。個別の試験では出ず、全件の試験で初めて出た）。仕事の間は GC を止め、最後の仕事が終わったとき
    主スレッドで集める（プロセス共通の参照数。仕事が重なっても、先に終わった方が GC を戻さない）
  - 変換が Python のループで GIL を握り続けると、主スレッドが Tk を触るたびに GIL を待つ。進みを知らせるたびに少し譲る（PROGRESS_YIELD_S）
  - 画面側の関数が例外を投げても読み取りを止めない（止めると仕事の終わりが届かず、モーダルのダイアログが閉じないまま固まる）
  - root.after の予約が失敗しても、結果を捨てない（Cancel を立て、別スレッドの終わりを主スレッドで待ち、結果は通常どおり on_done へ）
  - windowed の exe では sys.stderr が None・閉じている・書けないことがある。診断の出力（report_problem）は、その失敗も握る
  - done を読んだときワーカーのスレッドがまだ生きていることがある（done をキューへ入れた後、スレッドが終わるまでの短い間）。そこで GC を戻すと、
    別スレッドの GC の守りが破れる。done を読んだら、スレッドが終わったことを after で確かめ直し（THREAD_END_POLL_MS。主ループは止めない）、
    終わってから GC を戻して on_done を呼ぶ。THREAD_END_LIMIT_S を超えても終わらないときは、結果を捨てず画面も固めないために on_done は呼ぶが、
    その時点では GC は戻さず、poll_warning に書く。その後も主スレッドの after（THREAD_END_POLL_MS 間隔）でスレッドの終わりを見続け、
    終わったらその仕事の保持だけを外す（最後の保持なら GC を戻して集める）。after が使えないとき（予約が失敗する・窓が壊れている）は、
    終わりを見張る手段が無いので GC は止めたまま残し（別スレッドの GC を避ける方を優先）、poll_warning にそう書く。残った保持は
    release_late_holds() で、スレッドが終わったと分かっている場所（プロセスの終わりの直前など）から主スレッドで外せる
  - 開始の準備はどこで失敗しても、GC・running・保持の旗を戻す（戻さないと、次の仕事が永久に始められない）
"""

from __future__ import annotations

import gc
import queue
import sys
import threading
import time
import traceback

_GC_LOCK = threading.Lock()
_GC_JOBS = 0  # GC を止めている仕事の数（プロセス共通。GC もプロセス共通なので）
_GC_WAS_ENABLED = True  # 最初の仕事が始まる前の GC の状態
_LATE_HOLDS: list = []  # 上限を超えて on_done を呼んだ後も、終わりを見張れていない仕事のスレッド（release_late_holds が外す）


POLL_MS = 40  # キューを読む間隔（画面が滑らかに見える程度で、主スレッドの負担にならない値）
# 変換（別スレッド）は Python の 1 レコードずつのループで GIL を握り続ける。主スレッドが Tk を触るたびに GIL を取り戻すのを待つので、
# 進み具合を知らせるたびに少し譲る（実測: 譲らないと、読み取りの間、画面が数秒止まって見えた）
PROGRESS_YIELD_S = 0.002
THREAD_END_POLL_MS = 10  # done を読んだとき、まだ生きているワーカーのスレッドの終わりを確かめ直す間隔（主ループは止めない）
THREAD_END_LIMIT_S = 5.0  # 【仮置き】終わりを待つ上限。done を入れた後のスレッドは一瞬で終わる。超えたら GC は戻さず on_done は呼ぶ
DEFAULT_THREAD_NAME = "converter-job"  # 変換のスレッドの名前の既定（JobRunner の thread_name で変える）


def _release_gc_hold() -> None:
    """GC の停止の保持を 1 つ外す。最後の保持のときだけ GC を戻し、たまった循環のごみを、いま（主スレッド）集める。"""
    global _GC_JOBS
    last = False
    with _GC_LOCK:
        _GC_JOBS -= 1
        if _GC_JOBS == 0:
            last = True
            if _GC_WAS_ENABLED:
                gc.enable()
    if last:
        gc.collect()


def release_late_holds() -> int:
    """終わりを見張れなかった仕事（_LATE_HOLDS）のうち、スレッドが終わったものの保持を主スレッドで外す。外した数を返す。"""
    released = 0
    for thread in list(_LATE_HOLDS):
        if not thread.is_alive():
            _LATE_HOLDS.remove(thread)
            _release_gc_hold()
            released += 1
    return released


def report_problem(text: str, log=None) -> None:
    """診断の文面を残す。stderr（windowed の exe では None・閉じている・書けないことがある）と、log（GUI のログ欄。主スレッドで呼ぶ関数）の
    両方へ。どちらの失敗も握って、呼び出し側（後片付け・状態の戻し）を妨げない。"""
    try:
        print(text, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 -- 出力の失敗で、後片付けを止めない
        pass
    if log is not None:
        try:
            log(text)
        except Exception:  # noqa: BLE001 -- ログ欄が使えない（窓が壊れている等）ときは、黙って飛ばす
            pass


class Emitter:
    """仕事（別スレッド）が主スレッドへ知らせる口。スレッドから呼んでよい。cancel は Cancel の旗（threading.Event）。"""

    def __init__(self, q: queue.Queue, cancel: threading.Event | None = None) -> None:
        self._q = q
        self.cancel = cancel

    def progress(self, event) -> None:
        self._q.put(("progress", event))
        time.sleep(PROGRESS_YIELD_S)  # GIL を譲り、主スレッド（画面）が動けるようにする

    def log(self, text: str) -> None:
        self._q.put(("log", text))


class JobRunner:
    """1 度に 1 つの仕事を別スレッドで走らせる。start() は主スレッドから呼ぶ。"""

    def __init__(self, root, on_progress, on_log, poll_ms: int = POLL_MS, thread_name: str = DEFAULT_THREAD_NAME) -> None:
        self._root = root
        self._thread_name = thread_name
        self._on_progress = on_progress
        self._on_log = on_log
        self._poll_ms = poll_ms
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._on_done = None
        self.running = False
        self.cancel_event = threading.Event()  # 仕事ごとに作り直す（start で）
        self._holds_gc = False
        self.poll_warning: str | None = None  # 読み取りの予約に失敗したときの警告（仕事の結果・例外とは別に持つ。on_done が読む）
        self.callback_errors: list[str] = []  # 画面側の関数（_on_progress・_on_log）が投げた例外の文面（読み取りは続ける）

    def start(self, work, on_done) -> None:
        """work(emitter) -> 結果 を別スレッドで走らせる。終わったら on_done(結果, 例外, 例外の文面) を主スレッドで呼ぶ。"""
        if self.running:
            raise RuntimeError("a job is already running")
        self.running = True
        # 仕事の間は、循環参照のごみ集め（GC）を止める。別スレッドで GC が走ると、主スレッドの Tk の変数・画像（循環の中にある物）が
        # そのスレッドで片付けられ、Tcl が「別のスレッドで消された」と落ちる（Windows fatal exception 0x80000003。全件の試験で
        # 実際に落ちた）。止めた分は、終わったとき主スレッドで集める
        self._hold_gc()
        self._on_done = on_done
        self.poll_warning = None
        self._q = queue.Queue()
        self.cancel_event = threading.Event()
        emitter = Emitter(self._q, self.cancel_event)

        def target() -> None:
            try:
                result = work(emitter)
            except BaseException as exc:  # noqa: BLE001 -- 想定外の失敗も主スレッドへ運ぶ（スレッドを黙って死なせない）
                self._q.put(("done", None, exc, traceback.format_exc()))
            else:
                self._q.put(("done", result, None, ""))

        self._thread = threading.Thread(target=target, name=self._thread_name, daemon=True)
        try:
            # 開始の準備は、どこで失敗しても GC・running・保持の旗を戻す。
            # 読み取りの予約を先にし、予約が失敗すれば、スレッドは始めない。スレッドの開始が失敗したときは、予約済みの _poll が何もしない
            # （running が False なので、再予約もしない）
            self._root.after(self._poll_ms, self._poll)
            self._thread.start()
        except BaseException:
            self._restore_gc()
            self.running = False
            self._on_done = None
            raise

    def _hold_gc(self) -> None:
        global _GC_JOBS, _GC_WAS_ENABLED
        with _GC_LOCK:
            if _GC_JOBS == 0:
                _GC_WAS_ENABLED = gc.isenabled()
                gc.disable()
            _GC_JOBS += 1
        self._holds_gc = True

    def _restore_gc(self) -> None:
        """この仕事の分の GC の停止を外す。最後の仕事が終わったときだけ GC を戻し、たまった循環のごみを、いま（主スレッド）集める。"""
        if not self._holds_gc:
            return
        self._holds_gc = False
        _release_gc_hold()

    def _watch_late_end(self, thread) -> None:
        """on_done を呼んだ後も生きているワーカーを、主スレッドの after で見続け、終わったらこの仕事の保持を外す。
        この仕事の保持は、呼び出し側が _holds_gc を下ろして（所有を移して）あるので、次の仕事の保持とは混ざらない。"""
        if thread.is_alive():
            try:
                self._root.after(THREAD_END_POLL_MS, lambda: self._watch_late_end(thread))
            except Exception as exc:  # noqa: BLE001 -- 見張れない: GC は止めたまま残す（release_late_holds で外せる）
                _LATE_HOLDS.append(thread)
                report_problem(f"[WARN] Could not keep watching the worker thread; the garbage collector stays off ({exc!r}).")
            return
        _release_gc_hold()

    def request_cancel(self) -> None:
        """走っている仕事へ Cancel を伝える（旗を立てるだけ。止まるのは、仕事が次の通知の口で旗を見たとき）。"""
        self.cancel_event.set()

    def _call_screen(self, fn, arg) -> None:
        """画面側の関数を呼ぶ。例外は受けて stderr とリストへ残し、読み取りを続ける。"""
        try:
            fn(arg)
        except Exception:  # noqa: BLE001 -- 画面の更新の失敗で、読み取りと仕事の終わりの受け取りを止めない
            text = traceback.format_exc()
            self.callback_errors.append(text)
            report_problem(text)

    def _poll(self) -> None:
        if not self.running:  # 開始に失敗して取り消した仕事の予約。何もせず、再予約もしない
            return
        finished = None
        latest_progress = None  # 進み具合は、溜まっていれば最後の 1 つだけを画面へ反映する（途中の分は捨てても、バーは単調に進む）
        try:
            while True:
                item = self._q.get_nowait()
                kind = item[0]
                if kind == "progress":
                    latest_progress = item[1]
                elif kind == "log":
                    if latest_progress is not None:  # 順序を保つ: ログの前の進みは先に反映する
                        self._call_screen(self._on_progress, latest_progress)
                        latest_progress = None
                    self._call_screen(self._on_log, item[1])
                else:
                    finished = item
                    break
        except queue.Empty:
            pass
        if latest_progress is not None:
            self._call_screen(self._on_progress, latest_progress)
        if finished is None:
            try:
                self._root.after(self._poll_ms, self._poll)
            except Exception as exc:  # noqa: BLE001 -- 予約できない（Tk が壊れた等）。別スレッドの終わりを待ってから戻す
                self._finish_without_poll(exc)
            return
        self._complete_after_thread_end(finished, time.monotonic())

    def _complete_after_thread_end(self, finished, since: float) -> None:
        """done を読んだ後、ワーカーのスレッドが終わるのを（主ループを止めずに）待ってから、GC を戻して on_done を呼ぶ。"""
        thread = self._thread
        if thread is None or not thread.is_alive():
            self._complete(finished)
            return
        if time.monotonic() - since >= THREAD_END_LIMIT_S:
            self.poll_warning = ((self.poll_warning or "") + f"[WARN] The worker thread did not end within {THREAD_END_LIMIT_S} s after its result; "
                                 "the garbage collector is kept off to avoid collecting Tk objects on another thread.\n")
            self._holds_gc = False  # この仕事の保持は、下の監視（遅れての解除）へ渡す。次の仕事の保持と混ざらない
            self._complete(finished, restore_gc=False)
            self._hand_over_late_hold(thread)
            return
        try:
            self._root.after(THREAD_END_POLL_MS, lambda: self._complete_after_thread_end(finished, since))
        except Exception as exc:  # noqa: BLE001 -- 予約できない: 上限まで主スレッドで待つ（予約の失敗は警告に残す）
            thread.join(max(0.0, THREAD_END_LIMIT_S - (time.monotonic() - since)))
            self.poll_warning = ((self.poll_warning or "") + f"[WARN] Could not schedule the end-of-thread check ({exc!r}).\n")
            alive = thread.is_alive()
            if alive:
                self._holds_gc = False
            self._complete(finished, restore_gc=not alive)
            if alive:
                self._hand_over_late_hold(thread)

    def _hand_over_late_hold(self, thread) -> None:
        """上限を超えた仕事の保持を、遅れての監視へ渡す。after が使えなければ、止めたまま残し、警告にそう書く（release_late_holds で外せる）。"""
        try:
            self._root.after(THREAD_END_POLL_MS, lambda: self._watch_late_end(thread))
        except Exception as exc:  # noqa: BLE001 -- 見張れない
            _LATE_HOLDS.append(thread)
            self.poll_warning = ((self.poll_warning or "") + f"[WARN] Could not schedule a later check ({exc!r}); the garbage collector is kept off "
                                 "and there is no later release (call jobs.release_late_holds() once the thread has ended).\n")

    def _complete(self, finished, restore_gc: bool = True) -> None:
        self.running = False
        if restore_gc:
            self._restore_gc()
        _kind, result, exc, tb = finished
        done, self._on_done = self._on_done, None
        try:
            done(result, exc, tb)
        except Exception:  # noqa: BLE001 -- 状態（running・GC）は戻した後。on_done の失敗を Tk の例外表示へ流さず、残して読み取りの終わりを守る
            text = traceback.format_exc()
            self.callback_errors.append(text)
            report_problem(text)

    def _finish_without_poll(self, poll_exc: Exception) -> None:
        """読み取りの予約に失敗したとき。すぐ状態を戻すと、まだ走っている別スレッドの
        書き込みと、次の仕事・窓の破棄がぶつかる。Cancel を立て、別スレッドの終わりを主スレッドで join して待つ（旗は段の境目で効く）。
        終わってから、残った進み・ログを画面へ流し、仕事の結果・例外は通常どおり on_done へ渡す。予約の失敗は poll_warning に別に持つ
        （結果を例外に置き換えない: 公開済みの MES・台帳・起点と画面が食い違うため）。GC と running を戻してから on_done を呼ぶ。"""
        self.request_cancel()
        thread = self._thread
        if thread is not None:
            thread.join()
        finished = None
        try:
            while True:
                item = self._q.get_nowait()
                if item[0] == "progress":
                    self._call_screen(self._on_progress, item[1])
                elif item[0] == "log":
                    self._call_screen(self._on_log, item[1])
                else:
                    finished = item
        except queue.Empty:
            pass
        self.poll_warning = (f"[WARN] The progress display could not be updated ({poll_exc!r}); Cancel was requested to end the conversion "
                             "(whether it stopped early is shown in the result below).\n" + "".join(traceback.format_exception(poll_exc)))
        if finished is None:  # スレッドが終わりを残さずに消えた（想定外）。結果は無い
            finished = ("done", None, RuntimeError("the job ended without a result"), "")
        self._complete(finished)
