# -*- coding: utf-8 -*-
"""docs/provenance.md の「アプリ部分の写し」の台帳と現物の照合。RCZ2MES が無くても通る（台帳の SHA-256 だけを使う）。"""

from __future__ import annotations

import hashlib
import re

from conftest import ROOT

DOC = ROOT / "docs" / "provenance.md"
ROW = re.compile(r"^\| `([^`]+)` \| `([^`]+)` \| `([0-9a-f]{7})` \| `([0-9a-f]{64})` \| 改変（手直し） \| `([0-9a-f]{64})` \| (.+) \|$")
EXPECTED = {
    "mbd2mes/channel_map.py", "mbd2mes/config.py", "mbd2mes/map_rules.py", "mbd2mes/gui.py", "mbd2mes/console_io.py",
    "mbd2mes/version.py", "mbd2mes/batch.py", "mbd2mes/race_env.py", "mbd2mes_app.py", "dist_build/mbd2mes.spec", "dist_build/build_exe.bat",
    "tools/write_build_info.py", "tools/check_exe_version.py", "mbd2mes_config.seed.json",
}


def rows():
    return [m.groups() for m in (ROW.match(ln) for ln in DOC.read_text(encoding="utf-8").splitlines()) if m]


def test_every_app_copy_is_listed_with_commit_and_blob():
    got = rows()
    assert {r[0] for r in got} == EXPECTED
    assert all(r[2] == "5b31da8" and r[1].startswith("C:\\_Prog\\ECU\\Logger\\RCZ2MES\\") for r in got)


def test_recorded_copy_sha256_matches_the_files():
    for path, _src, _commit, _blob, copy_sha, _note in rows():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == copy_sha, path


def test_the_copies_are_not_just_the_blob():
    """手直しの区分なので、写し先 = 元の blob ではない（無改変の写しをここに載せていない）。"""
    for path, _src, _c, blob, copy_sha, _n in rows():
        assert blob != copy_sha, path


def test_seed_generation_record_is_present():
    text = DOC.read_text(encoding="utf-8")
    assert "089d052133ccd87a9d9d525563ccf3be5955bb644b98c0c71174cd0031f9982f" in text
    assert hashlib.sha256((ROOT / "channel_map.seed.json").read_bytes()).hexdigest() in text
