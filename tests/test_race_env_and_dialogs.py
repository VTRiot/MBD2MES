# -*- coding: utf-8 -*-
"""FB01 の 2（今のイベントフォルダ = RACE.INI の候補と Use This）・3（Browse と Change の始まりのフォルダが別々）と、
FB01 の 1 の GUI の流れ（Convert Unconverted のボタン）。Tk の部品は窓を出さない（withdraw）。

RACE.INI の中身は、2D の実物の形（[ALL] Data_DRV・[START] EVENT・[DATADIR] 0=）で、この試験が手で組む（実物の設定は読まない）。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import map_synth as ms
import pytest
from conftest import fresh_settings

from mbd2mes import config as cfgmod
from mbd2mes import gui
from mbd2mes import race_env as renv

PAST_NS = 946684800 * 10**9  # 2000-01-01（どのファイルも起点より新しい）
TK_TRIES, TK_RETRY_WAIT_S = 5, 0.3  # Tk の初期化のやり直し（回数・待ち）
REAL_DETECT = renv.detect_output_dir  # 差し替える前の本物（試験が組んだ RACE.INI に当てる）


# ---------------------------------------------------------------- race_env（写しのままの判定）
def make_race(tmp: Path, *, year=2026, event="EV1", datadir0="@event", include_datadir=True, make_event=True, event_value=None):
    """<tmp>/ProgramData/Race<year>/RACE.INI と、Data_DRV の下のイベントフォルダを作る。(race_root, データの置き場, イベントのフォルダ)。"""
    pd = tmp / "ProgramData"
    root = pd / f"Race{year}"
    root.mkdir(parents=True)
    drv = tmp / "data"
    ev = drv / event
    if make_event:
        ev.mkdir(parents=True)
    lines = ["[ALL]", f"Data_DRV={drv}", "", "[START]", f"EVENT={event_value if event_value is not None else event}", ""]
    if include_datadir:
        d0 = str(ev) if datadir0 == "@event" else datadir0
        lines += ["[DATADIR]", f"0={d0}", ""]
    (root / "RACE.INI").write_text("\r\n".join(lines), encoding="cp1252")
    return root, drv, ev


def test_high_confidence_when_event_and_datadir_agree(tmp_path):
    root, _drv, ev = make_race(tmp_path)
    assert renv.detect_output_dir(root) == (ev, "high", "Data_DRV+EVENTとDATADIR 0=が一致・実在確認済み")


@pytest.mark.parametrize("kind, expect_reason", [
    ("no_datadir", "DATADIR 0=キー欠損"),
    ("other_event", "不一致"),
    ("outside", "配下外"),
])
def test_low_confidence_cases(tmp_path, kind, expect_reason):
    kw = {"no_datadir": {"include_datadir": False},
          "other_event": {"datadir0": str(tmp_path / "data" / "OTHER")},  # Data_DRV の配下だが、EVENT と別のフォルダ
          "outside": {"datadir0": str(tmp_path / "elsewhere" / "EV1")}}[kind]  # Data_DRV の配下ではない
    root, _drv, ev = make_race(tmp_path, **kw)
    path, confidence, reason = renv.detect_output_dir(root)
    assert path == ev and confidence == "low" and expect_reason in reason


@pytest.mark.parametrize("kw, expect_reason", [
    ({"make_event": False}, "実在しない"),
    ({"event_value": "C:/abs/EV1"}, "絶対パス"),
    ({"event_value": ""}, "空"),
])
def test_not_detected_cases(tmp_path, kw, expect_reason):
    root, _drv, _ev = make_race(tmp_path, **kw)
    path, confidence, reason = renv.detect_output_dir(root)
    assert path is None and confidence == "" and expect_reason in reason


def test_no_race_root_and_no_ini_are_not_detected(tmp_path):
    assert renv.detect_output_dir(tmp_path / "nowhere")[0] is None
    (tmp_path / "Race2026").mkdir()
    path, confidence, reason = renv.detect_output_dir(tmp_path / "Race2026")
    assert path is None and "RACE.INI" in reason


def test_find_race_root_picks_the_newest_year(tmp_path):
    for y in ("Race2024", "Race2026", "Race2025", "NotRace", "Race20xx"):
        (tmp_path / y).mkdir()
    assert renv.find_race_root(tmp_path).name == "Race2026"
    assert renv.find_race_root(tmp_path / "missing") is None


def test_detection_never_writes_the_ini(tmp_path):
    root, _drv, _ev = make_race(tmp_path)
    ini = root / "RACE.INI"
    before = (ini.read_bytes(), ini.stat().st_mtime_ns)
    renv.detect_output_dir(root)
    assert (ini.read_bytes(), ini.stat().st_mtime_ns) == before


# ---------------------------------------------------------------- GUI の道具
def _root():
    tk = pytest.importorskip("tkinter")
    last = None
    for _ in range(TK_TRIES):  # Tk の初期化が数回に 1 回「init.tcl が見つからない」で失敗する環境がある（原因は報告書）。数回やり直す
        try:
            root = tk.Tk()
            root.withdraw()  # 画面に窓を出さない
            return root
        except tk.TclError as exc:
            last = exc
            time.sleep(TK_RETRY_WAIT_S)
    pytest.skip(f"Tk unavailable after {TK_TRIES} tries: {last}")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    monkeypatch.setattr(gui.renv, "detect_output_dir", lambda *a, **k: (None, "", "stub"))  # 実物の ProgramData を読まない
    root = _root()
    yield gui.MbdGui(root)
    root.destroy()


# ---------------------------------------------------------------- FB01 の 3: 始まりのフォルダが別々
def test_dialog_start_dir_rules(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    assert gui.dialog_start_dir(lambda c: c["k"], {"k": d}) == str(d)
    assert gui.dialog_start_dir(lambda c: None, {}) is None  # 設定なし -> None（Windows の記憶に任せる）
    assert gui.dialog_start_dir(lambda c: c["k"], {"k": tmp_path / "gone"}) is None  # もう無い
    assert gui.dialog_start_dir(lambda c: c["k"], {"k": d / ("x" * 400)}) is None  # 例外にしない
    assert gui.dialog_start_dir(lambda c: (_ for _ in ()).throw(ValueError("x")), {}) is None


def test_browse_and_change_start_from_different_settings(app, tmp_path, monkeypatch):
    mbd_dir, out_dir, picked, new_out = (tmp_path / n for n in ("mbd_dir", "out_dir", "picked", "new_out"))
    for p in (mbd_dir, out_dir, picked, new_out):
        p.mkdir()
    cfgmod.set_last_mbd_dir(mbd_dir)
    cfgmod.set_output_dir(out_dir)
    seen = {}
    answers = {"files": (), "dir": ""}

    def fake_open(**kw):
        seen["browse"] = kw.get("initialdir")
        return answers["files"]

    def fake_dir(**kw):
        seen["change"] = kw.get("initialdir")
        return answers["dir"]

    monkeypatch.setattr(gui.filedialog, "askopenfilenames", fake_open)
    monkeypatch.setattr(gui.filedialog, "askdirectory", fake_dir)
    # 取り消しても、それぞれ自分の設定から始まる（もう片方の設定ではない）
    app._on_browse()
    app._on_change_output_dir()
    assert seen == {"browse": str(mbd_dir), "change": str(out_dir)}
    # Browse で別のフォルダの .MBD を選ぶ -> Change の始まりは動かない（連動しない）
    f = ms.write(picked / "x.MBD")
    answers["files"] = (str(f),)
    app._on_browse()
    app._on_change_output_dir()
    assert seen["change"] == str(out_dir) and cfgmod.get_last_mbd_dir(cfgmod.load_or_init_config()) == picked.resolve()
    # Change で出力先を替える -> 次の Browse の始まりは動かない
    answers["dir"] = str(new_out)
    app._on_change_output_dir()
    app._on_browse()
    assert seen["browse"] == str(picked.resolve()) and cfgmod.get_output_dir(cfgmod.load_or_init_config()) == new_out
    assert app.output_dir_var.get() == str(new_out)
    app._on_change_output_dir()
    assert seen["change"] == str(new_out)  # Change は今の出力先から


def test_dialogs_get_no_start_dir_when_nothing_is_set_or_the_folder_is_gone(app, tmp_path, monkeypatch):
    seen = {}
    def fake_open(**kw):
        seen["browse"] = kw.get("initialdir", "absent")
        return ()

    def fake_dir(**kw):
        seen["change"] = kw.get("initialdir", "absent")
        return ""

    monkeypatch.setattr(gui.filedialog, "askopenfilenames", fake_open)
    monkeypatch.setattr(gui.filedialog, "askdirectory", fake_dir)
    app._on_browse()
    app._on_change_output_dir()
    assert seen == {"browse": None, "change": None}  # None は Tk へ送られない = 渡さないのと同じ
    gone = tmp_path / "gone"
    gone.mkdir()
    cfgmod.set_output_dir(gone)
    gone.rmdir()
    seen.clear()
    app._on_change_output_dir()
    assert seen == {"change": None}


# ---------------------------------------------------------------- FB01 の 2: 今のイベントフォルダを出力先に
def test_use_this_sets_the_output_dir_from_the_detected_candidate(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    root_dir, _drv, ev = make_race(tmp_path)
    monkeypatch.setattr(gui.renv, "detect_output_dir", lambda *a, **k: REAL_DETECT(root_dir))
    root = _root()
    try:
        app = gui.MbdGui(root)
        assert "Detected candidate (confidence=high)" in app.candidate_var.get() and str(ev) in app.candidate_var.get()
        assert str(app.use_candidate_button.cget("state")) == "normal"
        assert app.output_dir_var.get() == "(Not set)"  # 候補が出ても、押すまで出力先は変わらない
        app._on_use_candidate()
        assert app.output_dir_var.get() == str(ev) and cfgmod.get_output_dir(cfgmod.load_or_init_config()) == ev
    finally:
        root.destroy()


def test_not_detected_disables_use_this_and_reload_picks_up_a_new_event(app, tmp_path, monkeypatch):
    assert "Not detected" in app.candidate_var.get() and str(app.use_candidate_button.cget("state")) == "disabled"
    root_dir, _drv, ev = make_race(tmp_path)
    monkeypatch.setattr(gui.renv, "detect_output_dir", lambda *a, **k: REAL_DETECT(root_dir))
    app._on_reload_candidate()  # 2D でイベントを替えたあと Reload
    assert str(app.use_candidate_button.cget("state")) == "normal" and app._candidate == ev
    monkeypatch.setattr(gui.renv, "detect_output_dir", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    app._on_reload_candidate()  # 読み直しの失敗で GUI を落とさない
    assert "Not detected" in app.candidate_var.get() and app._candidate is None


# ---------------------------------------------------------------- FB01 の 1: Convert Unconverted のボタンの流れ
def stub_boxes(monkeypatch, yes=True):
    shown = {"info": [], "warn": [], "error": [], "asked": []}
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: shown["info"].append(a))
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: shown["warn"].append(a))
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: shown["error"].append(a))
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: shown["asked"].append(a) or yes)
    return shown


def test_the_batch_button_and_the_convert_all_check_exist(app):
    assert str(app.convert_unconverted_button.cget("text")) == "Convert Unconverted"
    assert str(app.convert_all_check.cget("text")) == "Convert all .MBD files" and app.convert_all_var.get() is False


def test_batch_button_guides_when_output_or_source_is_missing(app, tmp_path, monkeypatch):
    shown = stub_boxes(monkeypatch)
    app._on_convert_unconverted()
    assert shown["warn"] and "Output directory is not set" in shown["warn"][0][1]
    out = tmp_path / "out"
    out.mkdir()
    cfgmod.set_output_dir(out)
    app._on_convert_unconverted()
    assert shown["info"] and "Source directory is not set" in shown["info"][0][1]


def test_first_press_records_the_checkpoint_and_converts_nothing_like_ld2mes(app, tmp_path, monkeypatch):
    """起点が無い初回（「全部変換」オフ）は、起点だけ記録して変換しない。画面（LD2MES の文言）とログで分かる。"""
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    ms.write(src / "old1.MBD", course="old1")
    ms.write(src / "old2.MBD", course="old2")
    cfgmod.set_output_dir(out)
    cfgmod.set_last_mbd_dir(src)
    shown = stub_boxes(monkeypatch, yes=True)
    assert cfgmod.get_batch_checkpoint(src) is None
    app._on_convert_unconverted()
    assert shown["asked"] == [] and list(out.iterdir()) == []  # 確認の画面は出ず、何も変換していない
    title, text = shown["info"][-1][0], shown["info"][-1][1]
    assert title == "MBD2MES - Checkpoint Recorded"
    assert text == ("Baseline checkpoint recorded for this directory.\n\n"
                    "Only newer .MBD files added or modified after this will be converted on subsequent runs.\n"
                    "To convert all existing files, check 'Convert all .MBD files' or use the Convert button.")
    log = app.log_text.get("1.0", "end")
    assert "Baseline checkpoint recorded for" in log and "Nothing was converted this time" in log and str(src) in log
    cp_ = cfgmod.get_batch_checkpoint(src)
    assert cp_ is not None and cp_["failed_files"] == []
    # 2 回目: 既存の物は起点より古いので候補にならない（確認の画面は出ない）。起点は動かない
    app._on_convert_unconverted()
    assert shown["asked"] == [] and "Nothing to convert" in shown["info"][-1][1] and "Older than the checkpoint (not converted by this button): 2" in shown["info"][-1][1]
    assert cfgmod.get_batch_checkpoint(src) == cp_ and list(out.iterdir()) == []


def test_after_the_first_press_only_files_that_arrive_later_are_candidates(app, tmp_path, monkeypatch):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    ms.write(src / "old.MBD", course="old")
    cfgmod.set_output_dir(out)
    cfgmod.set_last_mbd_dir(src)
    shown = stub_boxes(monkeypatch, yes=True)
    app._on_convert_unconverted()  # 初回: 起点だけ
    time.sleep(0.05)
    ms.write(src / "new1.MBD", course="new1")  # 起点より後に届いた
    ms.write(src / "new2.MBD", course="new2")
    app._on_convert_unconverted()
    confirm = shown["asked"][0][1]
    assert "Found 2 .MBD file(s) to convert" in confirm and "new1.MBD" in confirm and "new2.MBD" in confirm
    assert "old.MBD" not in confirm.split("Target files:")[1].split("Recording date")[0]
    assert sorted(p.name for p in out.glob("*.MES")) == ["new1.MES", "new2.MES"]  # 古い物は変換しない
    assert "Successfully converted: 2" in shown["info"][-1][1] and "Skipped (older than the checkpoint): 1" in shown["info"][-1][1]
    assert app.selected_files == []
    # 3 回目: もう何も無い
    app._on_convert_unconverted()
    assert len(shown["asked"]) == 1 and "Nothing to convert" in shown["info"][-1][1]


def test_first_press_with_convert_all_checked_converts_everything_and_records_the_checkpoint(app, tmp_path, monkeypatch):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    ms.write(src / "a.MBD", course="a")
    ms.write(src / "b.MBD", course="b")
    cfgmod.set_output_dir(out)
    cfgmod.set_last_mbd_dir(src)
    shown = stub_boxes(monkeypatch, yes=True)
    app.convert_all_var.set(True)
    app._on_convert_unconverted()
    assert sorted(p.name for p in out.glob("*.MES")) == ["a.MES", "b.MES"]
    assert cfgmod.get_batch_checkpoint(src) is not None and app.convert_all_var.get() is False


def test_batch_button_mixed_folder_confirm_shows_only_unconverted_and_the_dates(app, tmp_path, monkeypatch):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    done = ms.write(src / "done.MBD", course="done")
    (src / "readme.txt").write_text("x")
    from mbd2mes import app_convert as ac
    ac.convert_many([done], out, channel_map_data=None)  # 変換済みは素の変換で作る（走査の判定を通さない）
    cfgmod.set_output_dir(out)
    cfgmod.set_last_mbd_dir(src)
    cfgmod.set_batch_checkpoint(src, time.time_ns(), [])  # 起点: done は起点より前
    time.sleep(0.05)
    ms.write(src / "26.11.8todo1.MBD", course="todo1")  # 起点より後に届いた 2 本
    ms.write(src / "todo2.MBD", course="todo2")
    shown = stub_boxes(monkeypatch, yes=True)
    app._on_convert_unconverted()
    confirm = shown["asked"][0][1]
    targets = confirm.split("Target files:")[1].split("Recording date")[0]
    assert "Found 2 .MBD file(s) to convert" in confirm and "done.MBD" not in targets
    assert "26.11.8todo1.MBD" in targets and "todo2.MBD" in targets
    dates_part = confirm.split("Recording date (HED) and where it comes from:")[1].split("Skipped")[0]
    assert "26.11.8todo1.MBD: 2026-11-08 (file name)" in dates_part  # 手で書いた期待値: 名前の 26.11.8 = 2026-11-08
    assert "todo2.MBD: from the file modification time -- CHECK" in dates_part
    assert "WARNING: 1 file(s) have no date in the name" in confirm
    hed = (out / "26-11-8todo1.MES" / "26-11-8todo1.HED").read_text(encoding="cp1252")
    assert "Start of download=08.11.2026 09:56:43" in hed  # 合成の GPS の UTC 00:56:43 + 9 時間
    assert "[INFO] recording date: 26.11.8todo1.MBD: 2026-11-08 (file name)" in app.log_text.get("1.0", "end")


def test_batch_button_no_to_the_confirmation_writes_nothing(app, tmp_path, monkeypatch):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    ms.write(src / "a.MBD", course="a")
    cfgmod.set_output_dir(out)
    cfgmod.set_last_mbd_dir(src)
    cfgmod.set_batch_checkpoint(src, PAST_NS, [])
    before = cfgmod.get_batch_checkpoint(src)
    shown = stub_boxes(monkeypatch, yes=False)
    app._on_convert_unconverted()
    assert shown["asked"] and list(out.iterdir()) == [] and cfgmod.get_batch_checkpoint(src) == before
    assert app.convert_all_var.get() is False


def test_convert_all_overwrites_and_the_check_is_reset(app, tmp_path, monkeypatch):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    a = ms.write(src / "a.MBD", course="a")
    from mbd2mes import app_convert as ac
    ac.convert_many([a], out, channel_map_data=None)
    cfgmod.set_output_dir(out)
    cfgmod.set_last_mbd_dir(src)
    cfgmod.set_batch_checkpoint(src, time.time_ns() + 3600 * 10**9, [])  # どれも起点より古い
    shown = stub_boxes(monkeypatch, yes=True)
    app._on_convert_unconverted()
    assert "Nothing to convert" in shown["info"][-1][1]  # 古い・済み -> 何もしない
    app.convert_all_var.set(True)
    app._on_convert_unconverted()
    assert "OVERWRITTEN" in shown["asked"][-1][1] and "a.MBD (overwrites existing MES)" in shown["asked"][-1][1]
    assert app.convert_all_var.get() is False


def test_an_unexpected_exception_is_logged_shown_and_resets_the_check(app, tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    src = tmp_path / "src"
    src.mkdir()
    cfgmod.set_output_dir(out)
    cfgmod.set_last_mbd_dir(src)
    shown = stub_boxes(monkeypatch)
    monkeypatch.setattr(gui.batch, "scan_mbd_directory", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    app.convert_all_var.set(True)
    app._on_convert_unconverted()
    assert shown["error"] and "boom" in shown["error"][0][1] and app.convert_all_var.get() is False
    assert "boom" in app.log_text.get("1.0", "end")


def test_gui_imports_batch_at_the_top_so_the_exe_build_finds_it():
    import ast

    tree = ast.parse(Path(gui.__file__).read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, ast.ImportFrom)]
    assert any(any(a.name == "batch" for a in n.names) for n in top)  # PyInstaller が静的に辿れる位置
    assert any(any(a.name == "race_env" for a in n.names) for n in top)
    assert os.path.basename(gui.__file__) == "gui.py"


# ---------------------------------------------------------------- Codex FB01 [1]: % と読めないバイトで検出が止まらない
def test_percent_in_a_value_does_not_break_detection(tmp_path):
    drv = tmp_path / "100%data"
    ev = drv / "EV1"
    ev.mkdir(parents=True)
    root = tmp_path / "PD" / "Race2026"
    root.mkdir(parents=True)
    (root / "RACE.INI").write_text(f"[ALL]\r\nData_DRV={drv}\r\n\r\n[START]\r\nEVENT=EV1\r\n\r\n[DATADIR]\r\n0={ev}\r\n", encoding="cp1252")
    assert renv.detect_output_dir(root) == (ev, "high", "Data_DRV+EVENTとDATADIR 0=が一致・実在確認済み")


def test_bytes_cp1252_cannot_decode_are_not_detected_with_a_reason_not_an_exception(tmp_path):
    root = tmp_path / "PD" / "Race2026"
    root.mkdir(parents=True)
    (root / "RACE.INI").write_bytes(b"[ALL]\r\nData_DRV=C:\data\r\n[START]\r\nEVENT=\x81\x5b\r\n")  # cp932 の「ー」: 0x81 は cp1252 で読めない
    path, confidence, reason = renv.detect_output_dir(root)
    assert path is None and confidence == "" and "RACE.INI" in reason
