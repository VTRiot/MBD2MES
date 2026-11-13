# -*- coding: utf-8 -*-
"""RCZ2MES の MES 書き出し部を mbd2mes/ へ写す（docs/provenance.md の元）。

  python -I tools/copy_from_rcz2mes.py <RCZ2MES のフォルダ> <commit> <写し先 mbd2mes/ のフォルダ> <出力 JSON>

元は `git show <commit>:<file>`（LF の blob）。import 行（パッケージ内の相対 import）だけを書き換え、それ以外は無改変。
RCZ2MES は読むだけ（git show のみ）。結果（元の blob と写した先の SHA-256、作業ツリーの SHA-256）を JSON に書く。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

# 写すファイル -> import の書き換え（元の行, 新しい行）
FILES: dict[str, list[tuple[str, str]]] = {
    "mes_reader.py": [],
    "mes_writer.py": [("import mes_reader as mr", "from . import mes_reader as mr")],
    "ddd_generator.py": [
        ("import mes_reader as mr", "from . import mes_reader as mr"),
        ("import mes_writer as mw", "from . import mes_writer as mw"),
    ],
    "ddd_invariants.py": [],
    "gps_entries.py": [
        ("import ddd_generator as dg", "from . import ddd_generator as dg"),
        ("import mes_reader as mr", "from . import mes_reader as mr"),
    ],
    "hed_download.py": [("import gps_entries as ge", "from . import gps_entries as ge")],
    "lap_files.py": [],
    "event_ini.py": [],
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    src, commit, dst, out_json = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    dst.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, rewrites in FILES.items():
        blob = subprocess.run(["git", "-C", str(src), "show", f"{commit}:{name}"], check=True, capture_output=True).stdout
        if b"\r\n" in blob:
            raise SystemExit(f"{name}: blob has CRLF; expected LF")
        text = blob.decode("utf-8")
        for old, new in rewrites:
            if text.count(old + "\n") != 1:
                raise SystemExit(f"{name}: expected exactly one line {old!r}")
            text = text.replace(old + "\n", new + "\n")
        data = text.encode("utf-8")
        (dst / name).write_bytes(data)
        work = (src / name).read_bytes()
        rows.append({
            "file": name,
            "blob_sha256": sha(blob),
            "copy_sha256": sha(data),
            "worktree_sha256": sha(work),
            "worktree_crlf": b"\r\n" in work,
            "modified": bool(rewrites),
            "rewrites": [new for _old, new in rewrites],
        })
    out_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in rows:
        print(r["file"], "unchanged" if not r["modified"] else "imports-rewritten", r["copy_sha256"][:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
