# -*- coding: utf-8 -*-
"""tools/write_build_info.py -- exe を作る直前に、版の生成物 `dist_build/_gen/_build_info.py` を書く。

RCZ2MES の tools/write_build_info.py（commit 5b31da8。元は LD2MES）からの写し。改変は DIRTY_PATHSPECS（MBD2MES の spec に合わせた）と説明だけ。
git の呼び方は、状態を変えない読むだけの形（log・diff・ls-files。`git status` は使わない決まり）:
    COMMIT: `git log -1 --abbrev=7 --format=%h`
    DIRTY : `git diff --name-only HEAD -- <exe に入る物>` か `git ls-files --others --exclude-standard -- <同>` が空でない

COMMIT: 取れなければ None / DIRTY: exe に入る物にコミットしていない変更（未追跡を含む）があれば True。git が無ければ None
BUILT : ビルド日（YYYY-MM-DD・ローカル時刻）
生成物は開発起動の sys.path に入らない場所（dist_build/_gen）へ書く。毎回上書きする。
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN_DIR = ROOT / "dist_build" / "_gen"
COMMIT_ABBREV = 7  # 版の文字列に出すコミットの桁数

# exe に入る物。mbd2mes.spec の datas と Analysis のスクリプト・パッケージを覆うこと（tests/test_build_files.py が spec を読んで固定する）
DIRTY_PATHSPECS = [
    ":(glob)*.py",
    ":(glob)*.seed.json",
    "mbd2mes",
    "Pic/ICON/MBD2MES.ico",
    "tools",
    "dist_build",
]


def _git(args: list[str], cwd: Path = ROOT) -> str | None:
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return p.stdout


def read_commit(cwd: Path = ROOT) -> str | None:
    out = _git(["log", "-1", f"--abbrev={COMMIT_ABBREV}", "--format=%h"], cwd)
    return out.strip() if out and out.strip() else None


def read_dirty(cwd: Path = ROOT) -> bool | None:
    changed = _git(["diff", "--name-only", "HEAD", "--", *DIRTY_PATHSPECS], cwd)
    untracked = _git(["ls-files", "--others", "--exclude-standard", "--", *DIRTY_PATHSPECS], cwd)
    if changed is None or untracked is None:
        return None
    return bool(changed.strip() or untracked.strip())


def render(commit: str | None, dirty: bool | None, built: str) -> str:
    return (
        "# -*- coding: utf-8 -*-\n"
        "# 自動生成（tools/write_build_info.py）。手で編集しない。コミットしない（dist_build/_gen は .gitignore）。\n"
        f"COMMIT = {commit!r}\n"
        f"DIRTY = {dirty!r}\n"
        f"BUILT = {built!r}\n"
    )


def main() -> int:
    commit = read_commit()
    dirty = read_dirty() if commit else None
    built = datetime.now().strftime("%Y-%m-%d")
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GEN_DIR / "_build_info.py"
    path.write_text(render(commit, dirty, built), encoding="utf-8")
    print(f"[write_build_info] {path}: COMMIT={commit} DIRTY={dirty} BUILT={built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
