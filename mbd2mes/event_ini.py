# -*- coding: utf-8 -*-
"""event_ini.py -- 変換先のイベントの Event.ini を読み、GPS のチャンネル名の食い違いを警告する（読むだけ。書かない）。

場所: <出力先>\\Event.ini（MES の親のフォルダ。計画 3.7・F14）。
[Special channels] の GPS_Latitude・GPS_Longitude が書かれていて、今回の MES の位置の名前と違うとき警告する
（M1 の Analyzer の確認 5-2: Analyzer は Event.ini にこの 2 行を書き足す。名前が違うと地図が出ない推測。B10）。
キーも値も大文字小文字を区別せずに比べる（実物に GPS_LATITUDE=LATITUDE がある）。
行が無い・節が無い・ファイルが無いときは何も出さない。Event.ini は書き換えない（LD2MES も触らない）。
"""

from __future__ import annotations

from pathlib import Path

EVENT_INI_NAME = "Event.ini"
SECTION = "special channels"
ENCODING = "cp1252"
KEY_LAT = "gps_latitude"
KEY_LON = "gps_longitude"

READ_FAILED = "[INFO] Event.ini could not be read; GPS name check skipped"


def read_special_channels(path: Path) -> dict[str, str] | None:
    """[Special channels] の key(小文字) -> value。読めなければ None。節が無ければ空の辞書。"""
    try:
        text = path.read_bytes().decode(ENCODING)
    except (OSError, UnicodeDecodeError):
        return None
    out: dict[str, str] = {}
    in_section = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_section = line[1:-1].strip().lower() == SECTION
            continue
        if not in_section or "=" not in line or line.startswith((";", "#")):
            continue
        key, _, value = line.partition("=")
        out[key.strip().lower()] = value.strip()
    return out


def check(out_dir: Path, lat_name: str, lon_name: str) -> list[str]:
    """警告の文のリスト（空 = 何も出さない）。Event.ini が読めなければ INFO を 1 本。"""
    path = Path(out_dir) / EVENT_INI_NAME
    if not path.is_file():
        return []
    special = read_special_channels(path)
    if special is None:
        return [READ_FAILED]
    warnings: list[str] = []
    for key, label, expected in ((KEY_LAT, "latitude", lat_name), (KEY_LON, "longitude", lon_name)):
        value = special.get(key)
        if not value or value.lower() == expected.lower():
            continue
        shown = "GPS_Latitude" if key == KEY_LAT else "GPS_Longitude"
        warnings.append(
            f"[WARN] Event.ini ({path}): {shown}={value}, but this MES writes the {label} as '{expected}'. "
            "2D Analyzer may not draw the map. RCZ2MES does not edit Event.ini."
        )
    return warnings
