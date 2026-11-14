# -*- coding: utf-8 -*-
"""tools/check_exe_version.py -- ビルドした exe が、今回の生成物（COMMIT / DIRTY / BUILT）を本当に梱包したかを確かめる。

RCZ2MES の tools/check_exe_version.py（commit 5b31da8。元は LD2MES）からの写し。改変は exe の名前（mbd2mes.exe）・import 先・説明だけ。

`dist/mbd2mes.exe` を **dist の外の一時フォルダへ写して**、`--version-file` 付きで起動する（設定・対応表は一時フォルダの隣に作られ、
`dist\\` の設定を汚さない。画面は出ない）。出力が `dist_build/_gen/_build_info.py` から組み立てた文字列と一致すれば 0 を返す。
"""

from __future__ import annotations

import runpy
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mbd2mes import version  # noqa: E402


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "mbd2mes.exe"  # 第 1 引数: 別の置き場の exe（dist の exe が使用中のとき）
    gen = ROOT / "dist_build" / "_gen" / "_build_info.py"
    if not exe.is_file() or not gen.is_file():
        print(f"[check_exe_version] missing: {exe if not exe.is_file() else gen}")
        return 2
    info = runpy.run_path(str(gen))
    expected = version.format_version(True, {"commit": info["COMMIT"], "dirty": info["DIRTY"], "built": info["BUILT"]})
    tmp = Path(tempfile.mkdtemp(prefix="mbd2mes_exe_version_"))
    try:
        copy = tmp / "mbd2mes.exe"
        shutil.copyfile(exe, copy)
        out_file = tmp / "version.txt"
        p = subprocess.run([str(copy), "--version-file", str(out_file)], cwd=str(tmp), capture_output=True, timeout=120,
                           stdin=subprocess.DEVNULL)
        got = out_file.read_text(encoding="utf-8").strip() if out_file.is_file() else None
        print(f"[check_exe_version] exit={p.returncode}")
        print(f"[check_exe_version] expected: {expected}")
        print(f"[check_exe_version] actual  : {got}")
        ok = p.returncode == 0 and got == expected
        print("[check_exe_version] RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
