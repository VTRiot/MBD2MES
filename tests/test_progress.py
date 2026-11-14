# -*- coding: utf-8 -*-
"""変換の進み具合（FB02）の通知: 段の順・単調に増える・100% で終わる。結果（MES）と CLI の出力は変わらない。"""

from __future__ import annotations

import os
import subprocess
import sys

import map_synth as ms
import pytest
from conftest import ROOT, SETTINGS_ENV, fresh_settings

from mbd2mes import app_convert as ac
from mbd2mes import batch
from mbd2mes import convert as cv
from mbd2mes import progress as prg


def tree_bytes(d) -> dict:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------- progress.py（計算）
def test_weights_cover_the_whole_conversion_exactly_once():
    assert len(prg.STEP_WEIGHTS) == prg.STEP_COUNT == len(prg.STEP_LABELS) == 7
    assert sum(prg.STEP_WEIGHTS) == pytest.approx(1.0, abs=1e-12) and all(w > 0 for w in prg.STEP_WEIGHTS)
    assert prg.file_fraction(1, 0.0) == 0.0 and prg.file_fraction(prg.STEP_COUNT, 1.0) == pytest.approx(1.0)


def test_the_reading_and_resampling_steps_dominate_as_measured_on_the_sample():
    """標本の実測（報告書）: 読み取りが約 7 割、値の展開が約 2 割。重い段は重みも重い。"""
    w = prg.STEP_WEIGHTS
    assert w[0] == max(w) and w[0] + w[1] >= 0.8 and w[4] > w[2]


def test_file_fraction_is_monotonic_over_every_step_and_fraction():
    prev = -1.0
    for step in range(1, prg.STEP_COUNT + 1):
        for k in range(0, 11):
            now = prg.file_fraction(step, k / 10)
            assert now >= prev - 1e-12 and 0.0 <= now <= 1.0
            prev = now


def test_hand_computed_overall_for_three_files():
    # 手計算: 2 本目（k=2）の段 1 の半分 = (1 + 0.70 * 0.5) / 3 = 0.45
    assert prg.overall(2, 3, 1, 0.5) == pytest.approx((1 + 0.70 * 0.5) / 3)
    assert prg.overall(1, 3, 1, 0.0) == 0.0 and prg.overall(3, 3, 7, 1.0) == pytest.approx(1.0)
    assert prg.overall(5, 3, 7, 1.0) == pytest.approx(1.0) and prg.overall(0, 0, 9, 5.0) == pytest.approx(1.0)  # 範囲外は丸める


def test_event_texts_and_percent():
    ev = prg.make_event(2, 5, "b.MBD", 3, 0.5)
    assert ev.step_text() == "Step 3/7: Preparing the GPS position" and ev.file_text() == "File 2/5: b.MBD"
    assert ev.percent == int(ev.overall * 100) and 0 <= ev.percent <= 100
    assert prg.make_event(1, 1, "a.MBD", 7, 1.0).percent == 100


# ---------------------------------------------------------------- convert_one の呼ばれ方
def run_with_progress(tmp_path, name="p.MBD"):
    mbd = ms.write(tmp_path / name)
    calls = []
    res = cv.convert_one(mbd, tmp_path / "o", date=cv.datetime.date(2026, 11, 8), progress=lambda s, f: calls.append((s, f)))
    return res, calls


def test_steps_come_in_order_and_fractions_never_go_back(tmp_path):
    _res, calls = run_with_progress(tmp_path)
    steps = [s for s, _f in calls]
    assert steps == sorted(steps) and set(steps) == set(range(1, prg.STEP_COUNT + 1))  # 7 段が全部、順に
    assert calls[0] == (1, 0.0) and calls[-1] == (prg.STEP_COUNT, 1.0)  # 最初は読み取りの 0、最後は 100%
    overalls = [prg.file_fraction(s, f) for s, f in calls]
    assert all(b >= a - 1e-12 for a, b in zip(overalls, overalls[1:]))  # 全体の % は単調に増える
    assert all(0.0 <= f <= 1.0 for _s, f in calls) and overalls[-1] == pytest.approx(1.0)
    for step in range(1, prg.STEP_COUNT + 1):  # 段の中でも戻らない
        fr = [f for s, f in calls if s == step]
        assert fr == sorted(fr)


def test_heavy_steps_report_inside_the_step_too(tmp_path):
    _res, calls = run_with_progress(tmp_path)
    for step in (1, 2, 4, 5):  # 読み取り・値の展開・定義作り・書き出し
        inner = {f for s, f in calls if s == step}
        assert len(inner) >= 3 and min(inner) == 0.0 and max(inner) == 1.0, (step, inner)
    assert len({f for s, f in calls if s == 1}) > 10  # データ領域の走査が 1% ごとに知らせる（合成でも細かく）
    assert len({f for s, f in calls if s == 5}) >= 8  # 書き出しは、チャンネルを 1 本書くたびに知らせる（8 本以上）


def test_progress_does_not_change_the_result(tmp_path):
    mbd = ms.write(tmp_path / "same.MBD")
    day = cv.datetime.date(2026, 11, 8)
    a = cv.convert_one(mbd, tmp_path / "a", date=day)
    b = cv.convert_one(mbd, tmp_path / "b", date=day, progress=lambda s, f: None)
    assert tree_bytes(a.mes_dir) == tree_bytes(b.mes_dir)  # 記録ファイルを含めて 1 byte も違わない


