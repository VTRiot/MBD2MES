# -*- coding: utf-8 -*-
"""progress.py: 重み・全体の %・残りの目安・時計。期待値はすべて手計算（コードの式の再計算ではない）。"""

from __future__ import annotations

import importlib

import pytest
from .conftest import PACKAGE

prg = importlib.import_module(f"{PACKAGE}.progress")
# 4 段・重み 0.1 / 0.5 / 0.3 / 0.1（合計 1.0）。段の始まりまでの合計は 0 / 0.1 / 0.6 / 0.9
CONFIG = prg.ProgressConfig(("Read", "Convert", "Write", "Finish"), (0.1, 0.5, 0.3, 0.1))


def test_config_requires_weights_that_sum_to_one_and_match_the_labels():
    assert CONFIG.step_count == 4 and sum(CONFIG.step_weights) == pytest.approx(1.0, abs=1e-12)
    with pytest.raises(ValueError):
        prg.ProgressConfig(("a", "b"), (0.5, 0.4))  # 合計 0.9
    with pytest.raises(ValueError):
        prg.ProgressConfig(("a", "b"), (0.5, 0.6))  # 合計 1.1
    with pytest.raises(ValueError):
        prg.ProgressConfig(("a", "b"), (1.0,))  # 長さが違う
    with pytest.raises(ValueError):
        prg.ProgressConfig(("a", "b"), (1.5, -0.5))  # 合計は 1.0 だが負
    with pytest.raises(ValueError):
        prg.ProgressConfig((), ())
    prg.ProgressConfig(["a", "b"], [0.25, 0.75])  # list で渡しても受ける（tuple に直す）


def test_config_has_no_default_steps():
    """アプリの段を黙って使わない: 引数なしでは作れない。"""
    with pytest.raises(TypeError):
        prg.ProgressConfig()  # type: ignore[call-arg]
    assert not hasattr(prg, "STEP_LABELS") and not hasattr(prg, "STEP_WEIGHTS")


def test_hand_computed_file_fraction():
    assert prg.file_fraction(CONFIG, 1, 0.0) == 0.0
    assert prg.file_fraction(CONFIG, 2, 0.5) == pytest.approx(0.35)  # 0.1 + 0.5 * 0.5
    assert prg.file_fraction(CONFIG, 3, 1.0) == pytest.approx(0.9)  # 0.6 + 0.3
    assert prg.file_fraction(CONFIG, 4, 0.0) == pytest.approx(0.9)
    assert prg.file_fraction(CONFIG, 4, 1.0) == pytest.approx(1.0)


def test_out_of_range_inputs_are_clamped():
    assert prg.file_fraction(CONFIG, 0, -3.0) == 0.0  # 段 1・進み 0
    assert prg.file_fraction(CONFIG, 99, 5.0) == pytest.approx(1.0)  # 最後の段・進み 1
    assert prg.overall(CONFIG, 0, 0, 1, 0.0) == 0.0
    assert prg.overall(CONFIG, 9, 3, 4, 1.0) == pytest.approx(1.0)  # 3 本中 9 本目は 3 本目へ丸める


def test_hand_computed_overall_for_several_files():
    # 4 本中の 3 本目（k=3）の段 2 の半分: (2 + 0.35) / 4 = 0.5875
    assert prg.overall(CONFIG, 3, 4, 2, 0.5) == pytest.approx(0.5875)
    assert prg.overall(CONFIG, 1, 4, 1, 0.0) == 0.0
    assert prg.overall(CONFIG, 4, 4, 4, 1.0) == pytest.approx(1.0)
    assert prg.overall(CONFIG, 2, 2, 3, 0.0) == pytest.approx((1 + 0.6) / 2)  # 0.8


def test_overall_is_monotonic_over_every_step_fraction_and_file():
    prev = -1.0
    for k in range(1, 4):
        for step in range(1, CONFIG.step_count + 1):
            for i in range(11):
                now = prg.overall(CONFIG, k, 3, step, i / 10)
                assert now >= prev - 1e-12 and 0.0 <= now <= 1.0
                prev = now
    assert prev == pytest.approx(1.0)


def test_event_texts_and_percent():
    ev = prg.make_event(CONFIG, 3, 4, "b.dat", 2, 0.5)
    assert ev.file_text() == "File 3/4: b.dat" and ev.step_text() == "Step 2/4: Convert"
    assert ev.overall == pytest.approx(0.5875) and ev.percent == 58  # 58.75 を切り捨て
    assert (ev.step, ev.step_count, ev.label, ev.step_fraction) == (2, 4, "Convert", 0.5)
    assert prg.make_event(CONFIG, 1, 1, "a", 4, 1.0).percent == 100


def test_percent_does_not_drop_a_whole_number_to_float_error():
    cfg = prg.ProgressConfig(("a", "b"), (0.29, 0.71))
    ev = prg.make_event(cfg, 1, 1, "a", 2, 0.0)  # 手計算: ちょうど 29%（浮動小数では 28.999999999999996）
    assert ev.percent == 29


def test_second_config_for_a_different_weighting_is_independent():
    alt = prg.ProgressConfig(CONFIG.step_labels, (0.7, 0.1, 0.1, 0.1))
    assert prg.file_fraction(alt, 2, 0.0) == pytest.approx(0.7)
    assert prg.file_fraction(CONFIG, 2, 0.0) == pytest.approx(0.1)


@pytest.mark.parametrize("elapsed,fraction,expected", [
    (10.0, 0.25, 30.0),  # 10 秒で 25% -> 全体 40 秒 -> 残り 30 秒
    (6.0, 0.5, 6.0),  # 6 秒で半分 -> 残り 6 秒
    (3.0, 0.03, 97.0),  # 出し始めの境目: 3 秒で 3% -> 全体 100 秒 -> 残り 97 秒
])
def test_estimate_remaining_hand_values(elapsed, fraction, expected):
    assert prg.estimate_remaining(elapsed, fraction) == pytest.approx(expected)


@pytest.mark.parametrize("elapsed,fraction", [(2.9, 0.5), (10.0, 0.029), (10.0, 1.0), (10.0, 1.2), (0.0, 0.0)])
def test_estimate_remaining_is_none_while_unreliable_or_finished(elapsed, fraction):
    assert prg.estimate_remaining(elapsed, fraction) is None


@pytest.mark.parametrize("seconds,text", [(0, "0:00"), (59, "0:59"), (61, "1:01"), (3599, "59:59"), (3600, "1:00:00"), (3725, "1:02:05"), (-5, "0:00")])
def test_format_clock(seconds, text):
    assert prg.format_clock(seconds) == text


def test_progress_callback_emits_events_for_the_given_file():
    got = []
    cb = prg.make_progress_callback(CONFIG, got.append, 2, 5, "x.dat")
    cb(1, 0.0)
    cb(3, 0.5)
    assert [(e.file_index, e.file_count, e.file_name, e.step) for e in got] == [(2, 5, "x.dat", 1), (2, 5, "x.dat", 3)]
    assert got[1].overall == pytest.approx((1 + 0.75) / 5)  # 0.6 + 0.3 * 0.5 = 0.75
