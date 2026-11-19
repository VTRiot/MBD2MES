# -*- coding: utf-8 -*-
"""docs/provenance.md の converter_progress の節（Skill の版を無改変で写した記録）と現物の照合（B19）。Skill が手元に無くても通る。"""

from __future__ import annotations

import hashlib
import re

from conftest import ROOT

DOC = ROOT / "docs" / "provenance.md"
PKG = ROOT / "mbd2mes" / "converter_progress"
ROW = re.compile(r"^\| `mbd2mes/converter_progress/([^`]+)` \| [^|]+ \| `([0-9a-f]{64})` \|$")
EXPECTED = {"__init__.py", "busy_animation.py", "jobs.py", "progress.py", "progress_dialog.py"}


def rows() -> dict:
    return {m.group(1): m.group(2) for m in (ROW.match(ln) for ln in DOC.read_text(encoding="utf-8").splitlines()) if m}


def test_every_copied_file_is_recorded_and_matches_the_recorded_sha256():
    got = rows()
    assert set(got) == EXPECTED and {p.name for p in PKG.glob("*.py")} == EXPECTED
    for name, sha in got.items():
        assert hashlib.sha256((PKG / name).read_bytes()).hexdigest() == sha, name


def test_the_old_self_made_modules_are_gone():
    for name in ("jobs.py", "progress_dialog.py", "busy_animation.py"):
        assert not (ROOT / "mbd2mes" / name).exists(), name
