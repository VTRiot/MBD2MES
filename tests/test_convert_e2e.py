# -*- coding: utf-8 -*-
"""合成 MBD を最後まで変換し、出力の MES を読み戻す。実データの標本の試験は環境変数 MBD2MES_SAMPLE があるときだけ。"""

from __future__ import annotations

import datetime
import math
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import synth_mbd as sm
from conftest import ROOT, sample_path

from mbd2mes import convert as cv
from mbd2mes import mes_reader as mr

LAT0, LON0 = 208_800_000, 819_000_000  # 34.8 deg, 136.5 deg（1/6,000,000 度）


def _channels():
    return [
        sm.entry("SysV", "V"), sm.entry("GPS1"), sm.entry("GPS2"),
        sm.entry("Ne", "rpm", can_id=0x6A0),
        sm.entry("THP", "%", can_id=0x6A1, a=1000, b=10000, fmt=1, mode=3),
        sm.entry("GYROAN", "deg", can_id=0x6A5, a=1000, b=200000, fmt=5, mode=3),
        sm.entry("GPSspd", "km/h", a=1000, b=1000, mode=3),
        sm.entry("LAF", "afr", can_id=0x6A6, a=9000, b=255000, c=9000, fmt=2, mode=3),
    ]


def _synth(tmp_path: Path) -> Path:
    """41 tick（205 ms）。GPS は 8 tick（40 ms = 25 Hz）ごとに 6 本。UTC 00:56:43.60 から 4 cs ずつ。"""
    ticks = []
    for tk in range(41):
        recs = []
        if tk % 8 == 0:
            k = tk // 8
            recs.append((1, sm.gps_block(LAT0 + 1000 * k, LON0 + 2000 * k, 1000 * k, 564360 + 4 * k)))
        if tk == 0:
            recs += [(3, 3000), (4, 500), (5, 65535), (7, 13)]
        if tk == 10:
            recs.append((3, 4000))
        if tk == 12:
            recs.append((7, 213))
        if tk == 20:
            recs.append((4, 1000))
        if tk == 25:
            recs.append((3, 5000))
        if tk == 30:
            recs.append((5, 1000))
        ticks.append(recs)
    p = tmp_path / "synth.MBD"
    p.write_bytes(sm.build_mbd(_channels(), ticks))
    return p


@pytest.fixture()
def synth_mes(tmp_path):
    res = cv.convert_one(_synth(tmp_path), tmp_path / "out", date=datetime.date(2026, 11, 8))
    return res, mr.load_mes(res.mes_dir)


def test_synth_channel_values(synth_mes):
    res, mes = synth_mes
    assert res.violations == []
    assert set(mes) == {"SysV", "Ne", "THP", "GYROAN", "LAF", "V_GPS", "Latitude", "Longitude"}
    ne = np.array([3000] * 10 + [4000] * 15 + [5000] * 16, float)  # 5 ms の格子。tick 10 から 4000、25 から 5000
    assert mes["Ne"] == pytest.approx(ne, abs=0.02)  # 16 bit の量子化（範囲 2000 / 65535 の半分）
    assert mes["THP"] == pytest.approx([50.0] * 20 + [100.0] * 21, abs=0.002)
    assert mes["GYROAN"] == pytest.approx([-0.005] * 30 + [5.0] * 11, abs=0.001)
    laf = np.array([13 * 9000 / 255000 + 9] * 12 + [213 * 9000 / 255000 + 9] * 29)
    assert mes["LAF"] == pytest.approx(laf, abs=0.001)


def test_synth_gps_and_lengths(synth_mes):
    res, mes = synth_mes
    for nm in ("Ne", "THP", "GYROAN", "LAF", "SysV"):
        assert len(mes[nm]) == 41  # ceil(205 ms * 200 Hz / 1000)
    for nm in ("V_GPS", "Latitude", "Longitude"):
        assert len(mes[nm]) == 6  # ceil(205 ms * 25 Hz / 1000)
    assert mes["Latitude"] == pytest.approx([34.8 + 1000 * k / 6e6 for k in range(6)], abs=2e-7)
    assert mes["Longitude"] == pytest.approx([136.5 + 2000 * k / 6e6 for k in range(6)], abs=2e-7)
    assert mes["V_GPS"] == pytest.approx([10.0 * k for k in range(6)], abs=0.01)
    assert res.base_hz == 400
    by = {c.name: c for c in res.channels}
    assert (by["Latitude"].bits, by["Ne"].bits, by["Latitude"].rate, by["Ne"].rate) == (32, 16, 25, 200)


