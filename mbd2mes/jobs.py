# -*- coding: utf-8 -*-
"""jobs.py -- 変換を別スレッドで回し、画面（Tk の主ループ）を止めないための小さな道具（FB02）。

仕事（work）は別スレッドで走り、進み具合（progress）とログ（log）をキューへ置く。画面側は root.after で一定間隔にキューを読み、
主スレッドの中で画面を更新する（Tk の部品は主スレッドからしか触らない）。仕事が終わると、結果か例外が on_done へ渡る（主スレッド）。
tk は import しない（root は after() を持つ物なら何でもよい。試験しやすい）。
"""

from __future__ import annotations

import gc
import queue
import threading
import time
import traceback

_GC_LOCK = threading.Lock()
_GC_JOBS = 0  # GC を止めている仕事の数（プロセス共通。GC もプロセス共通なので）
_GC_WAS_ENABLED = True  # 最初の仕事が始まる前の GC の状態


POLL_MS = 40  # キューを読む間隔（画面が滑らかに見える程度で、主スレッドの負担にならない値）
# 変換（別スレッド）は Python の 1 レコードずつのループで GIL を握り続ける。主スレッドが Tk を触るたびに GIL を取り戻すのを待つので、
# 進み具合を知らせるたびに少し譲る（FB02 の実測: 譲らないと、読み取りの間、画面が数秒止まって見えた）
PROGRESS_YIELD_S = 0.002


class Emitter:
    """仕事（別スレッド）が主スレッドへ知らせる口。スレッドから呼んでよい。cancel は Cancel の旗（threading.Event。FB03）。"""

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

    def __init__(self, root, on_progress, on_log, poll_ms: int = POLL_MS) -> None:
        self._root = root
        self._on_progress = on_progress
        self._on_log = on_log
        self._poll_ms = poll_ms
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._on_done = None
        self.running = False
        self.cancel_event = threading.Event()  # 仕事ごとに作り直す（start で）
        self._holds_gc = False

    def start(self, work, on_done) -> None:
        """work(emitter) -> 結果 を別スレッドで走らせる。終わったら on_done(結果, 例外, 例外の文面) を主スレッドで呼ぶ。"""
        if self.running:
            raise RuntimeError("a job is already running")
        self.running = True
        # 仕事の間は、循環参照のごみ集め（GC）を止める。別スレッドで GC が走ると、主スレッドの Tk の変数・画像（循環の中にある物）が
        # そのスレッドで片付けられ、Tcl が「別のスレッドで消された」と落ちる（Windows fatal exception 0x80000003。FB03 の全件の試験で
        # 実際に落ちた）。止めた分は、終わったとき主スレッドで集める
        self._hold_gc()
        self._on_done = on_done
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

        self._thread = threading.Thread(target=target, name="mbd2mes-job", daemon=True)
        try:
            # 開始の準備は、どこで失敗しても GC・running・保持の旗を戻す（Codex の FB03 レビュー 2 巡目 [1]）。
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
        global _GC_JOBS
        if not self._holds_gc:
            return
        self._holds_gc = False
        last = False
        with _GC_LOCK:
            _GC_JOBS -= 1
            if _GC_JOBS == 0:
                last = True
                if _GC_WAS_ENABLED:
                    gc.enable()
        if last:
            gc.collect()

    def request_cancel(self) -> None:
        """走っている仕事へ Cancel を伝える（旗を立てるだけ。止まるのは、仕事が次の通知の口で旗を見たとき）。"""
        self.cancel_event.set()

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
                        self._on_progress(latest_progress)
                        latest_progress = None
                    self._on_log(item[1])
                else:
                    finished = item
                    break
        except queue.Empty:
            pass
        if latest_progress is not None:
            self._on_progress(latest_progress)
        if finished is None:
            self._root.after(self._poll_ms, self._poll)
            return
        self.running = False
        self._restore_gc()
        _kind, result, exc, tb = finished
        done, self._on_done = self._on_done, None
        done(result, exc, tb)
