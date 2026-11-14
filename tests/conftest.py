# -*- coding: utf-8 -*-
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# 設定・対応表の置き場を一時フォルダへ替える（mbd2mes を import する前に。環境変数なので subprocess の CLI・exe の試験にも効く）。
# 利用者の実際の設定・リポ直下の実ファイルには触れない（tests/test_isolation.py が確かめる）
SETTINGS_ENV = "MBD2MES_SETTINGS_DIR"  # mbd2mes.config.SETTINGS_ENV と同じでなければならない（test_isolation が照合）
_TMP_SETTINGS = tempfile.mkdtemp(prefix="mbd2mes_test_settings_")
os.environ[SETTINGS_ENV] = _TMP_SETTINGS
atexit.register(lambda: shutil.rmtree(_TMP_SETTINGS, ignore_errors=True))


def fresh_settings(tmp_path, monkeypatch):
    """試験ごとの空の設定フォルダ（環境変数を替える）。置いた Path を返す。"""
    d = tmp_path / "settings"
    d.mkdir()
    monkeypatch.setenv(SETTINGS_ENV, str(d))
    return d


# 実データの標本（リポに入れない）。環境変数 MBD2MES_SAMPLE にパスを渡す。無ければ該当の試験は skip
SAMPLE_ENV = "MBD2MES_SAMPLE"


def sample_path():
    v = os.environ.get(SAMPLE_ENV)
    return Path(v) if v and Path(v).is_file() else None
