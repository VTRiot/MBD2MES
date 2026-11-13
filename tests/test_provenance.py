# -*- coding: utf-8 -*-
"""docs/provenance.md の台帳と、写したファイルの照合。RCZ2MES が無くても通る（台帳の blob の SHA-256 だけを使う）。"""

from __future__ import annotations

import hashlib
import re

from conftest import ROOT

DOC = ROOT / "docs" / "provenance.md"
ROW = re.compile(r"^\| `(mbd2mes/[\w.]+)` \| `[^`]+` \| `[0-9a-f]{7}` \| `([0-9a-f]{64})` \| (無改変|改変) \| `([0-9a-f]{64})` \| (.*) \|$")


def _rows():
    return [m.groups() for m in (ROW.match(line) for line in DOC.read_text(encoding="utf-8").splitlines()) if m]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_table_lists_the_eight_copied_files():
    names = {r[0] for r in _rows()}
    assert names == {f"mbd2mes/{n}" for n in (
        "mes_reader.py", "mes_writer.py", "ddd_generator.py", "ddd_invariants.py",
        "gps_entries.py", "hed_download.py", "lap_files.py", "event_ini.py")}


def test_copies_match_the_recorded_sha256():
    for path, _blob, _kind, copy_sha, _note in _rows():
        assert _sha((ROOT / path).read_bytes()) == copy_sha, path


def test_unmodified_copies_equal_the_blob():
    for path, blob, kind, copy_sha, _note in _rows():
        if kind == "無改変":
            assert blob == copy_sha == _sha((ROOT / path).read_bytes()), path


def test_modified_copies_differ_only_in_import_lines():
    """改変の行は import 行だけ。`from . import X as Y` を `import X as Y` に戻すと、記録した blob の SHA-256 に戻る。"""
    for path, blob, kind, _copy, _note in _rows():
        if kind != "改変":
            continue
        text = (ROOT / path).read_text(encoding="utf-8")
        restored = re.sub(r"^from \. import (\w+ as \w+)$", r"import \1", text, flags=re.M)
        assert restored != text, path
        assert _sha(restored.encode("utf-8")) == blob, path
        assert b"\r\n" not in (ROOT / path).read_bytes(), path  # LF のまま