def test_a_failed_conversion_stops_the_notifications_without_a_final_100(tmp_path):
    bad = tmp_path / "bad.MBD"
    bad.write_bytes(b"4OEL V0003".ljust(15, b" ") + b"\x00" + b"\xff" * 0x2100)
    calls = []
    with pytest.raises(Exception):
        cv.convert_one(bad, tmp_path / "o", progress=lambda s, f: calls.append((s, f)))
    assert (prg.STEP_COUNT, 1.0) not in calls


# ---------------------------------------------------------------- 複数本（File k/n）
def test_many_files_count_up_and_reach_one_even_when_a_file_fails_or_is_skipped(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    good1, good2 = ms.write(tmp_path / "a.MBD", course="a"), ms.write(tmp_path / "c.MBD", course="c")
    bad = tmp_path / "b.MBD"
    bad.write_bytes(b"not an mbd" * 1000)
    ac.convert_many([good2], tmp_path / "o", channel_map_data=None)  # c は変換済み（上書きを断る）
    events = []
    out = ac.convert_many([good1, bad, good2], tmp_path / "o", channel_map_data=None, progress=events.append,
                          confirm_overwrite=lambda _p, _d: False)
    assert [r.mes_name for r in out.results] == ["a"] and len(out.failed) == 1 and len(out.declined) == 1
    assert {e.file_count for e in events} == {3} and [e.file_index for e in events] == sorted(e.file_index for e in events)
    assert {e.file_index for e in events} == {1, 2, 3}
    overalls = [e.overall for e in events]
    assert all(b >= a - 1e-12 for a, b in zip(overalls, overalls[1:])) and overalls[-1] == pytest.approx(1.0)
    # 失敗した 2 本目・見送った 3 本目も、終わった印（段 7 の 100%）で全体が進む
    assert any(e.file_index == 2 and e.step == prg.STEP_COUNT and e.step_fraction == 1.0 for e in events)
    assert any(e.file_index == 3 and e.step == prg.STEP_COUNT and e.step_fraction == 1.0 for e in events)
    assert events[0].file_text().startswith("File 1/3: a.MBD")


def test_batch_conversion_continues_the_file_numbers(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    for n in "abc":
        ms.write(src / f"{n}.MBD", course=n)
    scan = batch.scan_mbd_directory(src, out)
    events = []
    report = batch.convert_unconverted(scan, channel_map_data=None, progress=events.append)
    assert report.converted_count == 3
    assert [e.file_index for e in events] == sorted(e.file_index for e in events) and {e.file_count for e in events} == {3}
    assert events[-1].overall == pytest.approx(1.0) and {e.file_index for e in events} == {1, 2, 3}


# ---------------------------------------------------------------- CLI は変わらない
def test_cli_output_has_no_progress_and_matches_the_no_progress_form(tmp_path, monkeypatch):
    s = fresh_settings(tmp_path, monkeypatch)
    mbd = ms.write(tmp_path / "26.11.8cli.MBD", course="cli")
    env = dict(os.environ)
    env[SETTINGS_ENV] = str(s)
    r = subprocess.run([sys.executable, "-m", "mbd2mes", str(mbd), "-o", str(tmp_path / "o")], cwd=ROOT, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "Step " not in r.stdout and "%" not in r.stdout and "File 1/1" not in r.stdout  # 進み具合は CLI に出さない
    lines = r.stdout.splitlines()
    assert lines[0] == "[INFO] 26.11.8cli.MBD: recording date 2026-11-08 (file name)"
    assert [ln.split(":")[0].strip() for ln in lines[1:]] == ["Input", "Output", "Channels", "Base Hz", "Start (HED)", "Not written", "Laps", "Invariant check"]


def test_every_kind_of_failure_still_advances_the_whole_progress(tmp_path, monkeypatch):
    """変換の失敗の種類ごと（読めない MBD・変換の失敗（既存の MES）・想定外の例外）で、その 1 本は「終わった」印で全体が進む。"""
    fresh_settings(tmp_path, monkeypatch)
    ok = ms.write(tmp_path / "ok.MBD", course="ok")
    exists = ms.write(tmp_path / "exists.MBD", course="exists")
    boom = ms.write(tmp_path / "boom.MBD", course="boom")
    ac.convert_many([exists], tmp_path / "o", channel_map_data=None)  # exists は変換済み。確認なし・force なし = ConvertError で失敗
    real = cv.convert_one

    def convert_one(path, *a, **k):
        if path.name == "boom.MBD":
            raise RuntimeError("unexpected")
        return real(path, *a, **k)

    monkeypatch.setattr(cv, "convert_one", convert_one)
    events = []
    out = ac.convert_many([exists, boom, ok], tmp_path / "o", channel_map_data=None, progress=events.append)
    assert [c for _p, _r, c in out.failed] == [ac.EXIT_FAIL, ac.EXIT_FAIL] and [r.mes_name for r in out.results] == ["ok"]
    for idx in (1, 2):  # 失敗した 1 本目（ConvertError）・2 本目（想定外の例外）にも、終わった印がある
        assert any(e.file_index == idx and e.step == prg.STEP_COUNT and e.step_fraction == 1.0 for e in events), idx
    overalls = [e.overall for e in events]
    assert all(b >= a - 1e-12 for a, b in zip(overalls, overalls[1:])) and overalls[-1] == pytest.approx(1.0)
