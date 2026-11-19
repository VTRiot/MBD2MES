# -*- coding: utf-8 -*-
"""FB02: 変換中も画面が止まらない・ボタンの無効化と復帰・GIF の読み込みと大きさ・別スレッドの橋。Tk の窓は出さない（withdraw）。

FB03 で、メイン窓の Progress 欄と窓の端の GIF は外れ、進捗はモーダルのダイアログへ移った。その試験は tests/test_progress_dialog.py。"""

from __future__ import annotations

import struct
import threading
import time
from pathlib import Path

import map_synth as ms
import pytest
from conftest import fresh_settings

from mbd2mes import app_convert as ac
from mbd2mes.converter_progress import busy_animation as ba
from mbd2mes import config as cfgmod
from mbd2mes import gui
from mbd2mes.converter_progress import jobs


def _root():
    tk = pytest.importorskip("tkinter")
    last = None
    for _ in range(5):  # Tk の初期化が数回に 1 回失敗する環境がある。数回やり直す
        try:
            root = tk.Tk()
            root.withdraw()
            return root
        except tk.TclError as exc:
            last = exc
            time.sleep(0.3)
    pytest.skip(f"Tk unavailable: {last}")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(gui.renv, "detect_output_dir", lambda *a, **k: (None, "", "stub"))
    monkeypatch.setenv(gui.GIF_ENV, str(tmp_path / "no_such.gif"))  # 既定では GIF なし
    root = _root()
    a = gui.MbdGui(root)
    out = tmp_path / "out"
    out.mkdir()
    cfgmod.set_output_dir(out)
    a.out = out
    yield a
    root.destroy()


def stub_boxes(monkeypatch, yes=True):
    shown = {"info": [], "warn": [], "error": [], "asked": []}
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: shown["info"].append(a))
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: shown["warn"].append(a))
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: shown["error"].append(a))
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: shown["asked"].append(a) or yes)
    return shown


def all_states(app) -> dict:
    return {w: str(w.cget("state")) for w in app._busy_widgets}


def pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.root.update()
        time.sleep(0.005)


class Gate:
    """変換の仕事を止めておく関数の差し替え。開けるまで別スレッドで待つ（画面が止まらないことを確かめるため）。"""

    def __init__(self, monkeypatch, steps_before=3):
        self.release = threading.Event()
        self.reached = threading.Event()
        self._steps = steps_before
        real = ac.convert_many

        def slow(paths, out_dir, **kw):
            emit = kw["progress"]
            from mbd2mes import progress as prg

            for s in range(1, self._steps + 1):
                emit(prg.make_event(1, len(paths), Path(paths[0]).name, s, 0.5))
            self.reached.set()
            assert self.release.wait(30)
            return real(paths, out_dir, **kw)

        monkeypatch.setattr(ac, "convert_many", slow)


def test_per_file_failures_inside_the_conversion_also_restore_the_buttons(app, tmp_path, monkeypatch):
    bad = tmp_path / "bad.MBD"
    bad.write_bytes(b"not an mbd" * 1000)
    app.selected_files.append(bad)
    before = all_states(app)
    shown = stub_boxes(monkeypatch)
    app._on_convert()
    app.wait_idle()
    assert not app._busy and all_states(app) == before and "Failed: 1" in shown["info"][-1][1]


STEP_TEXTS = {f"Step {k}/7: {label}" for k, label in enumerate(
    ["Reading the MBD file", "Converting channel values", "Preparing the GPS position", "Building channel definitions",
     "Writing channel data files", "Writing laps and checking the result", "Finishing"], start=1)}


# ---------------------------------------------------------------- 対応表・窓を閉じる
def test_map_tab_actions_do_nothing_while_converting(app, tmp_path, monkeypatch):
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    stub_boxes(monkeypatch)
    gate = Gate(monkeypatch)
    app._on_convert()
    while not gate.reached.is_set():
        app.root.update()
    saved = []
    monkeypatch.setattr(gui.map_rules, "save_map_preserving_others", lambda *a, **k: saved.append(1))
    app._on_save_map()
    app._on_reset_all()
    app._on_delete_row()
    app._on_edit_row()
    assert saved == []
    gate.release.set()
    app.wait_idle()


