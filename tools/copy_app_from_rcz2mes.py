# -*- coding: utf-8 -*-
"""RCZ2MES のアプリ部分（対応表・設定・GUI・exe のビルド）の元の blob を取り、SHA-256 を記録する（docs/provenance.md の元）。

  python -I tools/copy_app_from_rcz2mes.py <RCZ2MES のフォルダ> <commit> <blob の置き場> <出力 JSON>

元は `git show <commit>:<file>`（読むだけ。RCZ2MES の状態は変えない）。blob は <blob の置き場> へそのまま書く（参照用。
リポには入れない）。写し先は手で直す（改変が import 行だけではないため）。直した後の SHA-256 は別に記録する。
作業ツリーの SHA-256 も取り、blob と違えば `worktree_matches_blob: false` で出す。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

FILES = (
    "channel_map.py",
    "config.py",
    "map_rules.py",
    "rcz2mes_gui.py",
    "rcz2mes.py",  # console_io へ切り出す関数と、入口の分岐の元
    "version_info.py",
    "channel_map.seed.json",
    "rcz2mes_config.seed.json",
    "dist_build/rcz2mes.spec",
    "dist_build/build_exe.bat",
    "tools/write_build_info.py",
    "tools/check_exe_version.py",
    "race_env.py",  # FB01: 無改変で mbd2mes/race_env.py へ写す（blob をそのままコピー）
    "rcz_batch.py",  # FB01: 一発変換の元（batch.py へ書き直す）
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    src, commit, dst, out_json = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    dst.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in FILES:
        blob = subprocess.run(["git", "-C", str(src), "show", f"{commit}:{name}"], check=True, capture_output=True).stdout
        target = dst / name.replace("/", "__")
        target.write_bytes(blob)
        work = (src / name).read_bytes()
        rows.append({"file": name, "blob_sha256": sha(blob), "worktree_matches_blob": sha(work) == sha(blob),
                     "blob_has_crlf": b"\r\n" in blob})
    out_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in rows:
        print(r["file"], r["blob_sha256"][:12], "worktree==blob" if r["worktree_matches_blob"] else "WORKTREE DIFFERS", "CRLF" if r["blob_has_crlf"] else "LF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
