# -*- coding: utf-8 -*-
"""FB03: 変換中のモーダルの進捗ダイアログ（Windows の進捗ダイアログの形・Cancel・GIF・自動で閉じる）と、メイン窓が FB02 以前の見た目に戻ること。
Tk の窓は出さない（親を withdraw。ダイアログも親が見えない間は見えない）。"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import map_synth as ms
import pytest
from conftest import fresh_settings
from test_gui_progress import _root, make_gif, pump, stub_boxes

from mbd2mes import app_convert as ac
from mbd2mes import batch
from mbd2mes import busy_animation as ba
from mbd2mes import config as cfgmod
from mbd2mes import convert as cv
from mbd2mes import gui
from mbd2mes import progress as prg
from mbd2mes import progress_dialog as pd

PAST_NS = 946684800 * 10**9


@pytest.fixture()
def app(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(gui.renv, "detect_output_dir", lambda *a, **k: (None, "", "stub"))
    monkeypatch.setenv(ba.GIF_ENV, str(tmp_path / "no_such.gif"))  # 既定では GIF なし
    root = _root()
    a = gui.MbdGui(root)
    out = tmp_path / "out"
    out.mkdir()
    cfgmod.set_output_dir(out)
    a.out = out
    yield a
    root.destroy()


def snapshot(d: Path) -> dict:
    import hashlib

    if not d.exists():
        return {}
    return {p.relative_to(d).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<dir>") for p in sorted(d.rglob("*"))}


class Block:
    """name の変換を、指定の場所（段の途中 / 公開の最中）で止めておく。reached を待ち、release で進める（その間、画面は動く）。"""

    def __init__(self, monkeypatch, name: str, step: int = 5, frac: float = 0.2, where: str = "progress"):
        self.reached, self.release = threading.Event(), threading.Event()
        real = cv.convert_one

        def wrapped(path, *a, **k):
            if path.name != name:
                return real(path, *a, **k)
            if where == "progress":
                user = k.get("progress")

                def hook(s, f):
                    if user is not None:
                        user(s, f)
                    if s == step and f >= frac and not self.reached.is_set():
                        self.reached.set()
                        assert self.release.wait(30)

                k["progress"] = hook
            return real(path, *a, **k)

        monkeypatch.setattr(cv, "convert_one", wrapped)
        if where == "publish":  # 入れ替え（作業フォルダの MES を最終の位置へ rename）の直前で止める = 公開の最中
            real_rename = Path.rename
            mes_name = cv.sanitize_mes_name(Path(name).stem)

            def rename(self_path, target):
                if self_path.name == f"{mes_name}.MES" and self_path.parent.name.startswith(cv.STAGE_PREFIX):
                    self.reached.set()
                    assert self.release.wait(30)
                return real_rename(self_path, target)

            monkeypatch.setattr(Path, "rename", rename)

    def wait(self, app, timeout=30.0):
        end = time.monotonic() + timeout
        while not self.reached.is_set() and time.monotonic() < end:
            app.root.update()
            time.sleep(0.005)
        assert self.reached.is_set()


def states(app) -> dict:
    return {w: str(w.cget("state")) for w in app._busy_widgets}


def event(file_index=1, file_count=1, name="a.MBD", step=1, frac=0.0):
    return prg.make_event(file_index, file_count, name, step, frac)


# ---------------------------------------------------------------- 1: メイン窓は FB02 以前の見た目
def test_main_window_has_no_progress_panel_and_no_animation(app):
    def walk(w):
        yield w
        for c in w.winfo_children():
            yield from walk(c)

    titles = [str(w.cget("text")) for w in walk(app.root) if w.winfo_class() == "Labelframe"]
    assert "Progress" not in titles and {"Log", "MBD Files to Convert", "Output Directory", "Recording Date (HED)"} <= set(titles)
    assert app.root.place_slaves() == [] and not hasattr(app, "animation") and not hasattr(app, "progress_bar")
    assert app.log_text.winfo_exists()  # ログ欄は残る


# ---------------------------------------------------------------- 2: ダイアログの形
def make_dialog(root, **kw):
    called = []
    d = pd.ProgressDialog(root, on_cancel=lambda: called.append(1), **kw)
    return d, called


def test_dialog_has_the_standard_windows_progress_layout(tmp_path):
    root = _root()
    try:
        d, _ = make_dialog(root, gif_path=tmp_path / "no.gif")
        assert d.title() == "Converting..." and d.resizable() == (False, False)  # 固定サイズ（最大化のボタンも無い）
        assert str(d.transient()) == str(root)  # 親の上に出る・最小化のボタンも無い
        assert (d.file_var.get(), d.percent_var.get(), d.time_var.get()) == ("Preparing...", "0%", "Elapsed: 0:00    Remaining: calculating...")
        rows = {}
        for w in d.winfo_children()[0].winfo_children():
            info = w.grid_info()
            if info:
                rows[int(info["row"])] = (w.winfo_class(), str(info.get("sticky")))
        # 上: 今の処理の説明 -> % 付きのバー -> 経過時間 -> 区切り -> 右下の Cancel
        assert [rows[r][0] for r in sorted(rows)] == ["Label", "Label", "Frame", "Label", "TSeparator", "TButton"]
        assert rows[5] == ("TButton", "e") and str(d.cancel_button.cget("text")) == "Cancel"
        assert d.bar.winfo_class() == "TProgressbar" and str(d.bar.cget("mode")) == "determinate" and float(d.bar.cget("maximum")) == 100.0
        d.close()
    finally:
        root.destroy()


def test_gif_goes_to_the_right_margin_and_without_a_gif_the_margin_is_closed_up(tmp_path):
    root = _root()
    try:
        none, _ = make_dialog(root, gif_path=tmp_path / "no.gif")
        gif = make_gif(tmp_path / "busy.gif", frames=3, size=60)
        with_gif, _ = make_dialog(root, gif_path=gif)
        assert none.animation.label is None and none.animation.loaded is False
        info = with_gif.animation.label.grid_info()
        assert int(info["column"]) == 1 and int(info["row"]) == 0 and int(info["rowspan"]) == 4 and str(info["sticky"]) == "ne"  # 右の余白・上寄せ
        assert with_gif.winfo_reqwidth() > none.winfo_reqwidth() + 40  # GIF の分だけ広い。無いときは余白を詰める
        assert none.winfo_reqwidth() <= pd.BAR_PX + 120
        none.close()
        with_gif.close()
    finally:
        root.destroy()


def test_dialog_is_centered_on_the_parent_and_fixed_in_size(tmp_path, monkeypatch):
    import tkinter as tk

    root = _root()
    try:
        root.winfo_viewable = lambda: True  # 親が見えている状態の座標（窓は出さない。値だけ差し替える）
        root.winfo_width, root.winfo_height = (lambda: 900), (lambda: 640)
        root.winfo_rootx, root.winfo_rooty = (lambda: 120), (lambda: 80)
        specs = []
        real_geometry = tk.Toplevel.geometry

        def record(self, spec=None):
            if spec:
                specs.append(spec)
            return real_geometry(self, spec)

        monkeypatch.setattr(pd.ProgressDialog, "geometry", record)
        d, _ = make_dialog(root, gif_path=tmp_path / "no.gif")
        w, h = d.winfo_reqwidth(), d.winfo_reqheight()
        # 要求された大きさに固定し、親窓の中央（手計算: x = 120 + (900 - w) / 2、y = 80 + (640 - h) / 2）
        assert specs[-1] == f"{w}x{h}+{120 + (900 - w) // 2}+{80 + (640 - h) // 2}"
        assert d.resizable() == (False, False)
        d.close()
    finally:
        root.destroy()


def test_dialog_progress_text_bar_and_time(tmp_path):
    root = _root()
    try:
        now = [100.0]
        d, _ = make_dialog(root, gif_path=tmp_path / "no.gif", clock=lambda: now[0])
        d.update_progress(event(2, 5, "b.MBD", 3, 0.5))
        assert d.file_var.get() == "File 2/5: b.MBD" and d.step_var.get() == "Step 3/7: Preparing the GPS position"
        v1 = float(d.bar["value"])
        assert v1 == pytest.approx(prg.overall(2, 5, 3, 0.5) * 100) and d.percent_var.get() == f"{int(v1)}%"
        d.update_progress(event(1, 5, "a.MBD", 1, 0.1))  # 古い・小さい通知が来ても、バーは戻らない
        assert float(d.bar["value"]) == v1 and d.percent_var.get() == f"{int(v1)}%"
        now[0] = 110.0  # 10 秒経過・進み 25% のつもり: 手計算 残り 30 秒
        d._max_value = 25.0
        assert d._time_text() == "Elapsed: 0:10    Remaining: about 0:30"
        now[0] = 101.0
        assert d._time_text() == "Elapsed: 0:01    Remaining: calculating..."  # 始めのうちは当てにならない
        d.close()
    finally:
        root.destroy()


def test_cancel_button_x_and_escape_all_cancel_once(tmp_path):
    root = _root()
    try:
        for how in ("button", "x", "escape"):
            d, called = make_dialog(root, gif_path=tmp_path / "no.gif")
            d.update_progress(event(1, 1, "a.MBD", 4, 0.2))
            if how == "button":
                d.cancel_button.invoke()
            elif how == "x":
                cmd = root.tk.call("wm", "protocol", str(d), "WM_DELETE_WINDOW")  # × が呼ぶ関数
                root.tk.call(cmd)
            else:
                assert d.bind("<Escape>")  # Esc も Cancel に結ばれている
                d.request_cancel()
            assert called == [1] and d.cancel_requested
            assert d.cancel_button.instate(["disabled"]) and d.step_var.get() == pd.CANCELLING_TEXT  # 押せなくし、案内を出す
            d.request_cancel()
            d.cancel_button.invoke()
            assert called == [1]  # 2 回目以降は何もしない
            d.update_progress(event(1, 1, "a.MBD", 5, 0.5))
            assert d.step_var.get() == pd.CANCELLING_TEXT and "Remaining" not in d._time_text()  # 案内を上書きしない
            d.close()
            assert not d.winfo_exists()
    finally:
        root.destroy()


def test_dialog_close_is_idempotent_and_stops_the_gif(tmp_path):
    root = _root()
    try:
        d, _ = make_dialog(root, gif_path=make_gif(tmp_path / "busy.gif", frames=3, size=40))
        anim = d.animation
        assert anim.running  # 開いている間は動く
        images = set()
        end = time.monotonic() + 0.8
        while time.monotonic() < end:
            root.update()
            images.add(str(anim.label.cget("image")))
            time.sleep(0.01)
        assert len(images) == 3
        d.close()
        d.close()
        assert anim.running is False and not d.winfo_exists()
        assert anim.frames == [] and anim.label is None and d.file_var is None  # GIF のコマと Tk の変数は、閉じるときに（主スレッドで）手放す
    finally:
        root.destroy()


# ---------------------------------------------------------------- 2: 変換の流れ（モーダルを出し、自動で閉じる）
def test_convert_shows_the_modal_dialog_then_closes_it_and_reports_in_the_log(app, tmp_path, monkeypatch):
    app.selected_files.append(ms.write(tmp_path / "26.11.8a.MBD", course="a"))
    shown = stub_boxes(monkeypatch)
    before = states(app)
    block = Block(monkeypatch, "26.11.8a.MBD", step=5, frac=0.2)
    app._on_convert()
    block.wait(app)
    pump(app, 0.2)
    d = app._dialog
    assert d is not None and d.winfo_exists() and d.title() == "Converting..."
    assert d.file_var.get() == "File 1/1: 26.11.8a.MBD" and d.step_var.get().startswith("Step ") and float(d.bar["value"]) > 50
    assert all(v == "disabled" for v in states(app).values())
    block.release.set()
    app.wait_idle()
    assert app._dialog is None and not d.winfo_exists() and states(app) == before  # 自動で閉じ、部品も戻る
    log = app.log_text.get("1.0", "end")
    assert "recording date 2026-11-08 (file name)" in log and "Invariant check: PASS" in log  # 結果はメイン窓のログへ
    assert shown["info"] and "Converted 1 of 1" in shown["info"][-1][1] and shown["error"] == []


def test_a_failed_conversion_closes_the_dialog_restores_the_buttons_and_shows_the_error(app, tmp_path, monkeypatch):
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    shown = stub_boxes(monkeypatch)
    before = states(app)
    seen = []
    real_open = app._open_progress_dialog
    app._open_progress_dialog = lambda: (real_open(), seen.append(app._dialog))

    def boom(*a, **k):
        raise RuntimeError("converter exploded")

    monkeypatch.setattr(ac, "convert_many", boom)
    app._on_convert()
    app.wait_idle()
    assert seen and seen[0] is not None and not seen[0].winfo_exists() and app._dialog is None  # 出て、閉じた
    assert states(app) == before and shown["error"] and "converter exploded" in shown["error"][0][1]
    assert "converter exploded" in app.log_text.get("1.0", "end")


def test_the_dialog_failing_to_open_does_not_stop_the_conversion(app, tmp_path, monkeypatch):
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    stub_boxes(monkeypatch)

    def no_dialog(*a, **k):
        raise RuntimeError("no dialog today")

    monkeypatch.setattr(gui.progress_dialog, "ProgressDialog", no_dialog)
    app._on_convert()
    app.wait_idle()
    assert (app.out / "a.MES" / "a.DDD").is_file() and "The progress dialog could not be shown" in app.log_text.get("1.0", "end")


def test_the_gif_plays_in_the_dialog_only_while_converting(app, tmp_path, monkeypatch):
    monkeypatch.setenv(ba.GIF_ENV, str(make_gif(tmp_path / "busy.gif", frames=3, size=40)))
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    stub_boxes(monkeypatch)
    block = Block(monkeypatch, "a.MBD")
    app._on_convert()
    block.wait(app)
    anim = app._dialog.animation
    assert anim.loaded and anim.running and anim.label.winfo_exists()
    block.release.set()
    app.wait_idle()
    assert anim.running is False  # 終わったら止まる（ダイアログごと閉じる）


# ---------------------------------------------------------------- 3: Cancel（GUI の経路。実際の変換を止める）
def press_cancel(app, how):
    d = app._dialog
    if how == "button":
        d.cancel_button.invoke()
    else:  # × ボタン
        app.root.tk.call(app.root.tk.call("wm", "protocol", str(d), "WM_DELETE_WINDOW"))


@pytest.mark.parametrize("how", ["button", "x"])
def test_cancel_in_the_dialog_stops_a_real_conversion_without_leaving_anything(app, tmp_path, monkeypatch, how):
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    shown = stub_boxes(monkeypatch)
    before_states, out_before = states(app), snapshot(app.out)
    block = Block(monkeypatch, "a.MBD", step=5, frac=0.2)
    app._on_convert()
    block.wait(app)
    press_cancel(app, how)
    pump(app, 0.1)
    assert app._dialog.step_var.get() == pd.CANCELLING_TEXT and app._dialog.cancel_button.instate(["disabled"])
    block.release.set()  # 止めた場所から先へ進むと、次の通知の口で止まる
    app.wait_idle()
    assert app._dialog is None and states(app) == before_states
    assert snapshot(app.out) == out_before and not list(app.out.glob(cv.STAGE_PREFIX + "*"))  # 作りかけの MES も作業フォルダも無い
    log = app.log_text.get("1.0", "end")
    assert '[CANCEL] a.MBD: cancelled while "Writing channel data files"; nothing was written for it' in log
    assert "[CANCEL] Cancelled. Finished before the cancel: none" in log
    assert shown["error"] == [] and "Cancelled by the user." in shown["info"][-1][1]  # エラーではない


def test_cancel_during_publish_is_finished_first_and_logged(app, tmp_path, monkeypatch):
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    shown = stub_boxes(monkeypatch)
    block = Block(monkeypatch, "a.MBD", where="publish")
    app._on_convert()
    block.wait(app)
    press_cancel(app, "button")  # 公開の最中に Cancel
    pump(app, 0.1)
    block.release.set()
    app.wait_idle()
    assert (app.out / "a.MES" / "a.DDD").is_file() and not list(app.out.glob(cv.STAGE_PREFIX + "*"))  # 入れ替えは終わっている
    log = app.log_text.get("1.0", "end")
    assert "Cancel was requested while the MES was being published; the publish was finished first" in log
    assert "cancelled while" not in log and "Converted 1 of 1" in shown["info"][-1][1]  # 公開は終わっていて、その 1 本は変換済み


def test_cancel_in_a_batch_keeps_finished_files_and_stops_the_rest(app, tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    for n in "abc":
        ms.write(src / f"{n}.MBD", course=n)
    cfgmod.set_last_mbd_dir(src)
    cfgmod.set_batch_checkpoint(src, PAST_NS, [])
    before_cp = cfgmod.get_batch_checkpoint(src)
    shown = stub_boxes(monkeypatch, yes=True)
    before = states(app)
    block = Block(monkeypatch, "b.MBD", step=5, frac=0.3)
    app.convert_all_var.set(False)
    app._on_convert_unconverted()
    block.wait(app)
    assert app._dialog is not None and app._dialog.file_var.get().startswith("File ")
    press_cancel(app, "button")
    block.release.set()
    app.wait_idle()
    assert app._dialog is None and states(app) == before and app.convert_all_var.get() is False
    assert sorted(p.name for p in app.out.glob("*.MES")) == ["a.MES"]  # 終わった 1 本目は変換済みのまま。2 本目・3 本目は無い
    ledger = json.loads((app.out / batch.MANIFEST_NAME).read_text(encoding="utf-8"))["entries"]
    assert list(ledger) == ["a"] and cfgmod.get_batch_checkpoint(src) == before_cp  # 止めた物を変換済みと記録しない・起点は動かさない
    log = app.log_text.get("1.0", "end")
    assert "[CANCEL] Batch conversion cancelled." in log and "Finished (kept as converted): a.MBD" in log
    assert "Stopped in the middle (nothing written): b.MBD" in log and "Not started: c.MBD" in log
    assert [Path(p).name for p in app.selected_files] == ["b.MBD", "c.MBD"]  # 一覧に残る（もう一度押せる）
    assert "Cancelled by the user. Not converted: 2" in shown["info"][-1][1] and shown["error"] == []


def test_the_scan_of_a_batch_runs_without_a_dialog(app, tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    ms.write(src / "a.MBD", course="a")
    cfgmod.set_last_mbd_dir(src)
    cfgmod.set_batch_checkpoint(src, PAST_NS, [])
    stub_boxes(monkeypatch, yes=False)  # 確認の画面で No
    reached, release = threading.Event(), threading.Event()
    real = batch.scan_mbd_directory

    def slow_scan(*a, **k):
        reached.set()
        assert release.wait(30)
        return real(*a, **k)

    monkeypatch.setattr(batch, "scan_mbd_directory", slow_scan)
    app._on_convert_unconverted()
    while not reached.is_set():
        app.root.update()
    assert app._busy and app._dialog is None  # 走査の間はダイアログを出さない（変換の本体だけ）
    release.set()
    app.wait_idle()
    assert app._dialog is None and list(app.out.iterdir()) == []


def test_cli_still_has_no_dialog_cancel_or_progress_output(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys

    from conftest import ROOT, SETTINGS_ENV

    s = fresh_settings(tmp_path, monkeypatch)
    env = dict(os.environ)
    env[SETTINGS_ENV] = str(s)
    r = subprocess.run([sys.executable, "-m", "mbd2mes", str(ms.write(tmp_path / "x.MBD")), "-o", str(tmp_path / "o")], cwd=ROOT,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "CANCEL" not in r.stdout and "Step " not in r.stdout and "Converting..." not in r.stdout
