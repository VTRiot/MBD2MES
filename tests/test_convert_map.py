# -*- coding: utf-8 -*-
"""対応表が変換に効くこと（受け入れ条件 1）と、恒等のとき何も変わらないこと。期待値は map_synth の手計算。"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from pathlib import Path

import map_synth as ms
import numpy as np
import pytest
from conftest import fresh_settings

from mbd2mes import channel_map as cm
from mbd2mes import convert as cv
from mbd2mes import gps_entries as ge
from mbd2mes import map_rules
from mbd2mes import mes_reader as mr

DATE = datetime.date(2026, 11, 8)
HALF_STEP = 0.003  # 16 bit の量子化の半分（今の e2e の許容と同じ桁。値の幅 / 65535 / 2 の上限）


@pytest.fixture()
def env(tmp_path, monkeypatch):
    settings = fresh_settings(tmp_path, monkeypatch)
    return tmp_path, settings, ms.write(tmp_path / "synth.MBD")


def seed_map():
    return cm.load_or_init_map()


def convert(env, cmap, out="o", **kw):
    tmp, _settings, mbd = env
    return cv.convert_one(mbd, tmp / out, date=DATE, channel_map_data=cmap, **kw)


def tree_bytes(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def edit(cmap, name, *, unit=None, custom=None, mult=1.0, off=0.0):
    cm.update_entry(cmap, name, unit, custom, multiplier=mult, offset=off)
    return cmap


# ---------------------------------------------------------------- 恒等
def test_identity_map_is_byte_identical_to_no_map(env):
    """seed のままの表は、表なしと 1 byte も違わない（記録ファイルを含む出力フォルダの全ファイル）。"""
    a = convert(env, None, "no_map")
    b = convert(env, seed_map(), "seed_map")
    assert b.map_applied == [] and "Channel map applied" not in b.record_text
    ta, tb = tree_bytes(a.mes_dir), tree_bytes(b.mes_dir)
    assert ta.keys() == tb.keys()
    for name in ta:
        assert ta[name] == tb[name], name


def test_protected_names_are_the_variant_names():
    var = ge.get_variant(ge.DEFAULT_VARIANT)
    assert tuple(var.rename[k] for k in ("Lat_dez", "Lon_dez", "V_Sat")) == map_rules.PROTECTED_NAMES


# ---------------------------------------------------------------- 効く（手計算）
def test_multiplier_offset_applied_hand_computed(env):
    """THP: 生値 500 / 1000 -> 50.0 / 100.0 %。Multiplier 2・Offset 1・単位 x -> 101.0 / 201.0。"""
    cmap = edit(seed_map(), "THP", unit="x", mult=2.0, off=1.0)
    res = convert(env, cmap)
    mes = mr.load_mes(res.mes_dir)
    assert mes["THP"] == pytest.approx([101.0] * 20 + [201.0] * 21, abs=HALF_STEP)
    unit = {e.name: e.unit for e in mr.parse_ddd(res.mes_dir / f"{res.mes_name}.DDD")}
    assert unit["THP"] == "x"
    assert any(x.startswith("THP:") and "x2.0+1.0" in x for x in res.map_applied)
    assert "Channel map applied: 1" in res.record_text


def test_editing_one_row_leaves_others_unchanged_and_changes_the_target(env):
    base = mr.load_mes(convert(env, seed_map(), "base").mes_dir)
    res = convert(env, edit(seed_map(), "THP", unit="x", mult=2.0, off=1.0), "edited")
    mes = mr.load_mes(res.mes_dir)
    assert set(mes) == set(base)
    for name in base:
        if name == "THP":
            assert not np.allclose(mes[name], base[name])  # 編集した行は変わる
        else:
            assert np.array_equal(mes[name], base[name]), name  # 他は 1 値も変わらない


def test_scaling_without_unit_is_refused(env):
    """一次変換を指定して単位を指定しない（生単位追従のまま）と、変換前に止まる（変換後の値に未変換の単位が付くのを防ぐ）。"""
    cmap = seed_map()
    cmap["channels"]["THP"]["multiplier"] = 2.0
    with pytest.raises(ValueError, match="unit"):
        convert(env, cmap)


# ---------------------------------------------------------------- 任意名（元を残して別名のコピーを足す）
def test_custom_name_adds_a_copy(env):
    res = convert(env, edit(seed_map(), "Ne", custom="Engine"))
    mes = mr.load_mes(res.mes_dir)
    assert np.array_equal(mes["Engine"], mes["Ne"])
    assert mes["Ne"] == pytest.approx(ms.expected()["Ne"], abs=0.02)
    assert any(x.startswith("Engine:") and "copy of Ne" in x for x in res.map_applied)


def test_unencodable_custom_name_skips_copy_only(env):
    res = convert(env, edit(seed_map(), "GYROAN", custom="スロットル"))
    mes = mr.load_mes(res.mes_dir)
    assert "GYROAN" in mes and not any("ス" in n for n in mes)
    assert any("cp1252" in why for _n, why in res.skipped)
    assert mes["GYROAN"] == pytest.approx(ms.expected()["GYROAN"], abs=HALF_STEP)


# ---------------------------------------------------------------- entry と元の行の対応（Plan §2-1・§5-2）
def test_layout_maps_each_entry_to_its_source_row(env):
    """任意名のコピー・書けない任意名・既存名との衝突・32 byte を超える任意名・一次変換を同居させ、
    DDD から読んだ各 entry の値・divisor を、手計算の元の行の期待値と照合する。記録ファイルの各行も同じ。"""
    long_name = "T" * 40
    cmap = seed_map()
    edit(cmap, "Ne", custom="Engine")
    edit(cmap, "THP", unit="x", custom=long_name, mult=2.0, off=1.0)
    edit(cmap, "GYROAN", custom="スロットル")
    edit(cmap, "LAF", custom="SysV")  # 既存の名前と衝突
    res = convert(env, cmap)
    exp = ms.expected()
    thp2 = exp["THP"] * 2.0 + 1.0
    ddd = mr.parse_ddd(res.mes_dir / f"{res.mes_name}.DDD")
    names = [e.name for e in ddd]
    assert len(names) == len(set(names)) and all(len(n.encode("cp1252")) <= 32 for n in names)
    mes = mr.load_mes(res.mes_dir)
    # 元の行の期待値（名前は一意化で変わりうるので、値で行を特定する）
    want = {"SysV": exp["SysV"], "Ne": exp["Ne"], "Engine": exp["Ne"], "THP": thp2, "GYROAN": exp["GYROAN"], "LAF": exp["LAF"]}
    for name, values in want.items():
        assert mes[name] == pytest.approx(values, abs=HALF_STEP if name != "Ne" and name != "Engine" else 0.02), name
    copies_of_thp = [n for n in names if n.startswith("T" * 8)]
    assert len(copies_of_thp) == 1 and mes[copies_of_thp[0]] == pytest.approx(thp2, abs=HALF_STEP)
    laf_copy = [n for n in names if n.startswith("SysV") and n != "SysV"]
    assert len(laf_copy) == 1 and mes[laf_copy[0]] == pytest.approx(exp["LAF"], abs=HALF_STEP)
    assert mes["SysV"] == pytest.approx(exp["SysV"], abs=HALF_STEP)  # 衝突しても元の SysV は動かない
    assert not any("ス" in n for n in names)
    # GPS の 3 本は 25 Hz・32 bit（位置）で、表を通らない
    by_ddd = {e.name: e for e in ddd}
    assert by_ddd["Latitude"].bit_width == 32 and by_ddd["V_GPS"].bit_width == 16
    assert by_ddd["Ne"].divisor == 2 and by_ddd["V_GPS"].divisor == 16  # 400 / 200、400 / 25
    # 記録ファイル: 行の並びと名前・divisor・bit が DDD の entry と 1:1
    lines = [ln for ln in res.record_text.splitlines() if re.match(r"^  \S.* \| .* \| \d+ Hz \| divisor \d+ \|", ln)]
    assert len(lines) == len(ddd)
    for ln, e in zip(lines, ddd):
        cols = [c.strip() for c in ln.split("|")]
        assert cols[0] == e.name and cols[3] == f"divisor {e.divisor}" and cols[5] == f"{e.bit_width} bit", ln
        assert cols[2] == f"{int(e.base_hz) // e.divisor} Hz", ln  # レート（400 Hz / divisor）
        assert cols[4] == f"{len(mes[e.name])} samples", ln
    laf_line = next(ln for ln in lines if ln.strip().startswith("LAF |"))
    laf_copy_line = next(ln for ln in lines if ln.strip().startswith(laf_copy[0] + " |"))
    for ln in (laf_line, laf_copy_line):
        assert f"first {ms.lead_of_laf()} samples hold the first value" in ln
    assert "copy of LAF" in laf_copy_line and "copy of" not in laf_line


# ---------------------------------------------------------------- 保護する行
def test_protected_rows_ignore_the_map(env):
    base = convert(env, None, "base")
    cmap = seed_map()
    for name in map_rules.PROTECTED_NAMES:
        cmap["channels"][name].update({"custom_name": "Renamed", "unit": "zz", "multiplier": 3.0, "offset": 5.0})
    res = convert(env, cmap, "prot")
    a, b = mr.load_mes(base.mes_dir), mr.load_mes(res.mes_dir)
    assert set(a) == set(b) and not any("Renamed" in n for n in b)
    for name in map_rules.PROTECTED_NAMES:
        assert np.array_equal(a[name], b[name]), name
    for name in map_rules.PROTECTED_NAMES:
        assert any(w.startswith(f"[WARN] {name}:") for w in res.warnings)
    hed = (res.mes_dir / f"{res.mes_name}.HED").read_text(encoding="cp1252")
    assert "[GPS]" in hed
    ddd = {e.name: e for e in mr.parse_ddd(res.mes_dir / f"{res.mes_name}.DDD")}
    assert ddd["V_GPS"].unit == "km/h" and ddd["V_GPS"].raw_key6[2] == "S227D5"


# ---------------------------------------------------------------- 不正な表では何も残さない
@pytest.mark.parametrize("bad", [0.0, None, float("nan"), "abc"])
def test_bad_scaling_stops_before_writing(env, bad):
    tmp, settings, mbd = env
    cmap = seed_map()
    cmap["channels"]["THP"].update({"unit": "x", "multiplier": bad})
    before_settings = tree_bytes(settings)
    with pytest.raises(ValueError):
        cv.convert_one(mbd, tmp / "fresh_out", date=DATE, channel_map_data=cmap)
    assert not (tmp / "fresh_out").exists()  # 出力先のフォルダも作らない
    assert tree_bytes(settings) == before_settings  # 設定ファイルも増えない・変わらない
    good = convert(env, seed_map(), "existing")
    existing = tree_bytes(good.mes_dir)
    listing = sorted(p.name for p in (tmp / "existing").iterdir())
    with pytest.raises(ValueError):
        cv.convert_one(mbd, tmp / "existing", date=DATE, force=True, channel_map_data=cmap)
    assert tree_bytes(good.mes_dir) == existing and sorted(p.name for p in (tmp / "existing").iterdir()) == listing


# ---------------------------------------------------------------- 自動成長
def test_auto_grow_adds_only_missing_rows(env):
    _tmp, _settings, _mbd = env
    disk = edit(seed_map(), "Ne", custom="Engine")
    cm.save_map(disk)  # 利用者の編集がディスクにある
    mem = seed_map_without_disk()  # メモリの表は古い（編集前）で、THP の行も無い（新しい版の MBD で足されるチャンネルの想定）
    del mem["channels"]["THP"]
    res = convert(env, mem)
    assert res.map_saved
    on_disk = json.loads(cm.map_path().read_text(encoding="utf-8"))["channels"]
    assert on_disk["Ne"]["custom_name"] == "Engine"  # 既存の行は書き換えない
    assert on_disk["THP"]["raw_unit"] == "%" and on_disk["THP"]["unit"] is None and on_disk["THP"]["multiplier"] == 1.0


def test_auto_grow_does_not_overwrite_a_corrupt_map(env):
    path = cm.map_path()
    path.write_bytes(b"{ not json")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    mem = seed_map_without_disk()
    del mem["channels"]["THP"]
    res = convert(env, mem)
    assert res.map_saved is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before  # 元を守る
    assert (res.mes_dir / f"{res.mes_name}.DDD").is_file()  # 変換は成功のまま


def seed_map_without_disk():
    return json.loads(cm.seed_path().read_text(encoding="utf-8"))
