# -*- coding: utf-8 -*-
"""jobs.py: 別スレッドの仕事・進みの運び方・画面側の例外・after の失敗・GC の停止と復帰・重なった仕事。
Tk は使わない（after を持つ代役の root で、主ループの代わりに手で回す）。1 つだけ本物の Tk を使う試験がある。"""

from __future__ import annotations

import gc
import sys
import threading
import time

import importlib

import pytest
from .conftest import PACKAGE

jobs = importlib.import_module(f"{PACKAGE}.jobs")
WAIT_LIMIT_S = 10.0  # 【仮置き】試験の 1 つの仕事は一瞬で終わる。遅い機械で落ちたら延ばす
IDLE_SLEEP_S = 0.001


class FakeRoot:
    """after だけを持つ代役。予約は並べておき、pump_until が主ループのように 1 つずつ呼ぶ。fail_calls は、失敗させる after の呼び出し番号（1 始まり）。"""

    def __init__(self, fail_calls=()):
        self.queue = []
        self.calls = 0
        self.delays = []
        self.fail_calls = set(fail_calls)

    def after(self, ms, fn):
        self.calls += 1
        self.delays.append(ms)
        if self.calls in self.fail_calls:
            raise RuntimeError("tk is gone")
        self.queue.append(fn)
        return str(self.calls)

    def pump_until(self, predicate, limit_s=WAIT_LIMIT_S):
        end = time.monotonic() + limit_s
        while not predicate():
            assert time.monotonic() < end, "timed out"
            if self.queue:
                self.queue.pop(0)()
            else:
                time.sleep(IDLE_SLEEP_S)


class Recorder:
    def __init__(self):
        self.events = []  # 順序つき: ("p", 値) ("l", 文) 
        self.done = None

    def on_progress(self, ev):
        self.events.append(("p", ev))

    def on_log(self, text):
        self.events.append(("l", text))

    def on_done(self, result, exc, tb):
        self.done = (result, exc, tb)


def run(work, root=None, **kw):
    root = root or FakeRoot()
    rec = Recorder()
    runner = jobs.JobRunner(root, rec.on_progress, rec.on_log, **kw)
    runner.start(work, rec.on_done)
    root.pump_until(lambda: rec.done is not None)
    return runner, rec, root


def test_work_runs_on_a_named_other_thread_and_its_result_reaches_on_done():
    seen = []

    def work(em):
        seen.append(threading.current_thread())
        return 42

    _runner, rec, _root = run(work, thread_name="my-job")
    assert rec.done == (42, None, "")
    assert seen[0] is not threading.main_thread() and seen[0].name == "my-job"
    assert jobs.DEFAULT_THREAD_NAME == "converter-job"
    _r2, _rec2, _ = run(lambda em: threading.current_thread().name)
    assert _rec2.done[0] == "converter-job"


def test_an_exception_in_work_is_carried_to_on_done_with_its_traceback():
    def work(em):
        raise ValueError("bad input")

    runner, rec, _ = run(work)
    result, exc, tb = rec.done
    assert result is None and isinstance(exc, ValueError) and "bad input" in tb and "ValueError" in tb
    assert runner.running is False


def test_progress_bursts_collapse_to_the_latest_but_keep_the_order_with_logs():
    root = FakeRoot()
    rec = Recorder()
    runner = jobs.JobRunner(root, rec.on_progress, rec.on_log)

    def work(em):
        em.progress(1)
        em.progress(2)
        em.log("x")
        em.progress(3)
        return "r"

    runner.start(work, rec.on_done)
    runner._thread.join(WAIT_LIMIT_S)  # 仕事が先に終わり、キューに全部溜まってから主スレッドが読む
    root.pump_until(lambda: rec.done is not None)
    # 手で並べた期待: p1 p2 の途中の分は捨て（p2 だけ）、log の前に p2 を出し、その後 p3
    assert rec.events == [("p", 2), ("l", "x"), ("p", 3)] and rec.done[0] == "r"


def test_the_poll_interval_is_what_the_caller_gave():
    _r, _rec, root = run(lambda em: 1, poll_ms=17)
    assert set(root.delays) == {17}
    _r, _rec, root = run(lambda em: 1)
    assert set(root.delays) == {jobs.POLL_MS}


def test_emitter_progress_yields_the_gil(monkeypatch):
    slept = []
    monkeypatch.setattr(jobs.time, "sleep", lambda s: slept.append(s))
    em = jobs.Emitter(jobs.queue.Queue())
    em.progress("e")
    assert slept == [jobs.PROGRESS_YIELD_S] and jobs.PROGRESS_YIELD_S > 0


