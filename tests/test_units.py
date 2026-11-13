# -*- coding: utf-8 -*-
"""読み取り・換算・零次ホールド・ラップの単体試験。期待値は仕様書（docs/mbd_format.md）の数値と手計算、別式（haversine）から。"""

from __future__ import annotations

import datetime
import math

import numpy as np
import pytest
import synth_mbd as sm

from mbd2mes import channels as chmod
from mbd2mes import laps, timeline as tl
from mbd2mes.convert import recording_start_ms
from mbd2mes.mbd_reader import MbdError, read_mbd

R_EARTH = 6371008.8


def _write(tmp_path, data: bytes):
    p = tmp_path / "t.MBD"
    p.write_bytes(data)
    return p


def _basic_channels():
    return [
        sm.entry("SysV", "V"), sm.entry("GPS1"), sm.entry("GPS2"),
        sm.entry("Ne", "rpm", can_id=0x6A0),
        sm.entry("THP", "%", can_id=0x6A1, a=1000, b=10000, fmt=1, mode=3),
        sm.entry("GYROAN", "deg", can_id=0x6A5, a=1000, b=200000, fmt=5, mode=3),
        sm.entry("GPSspd", "km/h", a=1000, b=1000, mode=3),
        sm.entry("LAF", "afr", can_id=0x6A6, a=9000, b=255000, c=9000, fmt=2, mode=3),
    ]


# ---------------------------------------------------------------- 読み取り
def test_read_gps_and_ticks(tmp_path):
    # 仕様 §5 の例: 564360 -> 00:56:43.60 = 3403.60 s、1273332 -> 01:27:33.32 = 5253.32 s
    lat = 208_800_000  # 34.8 deg
    lon = 819_000_000  # 136.5 deg
    ticks = [[(1, sm.gps_block(lat, lon, 29322, 564360)), (3, 3000)], [], [(1, sm.gps_block(lat + 6, lon, 100, 1273332))]]
    mbd = read_mbd(_write(tmp_path, sm.build_mbd(_basic_channels(), ticks)))
    assert mbd.n_ticks == 3
    assert mbd.duration_ms == 15
    assert len(mbd.gps) == 2
    assert mbd.gps.lat_deg[0] == pytest.approx(34.8, abs=1e-9)
    assert mbd.gps.lon_deg[0] == pytest.approx(136.5, abs=1e-9)
    assert mbd.gps.speed_kmh[0] == pytest.approx(293.22)
    assert mbd.gps.utc_s[0] == pytest.approx(3403.60)
    assert mbd.gps.utc_s[1] == pytest.approx(5253.32)
    assert list(mbd.gps.tick) == [0, 2]
    assert list(mbd.ticks[3]) == [0] and list(mbd.raws[3]) == [3000]
    assert len(mbd.ticks[0]) == 3  # SysV は毎 tick


@pytest.mark.parametrize("mut", ["magic", "short", "tag"])
def test_bad_files(tmp_path, mut):
    data = bytearray(sm.build_mbd(_basic_channels(), [[(3, 1)]]))
    if mut == "magic":
        data[0] = ord("X")
    elif mut == "short":
        data = data[:0x100]
    else:
        data += bytes([0x3F]) + b"\x00\x00"  # 表は 8 本なのでタグ 0x3F は未知
    with pytest.raises(MbdError):
        read_mbd(_write(tmp_path, bytes(data)))


def test_truncated_tail_warns(tmp_path):
    data = sm.build_mbd(_basic_channels(), [[(3, 1)]]) + bytes([3, 0])  # 値の途中で切れる
    mbd = read_mbd(_write(tmp_path, data))
    assert any("truncated" in w for w in mbd.warnings)


# ---------------------------------------------------------------- 換算（仕様 §6・付録 A の数値）
def _plans(tmp_path, ticks, channels=None):
    mbd = read_mbd(_write(tmp_path, sm.build_mbd(channels or _basic_channels(), ticks)))
    return chmod.plan_channels(mbd)


def test_conversion_values(tmp_path):
    ticks = [[(3, 3000), (4, 500), (5, 65535), (6, 1234), (7, 13)], [(7, 213)]]
    plans, skipped, warnings = _plans(tmp_path, ticks)
    by = {p.name: p for p in plans}
    assert list(by["Ne"].values) == [3000.0]  # Direct
    assert list(by["THP"].values) == [50.0]  # 500 * 1000 / 10000
    assert by["GYROAN"].values[0] == pytest.approx(-0.005)  # int16(65535) = -1 -> -1 * 1000 / 200000
    assert by["LAF"].values[0] == pytest.approx(9.4588235)  # 13 * 9000 / 255000 + 9（付録 A: 9.459）
    assert by["LAF"].values[1] == pytest.approx(16.517647)
    names = dict(skipped)
    assert names["GPS2"] == "no value records"
    assert "GPSspd" in names and "V_GPS" in names["GPSspd"]
    assert warnings == []


def test_signed_rule_disagreement_warns(tmp_path):
    ch = _basic_channels()
    ch[5] = sm.entry("GYROAN", "deg", can_id=0x6A5, a=1000, b=200000, fmt=2, mode=3)  # 名前は符号付きの表、[14] は 2
    _plans2 = _plans(tmp_path, [[(5, 65535)]], ch)
    assert any("GYROAN" in w and "signed rule" in w for w in _plans2[2])


def test_unresolved_channel_written_raw(tmp_path):
    ch = _basic_channels() + [sm.entry("THGRPADJ", "deg", a=0, b=584000, fmt=1, mode=1)]
    plans, _s, warnings = _plans(tmp_path, [[(8, 578)]], ch)
    assert [p.values[0] for p in plans if p.name == "THGRPADJ"] == [578.0]
    assert any("THGRPADJ" in w for w in warnings)


