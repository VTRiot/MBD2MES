# -*- coding: utf-8 -*-
"""CLI（python -m mbd2mes）: 今までの呼び方は同じ結果、表と設定の使い方（Plan §2-4）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import map_synth as ms
import numpy as np
from conftest import ROOT, SETTINGS_ENV, fresh_settings

from mbd2mes import channel_map as cm
from mbd2mes import mes_reader as mr

SEED = json.loads((ROOT / "channel_map.seed.json").read_text(encoding="utf-8"))


def run(args, settings: Path):
    env = dict(os.environ)
    env[SETTINGS_ENV] = str(settings)
    return subprocess.run([sys.executable, "-m", "mbd2mes", *map(str, args)], cwd=ROOT, capture_output=True, text=True, env=env)


def tree_bytes(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def edited_map(settings: Path):
    data = json.loads(json.dumps(SEED))
    data["channels"]["THP"].update({"unit": "x", "multiplier": 2.0, "offset": 1.0})
    (settings / "channel_map.json").write_text(json.dumps(data), encoding="utf-8")


def test_dash_o_with_seed_map_matches_no_map(tmp_path, monkeypatch):
    """表が seed のままなら、-o 付きの呼び方は --no-map（対応表の前と同じ結果）と 1 byte も違わない。"""
    s = fresh_settings(tmp_path, monkeypatch)
    mbd = ms.write(tmp_path / "synth.MBD")
    a = run([mbd, "-o", tmp_path / "a", "--date", "2026-11-08"], s)
    b = run([mbd, "-o", tmp_path / "b", "--date", "2026-11-08", "--no-map"], s)
    assert a.returncode == 0 and b.returncode == 0, a.stderr + b.stderr
    assert tree_bytes(tmp_path / "a" / "synth.MES") == tree_bytes(tmp_path / "b" / "synth.MES")


def test_edited_map_changes_output_and_no_map_ignores_it(tmp_path, monkeypatch):
    s = fresh_settings(tmp_path, monkeypatch)
    edited_map(s)
    mbd = ms.write(tmp_path / "synth.MBD")
    assert run([mbd, "-o", tmp_path / "a"], s).returncode == 0
    assert run([mbd, "-o", tmp_path / "b", "--no-map"], s).returncode == 0
    thp_map = mr.load_mes(tmp_path / "a" / "synth.MES")["THP"]
    thp_plain = mr.load_mes(tmp_path / "b" / "synth.MES")["THP"]
    np.testing.assert_allclose(thp_map, ms.expected()["THP"] * 2 + 1, atol=0.003)  # 手計算
    np.testing.assert_allclose(thp_plain, ms.expected()["THP"], atol=0.003)


def test_without_o_uses_config_output_dir(tmp_path, monkeypatch):
    s = fresh_settings(tmp_path, monkeypatch)
    out = tmp_path / "from_config"
    out.mkdir()
    (s / "mbd2mes_config.json").write_text(json.dumps({"schema": 1, "output_dir": str(out), "last_mbd_dir": None}), encoding="utf-8")
    mbd = ms.write(tmp_path / "synth.MBD")
    r = run([mbd], s)
    assert r.returncode == 0, r.stderr
    assert (out / "synth.MES" / "synth.DDD").is_file()


def test_without_o_and_no_config_is_usage_error(tmp_path, monkeypatch):
    s = fresh_settings(tmp_path, monkeypatch)
    mbd = ms.write(tmp_path / "synth.MBD")
    r = run([mbd], s)
    assert r.returncode == 2 and "-o/--out is required" in r.stderr


def test_without_o_when_config_output_dir_is_gone_is_usage_error(tmp_path, monkeypatch):
    s = fresh_settings(tmp_path, monkeypatch)
    (s / "mbd2mes_config.json").write_text(
        json.dumps({"schema": 1, "output_dir": str(tmp_path / "missing"), "last_mbd_dir": None}), encoding="utf-8")
    r = run([ms.write(tmp_path / "synth.MBD")], s)
    assert r.returncode == 2


def test_module_main_without_args_is_usage_error(tmp_path, monkeypatch):
    s = fresh_settings(tmp_path, monkeypatch)
    r = run([], s)
    assert r.returncode == 2 and "no input" in r.stderr  # 従来どおり。GUI は mbd2mes_app.py／exe だけが開く


def test_cli_grows_the_map_file_and_version(tmp_path, monkeypatch):
    s = fresh_settings(tmp_path, monkeypatch)
    mbd = ms.write(tmp_path / "synth.MBD")
    assert run([mbd, "-o", tmp_path / "o"], s).returncode == 0
    assert set(json.loads((s / "channel_map.json").read_text(encoding="utf-8"))["channels"]) == set(SEED["channels"])
    r = run(["--version"], s)
    assert r.returncode == 0 and r.stdout.strip() == "MBD2MES v0.3.0 (dev)"
    f = tmp_path / "v.txt"
    assert run(["--version-file", f], s).returncode == 0 and f.read_text(encoding="utf-8").strip() == r.stdout.strip()
    assert cm.seed_path().is_file()
