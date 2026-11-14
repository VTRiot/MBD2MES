# -*- coding: utf-8 -*-
"""ビルドした exe の試験。環境変数 MBD2MES_EXE（dist\\mbd2mes.exe のパス）があるときだけ。窓は出さない（--version-file と CLI だけ）。

exe は一時フォルダへ写して動かす（dist\\ に設定を作らない）。設定・対応表が「exe の隣」にできることを見るため、
conftest が設定する MBD2MES_SETTINGS_DIR は子プロセスの環境から外す。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import map_synth as ms
import numpy as np
import pytest
from conftest import ROOT, SETTINGS_ENV, sample_path

from mbd2mes import mes_reader as mr

EXE = os.environ.get("MBD2MES_EXE")
pytestmark = pytest.mark.skipif(not EXE or not Path(EXE).is_file(), reason="set MBD2MES_EXE to dist\\mbd2mes.exe")
SEED = json.loads((ROOT / "channel_map.seed.json").read_text(encoding="utf-8"))
ICO = ROOT / "Pic" / "ICON" / "MBD2MES.ico"


def env_without_settings():
    env = dict(os.environ)
    env.pop(SETTINGS_ENV, None)
    return env


@pytest.fixture()
def exe_copy(tmp_path):
    d = tmp_path / "app"
    d.mkdir()
    shutil.copy2(EXE, d / "mbd2mes.exe")
    return d / "mbd2mes.exe"


def run(exe: Path, *args):
    return subprocess.run([str(exe), *map(str, args)], cwd=exe.parent, capture_output=True, text=True, env=env_without_settings(),
                          stdin=subprocess.DEVNULL, timeout=300)


def test_exe_version_matches_the_build_info(exe_copy):
    out = exe_copy.parent / "v.txt"
    assert run(exe_copy, "--version-file", out).returncode == 0
    text = out.read_text(encoding="utf-8").strip()
    assert text.startswith("MBD2MES v0.2.0 (") and ", built " in text and "(dev)" not in text


def test_exe_embedded_icon_equals_the_ico(exe_copy):
    """exe に埋まったアイコン（段の数・寸法・bit 数・画像のバイト列）が Pic\\ICON\\MBD2MES.ico と同じ。"""
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        import exe_icon
    finally:
        sys.path.pop(0)
    ok, text = exe_icon.compare(exe_copy, ICO)
    assert ok, text
    assert "7 sizes" in text


def test_exe_converts_and_map_lives_next_to_exe_and_persists(exe_copy, tmp_path):
    mbd = ms.write(tmp_path / "synth.MBD")
    r = run(exe_copy, mbd, "-o", tmp_path / "o1")
    assert r.returncode == 0, r.stderr
    app = exe_copy.parent
    assert (app / "channel_map.json").is_file()  # exe の隣
    assert json.loads((app / "channel_map.json").read_text(encoding="utf-8")) == SEED  # 初回は seed（exe に同梱）のまま
    # 利用者の編集（exe の隣の表）が、次の起動（再起動の代わり）で効く
    data = json.loads((app / "channel_map.json").read_text(encoding="utf-8"))
    data["channels"]["THP"].update({"unit": "x", "multiplier": 2.0, "offset": 1.0})
    (app / "channel_map.json").write_text(json.dumps(data), encoding="utf-8")
    assert run(exe_copy, mbd, "-o", tmp_path / "o2").returncode == 0
    mes = mr.load_mes(tmp_path / "o2" / "synth.MES")
    np.testing.assert_allclose(mes["THP"], ms.expected()["THP"] * 2 + 1, atol=0.003)
    again = json.loads((app / "channel_map.json").read_text(encoding="utf-8"))
    assert again["channels"]["THP"]["multiplier"] == 2.0  # exe は編集を消さない


def test_exe_without_o_and_without_config_is_usage_error(exe_copy, tmp_path):
    r = run(exe_copy, ms.write(tmp_path / "synth.MBD"))
    assert r.returncode == 2
    assert (exe_copy.parent / "mbd2mes_config.json").is_file()  # 設定も exe の隣にできる


@pytest.mark.skipif(sample_path() is None, reason="set MBD2MES_SAMPLE")
def test_exe_converts_the_sample_like_the_dev_cli(exe_copy, tmp_path):
    sample = sample_path()
    a = run(exe_copy, sample, "-o", tmp_path / "exe_out", "--date", "2026-11-08", "--no-map")
    assert a.returncode == 0, a.stderr
    b = subprocess.run([sys.executable, "-m", "mbd2mes", str(sample), "-o", str(tmp_path / "dev_out"), "--date", "2026-11-08", "--no-map"],
                       cwd=ROOT, capture_output=True, text=True)
    assert b.returncode == 0, b.stderr
    ea, eb = tmp_path / "exe_out", tmp_path / "dev_out"
    name = next(ea.glob("*.MES")).name
    fa = {p.name: p.read_bytes() for p in (ea / name).iterdir() if p.name != "MBD2MES_record.txt"}
    fb = {p.name: p.read_bytes() for p in (eb / name).iterdir() if p.name != "MBD2MES_record.txt"}
    assert fa == fb  # exe と開発の CLI で MES が 1 byte も違わない（記録ファイルは入力パスが違うので除く）