def test_synth_ddd_gps_form_and_hed(synth_mes):
    res, _ = synth_mes
    ddd = (res.mes_dir / f"{res.mes_name}.DDD").read_bytes().decode("cp1252")
    assert b"\r\n" in ddd.encode("cp1252")
    sec = {}
    cur = None
    for line in ddd.split("\r\n"):
        if line.startswith("["):
            cur = {}
            continue
        if cur is not None and "=" in line:
            k, _, v = line.partition("=")
            cur[k] = v
            if k == "4":
                sec[v.split(",")[0]] = cur
    lat = sec["Latitude"]
    assert lat["1"].split(",")[5] == "20"  # 32 bit
    assert lat["3"].split(",")[3] == "33D6BF95"  # 倍率 float32(1e-7)
    assert lat["6"].startswith("FFFFFFFC,W,S227D9,")  # 2D の GPS ロガー実物の形
    assert sec["Longitude"]["6"].split(",")[2] == "S227D10"
    assert sec["V_GPS"]["6"].split(",")[2] == "S227D5"
    hed = (res.mes_dir / f"{res.mes_name}.HED").read_bytes().decode("cp1252")
    assert "Start of download=08.11.2026 09:56:43" in hed and "MainSamplingRate=400" in hed
    assert "[GPS]" in hed and "MSR=400" in hed


def test_synth_no_laps_when_no_control_line(synth_mes):
    res, _ = synth_mes
    assert res.lap_file_names == []
    assert not any(p.suffix == ".IXR" for p in res.mes_dir.iterdir())


