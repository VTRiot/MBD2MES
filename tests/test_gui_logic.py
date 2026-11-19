# -*- coding: utf-8 -*-
"""GUI のロジック（Tk を使わない関数）と、Tk の部品の smoke（窓は出さない: withdraw）。"""

from __future__ import annotations

import json
import time

import map_synth as ms
import pytest
from conftest import ROOT, fresh_settings

from mbd2mes import app_convert as ac
from mbd2mes import channel_map as cm
from mbd2mes import gui, map_rules
from mbd2mes import mes_reader as mr

SEED = json.loads((ROOT / "channel_map.seed.json").read_text(encoding="utf-8"))


def test_format_scaling():
    assert gui.format_scaling(1.0) == "1.0" and gui.format_scaling(0.5) == "0.5" and gui.format_scaling(None) == ""
    assert gui.format_scaling(float("nan")) == "nan" and gui.format_scaling("abc") == "abc"


def test_sorted_rows_put_empty_unit_first_and_show_raw_unit():
    data = {"channels": {"B": {"unit": "x", "raw_unit": "u"}, "A": {"unit": None, "raw_unit": "rpm", "custom_name": "Z"}, "C": {}}}
    rows = gui.sorted_channel_rows(data)
    assert [r[0] for r in rows] == ["A", "C", "B"]
    assert rows[0] == ("A", "rpm", "", "Z", "1.0", "0.0")


def test_filter_matches_name_and_custom_case_insensitive():
    assert gui.row_matches_filter("", "Ne", "") and gui.row_matches_filter(" ne ", "Ne", "")
    assert gui.row_matches_filter("eng", "Ne", "Engine") and not gui.row_matches_filter("zzz", "Ne", "Engine")


def test_check_edit_rules():
    assert gui.check_edit("Ne", True, "", "1", "0") == (None, 1.0, 0.0)
    assert gui.check_edit("Ne", False, " x ", "2", "1") == ("x", 2.0, 1.0)
    assert gui.check_edit("Ne", False, "", "1", "0") == ("", 1.0, 0.0)  # 空の単位を明示するのは許す
    with pytest.raises(ValueError, match="explicitly"):
        gui.check_edit("Ne", True, "", "2", "0")  # 一次変換と生単位追従は両立しない
    for bad in ("0", "nan", "inf", "abc", ""):
        with pytest.raises(ValueError):
            gui.check_edit("Ne", False, "x", bad, "0")
    with pytest.raises(ValueError):
        gui.check_edit("Ne", False, "x", "1", "nan")


def test_apply_edit_updates_the_map_and_warns_about_silent_renames():
    data = json.loads(json.dumps(SEED))
    assert gui.apply_edit(data, "Ne", "x", "Engine", 2.0, 1.0) == []
    e = data["channels"]["Ne"]
    assert (e["unit"], e["custom_name"], e["multiplier"], e["offset"], e["raw_unit"]) == ("x", "Engine", 2.0, 1.0, "rpm")
    warns = gui.apply_edit(data, "Ne", "x", "a,b", 1.0, 0.0)  # カンマは変換時に置き換わる
    assert warns and "a,b" in warns[0]


def test_protected_rows_are_refused_in_the_gui_rules():
    assert all(map_rules.is_protected(n) for n in ("Latitude", "Longitude", "V_GPS")) and not map_rules.is_protected("Ne")


