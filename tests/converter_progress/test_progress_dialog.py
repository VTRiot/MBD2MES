# -*- coding: utf-8 -*-
"""progress_dialog.py: 形・バーが戻らない・Cancel・Done と最低の表示時間・grab の取り直し・GIF・後始末。
窓は利用者の画面に出さない（親は withdraw のまま・ダイアログは画面の外の座標）。期待値は手計算。"""

from __future__ import annotations

import time
import tkinter as tk

import importlib

import pytest
from .conftest import PACKAGE
from .conftest import OFFSCREEN, make_gif, pump

ba = importlib.import_module(f"{PACKAGE}.busy_animation")
prg = importlib.import_module(f"{PACKAGE}.progress")
pd = importlib.import_module(f"{PACKAGE}.progress_dialog")
# 5 段・重み 0.1 / 0.2 / 0.4 / 0.2 / 0.1。段の始まりまでの合計は 0 / 0.1 / 0.3 / 0.7 / 0.9
CONFIG = prg.ProgressConfig(("A", "B", "C", "D", "E"), (0.1, 0.2, 0.4, 0.2, 0.1))


def event(k=1, n=1, name="a.dat", step=1, frac=0.0):
    return prg.make_event(CONFIG, k, n, name, step, frac)


def make_dialog(root, tmp_path, gif=False, **kw):
    called = []
    kw.setdefault("place", OFFSCREEN)
    kw["gif_path"] = gif if gif else tmp_path / "no_such.gif"
    d = pd.ProgressDialog(root, on_cancel=lambda: called.append(1), **kw)
    return d, called


# ---------------------------------------------------------------- 形
def test_dialog_has_the_standard_progress_layout(root, tmp_path):
    d, _ = make_dialog(root, tmp_path)
    assert d.title() == "Converting..." and d.resizable() == (False, False)  # 固定サイズ（最大化のボタンも出ない）
    assert str(d.transient()) == str(root)  # 親の上に出る・最小化のボタンも無い
    assert (d.file_var.get(), d.percent_var.get()) == ("Preparing...", "0%")
    assert d.time_var.get() == "Elapsed: 0:00    Remaining: calculating..."
    rows = {}
    for w in d.winfo_children()[0].winfo_children():
        info = w.grid_info()
        if info:
            rows[int(info["row"])] = (w.winfo_class(), str(info["sticky"]))
    # 上から: 今の処理 -> 段 -> % 付きのバー -> 経過時間 -> 区切り -> 右下の Cancel
    assert [rows[r][0] for r in sorted(rows)] == ["Label", "Label", "Frame", "Label", "TSeparator", "TButton"]
    assert rows[5] == ("TButton", "e") and str(d.cancel_button.cget("text")) == "Cancel"
    assert d.bar.winfo_class() == "TProgressbar" and str(d.bar.cget("mode")) == "determinate" and float(d.bar.cget("maximum")) == 100.0
    d.close()


def test_window_is_placed_off_screen_before_it_is_shown(root, tmp_path):
    d, _ = make_dialog(root, tmp_path)
    # 親が見えないので窓は表示されず、大きさは 1x1 と報告される。位置の指定だけを確かめる（負の座標は +-32000 の形）
    assert d.geometry().endswith(f"+{OFFSCREEN[0]}+{OFFSCREEN[1]}")
    d.close()


def test_dialog_is_centered_on_a_visible_parent(root, tmp_path, monkeypatch):
    root.winfo_viewable = lambda: True  # 親が見えている状態の座標（窓は出さない。値だけ差し替える）
    root.winfo_width, root.winfo_height = (lambda: 900), (lambda: 640)
    root.winfo_rootx, root.winfo_rooty = (lambda: 120), (lambda: 80)
    specs = []
    real = tk.Toplevel.geometry

    def record(self, spec=None):
        if spec:
            specs.append(spec)
        return real(self, spec)

    monkeypatch.setattr(pd.ProgressDialog, "geometry", record)
    d, _ = make_dialog(root, tmp_path, place=None)
    w, h = d.winfo_reqwidth(), d.winfo_reqheight()
    assert specs[-1] == f"{w}x{h}+{120 + (900 - w) // 2}+{80 + (640 - h) // 2}"  # 手計算: x = 120 + (900 - w) / 2、y = 80 + (640 - h) / 2
    d.close()


