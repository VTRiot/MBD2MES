# -*- coding: utf-8 -*-
"""記録の日付の決め方（FB01 の 4・案 C）。期待値は、名前ごとに手で書いた日付（変換器・読み取りの関数を通さない）。

優先: 明示の指定（CLI の --date・GUI の欄）> ファイル名 > ファイルの更新時刻（警告）。基準の名前は標本の `26.11.8…`（YY.M.D）。
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

import map_synth as ms
import pytest
from conftest import ROOT, SETTINGS_ENV, fresh_settings

from mbd2mes import app_convert as ac
from mbd2mes import convert as cv
from mbd2mes import dates

D = datetime.date

# (ファイル名, 手で書いた期待値)。None = 名前から読めない（更新時刻へ落とす）
NAMES = [
    ("26.11.8鈴鹿サンデーR4決勝.MBD", D(2026, 11, 8)),  # 標本そのもの（基準）
    ("26.11.08x.MBD", D(2026, 11, 8)),
    ("26.1.5.MBD", D(2026, 1, 5)),
    ("26-11-8.MBD", D(2026, 11, 8)),
    ("26_11_8_run.MBD", D(2026, 11, 8)),
    ("race 26.11.8 final.MBD", D(2026, 11, 8)),
    ("2026-11-08.MBD", D(2026, 11, 8)),
    ("2026.11.8_A.MBD", D(2026, 11, 8)),
    ("2026_1_2.MBD", D(2026, 1, 2)),
    ("20261108.MBD", D(2026, 11, 8)),
    ("run_20261108_1.MBD", D(2026, 11, 8)),
    ("25.12.31.MBD", D(2025, 12, 31)),
    # 読めない（更新時刻へ）
    ("test.MBD", None),
    ("synth.MBD", None),
    ("11081530.MBD", None),  # MBDA2 の元の名前（月日時分。年が無い）。20261108 と取り違えない
    ("26.13.8.MBD", None),  # 月が成り立たない
    ("26.2.30.MBD", None),  # 日が成り立たない
    ("99.11.8.MBD", None),  # 99 = 2099 は範囲内だが、日付としては成り立つので別に扱う（下の表）
    ("1999-11-08.MBD", None),  # 年が範囲外
    ("v10.20.30.MBD", None),  # バージョン番号のような並び（20 月は無い）
    ("12345678.MBD", None),
    ("FWv26.11.8.MBD", None),  # 識別子の中の数列（Codex FB01 [1]）。英数字の直後は日付の始まりにしない
    ("build2026-11-08.MBD", None),
    ("abc20261108.MBD", None),
    ("決勝26.11.8.MBD", D(2026, 11, 8)),  # 日本語の直後は読む（提供者の名前の付け方）
    ("x_26.11.8.MBD", D(2026, 11, 8)),  # アンダースコアは区切り
    ("", None),
]


@pytest.mark.parametrize("name, expected", [r for r in NAMES if r[0] != "99.11.8.MBD"], ids=lambda v: str(v)[:30])
def test_names_are_read_like_the_hand_written_table(name, expected):
    assert dates.parse_date_from_name(name) == expected


def test_a_two_digit_year_is_read_as_20yy():
    assert dates.parse_date_from_name("99.11.8.MBD") == D(2099, 11, 8)


def test_the_first_valid_date_in_the_name_wins_and_invalid_ones_are_skipped():
    assert dates.parse_date_from_name("99.99.99_26.11.8.MBD") == D(2026, 11, 8)  # 先の並びは日付として成り立たない
    assert dates.parse_date_from_name("2026-11-08_26.1.1.MBD") == D(2026, 11, 8)  # 4 桁の年の型が先


def test_choose_priority_override_then_name_then_modification_time(tmp_path):
    p = tmp_path / "26.11.8x.MBD"
    named = dates.choose(p)
    assert (named.date, named.source, named.warning) == (D(2026, 11, 8), "file name", None)
    given = dates.choose(p, D(2026, 3, 4), "--date")
    assert (given.date, given.source) == (D(2026, 3, 4), "--date")  # 明示の指定が最優先（名前に日付があっても）
    field = dates.choose(p, D(2026, 3, 4), "date field")
    assert field.source == "date field" and field.describe() == "2026-03-04 (date field)"
    none = dates.choose(tmp_path / "nodate.MBD")
    assert none.date is None and none.source == "file modification time" and "[WARN] nodate.MBD" in none.warning
    assert "CHECK" in none.describe()


def test_date_field_text():
    assert dates.parse_date_text("") is None and dates.parse_date_text("  ") is None
    assert dates.parse_date_text(" 2026-11-08 ") == D(2026, 11, 8)
    for bad in ("2026/11/08", "11-08", "abc", "2026-13-01"):
        with pytest.raises(ValueError):
            dates.parse_date_text(bad)


# ---------------------------------------------------------------- 変換へ届く（手で書いた期待値: 合成の GPS の UTC 00:56:43 + 9 時間 = 09:56:43）
def hed(res) -> str:
    return (res.mes_dir / f"{res.mes_name}.HED").read_text(encoding="cp1252")


def test_convert_many_reads_the_name_per_file_and_logs_each_date(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    a = ms.write(tmp_path / "26.11.8a.MBD", course="a")
    b = ms.write(tmp_path / "2026-10-04_b.MBD", course="b")
    logs = []
    out = ac.convert_many([a, b], tmp_path / "o", channel_map_data=None, log=logs.append)
    assert not out.failed
    assert "Start of download=08.11.2026 09:56:43" in hed(out.results[0]) and "Start of download=04.10.2026 09:56:43" in hed(out.results[1])
    assert "[INFO] 26.11.8a.MBD: recording date 2026-11-08 (file name)" in logs
    assert "[INFO] 2026-10-04_b.MBD: recording date 2026-10-04 (file name)" in logs
    assert "date source: file name 2026-11-08 (local) + GPS time of day" in out.results[0].record_text
    assert not any(w.startswith("[WARN]") and "recording date" in w for r in out.results for w in r.warnings)  # 名前から読めたので警告なし


def test_explicit_date_beats_the_name_for_every_file(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    a = ms.write(tmp_path / "26.11.8a.MBD", course="a")
    b = ms.write(tmp_path / "plain.MBD", course="b")
    out = ac.convert_many([a, b], tmp_path / "o", channel_map_data=None, date=D(2026, 3, 4), date_label="date field")
    for r in out.results:
        assert "Start of download=04.03.2026 09:56:43" in hed(r) and "date field 2026-03-04 (local)" in r.record_text


def test_no_date_in_the_name_falls_back_to_the_modification_time_and_warns(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    p = ms.write(tmp_path / "plain.MBD", course="p")
    stamp = datetime.datetime(2026, 11, 13, 19, 8, 21).timestamp()  # 受け取った日（レースの日ではない）
    os.utime(p, (stamp, stamp))
    logs = []
    out = ac.convert_many([p], tmp_path / "o", channel_map_data=None, log=logs.append)
    res = out.results[0]
    assert "Start of download=13.11.2026 09:56:43" in hed(res)  # 今までどおり更新時刻の日
    assert any(w.startswith("[WARN] plain.MBD: the recording date is not in the MBD file or its name") for w in res.warnings)
    assert any("[WARN] plain.MBD" in x for x in logs) and "file modification time" in res.record_text
    assert "Warnings: 1" in res.record_text or "Warnings:" in res.record_text


def test_convert_one_without_a_date_warns_even_when_called_directly(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    res = cv.convert_one(ms.write(tmp_path / "x.MBD"), tmp_path / "o")
    assert any("recording date is not in the MBD file" in w for w in res.warnings)
    res2 = cv.convert_one(ms.write(tmp_path / "y.MBD"), tmp_path / "o", date=D(2026, 11, 8))
    assert not any("recording date" in w for w in res2.warnings)  # 日付を渡せば警告は出ない


# ---------------------------------------------------------------- CLI: --date は今までどおり最優先
def run_cli(args, settings: Path):
    env = dict(os.environ)
    env[SETTINGS_ENV] = str(settings)
    return subprocess.run([sys.executable, "-m", "mbd2mes", *map(str, args)], cwd=ROOT, capture_output=True, text=True, env=env)


def test_cli_date_option_beats_the_name_and_default_reads_the_name(tmp_path, monkeypatch):
    s = fresh_settings(tmp_path, monkeypatch)
    f = ms.write(tmp_path / "26.11.8cli.MBD", course="cli")
    r1 = run_cli([f, "-o", tmp_path / "o1", "--date", "2026-03-04"], s)
    r2 = run_cli([f, "-o", tmp_path / "o2"], s)
    assert r1.returncode == 0 and r2.returncode == 0, r1.stderr + r2.stderr
    assert "Start of download=04.03.2026 09:56:43" in (tmp_path / "o1" / "26-11-8cli.MES" / "26-11-8cli.HED").read_text(encoding="cp1252")
    assert "Start of download=08.11.2026 09:56:43" in (tmp_path / "o2" / "26-11-8cli.MES" / "26-11-8cli.HED").read_text(encoding="cp1252")
    assert "recording date 2026-03-04 (--date)" in r1.stdout and "recording date 2026-11-08 (file name)" in r2.stdout


def test_cli_without_a_date_in_the_name_warns_on_the_output(tmp_path, monkeypatch):
    s = fresh_settings(tmp_path, monkeypatch)
    r = run_cli([ms.write(tmp_path / "plain.MBD", course="pl"), "-o", tmp_path / "o"], s)
    assert r.returncode == 0 and "[WARN] plain.MBD: the recording date is not in the MBD file or its name" in r.stdout


# ---------------------------------------------------------------- GUI の欄
def _gui_app(tmp_path, monkeypatch):
    import time

    import pytest as _pytest

    tk = _pytest.importorskip("tkinter")
    from mbd2mes import gui

    monkeypatch.setattr(gui.renv, "detect_output_dir", lambda *a, **k: (None, "", "stub"))
    last = None
    for _ in range(5):
        try:
            root = tk.Tk()
            root.withdraw()
            return gui, root, gui.MbdGui(root)
        except tk.TclError as exc:
            last = exc
            time.sleep(0.3)
    _pytest.skip(f"Tk unavailable: {last}")


def test_gui_date_field_is_used_by_convert_and_an_invalid_date_stops_before_converting(tmp_path, monkeypatch):
    fresh_settings(tmp_path, monkeypatch)
    gui, root, app = _gui_app(tmp_path, monkeypatch)
    try:
        out = tmp_path / "out"
        out.mkdir()
        f = ms.write(tmp_path / "26.11.8g.MBD", course="g")
        from mbd2mes import config as cfgmod

        cfgmod.set_output_dir(out)
        app.selected_files.append(f)
        warned, infos = [], []
        monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: warned.append(a))
        monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: infos.append(a))
        monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
        app.date_var.set("2026-13-45")
        app._on_convert()
        assert warned and "YYYY-MM-DD" in warned[0][1] and list(out.iterdir()) == []  # 何も変換しない
        app.date_var.set("2026-03-04")
        app._on_convert()
        assert "Start of download=04.03.2026 09:56:43" in (out / "26-11-8g.MES" / "26-11-8g.HED").read_text(encoding="cp1252")
        app.date_var.set("")  # 空 = 名前から（再変換。同名の MES があるので上書きの確認は Yes）
        app._on_convert()
        assert "Start of download=08.11.2026 09:56:43" in (out / "26-11-8g.MES" / "26-11-8g.HED").read_text(encoding="cp1252")
        log = app.log_text.get("1.0", "end")
        assert "recording date 2026-03-04 (date field)" in log and "recording date 2026-11-08 (file name)" in log
    finally:
        root.destroy()