def test_convert_many_failure_does_not_stop_the_rest(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    good = ms.write(tmp_path / "good.MBD")
    bad = tmp_path / "bad.MBD"
    bad.write_bytes(b"not an mbd" * 1000)
    logs = []
    out = ac.convert_many([bad, good], tmp_path / "o", log=logs.append)
    assert [r.mes_name for r in out.results] == ["good"] and len(out.failed) == 1 and out.failed[0][2] == ac.EXIT_CORRUPT
    assert (tmp_path / "o" / "good.MES" / "good.DDD").is_file() and any("[ERROR] bad.MBD" in x for x in logs)
    assert "Converted 1 of 2" in ac.outcome_text(out, 2)


def test_convert_many_overwrite_confirmation(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    mbd = ms.write(tmp_path / "synth.MBD")
    ac.convert_many([mbd], tmp_path / "o")
    stamp = (tmp_path / "o" / "synth.MES" / "synth.DDD").read_bytes()
    declined = ac.convert_many([mbd], tmp_path / "o", confirm_overwrite=lambda *_: False)
    assert declined.declined == [mbd] and declined.results == [] and declined.failed == []
    assert (tmp_path / "o" / "synth.MES" / "synth.DDD").read_bytes() == stamp
    accepted = ac.convert_many([mbd], tmp_path / "o", confirm_overwrite=lambda *_: True)
    assert len(accepted.results) == 1
    plain = ac.convert_many([mbd], tmp_path / "o")  # 確認なし・force なし -> 既存を壊さず失敗
    assert len(plain.failed) == 1 and "already exists" in plain.failed[0][1]


def test_gui_and_cli_share_one_conversion_function():
    import inspect

    from mbd2mes import __main__ as cli
    assert "convert_many" in inspect.getsource(cli.main) and "convert_many" in inspect.getsource(gui.MbdGui._on_convert)
    assert "convert_one" in inspect.getsource(ac.convert_many)


def test_icon_path_points_at_the_source_of_truth():
    p = gui.resolve_icon_path()
    assert p == ROOT / "Pic" / "ICON" / "MBD2MES.ico" and p.is_file()


# ---------------------------------------------------------------- Tk の smoke（窓は出さない）
def _root():
    tk = pytest.importorskip("tkinter")
    last = None
    for _ in range(5):  # Tk の初期化が数回に 1 回「init.tcl が見つからない」で失敗する環境がある。数回やり直す
        try:
            root = tk.Tk()
            root.withdraw()  # 画面に窓を出さない
            return root
        except tk.TclError as exc:
            last = exc
            time.sleep(0.3)
    pytest.skip(f"Tk unavailable after 5 tries: {last}")


def test_gui_builds_and_loads_the_icon_at_startup(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    root = _root()
    try:
        app = gui.MbdGui(root)
        root.update_idletasks()
        assert root.title() == "MBD2MES v0.3.1 (dev)"
        assert app._apply_window_icon() is True  # 起動時にアイコンを読み込める（iconbitmap が通る）
        names = {app.tree.item(i, "values")[0] for i in app.tree.get_children()}
        assert names == set(SEED["channels"])  # 表に seed の行が出る
        app.filter_var.set("thp")
        assert {app.tree.item(i, "values")[0] for i in app.tree.get_children()} == {"THP"}
        # 保存: ファイルへ出て、再読み込みで戻る
        cm.update_entry(app.channel_map_data, "Ne", None, "Engine")
        map_rules.save_map_preserving_others(app.channel_map_data, app.deleted_rows)
        assert cm.load_or_init_map()["channels"]["Ne"]["custom_name"] == "Engine"
    finally:
        root.destroy()


def test_gui_icon_failure_does_not_stop_startup(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(gui, "resolve_icon_path", lambda: tmp_path / "missing.ico")
    root = _root()
    try:
        app = gui.MbdGui(root)
        assert app._apply_window_icon() is False
    finally:
        root.destroy()


def test_gui_convert_uses_the_loaded_map(tmp_path, monkeypatch):
    """GUI の Convert ボタンと同じ経路（self.channel_map_data を渡す）。メッセージ箱はスタブにする。"""
    fresh_settings(tmp_path, monkeypatch)
    root = _root()
    try:
        app = gui.MbdGui(root)
        mbd = ms.write(tmp_path / "synth.MBD")
        out = tmp_path / "out"
        out.mkdir()
        cfg_mod = gui.cfgmod
        cfg_mod.set_output_dir(out)
        cm.update_entry(app.channel_map_data, "THP", "x", None, multiplier=2.0, offset=1.0)
        app.selected_files.append(mbd)
        shown = []
        monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: shown.append(a))
        monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
        app._on_convert()
        app.wait_idle()  # 変換は別スレッド（FB02）。終わるまで画面の更新を回して待つ
        assert shown and "Converted 1 of 1" in shown[0][1]
        mes = mr.load_mes(out / "synth.MES")
        assert mes["THP"] == pytest.approx(ms.expected()["THP"] * 2 + 1, abs=0.003)
    finally:
        root.destroy()