def test_without_a_gif_the_margin_is_closed_up_and_with_a_gif_it_is_on_the_right(root, tmp_path):
    none, _ = make_dialog(root, tmp_path)
    gif = make_gif(tmp_path / "busy.gif", frames=3, size=60)
    with_gif, _ = make_dialog(root, tmp_path, gif=gif)
    assert none.animation.label is None and none.animation.loaded is False
    info = with_gif.animation.label.grid_info()
    assert (int(info["column"]), int(info["row"]), int(info["rowspan"]), str(info["sticky"])) == (1, 0, 4, "ne")  # 右の余白・上寄せ
    assert with_gif.winfo_reqwidth() > none.winfo_reqwidth() + 40  # GIF の分だけ広い。無いときは余白を詰める
    assert none.winfo_reqwidth() <= pd.BAR_PX + 120
    none.close()
    with_gif.close()


def test_the_apps_gif_location_decides_the_file(root, tmp_path, monkeypatch):
    gif = make_gif(tmp_path / "mine.gif", frames=2, size=8)
    monkeypatch.setenv("APP_Y_BUSY_GIF", str(gif))
    d = pd.ProgressDialog(root, on_cancel=lambda: None, gif_location=ba.GifLocation(env_var="APP_Y_BUSY_GIF"), place=OFFSCREEN)
    assert d.animation.path == gif and d.animation.loaded
    d.close()


# ---------------------------------------------------------------- 更新
def test_text_bar_and_percent_follow_the_event_and_the_bar_never_goes_back(root, tmp_path):
    d, _ = make_dialog(root, tmp_path)
    d.update_progress(event(2, 5, "b.dat", 3, 0.5))
    assert d.file_var.get() == "File 2/5: b.dat" and d.step_var.get() == "Step 3/5: C"
    # 手計算: 2 本目の段 3 の半分 = (1 + 0.3 + 0.4 * 0.5) / 5 = 0.3 -> 30%
    assert float(d.bar["value"]) == pytest.approx(30.0) and d.percent_var.get() == "30%"
    d.update_progress(event(1, 5, "a.dat", 1, 0.1))  # 古い・小さい通知が遅れて届いても、バーと % は戻らない
    assert float(d.bar["value"]) == pytest.approx(30.0) and d.percent_var.get() == "30%"
    d.update_progress(event(3, 5, "c.dat", 1, 0.0))  # 3 本目の始め = 2 / 5 = 40%
    assert float(d.bar["value"]) == pytest.approx(40.0) and d.percent_var.get() == "40%"
    d.close()
    d.update_progress(event())  # 閉じた後の通知は無視する（例外にしない）


def test_elapsed_and_remaining_text_with_a_fake_clock(root, tmp_path):
    now = [100.0]
    d, _ = make_dialog(root, tmp_path, clock=lambda: now[0])
    d.update_progress(event(1, 1, "a.dat", 2, 0.5))  # 0.1 + 0.2 * 0.5 = 0.2
    now[0] = 110.0  # 10 秒で 20% -> 全体 50 秒 -> 残り 40 秒
    assert d._time_text() == "Elapsed: 0:10    Remaining: about 0:40"
    now[0] = 101.0
    assert d._time_text() == "Elapsed: 0:01    Remaining: calculating..."  # 始めのうちは当てにならない
    d.close()


# ---------------------------------------------------------------- Cancel
def _press(d, how, root):
    if how == "button":
        d.cancel_button.invoke()
    elif how == "x":
        root.tk.call(root.tk.call("wm", "protocol", str(d), "WM_DELETE_WINDOW"))  # × が呼ぶ関数
    else:  # Esc: 結びつけてあることと、その関数が Cancel になることを確かめる（キーを OS へ送らない = フォーカスを奪わない）
        assert d.bind("<Escape>")
        d.request_cancel()


@pytest.mark.parametrize("how", ["button", "x", "escape"])
def test_cancel_button_x_and_escape_cancel_exactly_once(root, tmp_path, how):
    d, called = make_dialog(root, tmp_path)
    d.update_progress(event(1, 1, "a.dat", 4, 0.2))
    _press(d, how, root)
    assert called == [1] and d.cancel_requested
    assert d.cancel_button.instate(["disabled"]) and d.step_var.get() == pd.CANCELLING_TEXT  # 押せなくし、案内を出す
    for other in ("button", "x", "escape"):
        _press(d, other, root)
    assert called == [1]  # 2 回目以降は、どの経路でも何もしない
    d.update_progress(event(1, 1, "a.dat", 5, 0.5))
    assert d.step_var.get() == pd.CANCELLING_TEXT and "Remaining" not in d._time_text()  # 案内を上書きしない・残りの目安を出さない
    d.close()
    assert not d.winfo_exists()