def test_the_window_cannot_be_closed_while_converting(app, tmp_path, monkeypatch):
    """変換中は閉じさせない（公開の途中でプロセスが終わると、退避した既存の MES が消えたままになりうる。Codex の FB02 レビュー [1]）。
    終わったら、聞かずに閉じる。"""
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    shown = stub_boxes(monkeypatch, yes=True)
    gate = Gate(monkeypatch)
    app._on_convert()
    while not gate.reached.is_set():
        app.root.update()
    destroyed = []
    monkeypatch.setattr(app.root, "destroy", lambda: destroyed.append(1))
    app._on_close()
    assert destroyed == [] and shown["info"] == []  # はいと答える道は無い。案内の窓（モーダル）も出さない（ダイアログを前に出し、ログに書く）
    assert shown["asked"] == [] and "Press Cancel in the progress window" in app.log_text.get("1.0", "end")
    gate.release.set()
    app.wait_idle()
    app._on_close()  # 変換していなければ、聞かずに閉じる
    assert destroyed == [1]


def test_batch_failure_in_the_thread_restores_buttons_and_the_check(app, tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    cfgmod.set_last_mbd_dir(src)
    cfgmod.set_batch_checkpoint(src, 946684800 * 10**9, [])
    ms.write(src / "a.MBD", course="a")
    shown = stub_boxes(monkeypatch)
    before = all_states(app)
    monkeypatch.setattr(gui.batch, "scan_mbd_directory", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("scan blew up")))
    app.convert_all_var.set(True)
    app._on_convert_unconverted()
    app.wait_idle()
    assert not app._busy and all_states(app) == before and app.convert_all_var.get() is False
    assert shown["error"] and "scan blew up" in shown["error"][0][1]


# ---------------------------------------------------------------- 5: 窓の端の GIF（絵は別。置き場と、変換中だけ再生する仕組み）
def make_gif(path: Path, frames: int = 3, size: int = 4) -> Path:
    """試験用の小さなアニメーション GIF（透過 1 色・数コマのループ）を手で組む（GIF89a。LZW は 2 画素ごとに clear して符号長を増やさない形）。"""
    palette = [(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255)]  # 0 番を透過に使う
    out = bytearray(b"GIF89a" + struct.pack("<HHBBB", size, size, 0x81, 0, 0))  # グローバルパレット 4 色
    for r, g, b in palette:
        out += bytes((r, g, b))
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"  # ループ
    for f in range(frames):
        out += b"\x21\xf9\x04" + bytes((0x09, 12, 0, 0)) + b"\x00"  # 透過あり・後始末 2・12/100 秒・透過色 0
        out += b"," + struct.pack("<HHHHB", 0, 0, size, size, 0)
        pixels = [1 + (f % 3) if (x + y) % 2 == 0 else 0 for y in range(size) for x in range(size)]
        bits, nbits, data = 0, 0, bytearray()

        def put(code, bits=0, nbits=0):
            return bits | (code << nbits), nbits + 3

        codes = []
        for i in range(0, len(pixels), 2):
            codes += [4, *pixels[i:i + 2]]  # clear, 画素, 画素（画素数が奇数のとき最後は 1 画素）
        codes.append(5)  # 終わり
        for c in codes:
            bits, nbits = put(c, bits, nbits)
            while nbits >= 8:
                data.append(bits & 0xFF)
                bits >>= 8
                nbits -= 8
        if nbits:
            data.append(bits & 0xFF)
        out += b"\x02"  # 最小符号長 2
        for i in range(0, len(data), 255):
            chunk = data[i:i + 255]
            out += bytes((len(chunk),)) + bytes(chunk)
        out += b"\x00"
    out += b";"
    path.write_bytes(bytes(out))
    return path


@pytest.mark.parametrize("payload", [b"", b"not a gif at all", b"GIF89a\x01\x00"])
def test_a_missing_or_broken_gif_never_raises(app, tmp_path, payload):
    bad = tmp_path / "bad.gif"
    bad.write_bytes(payload)
    for path in (bad, tmp_path / "nope.gif", tmp_path):  # 壊れた・無い・フォルダ
        anim = ba.BusyAnimation(app.root, path)
        assert anim.loaded is False and anim.start() is False
        anim.stop()


def test_gif_path_has_one_place_and_the_size_target_is_1_5_cm(app):
    assert gui.GIF_RELATIVE_PATH == ("Pic", "anim", "busy.gif") and ba.GIF_SIZE_CM == 1.5
    assert ba.recommended_size_px(app.root) == round(app.root.winfo_fpixels("1.5c"))
    assert ba.recommended_size_px(app.root) > 20


def test_default_gif_path_without_the_env_var(monkeypatch):
    monkeypatch.delenv(gui.GIF_ENV, raising=False)
    assert ba.resolve_gif_path(gui.GIF_LOCATION) == cfgmod.app_base_dir() / "Pic" / "anim" / "busy.gif"


