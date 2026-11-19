# -*- coding: utf-8 -*-
"""busy_animation.py: GIF の場所の決め方・整数倍の合わせ方・再生と停止・GIF なしの無害さ。窓は出さない（親は withdraw のまま）。"""

from __future__ import annotations

import sys
import time

import importlib

import pytest
from .conftest import PACKAGE
from .conftest import make_gif, make_tk_root, pump

ba = importlib.import_module(f"{PACKAGE}.busy_animation")
def test_default_location_is_pic_anim_busy_gif_and_frozen_name_is_busy_gif(tmp_path):
    assert ba.DEFAULT_RELATIVE_PATH == ("Pic", "anim", "busy.gif") and ba.DEFAULT_FROZEN_NAME == "busy.gif"
    assert ba.resolve_gif_path(ba.GifLocation(base_dir=tmp_path)) == tmp_path / "Pic" / "anim" / "busy.gif"


def test_location_priority_env_over_frozen_over_base_dir(tmp_path, monkeypatch):
    loc = ba.GifLocation(env_var="APP_X_BUSY_GIF", base_dir=tmp_path, relative_path=("a", "b.gif"), frozen_name="spin.gif")
    monkeypatch.delenv("APP_X_BUSY_GIF", raising=False)
    assert ba.resolve_gif_path(loc) == tmp_path / "a" / "b.gif"  # 開発起動
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert ba.resolve_gif_path(loc) == tmp_path / "bundle" / "spin.gif"  # exe: _MEIPASS 直下の同梱名
    monkeypatch.setenv("APP_X_BUSY_GIF", str(tmp_path / "other.gif"))
    assert ba.resolve_gif_path(loc) == tmp_path / "other.gif"  # 環境変数が最優先（ファイルが無くても）
    monkeypatch.setenv("APP_X_BUSY_GIF", "")
    assert ba.resolve_gif_path(loc) == tmp_path / "bundle" / "spin.gif"  # 空は無いのと同じ


def test_env_var_is_ignored_when_the_app_names_none(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_X_BUSY_GIF", str(tmp_path / "other.gif"))
    assert ba.resolve_gif_path(ba.GifLocation(base_dir=tmp_path)) == tmp_path / "Pic" / "anim" / "busy.gif"


def test_base_dir_may_be_a_function_and_defaults_to_the_started_script(tmp_path, monkeypatch):
    assert ba.resolve_gif_path(ba.GifLocation(base_dir=lambda: tmp_path / "d")) == tmp_path / "d" / "Pic" / "anim" / "busy.gif"
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "run" / "app.py")])
    assert ba.resolve_gif_path(ba.GifLocation()) == (tmp_path / "run").resolve() / "Pic" / "anim" / "busy.gif"


@pytest.mark.parametrize("w,h,target,expected", [
    (64, 64, 57, (1, 1)),    # 64 -> 57 は 7 差。半分の 32 は 25 差。等倍
    (128, 128, 57, (1, 2)),  # 1/2 = 64（差 7）、1/3 = 43（差 14）-> 1/2
    (20, 20, 57, (3, 1)),    # 2 倍 = 40（差 17）、3 倍 = 60（差 3）-> 3 倍
    (30, 10, 60, (2, 1)),    # 長い辺 30 -> 2 倍で 60（ぴったり）
    (0, 0, 57, (1, 1)),
    (64, 64, 0, (1, 1)),
    (0, 10, 30, (3, 1)),     # 幅 0 でも長い辺（10）で決める
])
def test_scale_factors_hand_values(w, h, target, expected):
    assert ba.scale_factors(w, h, target) == expected


def test_a_missing_or_broken_gif_never_raises_and_does_nothing(tmp_path):
    root = make_tk_root()
    try:
        attached = []
        for payload in (b"", b"not a gif at all", b"GIF89a\x01\x00"):
            bad = tmp_path / "bad.gif"
            bad.write_bytes(payload)
            for path in (bad, tmp_path / "nope.gif", tmp_path):  # 壊れた・無い・フォルダ
                anim = ba.BusyAnimation(root, path, attach=attached.append)
                assert anim.loaded is False and anim.label is None and anim.start() is False and anim.running is False
                anim.stop()
                anim.release()
        assert attached == []  # 余白を取る置き方は、GIF が無いと呼ばれない
    finally:
        root.destroy()


def test_frames_belong_to_the_given_master_even_with_two_roots(tmp_path):
    first = make_tk_root()
    second = make_tk_root()
    try:
        gif = make_gif(tmp_path / "busy.gif", frames=3, size=4)
        frames = ba.load_frames(gif, second)
        assert len(frames) == 3 and all(f.tk is second.tk for f in frames)  # 最初に作られた root（first）へ属さない
        anim = ba.BusyAnimation(second, gif, attach=lambda lbl: lbl.pack())
        assert all(f.tk is second.tk for f in anim.frames)
        anim.release()
    finally:
        second.destroy()
        first.destroy()


def test_animation_plays_only_between_start_and_stop_and_stop_shows_the_first_frame(tmp_path):
    root = make_tk_root()
    try:
        anim = ba.BusyAnimation(root, make_gif(tmp_path / "busy.gif", frames=3, size=4), frame_ms=15, attach=lambda lbl: lbl.pack())
        assert anim.loaded and anim.running is False
        assert anim.start() is True and anim.start() is True  # 2 回呼んでも 1 つだけ動く
        seen = set()
        end = time.monotonic() + 0.5
        while time.monotonic() < end:
            root.update()
            seen.add(str(anim.label.cget("image")))
            time.sleep(0.003)
        assert len(seen) == 3  # 3 コマ全部が現れた
        anim.stop()
        first = str(anim.frames[0])
        assert anim.running is False and str(anim.label.cget("image")) == first
        pump(root, 0.1)
        assert str(anim.label.cget("image")) == first  # 止めた後は動かない
        anim.release()
        assert anim.frames == [] and anim.label is None
    finally:
        root.destroy()


def test_without_attach_the_label_is_placed_at_the_top_right(tmp_path):
    root = make_tk_root()
    try:
        anim = ba.BusyAnimation(root, make_gif(tmp_path / "busy.gif", frames=2, size=4))
        info = anim.label.place_info()
        assert str(info["anchor"]) == "ne" and float(info["relx"]) == 1.0 and int(info["x"]) == -ba.MARGIN_PX
        anim.release()
    finally:
        root.destroy()


def test_frames_are_fitted_to_about_1_5_cm_by_an_integer_factor(tmp_path):
    root = make_tk_root()
    try:
        target = ba.recommended_size_px(root)
        assert target == round(root.winfo_fpixels(f"{ba.GIF_SIZE_CM}c")) and ba.GIF_SIZE_CM == 1.5
        gif = make_gif(tmp_path / "busy.gif", frames=2, size=10)
        anim = ba.BusyAnimation(root, gif, attach=lambda lbl: lbl.pack())
        zoom, sub = ba.scale_factors(10, 10, target)
        expected = 10 * zoom if zoom > 1 else -(-10 // sub)  # subsample は切り上げ
        assert anim.frames[0].width() == expected
        anim.release()
    finally:
        root.destroy()


def test_a_gif_with_too_many_frames_stops_at_the_limit(tmp_path, monkeypatch):
    root = make_tk_root()
    try:
        monkeypatch.setattr(ba, "MAX_FRAMES", 2)
        assert len(ba.load_frames(make_gif(tmp_path / "busy.gif", frames=5, size=4), root)) == 2
    finally:
        root.destroy()
