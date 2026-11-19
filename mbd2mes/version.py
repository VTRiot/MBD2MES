# -*- coding: utf-8 -*-
"""version.py -- アプリの版の名前。タイトルバーと `--version` が同じ文字列を使う。

RCZ2MES の version_info.py（commit 5b31da8）からの写し（改変: APP_NAME・APP_VERSION・説明。パッケージ内の位置）。

形:
    exe          : MBD2MES v0.3.0 (543b8e6, built 2026-11-14)
    exe(未コミット): MBD2MES v0.3.0 (543b8e6+dirty, built 2026-11-14)
    git が無くて取れなかった exe: MBD2MES v0.3.0 (unknown, built 2026-11-14)
    開発起動     : MBD2MES v0.3.0 (dev)

コミットとビルド日は、exe を作るたびに `tools/write_build_info.py` が `dist_build/_gen/_build_info.py` へ書く
（開発起動の sys.path には入らない）。版の番号（APP_VERSION）は発注で上げる（0.1.0 = 最初の動く版の CLI、0.2.0 = GUI・対応表・exe、0.3.0 = 変換中の進捗ダイアログと Cancel・一発変換・イベントフォルダ、0.3.1 = 進捗ダイアログを converter_progress（Skill の版）へ戻した。変換の中身は同じ）。
"""

from __future__ import annotations

import re
import sys

APP_NAME = "MBD2MES"
APP_VERSION = "0.3.1"

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _load_build_info() -> dict | None:
    """生成物 `_build_info`（COMMIT / DIRTY / BUILT）を読む。無ければ None。"""
    try:
        import _build_info  # type: ignore[import-not-found]
    except ImportError:
        return None
    return {
        "commit": getattr(_build_info, "COMMIT", None),
        "dirty": getattr(_build_info, "DIRTY", None),
        "built": getattr(_build_info, "BUILT", None),
    }


def format_version(frozen: bool, build_info: dict | None) -> str:
    """版の文字列を組み立てる（試験しやすいよう、環境の判定から分けてある）。"""
    base = f"{APP_NAME} v{APP_VERSION}"
    if not frozen:
        return f"{base} (dev)"
    info = build_info or {}
    commit = info.get("commit") or "unknown"
    if commit != "unknown" and info.get("dirty"):
        commit += "+dirty"
    built = info.get("built") or "unknown"
    return f"{base} ({commit}, built {built})"


def version_string() -> str:
    frozen = bool(getattr(sys, "frozen", False))
    return format_version(frozen, _load_build_info() if frozen else None)


def is_well_formed_version(v: str) -> bool:
    return bool(_VERSION_RE.match(v))