# ---------------------------------------------------------------- jobs.py（スレッドの橋）
class FakeRoot:
    def __init__(self):
        self.pending = []

    def after(self, _ms, fn):
        self.pending.append(fn)

    def run(self, until, timeout=10.0):
        end = time.monotonic() + timeout
        while not until() and time.monotonic() < end:
            todo, self.pending = self.pending, []
            for fn in todo:
                fn()
            time.sleep(0.002)


def test_job_runner_delivers_progress_log_and_result_on_the_calling_thread():
    root, got, main = FakeRoot(), [], threading.get_ident()

    def on_progress(ev):
        got.append(("progress", ev, threading.get_ident() == main))

    def on_log(text):
        got.append(("log", text, threading.get_ident() == main))

    runner = jobs.JobRunner(root, on_progress, on_log, poll_ms=1)
    done = []

    def work(emit):
        emit.log("hello")
        emit.progress("ev1")
        return 42

    runner.start(work, lambda res, exc, tb: done.append((res, exc, tb, threading.get_ident() == main)))
    assert runner.running
    root.run(lambda: done)
    assert done == [(42, None, "", True)] and not runner.running
    assert got == [("log", "hello", True), ("progress", "ev1", True)]


def test_job_runner_carries_exceptions_and_refuses_a_second_job():
    root = FakeRoot()
    runner = jobs.JobRunner(root, lambda e: None, lambda t: None, poll_ms=1)
    gate, done = threading.Event(), []

    def work(_emit):
        gate.wait(10)
        raise ValueError("bad input")

    runner.start(work, lambda res, exc, tb: done.append((res, exc, tb)))
    with pytest.raises(RuntimeError):
        runner.start(lambda e: 1, lambda *a: None)
    gate.set()
    root.run(lambda: done)
    res, exc, tb = done[0]
    assert res is None and isinstance(exc, ValueError) and "bad input" in tb and "ValueError" in tb and not runner.running
    again = []
    runner.start(lambda e: "ok", lambda res, exc, tb: again.append(res))  # 失敗の後も、次の仕事を始められる
    root.run(lambda: again)
    assert again == ["ok"]


def test_the_convert_all_check_is_reset_on_every_early_return(app, tmp_path, monkeypatch):
    """一発変換が、出力先なし・前回のフォルダなし・日付の欄が不正、のどれで早く終わっても「全部変換」のチェックを必ずオフへ戻す。"""
    stub_boxes(monkeypatch)
    src = tmp_path / "src"
    src.mkdir()
    # 出力先なし
    cfg = cfgmod.load_or_init_config()
    cfg["output_dir"] = None
    cfgmod._atomic_write_json(cfgmod.config_path(), cfg)
    app.convert_all_var.set(True)
    app._on_convert_unconverted()
    assert app.convert_all_var.get() is False
    # 出力先はあるが前回のフォルダなし
    cfgmod.set_output_dir(app.out)
    app.convert_all_var.set(True)
    app._on_convert_unconverted()
    assert app.convert_all_var.get() is False
    # 日付の欄が不正
    cfgmod.set_last_mbd_dir(src)
    app.date_var.set("not-a-date")
    app.convert_all_var.set(True)
    app._on_convert_unconverted()
    assert app.convert_all_var.get() is False and not app._busy


# ---------------------------------------------------------------- GIF の大きさ（約 1.5 cm に合わせる。Codex の FB02 レビュー [2]）
@pytest.mark.parametrize("w, h, target, expected", [
    # 手で計算した値: 変換後の長い辺と目標（57 px）の絶対差が最も小さい整数倍（隣り合う 2 つを比べる。縮小後は切り上げ）
    (57, 57, 57, (1, 1)),  # ちょうど
    (64, 64, 57, (1, 1)),  # 64（差 7）と 32（差 25）-> 1 倍
    (256, 256, 57, (1, 5)),  # 1/4 = 64（差 7）と 1/5 = 52（差 5）-> 1/5（Codex の FB02 2 巡目 [1]）
    (228, 100, 57, (1, 4)),  # 長い辺 228 -> 1/4 = 57（差 0）
    (100, 100, 57, (1, 2)),  # 100（差 43）と 50（差 7）-> 1/2
    (40, 40, 57, (1, 1)),  # 40（差 17）と 80（差 23）-> 1 倍
    (12, 12, 57, (5, 1)),  # 4 倍 = 48（差 9）と 5 倍 = 60（差 3）-> 5 倍
    (30, 20, 57, (2, 1)),  # 1 倍 = 30（差 27）と 2 倍 = 60（差 3）-> 2 倍
    (0, 0, 57, (1, 1)), (57, 57, 0, (1, 1)),
])
def test_scale_factors_pick_the_integer_ratio_closest_to_the_target(w, h, target, expected):
    assert ba.scale_factors(w, h, target) == expected  # 手で計算した値


