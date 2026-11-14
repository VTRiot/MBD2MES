# -*- coding: utf-8 -*-
"""設定（config）と対応表（channel_map）の置き場・保存・復旧。受け入れ条件 2（exe の隣に保存され、再起動で戻る）。"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest
from conftest import ROOT, SETTINGS_ENV, fresh_settings

from mbd2mes import channel_map as cm
from mbd2mes import config as cfgmod
from mbd2mes import map_rules

SEED = json.loads((ROOT / "channel_map.seed.json").read_text(encoding="utf-8"))


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ---------------------------------------------------------------- 隔離
def test_settings_env_name_matches_and_points_to_temp():
    assert SETTINGS_ENV == cfgmod.SETTINGS_ENV
    base = cfgmod.settings_base_dir().resolve()
    assert base != ROOT.resolve() and Path(tempfile.gettempdir()).resolve() in base.parents


def test_app_base_dir_is_the_repo_root_in_dev():
    assert cfgmod.app_base_dir() == ROOT.resolve()  # パッケージの 1 つ上（seed がある場所）
    assert cfgmod.seed_path().is_file() and cm.seed_path().is_file()


# ---------------------------------------------------------------- 対応表: 置き場・保存・読み直し
def test_map_lives_in_settings_dir_and_reloads(tmp_path, monkeypatch):
    d = fresh_settings(tmp_path, monkeypatch)
    data = cm.load_or_init_map()  # 無ければ seed から作る
    assert cm.map_path() == d / "channel_map.json" and (d / "channel_map.json").is_file()
    assert data == SEED
    cm.update_entry(data, "Ne", None, "Engine", multiplier=2.0, offset=3.0)
    cm.save_map(data)
    again = cm.load_or_init_map()  # 再起動の代わり: 新しく読み直す
    assert again["channels"]["Ne"]["custom_name"] == "Engine" and again["channels"]["Ne"]["multiplier"] == 2.0


def test_map_falls_back_when_dir_not_writable(tmp_path):
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    base = blocker / "sub"  # 親が通常のファイルなので作れない = 書けない
    fb = tmp_path / "fallback"
    assert cm.map_path(base=base, fallback_base=fb) == fb / "channel_map.json"
    data = cm.load_or_init_map(base=base, fallback_base=fb)
    assert (fb / "channel_map.json").is_file() and data == SEED
    cm.save_map(data, base=base, fallback_base=fb)
    assert (fb / "channel_map.json").is_file()
    assert cm.map_path(base=tmp_path / "ok", fallback_base=fb) == tmp_path / "ok" / "channel_map.json"  # 書ければ隣


def test_new_seed_rows_do_not_erase_user_edits(tmp_path, monkeypatch):
    """版を上げて seed に行が増えても、既存の表（利用者の編集）は上書きされず、足りない行だけが足される。"""
    fresh_settings(tmp_path, monkeypatch)
    old = json.loads(json.dumps(SEED))
    del old["channels"]["THP"]  # 古い版の表には THP の行が無い
    old["channels"]["Ne"]["custom_name"] = "Engine"
    cm.save_map(old)
    loaded = cm.load_or_init_map()  # 起動: 既存の表をそのまま読む（seed で上書きしない）
    assert "THP" not in loaded["channels"] and loaded["channels"]["Ne"]["custom_name"] == "Engine"
    _, added = cm.grow_channel_map(loaded, [{"name": "THP", "unit": "%"}])
    assert added == 1
    path, ok = cm.merge_and_save_map(loaded)
    assert ok
    final = json.loads(path.read_text(encoding="utf-8"))["channels"]
    assert final["Ne"]["custom_name"] == "Engine" and final["THP"]["raw_unit"] == "%"


# ---------------------------------------------------------------- 壊れた表（Plan §7-1）
def test_load_corrupt_sets_aside_and_recovers(tmp_path, monkeypatch):
    d = fresh_settings(tmp_path, monkeypatch)
    (d / "channel_map.json").write_bytes(b"{ broken")
    data = cm.load_or_init_map()
    assert data == {"schema": 1, "channels": {}}  # 空の表で続ける（seed へは戻さない）
    asides = list(d.glob("channel_map.json.corrupt_*"))
    assert len(asides) == 1 and asides[0].read_bytes() == b"{ broken"  # 元の中身は退避に残る
    assert json.loads((d / "channel_map.json").read_text(encoding="utf-8")) == {"schema": 1, "channels": {}}


def test_load_corrupt_unwritable_keeps_original(tmp_path, monkeypatch):
    d = fresh_settings(tmp_path, monkeypatch)
    path = d / "channel_map.json"
    path.write_bytes(b"{ broken")
    monkeypatch.setattr(cm.shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
    data = cm.load_or_init_map()
    assert data == {"schema": 1, "channels": {}}  # メモリ上の空の表で続ける
    assert path.read_bytes() == b"{ broken"  # 退避できなかったので元を残す


def test_merge_never_overwrites_corrupt(tmp_path, monkeypatch):
    d = fresh_settings(tmp_path, monkeypatch)
    path = d / "channel_map.json"
    for payload in (b"{ broken", json.dumps({"schema": 99, "channels": {}}).encode(), b"[1, 2]"):
        path.write_bytes(payload)
        before = sha(path)
        logs = []
        _p, ok = cm.merge_and_save_map(json.loads(json.dumps(SEED)), log=logs.append)
        assert ok is False and sha(path) == before and logs, payload


# ---------------------------------------------------------------- GUI の保存（Plan §7-2）
def test_gui_save_keeps_rows_added_by_another_process(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    gui_view = json.loads(json.dumps(SEED))  # GUI が読んだ時点の表
    cm.save_map(gui_view)
    other = json.loads(json.dumps(SEED))  # その後、別プロセスの自動成長が行を足した
    other["channels"]["NEWCH"] = {"unit": None, "custom_name": None, "raw_unit": "u", "multiplier": 1.0, "offset": 0.0}
    cm.save_map(other)
    cm.update_entry(gui_view, "Ne", None, "Engine")  # GUI で編集して保存
    path = map_rules.save_map_preserving_others(gui_view)
    final = json.loads(path.read_text(encoding="utf-8"))["channels"]
    assert "NEWCH" in final and final["Ne"]["custom_name"] == "Engine"


def test_gui_save_deletes_only_rows_deleted_in_this_session(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    disk = json.loads(json.dumps(SEED))
    for n in ("X1", "X2"):
        disk["channels"][n] = {"unit": None, "custom_name": None, "raw_unit": "", "multiplier": 1.0, "offset": 0.0}
    cm.save_map(disk)
    mem = json.loads(json.dumps(disk))
    assert cm.delete_entry(mem, "X1", SEED)  # この窓で X1 を削除した
    path = map_rules.save_map_preserving_others(mem, deleted={"X1"})
    final = json.loads(path.read_text(encoding="utf-8"))["channels"]
    assert "X1" not in final and "X2" in final


def test_gui_save_with_corrupt_disk_saves_memory(tmp_path, monkeypatch):
    d = fresh_settings(tmp_path, monkeypatch)
    (d / "channel_map.json").write_bytes(b"{ broken")
    path = map_rules.save_map_preserving_others(json.loads(json.dumps(SEED)))
    assert json.loads(path.read_text(encoding="utf-8")) == SEED


# ---------------------------------------------------------------- 設定（config）
def test_config_initial_and_persists(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    cfg = cfgmod.load_or_init_config()
    assert cfg == {"schema": 1, "output_dir": None, "last_mbd_dir": None} and cfgmod.get_output_dir(cfg) is None
    out = tmp_path / "out"
    out.mkdir()
    cfgmod.set_output_dir(out)
    cfgmod.set_last_mbd_dir(out)
    again = cfgmod.load_or_init_config()
    assert cfgmod.get_output_dir(again) == out and cfgmod.get_last_mbd_dir(again) == out.resolve()
    out.rmdir()
    assert cfgmod.get_output_dir(cfgmod.load_or_init_config()) is None  # 実在しない出力先は使わない


def test_config_schema_mismatch_keeps_existing_dir(tmp_path, monkeypatch):
    d = fresh_settings(tmp_path, monkeypatch)
    keep = tmp_path / "keep"
    keep.mkdir()
    (d / "mbd2mes_config.json").write_text(json.dumps({"schema": 99, "output_dir": str(keep)}), encoding="utf-8")
    cfg = cfgmod.load_or_init_config()
    assert cfg["schema"] == 1 and cfg["output_dir"] == str(keep)
    assert len(list(d.glob("mbd2mes_config.json.corrupt_*"))) == 1


def test_config_falls_back_when_dir_not_writable(tmp_path):
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    fb = tmp_path / "fb"
    assert cfgmod.config_path(base=blocker / "sub", fallback_base=fb) == fb / "mbd2mes_config.json"
    cfg = cfgmod.load_or_init_config(base=blocker / "sub", fallback_base=fb)
    assert (fb / "mbd2mes_config.json").is_file() and cfg["output_dir"] is None


# ---------------------------------------------------------------- seed の正当性（Plan §6。サンプルが無くても通る）
APPX_ROW = __import__("re").compile(r"^\| (\d+) \| (\w+) \| [^|]* \| [^|]* \|(?: [^|]* \|){8} (\d+) \|")


def test_seed_rows_match_appendix_a():
    """文書整合性の試験: docs/mbd_format.md 付録 A（参照実装 mbd_dump.py による以前の解析の記録）の件数 > 0 の行から
    GPSspd と GPS ブロックを除いた名前の集合が、追跡した seed の名前の集合（保護する 3 行を除く）と一致する。"""
    text = (ROOT / "docs" / "mbd_format.md").read_text(encoding="utf-8")
    appx = text[text.index("## 付録 A"):]
    want = set()
    for line in appx.splitlines():
        cols = [c.strip() for c in line.split("|")]
        if len(cols) > 14 and cols[1].isdigit():
            name, count = cols[2], int(cols[14])
            if count > 0 and name not in ("GPSspd", "GPS1", "GPS2"):
                want.add(name)
    have = set(SEED["channels"]) - set(map_rules.PROTECTED_NAMES)
    assert want == have, (sorted(want - have), sorted(have - want))
    assert set(map_rules.PROTECTED_NAMES) <= set(SEED["channels"])


def test_seed_rows_are_identity():
    for name, e in SEED["channels"].items():
        assert e["unit"] is None and e["custom_name"] is None and e["multiplier"] == 1.0 and e["offset"] == 0.0, name
        assert isinstance(e["raw_unit"], str)
