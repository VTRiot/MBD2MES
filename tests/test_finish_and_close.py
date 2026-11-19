# -*- coding: utf-8 -*-
"""B19: 変換の終わり方（成功は Done を見せてから閉じる・Cancel は待たない）と、ダイアログが出せないときのメイン窓の ×。
Tk の窓は出さない（親を withdraw。ダイアログは親が見えない間は見えない）。"""

from __future__ import annotations

import time

import map_synth as ms
from test_gui_progress import pump, stub_boxes
from test_progress_dialog import Block, app  # noqa: F401 -- app は fixture

from mbd2mes import gui
from mbd2mes.converter_progress import progress_dialog as pd

MIN_SHOW_S = pd.MIN_SHOW_S


def record_closes(monkeypatch) -> list:
    """ダイアログを閉じる直前の段の行と、finish_then_close へ渡された min_show_s を控える。"""
    seen: list = []
    real_close, real_finish = pd.ProgressDialog.close, pd.ProgressDialog.finish_then_close

    def close(self):
        if not self.closed:
            seen.append(("close", self.step_var.get() if self.step_var is not None else None, time.monotonic()))
        return real_close(self)

    def finish(self, text, full, on_closed=None, min_show_s=MIN_SHOW_S):
        seen.append(("finish", text, min_show_s))
        return real_finish(self, text, full, on_closed=on_closed, min_show_s=min_show_s)

    monkeypatch.setattr(pd.ProgressDialog, "close", close)
    monkeypatch.setattr(pd.ProgressDialog, "finish_then_close", finish)
    return seen


def test_a_quick_successful_conversion_shows_done_and_keeps_the_dialog_for_the_minimum_time(app, tmp_path, monkeypatch):
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    stub_boxes(monkeypatch)
    seen = record_closes(monkeypatch)
    t0 = time.monotonic()
    app._on_convert()
    app.wait_idle()
    closes = [s for s in seen if s[0] == "close"]
    assert closes and closes[0][1] == pd.DONE_TEXT  # 閉じる直前の段の行は Done
    assert closes[0][2] - t0 >= MIN_SHOW_S - 0.05  # 開いてから最低 MIN_SHOW_S は出ている（下限）
    assert ("finish", pd.DONE_TEXT, MIN_SHOW_S) in seen and (app.out / "a.MES" / "a.DDD").is_file()


def test_cancel_does_not_wait_for_the_minimum_time(app, tmp_path, monkeypatch):
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    stub_boxes(monkeypatch)
    seen = record_closes(monkeypatch)
    block = Block(monkeypatch, "a.MBD", step=5, frac=0.2)
    app._on_convert()
    block.wait(app)
    app._dialog.cancel_button.invoke()
    pump(app, 0.05)
    block.release.set()
    app.wait_idle()
    assert ("finish", pd.CANCELLED_TEXT, 0.0) in seen  # 待ちの時間 0 で閉じる（Done の保持も使わない）
    assert not [s for s in seen if s[0] == "finish" and s[1] == pd.DONE_TEXT]


def test_a_cancel_flag_that_arrived_too_late_still_shows_done_because_the_conversion_succeeded(app, tmp_path, monkeypatch):
    """旗が立ったかではなく、実際に止めた結果かで見分ける: 旗は立ったが変換は最後まで成功したなら、Done を見せる。"""
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    stub_boxes(monkeypatch)
    seen = record_closes(monkeypatch)
    real = gui.ac.convert_many

    def late_flag(paths, out_dir, **kw):
        out = real(paths, out_dir, **kw)  # 最後まで成功
        kw["cancel"].set()  # 終わった後で旗が立つ
        return out

    monkeypatch.setattr(gui.ac, "convert_many", late_flag)
    app._on_convert()
    app.wait_idle()
    assert ("finish", pd.DONE_TEXT, MIN_SHOW_S) in seen