def test_frames_are_fitted_to_about_1_5_cm_and_keep_playing(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    root = _root()
    try:
        for size in (12, 57, 120):  # 小さい（拡げる）・ちょうど・大きい（縮める）。画素数が多いと手組みの GIF の生成が遅いので 120 まで
            gif = make_gif(tmp_path / f"s{size}.gif", frames=3, size=size)
            frames = ba.fit_frames(ba.load_frames(gif, root), 57)
            assert len(frames) == 3
            side = frames[0].width()
            assert abs(side - 57) <= 57 * 0.3, (size, side)  # 約 1.5 cm（整数倍なので、ちょうどにはならないことがある）
            assert frames[0].height() == side  # 正方形のまま
        anim = ba.BusyAnimation(root, make_gif(tmp_path / "big.gif", frames=3, size=120))
        target = ba.recommended_size_px(root)
        assert abs(anim.frames[0].width() - target) <= target * 0.5 and len(anim.frames) == 3
    finally:
        root.destroy()


def test_job_runner_applies_only_the_latest_progress_when_several_pile_up_and_keeps_the_log_order():
    """画面を触るたびに GIL を取り戻すのを待つので、溜まった進みは最後の 1 つだけ反映する（バーは単調のまま）。ログとの順序は保つ。"""
    root, seen = FakeRoot(), []
    runner = jobs.JobRunner(root, lambda ev: seen.append(("progress", ev)), lambda t: seen.append(("log", t)), poll_ms=1)
    done = []
    runner.running = True
    runner._on_done = lambda res, exc, tb: done.append(res)
    for item in (("progress", 1), ("progress", 2), ("progress", 3), ("log", "x"), ("progress", 4), ("progress", 5),
                 ("done", "result", None, "")):
        runner._q.put(item)
    runner._poll()
    assert seen == [("progress", 3), ("log", "x"), ("progress", 5)] and done == ["result"] and not runner.running


def test_the_worker_yields_the_gil_each_time_it_reports_progress(monkeypatch):
    import queue

    slept = []
    monkeypatch.setattr(jobs.time, "sleep", lambda s: slept.append(s))
    q = queue.Queue()
    jobs.Emitter(q).progress("ev")
    assert slept == [jobs.PROGRESS_YIELD_S] and jobs.PROGRESS_YIELD_S > 0 and q.get_nowait() == ("progress", "ev")


def test_job_runner_gives_the_work_a_cancel_flag_that_request_cancel_sets():
    """FB03: 仕事は emit.cancel（旗）を見て止まれる。request_cancel は走っている仕事の旗を立てる。旗は仕事ごとに作り直す。"""
    root, done = FakeRoot(), []
    runner = jobs.JobRunner(root, lambda e: None, lambda t: None, poll_ms=1)
    started = threading.Event()

    def work(emit):
        assert emit.cancel is runner.cancel_event and not emit.cancel.is_set()
        started.set()
        assert emit.cancel.wait(10)  # Cancel が来るまで待つ
        return "stopped"

    runner.start(work, lambda res, exc, tb: done.append(res))
    assert started.wait(10)
    runner.request_cancel()
    root.run(lambda: done)
    assert done == ["stopped"]
    first = runner.cancel_event
    runner.start(lambda emit: emit.cancel.is_set(), lambda res, exc, tb: done.append(res))  # 次の仕事は、立っていない新しい旗
    root.run(lambda: len(done) == 2)
    assert done[1] is False and runner.cancel_event is not first


def test_emitter_without_a_flag_has_none():
    import queue

    assert jobs.Emitter(queue.Queue()).cancel is None


def test_garbage_collection_is_paused_while_a_job_runs_and_done_on_the_main_thread_afterwards(monkeypatch):
    """別スレッドで GC が走ると、主スレッドの Tk の変数・画像がそのスレッドで片付けられて Tcl が落ちる（FB03 の全件の試験で実際に落ちた）。
    仕事の間は GC を止め、終わったら主スレッドで集める。もともと止めてあれば、止めたまま。"""
    import gc

    main = threading.get_ident()
    collected = []
    real_collect = gc.collect
    monkeypatch.setattr(jobs.gc, "collect", lambda *a: collected.append(threading.get_ident()) or real_collect(*a))
    for initially in (True, False):
        (gc.enable if initially else gc.disable)()
        try:
            root, seen, done = FakeRoot(), [], []
            runner = jobs.JobRunner(root, lambda e: None, lambda t: None, poll_ms=1)

            def work(_emit):
                seen.append(gc.isenabled())  # 仕事（別スレッド）の間
                return 1

            collected.clear()
            runner.start(work, lambda res, exc, tb: done.append(gc.isenabled()))
            assert gc.isenabled() is False  # 仕事を始めたら止まる
            root.run(lambda: done)
            assert seen == [False] and done == [initially]  # 仕事の間は止まり、終わったら元の状態へ戻る
            assert collected == [main]  # 集めるのは主スレッド
        finally:
            gc.enable()
    # 始められなかったときも戻る
    gc.enable()
    runner = jobs.JobRunner(FakeRoot(), lambda e: None, lambda t: None)
    monkeypatch.setattr(jobs.threading.Thread, "start", lambda self: (_ for _ in ()).throw(RuntimeError("no thread")))
    with pytest.raises(RuntimeError):
        runner.start(lambda e: 1, lambda *a: None)
    assert gc.isenabled() and not runner.running


def test_garbage_collection_stays_paused_until_the_last_of_overlapping_jobs_finishes(monkeypatch):
    """GC はプロセス共通。2 つの仕事が重なったとき、先に終わった方で戻さない（Codex の FB03 レビュー [2]）。"""
    import gc

    gate1, gate2 = threading.Event(), threading.Event()
    root1, root2, done = FakeRoot(), FakeRoot(), []
    r1 = jobs.JobRunner(root1, lambda e: None, lambda t: None, poll_ms=1)
    r2 = jobs.JobRunner(root2, lambda e: None, lambda t: None, poll_ms=1)
    gc.enable()
    try:
        r1.start(lambda e: gate1.wait(10), lambda *a: done.append(1))
        r2.start(lambda e: gate2.wait(10), lambda *a: done.append(2))
        assert gc.isenabled() is False
        gate1.set()
        root1.run(lambda: 1 in done)
        assert gc.isenabled() is False  # 1 つ目が終わっても、2 つ目が走っている間は止めたまま
        gate2.set()
        root2.run(lambda: 2 in done)
        assert gc.isenabled() is True  # 最後の仕事が終わったら戻る
    finally:
        gate1.set()
        gate2.set()
        gc.enable()


def test_a_failed_start_restores_everything_wherever_it_fails():
    """開始の準備のどこで失敗しても、GC・running・保持の旗が戻る（Codex の FB03 レビュー 2 巡目 [1]）。after() の登録の失敗・スレッドの開始の失敗の
    どちらでも。開始に失敗した仕事の予約済みの _poll は、何もせず、再予約もしない。"""
    import gc

    class BrokenAfter(FakeRoot):
        def after(self, _ms, fn):
            raise RuntimeError("after failed")

    gc.enable()
    runner = jobs.JobRunner(BrokenAfter(), lambda e: None, lambda t: None)
    ran = []
    with pytest.raises(RuntimeError, match="after failed"):
        runner.start(lambda e: ran.append(1), lambda *a: None)
    assert gc.isenabled() and not runner.running and jobs._GC_JOBS == 0 and not runner._holds_gc
    assert ran == []  # 予約が失敗したので、スレッドは始めていない
    # スレッドの開始が失敗: 予約済みの _poll は何もしない
    root = FakeRoot()
    runner2 = jobs.JobRunner(root, lambda e: None, lambda t: None, poll_ms=1)
    real_start = jobs.threading.Thread.start
    jobs.threading.Thread.start = lambda self: (_ for _ in ()).throw(RuntimeError("no thread"))
    try:
        with pytest.raises(RuntimeError, match="no thread"):
            runner2.start(lambda e: 1, lambda *a: None)
    finally:
        jobs.threading.Thread.start = real_start
    assert gc.isenabled() and not runner2.running and jobs._GC_JOBS == 0
    pending, root.pending = root.pending, []
    for fn in pending:
        fn()  # 予約済みだった _poll
    assert root.pending == []  # 再予約しない（止まらずに回り続けない）
    done = []
    runner2.start(lambda e: "again", lambda res, exc, tb: done.append(res))  # 失敗の後も、次の仕事を始められる
    root.run(lambda: done)
    assert done == ["again"] and gc.isenabled() and jobs._GC_JOBS == 0