def test_ixr_words(tmp_path):
    """周回する合成軌跡から .IXR を作り、語を数値で確かめる（形は docs/mes_format_Part2.md §5）。

    コントロールラインは経度一定の短い線分。軌跡は 1 周 100 測位: 東向き 50 本（線分の上を通る）→ 西向き 50 本（線分の北＝線分の外）。
    測位 k は t = 0.04 k 秒。東向きの 26 本目（k = 25 + 100 周目）で経度が線に達する -> t = 1.0, 5.0, 9.0 s。
    """
    deg = 6_000_000
    a_lat, b_lat, lon_line = round(34.8450 * deg), round(34.8452 * deg), round(136.5400 * deg)
    pts = []
    for _lap in range(3):
        pts += [(round(34.8451 * deg), lon_line + (i - 25) * 600) for i in range(50)]  # 600 = 0.0001 度
        pts += [(round(34.8460 * deg), lon_line + (25 - i) * 600) for i in range(50)]
    ticks = []
    for k, (la, lo) in enumerate(pts):
        ticks.append([(1, sm.gps_block(la, lo, 0, 564360 + 4 * k))])
        ticks += [[] for _ in range(7)]  # 8 tick = 40 ms
    p = tmp_path / "loop.MBD"
    p.write_bytes(sm.build_mbd(_channels(), ticks, control_line_units=(a_lat, lon_line, b_lat, lon_line)))
    res = cv.convert_one(p, tmp_path / "o", date=datetime.date(2026, 11, 8))
    raw = (res.mes_dir / f"{res.mes_name}.IXR").read_bytes()
    words = struct.unpack("<%di" % (len(raw) // 4), raw)
    n = 3
    assert words[0:2] == (0, 0)
    assert [words[2 + 2 * i] for i in range(n)] == [400, 2000, 3600]  # floor(t * 400 + 0.5)
    assert words[2 + 2 * n] == res.lap_plan.end_sample == math.ceil(2400 * 5 * 400 / 1000)
    assert words[-4] == ((n << 16) | (8 + 8 * (n + 1)))
    assert words[-3:] == (400, n, 0)
    assert res.lap_plan.lap_times_s == pytest.approx([4.0, 4.0])


# ---------------------------------------------------------------- CLI
def test_cli_roundtrip_and_exit_codes(tmp_path):
    p = _synth(tmp_path)
    out = tmp_path / "cli_out"
    r = subprocess.run([sys.executable, "-m", "mbd2mes", str(p), "-o", str(out), "--date", "2026-11-08"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (out / "synth.MES" / "synth.DDD").is_file()
    again = subprocess.run([sys.executable, "-m", "mbd2mes", str(p), "-o", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert again.returncode == 1 and "already exists" in again.stderr  # 既存の MES は --force が無ければ置き換えない
    bad = tmp_path / "bad.MBD"
    bad.write_bytes(b"not an mbd" * 1000)
    r = subprocess.run([sys.executable, "-m", "mbd2mes", str(bad), "-o", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 4


def test_southern_hemisphere_is_refused(tmp_path):
    ticks = [[(1, sm.gps_block(LAT0, LON0, 0, 564360, ns="S"))], [(1, sm.gps_block(LAT0, LON0, 0, 564364, ns="S"))]]
    p = tmp_path / "s.MBD"
    p.write_bytes(sm.build_mbd(_channels(), ticks))
    with pytest.raises(cv.ConvertError, match="southern or western"):
        cv.convert_one(p, tmp_path / "o")
    assert not (tmp_path / "o").exists() or not list((tmp_path / "o").glob("*.MES"))


def test_force_replaces_and_leaves_no_stage(tmp_path):
    p = _synth(tmp_path)
    cv.convert_one(p, tmp_path / "o")
    cv.convert_one(p, tmp_path / "o", force=True)
    assert sorted(x.name for x in (tmp_path / "o").iterdir()) == ["synth.MES"]


# ---------------------------------------------------------------- 実データの標本（環境変数があるときだけ）
SAMPLE = sample_path()
needs_sample = pytest.mark.skipif(SAMPLE is None, reason="set MBD2MES_SAMPLE to a SHA-256-checked copy of the sample MBD")


@pytest.fixture(scope="module")
def sample_result(tmp_path_factory):
    out = tmp_path_factory.mktemp("sample_out")
    res = cv.convert_one(SAMPLE, out, date=datetime.date(2026, 11, 8))
    return res, mr.load_mes(res.mes_dir)


@needs_sample
def test_sample_spec_numbers(sample_result):
    """docs/mbd_format.md の実測値（tick 数・GPS 件数・範囲・周回時間）。"""
    res, mes = sample_result
    assert res.violations == []
    assert res.span_ms == 369_945 * 5  # 1849.725 s
    gps = {c.name: c for c in res.channels}
    assert gps["Latitude"].samples == 46_244 and gps["Ne"].samples == 369_945
    lat, lon, v = mes["Latitude"], mes["Longitude"], mes["V_GPS"]
    # 仕様書 §5 の緯度の下端 34.8433635 は最初の測位の値で、実際の最小は 34.8389833（参照実装 mbd_dump.py でも同じ。仕様書の誤り）
    assert lat.min() == pytest.approx(34.8389833, abs=2e-7) and lat.max() == pytest.approx(34.8484118, abs=2e-7)
    assert lat[0] == pytest.approx(34.8433635, abs=2e-7)
    assert lon.min() == pytest.approx(136.5219588, abs=2e-7) and lon.max() == pytest.approx(136.5434030, abs=2e-7)
    assert v.max() == pytest.approx(293.22, abs=0.01)
    assert "GPS time of day at tick 0: 3403.655 s UTC" in res.record_text  # 仕様書 §7.2: 中央値 3403.655（最初の測位は 3403.60）
    plan = res.lap_plan
    assert len(plan.boundaries) == 11
    laps_s = plan.lap_times_s
    assert laps_s[0] == pytest.approx(205.4, abs=0.1)
    assert all(136.2 - 0.1 <= t <= 139.6 + 0.1 for t in laps_s[1:]) and len(laps_s) == 10


@needs_sample
def test_sample_every_channel_covers_the_duration(sample_result):
    """地雷 1: 全チャンネルの標本数 = ceil(T * レート / 1000)（ファイルの大きさから別経路で数える）。"""
    res, _ = sample_result
    ddd = mr.parse_ddd(res.mes_dir / f"{res.mes_name}.DDD")
    assert len(ddd) == len(res.channels)
    for e in ddd:
        size = (res.mes_dir / f"{res.mes_name}.{e.data_ext}").stat().st_size
        n = size // (e.bit_width // 8)
        rate = e.base_hz / e.divisor
        assert n == math.ceil(res.span_ms * rate / 1000), e.name
        assert 0 <= n / rate - res.span_ms / 1000 < 1 / rate, e.name  # T 以上、T + 1 標本分未満


def test_gps_clock_offset_uses_median_of_tick_offsets(tmp_path):
    """GPS の最初の測位が tick 11 に置かれる記録。tick 0 の UTC = 3403.60 - 11 * 5 ms = 3403.545（全測位の中央値）。
    測位 k の時刻 = 0.055 + 0.04 k 秒 -> 25 Hz の格子の k + 1 番（四捨五入）。0 番は最初の値を保つ。"""
    ticks = [[] for _ in range(60)]
    for k in range(6):
        ticks[11 + 8 * k].append((1, sm.gps_block(LAT0 + 1000 * k, LON0, 0, 564360 + 4 * k)))
    p = tmp_path / "off.MBD"
    p.write_bytes(sm.build_mbd(_channels(), ticks))
    res = cv.convert_one(p, tmp_path / "o", date=datetime.date(2026, 11, 8))
    assert "GPS time of day at tick 0: 3403.545 s UTC" in res.record_text
    lat = mr.load_mes(res.mes_dir)["Latitude"]
    assert len(lat) == 8  # ceil(300 ms * 25 / 1000)
    assert lat == pytest.approx([34.8 + 1000 * k / 6e6 for k in (0, 0, 1, 2, 3, 4, 5, 5)], abs=2e-7)