# ---------------------------------------------------------------- 零次ホールド
def test_hold_ticks():
    v, before = tl.hold_ticks(np.array([2, 4, 7]), np.array([10.0, 20.0, 30.0]), 10)
    assert list(v) == [10, 10, 10, 10, 20, 20, 20, 30, 30, 30]  # 0..1 は最初の値を保つ
    assert before == 2


def test_hold_ticks_other_rate():
    # 25 Hz の格子 k は k*40 ms。tick = 5 ms。レコード tick 8 = 40 ms、tick 17 = 85 ms
    v, _ = tl.hold_ticks(np.array([0, 8, 17]), np.array([1.0, 2.0, 3.0]), 4, rate_hz=25)
    assert list(v) == [1, 2, 2, 3]  # 0 ms, 40 ms, 80 ms(85 ms のレコードはまだ), 120 ms


def test_hold_fixes():
    t = np.array([0.0, 0.04, 0.08, 0.16])  # 0.12 の測位が欠けた
    v = tl.hold_fixes(t, np.array([1.0, 2.0, 3.0, 5.0]), 6, 25)
    assert list(v) == [1, 2, 3, 3, 5, 5]


def test_sample_count_and_rate():
    assert tl.sample_count(1_849_725, 25) == 46_244  # ceil(1849.725 * 25)
    assert tl.sample_count(1_849_725, 200) == 369_945
    assert tl.choose_rate(0.04) == 25
    assert tl.choose_rate(0.005) == 200
    assert tl.BASE_HZ % tl.TICK_RATE_HZ == 0


# ---------------------------------------------------------------- 開始日時
def test_recording_start_with_date():
    # 現地 2026-11-08 + GPS の UTC 時刻 00:56:43.655 -> 現地 09:56:43.655 -> UTC 2026-11-08 00:56:43.655
    ms, how = recording_start_ms(3403.655, 1849.725, datetime.date(2026, 11, 8), 0.0)
    expect = datetime.datetime(2026, 11, 8, 0, 56, 43, 655000, tzinfo=datetime.timezone.utc).timestamp() * 1000
    assert ms == round(expect)
    assert "--date" in how


def test_recording_start_from_mtime():
    mtime = datetime.datetime(2026, 11, 8, 1, 30, 0, tzinfo=datetime.timezone.utc).timestamp()  # 記録の終わり付近
    ms, _ = recording_start_ms(3403.655, 1849.725, None, mtime)
    expect = datetime.datetime(2026, 11, 8, 0, 56, 43, 655000, tzinfo=datetime.timezone.utc).timestamp() * 1000
    assert ms == round(expect)


def test_recording_start_no_gps():
    ms, how = recording_start_ms(None, 10.0, None, 1000.0)
    assert ms == 990_000 and "no GPS" in how


# ---------------------------------------------------------------- ラップ（別式 haversine で期待値を作る）
def _hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R_EARTH * math.asin(math.sqrt(h))


LINE = (34.8450, 136.5400, 34.8452, 136.5400)  # 経度一定の短い線
P0, P1, P2, P3 = (34.8451, 136.5390), (34.8451, 136.5410), (34.8460, 136.5410), (34.8460, 136.5390)


def _loop_track(laps_n: int):
    legs = [(P0, P1, 20), (P1, P2, 30), (P2, P3, 30), (P3, P0, 20)]  # 1 周 100 s
    t, lat, lon = [], [], []
    for k in range(laps_n):
        base = 100 * k
        acc = 0
        for a, b, dur in legs:
            for s in range(dur):
                f = s / dur
                t.append(base + acc + s)
                lat.append(a[0] + f * (b[0] - a[0]))
                lon.append(a[1] + f * (b[1] - a[1]))
            acc += dur
    t.append(100 * laps_n)
    lat.append(P0[0])
    lon.append(P0[1])
    return np.array(t, float), np.array(lat), np.array(lon)


def test_laps_loop_track():
    t, lat, lon = _loop_track(4)  # 線を横切るのは各周 1 回（帰りの経路は線分の外）。t = 10, 110, 210, 310
    plan = laps.plan_laps(lat, lon, t, LINE, 400, 400_000)
    assert [s for s, _d in plan.boundaries] == [4000, 44000, 84000, 124000]  # floor(t * 400 + 0.5)
    half = _hav(P0, (34.8451, 136.5400))
    perimeter = _hav(P0, P1) + _hav(P1, P2) + _hav(P2, P3) + _hav(P3, P0)
    for k, (_s, d) in enumerate(plan.boundaries):
        assert d == pytest.approx(half + perimeter * k, abs=1.0)
    assert plan.lap_times_s == pytest.approx([100.0, 100.0, 100.0])
    assert plan.analyzer_count == 5
    assert plan.end_dist_m == pytest.approx(half * 0 + perimeter * 4, abs=2.0)


def test_laps_opposite_direction_dropped():
    lon = np.array([136.5395, 136.5405] * 3)  # 東・西・東・西 と往復（毎回線分の上を通る）
    lat = np.full(6, 34.8451)
    t = np.arange(6, dtype=float)
    plan = laps.plan_laps(lat, lon, t, LINE, 400, 10_000)
    assert [s for s, _d in plan.boundaries] == [200, 1000, 1800]  # t = 0.5, 2.5, 4.5 -> 東向き 3 本
    assert any("opposite" in w for w in plan.warnings)


def test_laps_single_crossing_is_not_a_lap():
    lat = np.full(3, 34.8451)
    lon = np.array([136.5395, 136.5405, 136.5415])
    plan = laps.plan_laps(lat, lon, np.arange(3.0), LINE, 400, 10_000)
    assert plan.boundaries == []