# ---------------------------------------------------------------- Done と最低の表示時間
def test_done_state_text_bar_buttons_and_frozen_clock(root, tmp_path):
    now = [0.0]
    d, called = make_dialog(root, tmp_path, clock=lambda: now[0])
    d.update_progress(event(1, 1, "a.dat", 2, 0.5))
    now[0] = 5.0
    d.show_finished(pd.DONE_TEXT, True)
    assert d.step_var.get() == "Done" and float(d.bar["value"]) == 100.0 and d.percent_var.get() == "100%"
    assert d.cancel_button.instate(["disabled"]) and d.time_var.get() == "Elapsed: 0:05"  # 「Remaining: calculating...」は出さない
    now[0] = 50.0
    d._tick()
    assert d.time_var.get() == "Elapsed: 0:05" and d._time_text() == "Elapsed: 0:05"  # Done の後は経過時間も止まる
    d.update_progress(event(1, 1, "a.dat", 1, 0.0))  # 遅れて届いた進みで Done を上書きしない
    d.request_cancel()  # Done の後の Cancel は無視
    assert d.step_var.get() == "Done" and called == [] and not d.cancel_requested
    d.close()


def test_done_with_errors_keeps_the_bar_where_it_was(root, tmp_path):
    d, _ = make_dialog(root, tmp_path)
    d.update_progress(event(1, 1, "a.dat", 3, 0.5))  # 0.3 + 0.2 = 0.5 -> 50%
    d.show_finished(pd.DONE_WITH_ERRORS_TEXT, False)
    assert d.step_var.get() == "Done (with errors)" and float(d.bar["value"]) == pytest.approx(50.0)
    assert d.percent_var.get() == "50%" and "Remaining" not in d.time_var.get()
    d.close()


def test_cancelled_after_pressing_cancel_shows_cancelled_and_no_remaining(root, tmp_path):
    d, _ = make_dialog(root, tmp_path)
    d.request_cancel()
    d.show_finished(pd.CANCELLED_TEXT, False)
    assert d.step_var.get() == "Cancelled" and "Remaining" not in d.time_var.get()
    d.close()


def test_min_show_s_holds_the_done_state_until_the_remaining_time_has_passed(root, tmp_path, monkeypatch):
    assert pd.MIN_SHOW_S == 1.0  # 【仮置き】
    scheduled = []
    real_after = root.after
    monkeypatch.setattr(root, "after", lambda ms, fn=None, *a: scheduled.append((ms, fn)) or real_after(10 ** 9, lambda: None), raising=False)
    now = [0.0]
    d, _ = make_dialog(root, tmp_path, clock=lambda: now[0])
    now[0] = 0.2
    closed = []
    d.finish_then_close(pd.DONE_TEXT, True, on_closed=lambda: closed.append(1))
    assert d.step_var.get() == "Done" and not d.closed and closed == []  # まだ見せている
    assert [ms for ms, _fn in scheduled] == [800]  # 手計算: 1.0 - 0.2 = 0.8 秒
    scheduled[0][1]()
    assert d.closed and closed == [1] and not d.winfo_exists()
    scheduled[0][1]()  # 2 回呼ばれても、後続は 1 度だけ
    assert closed == [1]


@pytest.mark.parametrize("took_s, expected_ms", [(0.2, 800), (0.99, 500), (3.0, 500)])
def test_the_close_time_is_the_later_of_min_show_since_open_and_done_hold_since_done(root, tmp_path, monkeypatch, took_s, expected_ms):
    assert pd.MIN_SHOW_S == 1.0 and pd.DONE_HOLD_S == 0.5  # 【仮置き】
    # 手計算: 閉じる時刻 = max(開いてから 1.0, Done にしてから 0.5)。(a) 0.2 秒 -> max(1.0, 0.7) = 1.0 -> 待ち 0.8 / (b) 0.99 -> max(1.0, 1.49) = 1.49 -> 待ち 0.5 / (c) 3 秒 -> 3.5 -> 待ち 0.5
    scheduled = []
    real_after = root.after
    monkeypatch.setattr(root, "after", lambda ms, fn=None, *a: scheduled.append((ms, fn)) or real_after(10 ** 9, lambda: None), raising=False)
    now = [0.0]
    d, _ = make_dialog(root, tmp_path, clock=lambda: now[0])
    now[0] = took_s
    closed = []
    d.finish_then_close(pd.DONE_TEXT, True, on_closed=lambda: closed.append(1))
    assert d.step_var.get() == "Done" and not d.closed and closed == []  # Done を見せたまま、イベントループへ描画を返す
    assert [ms for ms, _fn in scheduled] == [expected_ms]
    scheduled[0][1]()
    assert d.closed and closed == [1]


def test_min_show_s_zero_for_cancel_closes_at_once(root, tmp_path):
    d, _ = make_dialog(root, tmp_path)
    closed = []
    d.finish_then_close(pd.CANCELLED_TEXT, False, on_closed=lambda: closed.append(1), min_show_s=0.0)
    assert d.closed and closed == [1]