# ---------------------------------------------------------------- 画面側の関数の例外・stderr
def test_a_screen_callback_that_raises_does_not_stop_the_job_end(capsys):
    root, rec = FakeRoot(), Recorder()

    def bad_progress(ev):
        raise RuntimeError("screen broke")

    def bad_log(text):
        raise RuntimeError("log broke")

    runner = jobs.JobRunner(root, bad_progress, bad_log)

    def work(em):
        em.progress(1)
        em.log("x")
        return "ok"

    runner.start(work, rec.on_done)
    runner._thread.join(WAIT_LIMIT_S)
    root.pump_until(lambda: rec.done is not None)
    assert rec.done[0] == "ok" and len(runner.callback_errors) == 2
    assert "screen broke" in runner.callback_errors[0] and "log broke" in runner.callback_errors[1]
    assert "screen broke" in capsys.readouterr().err  # stderr にも残る


def test_on_done_raising_is_recorded_after_the_state_is_restored(capsys):
    root = FakeRoot()
    state = {}
    runner = jobs.JobRunner(root, lambda e: None, lambda t: None)

    def on_done(result, exc, tb):
        state["running"], state["gc"] = runner.running, gc.isenabled()
        raise RuntimeError("done handler broke")

    runner.start(lambda em: 1, on_done)
    root.pump_until(lambda: not runner.running)
    assert state == {"running": False, "gc": True}  # on_done が呼ばれた時点で、状態は戻っている
    assert len(runner.callback_errors) == 1 and "done handler broke" in capsys.readouterr().err
    runner.start(lambda em: 2, lambda r, e, t: state.update(second=r))  # 次の仕事を始められる
    root.pump_until(lambda: "second" in state)
    assert state["second"] == 2


class _BrokenStream:
    def write(self, _s):
        raise OSError("closed")

    def flush(self):
        raise OSError("closed")


@pytest.mark.parametrize("stream", [None, _BrokenStream()])
def test_report_problem_survives_a_missing_or_broken_stderr(monkeypatch, stream):
    monkeypatch.setattr(sys, "stderr", stream)  # windowed の exe では None のことがある
    logged = []
    jobs.report_problem("boom", logged.append)
    assert logged == ["boom"]


def test_a_broken_log_function_does_not_stop_report_problem(capsys):
    def bad_log(_t):
        raise RuntimeError("log window destroyed")

    jobs.report_problem("boom", bad_log)
    assert "boom" in capsys.readouterr().err


