# -*- coding: utf-8 -*-
r"""
[ORIGIN] copied, then adapted (2026-10-18)
  source path : C:\_Prog\GMN_Gemini\04_Bike_Car\Ld2MesConverter\[MoTeC]Ld2MesConverter\race_env.py
  source SHA-256 (as copied): 4b465d87021abbc4cb6d22b491ff9d04fb11dc1a85adf31243596199cfc94b6b
  derived on  : 2026-10-17 (LINK_LLGX2MES)
  changes     : detect_output_dir の RACE.INI 読み込みだけ。参考では、cp1252 で読めないバイト（例: cp932 の「ー」の 0x81）や
                値の中の % で例外が呼び出し側へ抜け、GUI が起動時・Reload 時に黙って止まった（実測）。
                % は補間しない（interpolation=None。INI の値に補間の意味は無い）、読めないバイトは「検出不能」として返す。
                文字コードは参考どおり cp1252 のまま（2D が RACE.INI を何の文字コードで書くかは未確認）。
race_env.py -- 2D RACE.INI から出力先候補を検出する（LD2MES_Converter Phase2 CP2 A-5）。

読み取り専用。RACE.INI を書き換えることは一切しない。

検出方針（計画 r7 + Codex レビュー review_r3 finding[1][2] 反映）:
    候補 = Path(Data_DRV) / EVENT （[ALL] Data_DRV と [START] EVENT から構成）。
    [DATADIR] の "0" キー（Analyzer 自身の直近使用フォルダの MRU 先頭）と一致すれば
    confidence="high"、候補自体は実在するが MRU と一致しない/参照できない場合は
    confidence="low" とする。呼び出し側（ld2mes.py）は対話確認時は confidence を
    問わず候補を提示し、`--yes`（無人実行）時は confidence="high" のときのみ自動採用する。

    当初「両者の完全一致」を自動採用の必須条件としていたが、Analyzer 起動直後や
    別イベント閲覧後で MRU が古いままの現実的ケースで検出失敗が頻発し、A-5 の
    目的（自動検出）を損なうと review_r3 で指摘され、confidence の2段階に変更した。
"""

from __future__ import annotations

import configparser
import os
import re
from pathlib import Path

_RACE_ROOT_RE = re.compile(r"^Race(\d+)$", re.IGNORECASE)


def find_race_root(programdata: Path | None = None) -> Path | None:
    """`<programdata>\\Race<年>` ディレクトリのうち年が最大のものを返す。無ければ None。"""
    programdata = programdata if programdata is not None else Path(r"C:\ProgramData")
    candidates: list[tuple[int, Path]] = []
    if not programdata.is_dir():
        return None
    for p in programdata.iterdir():
        if not p.is_dir():
            continue
        m = _RACE_ROOT_RE.match(p.name)
        if m:
            candidates.append((int(m.group(1)), p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0])
    return candidates[-1][1]


def _is_under(child: str, parent: str) -> bool:
    """normcase+normpath で比較し、child が parent 配下（一致含む）か判定する。"""
    child_n = os.path.normcase(os.path.normpath(child))
    parent_n = os.path.normcase(os.path.normpath(parent))
    if child_n == parent_n:
        return True
    parent_with_sep = parent_n if parent_n.endswith(os.sep) else parent_n + os.sep
    return child_n.startswith(parent_with_sep)


def _paths_equal(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def detect_output_dir(race_root: Path | None = None) -> tuple[Path | None, str, str]:
    """RACE.INI から出力先候補を検出する。

    戻り値: (検出パス or None, confidence, 理由)
      confidence: "high"（Data_DRV+EVENT と DATADIR 0= が一致・実在確認済み）
                  "low"（Data_DRV+EVENT のみ実在。DATADIR 0= 欠損/配下外/不一致）
                  ""（検出不能。パスは None）
    """
    if race_root is None:
        race_root = find_race_root()
    if race_root is None:
        return None, "", "Raceルートが見つからない"

    ini_path = race_root / "RACE.INI"
    if not ini_path.is_file():
        return None, "", f"{ini_path} が見つからない"

    cfg = configparser.ConfigParser(interpolation=None)
    try:
        cfg.read(ini_path, encoding="cp1252")
    except (OSError, configparser.Error, UnicodeDecodeError) as exc:
        return None, "", f"RACE.INI の読み取りに失敗: {exc}"

    try:
        data_drv = cfg["ALL"]["Data_DRV"]
        event = cfg["START"]["EVENT"]
    except KeyError as exc:
        return None, "", f"RACE.INI にキーが無い: {exc}"

    if not data_drv.strip() or not event.strip():
        return None, "", "Data_DRVまたはEVENTが空"

    if Path(event).is_absolute() or ":" in event:
        return None, "", "EVENTが相対イベント名でない（絶対パス風）"

    candidate = Path(data_drv) / event

    if not candidate.is_dir():
        return None, "", f"参照先が実在しない: {candidate}"

    if not cfg.has_section("DATADIR") or "0" not in cfg["DATADIR"]:
        return candidate, "low", "Data_DRV+EVENTのみ実在（DATADIR 0=キー欠損）"

    datadir0 = cfg["DATADIR"]["0"]

    if not _is_under(datadir0, data_drv):
        return candidate, "low", "DATADIR 0=がData_DRV配下外のため不採用"

    if not _paths_equal(str(candidate), datadir0):
        return candidate, "low", "Data_DRV+EVENTとDATADIR 0=が不一致"

    return candidate, "high", "Data_DRV+EVENTとDATADIR 0=が一致・実在確認済み"