def test_a_failing_after_closes_at_once_instead_of_waiting(root, tmp_path, monkeypatch):
    d, _ = make_dialog(root, tmp_path)

    def broken_after(*a, **k):
        raise tk.TclError("application has been destroyed")

    monkeypatch.setattr(root, "after", broken_after, raising=False)
    closed = []
    d.finish_then_close(pd.DONE_TEXT, True, on_closed=lambda: closed.append(1))  # 0 秒の変換 -> 待ちが要る -> 予約に失敗
    assert d.closed and closed == [1]


def test_a_failing_finished_display_still_closes_and_continues(root, tmp_path, monkeypatch, capsys):
    d, _ = make_dialog(root, tmp_path)

    def broken(*a, **k):
        raise RuntimeError("cannot draw")

    monkeypatch.setattr(d, "show_finished", broken)
    closed = []
    d.finish_then_close(pd.DONE_TEXT, True, on_closed=lambda: closed.append(1))
    assert d.closed and closed == [1] and "cannot draw" in capsys.readouterr().err


def test_a_failing_after_close_handler_is_reported_not_raised(root, tmp_path, capsys):
    d, _ = make_dialog(root, tmp_path)

    def bad():
        raise RuntimeError("handler broke")

    d.finish_then_close(pd.CANCELLED_TEXT, False, on_closed=bad, min_show_s=0.0)
    assert d.closed and "handler broke" in capsys.readouterr().err


# ---------------------------------------------------------------- 後始末
def test_close_is_idempotent_and_releases_the_gif_variables_and_grab(root, tmp_path):
    d, _ = make_dialog(root, tmp_path, gif=make_gif(tmp_path / "busy.gif", frames=3, size=40), frame_ms=20)
    anim = d.animation
    assert anim.running  # 開いている間は動く
    seen = set()
    end = time.monotonic() + 0.5
    while time.monotonic() < end:
        root.update()
        seen.add(str(anim.label.cget("image")))
        time.sleep(0.003)
    assert len(seen) == 3
    d.close()
    d.close()
    assert anim.running is False and not d.winfo_exists() and root.grab_current() is None  # grab を放した
    assert anim.frames == [] and anim.label is None and d.file_var is None and d.time_var is None  # 主スレッドのうちに手放す


def test_close_destroys_the_window_even_if_the_cleanup_steps_fail(root, tmp_path, monkeypatch):
    d, _ = make_dialog(root, tmp_path)

    def broken(*a, **k):
        raise RuntimeError("cleanup broke")

    monkeypatch.setattr(d.animation, "release", broken)
    monkeypatch.setattr(d, "grab_release", broken)
    with pytest.raises(RuntimeError, match="cleanup broke"):
        d.close()
    assert not d.winfo_exists() and d.closed  # 片付けが失敗しても、grab の解除の試みと窓の破棄までは行う


def test_grab_is_retried_until_the_window_is_visible(root, tmp_path, monkeypatch):
    monkeypatch.setattr(pd, "GRAB_RETRY_MS", 1)
    attempts = []

    def flaky(self):
        attempts.append(1)
        if len(attempts) < 3:
            raise tk.TclError("grab failed: window not viewable")

    monkeypatch.setattr(pd.ProgressDialog, "grab_set", flaky)
    d, _ = make_dialog(root, tmp_path)
    pump(root, 0.2)
    assert len(attempts) == 3  # 2 回失敗 -> 3 回目で取れて、そこで止まる
    d.close()


def test_grab_retries_give_up_after_the_limit_and_stop_when_closed(root, tmp_path, monkeypatch):
    monkeypatch.setattr(pd, "GRAB_RETRY_MS", 1)
    attempts = []

    def never(self):
        attempts.append(1)
        raise tk.TclError("grab failed")

    monkeypatch.setattr(pd.ProgressDialog, "grab_set", never)
    d, _ = make_dialog(root, tmp_path)
    pump(root, 0.5)
    assert len(attempts) == 1 + pd.GRAB_RETRIES  # 最初の 1 回 + 取り直し 20 回で諦める
    d.close()
    pump(root, 0.05)
    assert len(attempts) == 1 + pd.GRAB_RETRIES


def test_a_failure_while_building_leaves_no_window_behind(root, tmp_path, monkeypatch):
    def boom(self):
        raise RuntimeError("animation failed to start")

    monkeypatch.setattr(ba.BusyAnimation, "start", boom)
    with pytest.raises(RuntimeError, match="animation failed to start"):
        pd.ProgressDialog(root, on_cancel=lambda: None, gif_path=tmp_path / "no.gif", place=OFFSCREEN)
    pump(root, 0.1)
    assert root.winfo_children() == []  # 生成途中の窓・タイマーを残さない