def test_a_job_with_a_screen_error_finishes_even_without_stderr(monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    root, rec = FakeRoot(), Recorder()
    runner = jobs.JobRunner(root, lambda e: 1 / 0, rec.on_log)

    def work(em):
        em.progress(1)
        return "ok"

    runner.start(work, rec.on_done)
    root.pump_until(lambda: rec.done is not None)
    assert rec.done[0] == "ok" and len(runner.callback_errors) == 1


# ---------------------------------------------------------------- after の失敗
def test_a_failing_first_after_aborts_the_start_and_restores_everything():
    started = []
    root = FakeRoot(fail_calls={1})
    runner = jobs.JobRunner(root, lambda e: None, lambda t: None)
    with pytest.raises(RuntimeError, match="tk is gone"):
        runner.start(lambda em: started.append(1), lambda r, e, t: None)
    assert runner.running is False and gc.isenabled() and jobs._GC_JOBS == 0
    assert started == [] and runner._thread is not None and not runner._thread.is_alive()  # スレッドは始めていない
    rec = Recorder()
    runner.start(lambda em: "again", rec.on_done)  # 2 回目の after は通る
    root.pump_until(lambda: rec.done is not None)
    assert rec.done[0] == "again"


def test_a_failing_later_after_keeps_the_result_and_asks_the_job_to_cancel():
    root = FakeRoot(fail_calls={2})  # 1 回目（start）は通り、最初の読み取りが次を予約するとき失敗する
    rec = Recorder()
    runner = jobs.JobRunner(root, rec.on_progress, rec.on_log)
    in_work = threading.Event()

    def work(em):
        em.progress("first")
        in_work.set()
        while not em.cancel.is_set():  # 段の境目で旗を見る仕事の代わり
            time.sleep(IDLE_SLEEP_S)
        em.log("saw the cancel")
        return "finished-anyway"

    runner.start(work, rec.on_done)
    assert in_work.wait(WAIT_LIMIT_S)
    root.pump_until(lambda: rec.done is not None)
    assert rec.done[0] == "finished-anyway" and rec.done[1] is None  # 結果を例外に置き換えない
    assert "could not be updated" in runner.poll_warning and "tk is gone" in runner.poll_warning
    assert ("p", "first") in rec.events and ("l", "saw the cancel") in rec.events  # 残った進み・ログも画面へ流す
    assert runner.running is False and gc.isenabled() and runner.cancel_event.is_set()


# ---------------------------------------------------------------- GC
def test_gc_is_off_while_the_job_runs_and_back_on_after_with_one_collect(monkeypatch):
    collects = []
    real = gc.collect
    monkeypatch.setattr(gc, "collect", lambda *a: collects.append(1) or real(*a))
    states = []
    _runner, rec, _ = run(lambda em: states.append(gc.isenabled()))
    assert states == [False] and gc.isenabled() is True and collects == [1]  # 止めて走り、終わって戻し、主スレッドで集める


def test_a_gc_that_was_already_off_stays_off():
    gc.disable()
    try:
        states = []
        run(lambda em: states.append(gc.isenabled()))
        assert states == [False] and gc.isenabled() is False
    finally:
        gc.enable()  # この試験が替えた状態を戻す（gc_guard の前に）


def test_overlapping_jobs_on_two_runners_hold_the_gc_until_the_last_one_ends(monkeypatch):
    collects = []
    real = gc.collect
    monkeypatch.setattr(gc, "collect", lambda *a: collects.append(1) or real(*a))
    root = FakeRoot()
    release_a, release_b = threading.Event(), threading.Event()
    a, b = Recorder(), Recorder()
    ra = jobs.JobRunner(root, a.on_progress, a.on_log)
    rb = jobs.JobRunner(root, b.on_progress, b.on_log)
    ra.start(lambda em: release_a.wait(WAIT_LIMIT_S), a.on_done)
    rb.start(lambda em: release_b.wait(WAIT_LIMIT_S), b.on_done)
    assert jobs._GC_JOBS == 2 and not gc.isenabled()
    release_a.set()
    root.pump_until(lambda: a.done is not None)
    assert jobs._GC_JOBS == 1 and not gc.isenabled() and collects == []  # 先に終わった方は GC を戻さない
    release_b.set()
    root.pump_until(lambda: b.done is not None)
    assert jobs._GC_JOBS == 0 and gc.isenabled() and collects == [1]


def test_starting_a_second_job_on_a_running_runner_is_refused_without_harming_the_first():
    root, rec = FakeRoot(), Recorder()
    release = threading.Event()
    runner = jobs.JobRunner(root, rec.on_progress, rec.on_log)
    runner.start(lambda em: release.wait(WAIT_LIMIT_S) and "first", rec.on_done)
    with pytest.raises(RuntimeError, match="already running"):
        runner.start(lambda em: "second", lambda r, e, t: None)
    assert jobs._GC_JOBS == 1 and runner.running  # 拒んだ分で参照数を増やしも減らしもしない
    release.set()
    root.pump_until(lambda: rec.done is not None)
    assert rec.done[0] == "first"


# ---------------------------------------------------------------- 完了の通知とスレッドの終わりの順序
_RealQueue = jobs.queue.Queue


class HoldingQueue(_RealQueue):
    """"done" を入れた直後に、入れた側（ワーカーのスレッド）を release が立つまで止める。主スレッドが done を読んでも、ワーカーはまだ生きている状態を作る。"""

    entered = threading.Event()
    release = threading.Event()

    def put(self, item, *a, **k):
        super().put(item, *a, **k)
        if item[0] == "done":
            HoldingQueue.entered.set()
            HoldingQueue.release.wait(WAIT_LIMIT_S)


@pytest.fixture()
def holding(monkeypatch):
    HoldingQueue.entered, HoldingQueue.release = threading.Event(), threading.Event()
    monkeypatch.setattr(jobs.queue, "Queue", HoldingQueue)
    yield HoldingQueue
    HoldingQueue.release.set()  # 試験が落ちても、止めたスレッドを残さない


def test_gc_and_on_done_wait_for_the_worker_thread_to_really_end(holding):
    root, rec = FakeRoot(), Recorder()
    runner = jobs.JobRunner(root, rec.on_progress, rec.on_log)
    runner.start(lambda em: "r", rec.on_done)
    assert holding.entered.wait(WAIT_LIMIT_S)  # done はキューにある・ワーカーは止まっている（生きている）
    calls = root.calls
    root.pump_until(lambda: root.calls >= calls + 5)  # 主ループが done を読んでも
    assert rec.done is None and runner.running and not gc.isenabled() and jobs._GC_JOBS == 1  # GC は戻らず、on_done も呼ばれない
    holding.release.set()
    root.pump_until(lambda: rec.done is not None)
    assert rec.done[0] == "r" and gc.isenabled() and jobs._GC_JOBS == 0 and runner.running is False
    assert not runner._thread.is_alive()  # 戻したときには、スレッドは終わっている


def test_when_the_worker_does_not_end_in_time_on_done_is_called_but_the_gc_stays_held(holding, monkeypatch):
    monkeypatch.setattr(jobs, "THREAD_END_LIMIT_S", 0.05)
    root, rec = FakeRoot(), Recorder()
    runner = jobs.JobRunner(root, rec.on_progress, rec.on_log)
    runner.start(lambda em: "r", rec.on_done)
    root.pump_until(lambda: rec.done is not None)
    assert rec.done[0] == "r" and runner.running is False
    assert not gc.isenabled() and jobs._GC_JOBS == 1  # 別スレッドの GC を避けるため、戻さない
    assert "did not end" in runner.poll_warning
    holding.release.set()
    runner._thread.join(WAIT_LIMIT_S)
    root.pump_until(lambda: gc.isenabled(), limit_s=2.0)  # 後から主スレッドの after が保持を外す
    assert jobs._GC_JOBS == 0


def test_a_late_ending_worker_releases_its_gc_hold_later_on_the_main_thread(holding, monkeypatch):
    monkeypatch.setattr(jobs, "THREAD_END_LIMIT_S", 0.05)
    root, rec = FakeRoot(), Recorder()
    runner = jobs.JobRunner(root, rec.on_progress, rec.on_log)
    runner.start(lambda em: "r", rec.on_done)
    root.pump_until(lambda: rec.done is not None)  # 上限を超えて on_done は呼ばれる
    assert rec.done[0] == "r" and not gc.isenabled() and jobs._GC_JOBS == 1  # 止めはまだ外れない
    holding.release.set()  # ワーカーが終わる
    runner._thread.join(WAIT_LIMIT_S)
    root.pump_until(lambda: gc.isenabled(), limit_s=2.0)  # 主スレッドの after が終わりを見つけて、この仕事の保持を外す
    assert jobs._GC_JOBS == 0
    assert runner._holds_gc is False


def test_when_after_is_unusable_for_the_late_watch_the_hold_stays_and_the_warning_says_so(holding, monkeypatch):
    monkeypatch.setattr(jobs, "THREAD_END_LIMIT_S", 0.05)
    rec = Recorder()

    class RootThatLosesAfterOnceDone(FakeRoot):
        def after(self, ms, fn):
            if rec.done is not None:  # on_done の後の予約（遅れての監視）だけを失敗させる
                raise RuntimeError("tk is gone")
            return super().after(ms, fn)

    root = RootThatLosesAfterOnceDone()
    runner = jobs.JobRunner(root, rec.on_progress, rec.on_log)
    runner.start(lambda em: "r", rec.on_done)
    root.pump_until(lambda: rec.done is not None)
    assert rec.done[0] == "r" and not gc.isenabled() and jobs._GC_JOBS == 1  # 解除する手段が無いので、止めたまま
    assert "kept off" in runner.poll_warning and "no later release" in runner.poll_warning
    holding.release.set()
    runner._thread.join(WAIT_LIMIT_S)
    assert jobs.release_late_holds() == 1  # スレッドが終わったと分かっている場所から、残った保持を外せる
    assert gc.isenabled() and jobs._GC_JOBS == 0 and jobs._LATE_HOLDS == []


# ---------------------------------------------------------------- Cancel の旗
def test_cancel_flag_reaches_the_work_and_does_not_leak_into_the_next_job():
    root, rec = FakeRoot(), Recorder()
    runner = jobs.JobRunner(root, rec.on_progress, rec.on_log)
    entered = threading.Event()

    def work(em):
        entered.set()
        while not em.cancel.is_set():
            time.sleep(IDLE_SLEEP_S)
        return "cancelled"

    runner.start(work, rec.on_done)
    assert entered.wait(WAIT_LIMIT_S)
    runner.request_cancel()
    root.pump_until(lambda: rec.done is not None)
    assert rec.done[0] == "cancelled" and runner.cancel_event.is_set()
    flags = []
    rec2 = Recorder()
    runner.start(lambda em: flags.append(em.cancel.is_set()), rec2.on_done)
    root.pump_until(lambda: rec2.done is not None)
    assert flags == [False] and runner.cancel_event.is_set() is False  # 仕事ごとに旗を作り直す


def test_with_a_real_tk_root_progress_and_done_arrive_on_the_main_thread(root):
    main = threading.current_thread()
    where, got = [], []
    runner = jobs.JobRunner(root, lambda ev: where.append(threading.current_thread()), lambda t: None, poll_ms=5)
    runner.start(lambda em: em.progress("x") or "done", lambda r, e, t: (got.append(r), where.append(threading.current_thread())))
    end = time.monotonic() + WAIT_LIMIT_S
    while not got and time.monotonic() < end:
        root.update()
        time.sleep(IDLE_SLEEP_S)
    assert got == ["done"] and all(t is main for t in where)
