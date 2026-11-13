# -*- coding: utf-8 -*-
"""hed_download.py -- MES の .HED の [DOWNLOAD] 節（記録の開始の日付・時刻）。

欄の名前と日付の形は、2D の実物の HED から写した（F12。tests/fixtures/logger_hed_download_excerpt.txt）:
    Date=YY.MMDD / Time=HHMMSS / Timezone=+09:00 / Start of download=DD.MM.YYYY HH:MM:SS / End of download=（同じ）
書く欄はこの 5 本と MainSamplingRate（基準 Hz。実物では Mileage calculated の後。IXR のラップが標本番号に使う）。
実物にある残りの欄（LapMeter・Run total・Loggername・Logger serial など）は、値の意味を本ツールが決められないため書かない。

日時は RCZ の最初の時刻 t0（UTC の Unix ms）を秒で切り捨て、固定の +09:00 を足した値（計画 3.6・D4）。
節の並びは実物と同じ（[DOWNLOAD] が [GPS] より前）。cp1252・CRLF・節の後に空行 1 行。
"""

from __future__ import annotations

import datetime

from . import gps_entries as ge

JST_OFFSET_MIN = 540  # +09:00（らいおの運用は国内。実物の HED の Timezone はすべて +09:00。計画 3.6・R3）
MS_PER_S = 1000
SEC_PER_MIN = 60
MIN_PER_H = 60

SECTION = "[DOWNLOAD]"
# 書く欄の順（実物と同じ。MainSamplingRate は基準 Hz で埋める）
KEYS = ("Date", "Time", "Timezone", "Start of download", "End of download", "MainSamplingRate")


def local_datetime(t0_ms: int, offset_min: int = JST_OFFSET_MIN) -> datetime.datetime:
    """t0（UTC の Unix ms）を秒で切り捨て、offset_min 分を足した日時（時刻帯なしの壁時計）。"""
    seconds = t0_ms // MS_PER_S
    base = datetime.datetime(1970, 1, 1)
    return base + datetime.timedelta(seconds=seconds + offset_min * SEC_PER_MIN)


def format_timezone(offset_min: int) -> str:
    sign = "+" if offset_min >= 0 else "-"
    a = abs(offset_min)
    return f"{sign}{a // MIN_PER_H:02d}:{a % MIN_PER_H:02d}"


def start_text(t0_ms: int, offset_min: int = JST_OFFSET_MIN) -> str:
    """HED の Start of download と同じ形（DD.MM.YYYY HH:MM:SS）。"""
    return local_datetime(t0_ms, offset_min).strftime("%d.%m.%Y %H:%M:%S")


def download_items(t0_ms: int, base_hz: int, offset_min: int = JST_OFFSET_MIN) -> list[tuple[str, str]]:
    dt = local_datetime(t0_ms, offset_min)
    start = dt.strftime("%d.%m.%Y %H:%M:%S")
    values = (
        dt.strftime("%y.%m%d"),
        dt.strftime("%H%M%S"),
        format_timezone(offset_min),
        start,
        start,
        str(base_hz),
    )
    return list(zip(KEYS, values))


def render_download(t0_ms: int, base_hz: int, offset_min: int = JST_OFFSET_MIN) -> bytes:
    lines = [SECTION] + [f"{k}={v}" for k, v in download_items(t0_ms, base_hz, offset_min)] + [""]
    return (ge.HED_NEWLINE.join(lines) + ge.HED_NEWLINE).encode(ge.HED_ENCODING, errors="strict")


def render_hed(t0_ms: int, base_hz: int, with_gps: bool, offset_min: int = JST_OFFSET_MIN) -> bytes:
    """.HED 全体: [DOWNLOAD]、（変種が持てば）[GPS]。"""
    data = render_download(t0_ms, base_hz, offset_min)
    if with_gps:
        data += ge.render_hed_gps(base_hz)
    return data
