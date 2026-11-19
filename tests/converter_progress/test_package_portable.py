# -*- coding: utf-8 -*-
"""パッケージを写して名前を変えても動くこと（中は相対 import だけ）・tk を import してはいけない部品が import していないこと。"""

from __future__ import annotations

import importlib
import shutil
import sys

import pytest
from .conftest import PACKAGE, PACKAGE_DIR

NO_TK_MODULES = ("progress.py", "jobs.py")  # 画面に依存しない部品（試験しやすさ・別スレッドの安全のため）


def test_the_package_works_under_another_name(tmp_path):
    other = "my_app_progress_xyz"
    shutil.copytree(PACKAGE_DIR, tmp_path / other, ignore=shutil.ignore_patterns("__pycache__"))
    sys.path.insert(0, str(tmp_path))
    try:
        prg = importlib.import_module(f"{other}.progress")
        dlg = importlib.import_module(f"{other}.progress_dialog")
        cfg = prg.ProgressConfig(("a", "b"), (0.25, 0.75))
        assert prg.overall(cfg, 1, 1, 2, 0.0) == pytest.approx(0.25)
        assert dlg.busy_animation.__name__ == f"{other}.busy_animation" and importlib.import_module(f"{other}.jobs").JobRunner
    finally:
        sys.path.remove(str(tmp_path))
        for name in [n for n in sys.modules if n == other or n.startswith(other + ".")]:
            del sys.modules[name]


def test_no_module_names_the_package_it_lives_in():
    # import の行だけを見る（短いパッケージ名が説明文の語に含まれても誤検出しない）
    for path in PACKAGE_DIR.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in ("import", "from"):
                head = parts[1]
                hard = head == PACKAGE or head.startswith(PACKAGE + ".") or head.split(".")[0] == PACKAGE.split(".")[-1]
                assert not hard, f"{path.name} hard-codes the package name: {line}"


def test_no_absolute_import_of_a_sibling_module():
    siblings = {"jobs", "progress", "progress_dialog", "busy_animation"}
    for path in PACKAGE_DIR.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in ("import", "from") and not parts[1].startswith("."):
                assert parts[1].split(".")[0] not in siblings, f"{path.name}: {line}"


@pytest.mark.parametrize("name", NO_TK_MODULES)
def test_progress_and_jobs_do_not_import_tk(name):
    text = (PACKAGE_DIR / name).read_text(encoding="utf-8")
    assert "import tkinter" not in text and "from tkinter" not in text


def test_no_app_specific_defaults_are_left():
    text = "\n".join(p.read_text(encoding="utf-8") for p in PACKAGE_DIR.glob("*.py"))
    assert "STEP_WEIGHTS" not in text and "STEP_LABELS" not in text  # 段の名前・重みの既定値を持たない