def _no_dialog(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no dialog today")

    monkeypatch.setattr(gui.progress_dialog, "ProgressDialog", boom)


def _start_without_dialog(app, tmp_path, monkeypatch, yes):
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    shown = stub_boxes(monkeypatch, yes=yes)
    _no_dialog(monkeypatch)
    block = Block(monkeypatch, "a.MBD", step=5, frac=0.2)
    app._on_convert()
    block.wait(app)
    assert app._dialog is None and app._busy
    return shown, block


def test_close_without_a_dialog_asks_and_yes_sets_the_cancel_flag(app, tmp_path, monkeypatch):
    shown, block = _start_without_dialog(app, tmp_path, monkeypatch, yes=True)
    destroyed = []
    monkeypatch.setattr(app.root, "destroy", lambda: destroyed.append(1))
    app._on_close()
    assert destroyed == [] and len(shown["asked"]) == 1 and "Stop the conversion?" in shown["asked"][0][1]
    assert app._job.cancel_event.is_set()  # Yes: 旗が立った
    block.release.set()
    app.wait_idle()
    assert not (app.out / "a.MES").exists() and "Cancelled by the user." in shown["info"][-1][1]  # 実際に止まった


def test_close_without_a_dialog_asks_and_no_leaves_the_flag_down(app, tmp_path, monkeypatch):
    shown, block = _start_without_dialog(app, tmp_path, monkeypatch, yes=False)
    app._on_close()
    assert len(shown["asked"]) == 1 and not app._job.cancel_event.is_set()  # No: 旗は立たない
    block.release.set()
    app.wait_idle()
    assert (app.out / "a.MES" / "a.DDD").is_file()  # 変換は続いて成功した


def test_close_with_a_dialog_only_logs_and_never_asks_nor_stacks_a_modal(app, tmp_path, monkeypatch):
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    shown = stub_boxes(monkeypatch)
    block = Block(monkeypatch, "a.MBD", step=5, frac=0.2)
    app._on_convert()
    block.wait(app)
    destroyed = []
    monkeypatch.setattr(app.root, "destroy", lambda: destroyed.append(1))
    app._on_close()
    assert destroyed == [] and shown["asked"] == [] and shown["info"] == [] and "Press Cancel in the progress window" in app.log_text.get("1.0", "end") and not app._job.cancel_event.is_set()
    block.release.set()
    app.wait_idle()


def test_close_while_done_is_shown_does_not_point_at_cancel_nor_stack_a_modal(app, tmp_path, monkeypatch):
    """Done の保持中（仕事は終わっていて、Cancel はもう効かない）の ×: 「Cancel で止める」と案内せず、別のモーダルも重ねない。閉じもしない。"""
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    shown = stub_boxes(monkeypatch)
    destroyed = []
    seen = []
    real_finish = pd.ProgressDialog.finish_then_close

    def finish(self, text, full, on_closed=None, min_show_s=MIN_SHOW_S):
        real_finish(self, text, full, on_closed=on_closed, min_show_s=min_show_s)
        if not seen:  # Done を表示した直後（まだ閉じていない）に × を押す
            seen.append(self.finished)
            monkeypatch.setattr(app.root, "destroy", lambda: destroyed.append(1))
            app._on_close()

    monkeypatch.setattr(pd.ProgressDialog, "finish_then_close", finish)
    app._on_convert()
    app.wait_idle()
    assert seen == [True] and destroyed == [] and not [a for a in shown["info"] if "running" in a[1]]  # 案内の窓は出ない（結果の窓だけ）
    assert shown["asked"] == [] and "can be closed in a moment" in app.log_text.get("1.0", "end")


def test_close_confirmation_answered_yes_after_the_job_already_finished_does_not_raise_the_flag(app, tmp_path, monkeypatch):
    """確認の窓を開いている間に変換が終わった（ダイアログ無しの経路は、すぐ後始末へ進む）。そのあとの Yes は、終わった仕事の旗を立てない。"""
    app.selected_files.append(ms.write(tmp_path / "a.MBD", course="a"))
    shown = stub_boxes(monkeypatch)
    _no_dialog(monkeypatch)
    block = Block(monkeypatch, "a.MBD", step=5, frac=0.2)
    app._on_convert()
    block.wait(app)
    job_flag = app._job.cancel_event

    def ask_then_finish(*a, **k):
        shown["asked"].append(a)
        block.release.set()
        app.wait_idle()  # 確認を開いている間に、仕事が終わる
        return True

    monkeypatch.setattr(gui.messagebox, "askyesno", ask_then_finish)
    app._on_close()
    assert not job_flag.is_set() and (app.out / "a.MES" / "a.DDD").is_file() and len(shown["asked"]) == 1
