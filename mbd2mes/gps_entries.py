# -*- coding: utf-8 -*-
"""gps_entries.py -- 32 bit の位置チャンネル、試作の変種 V1〜V4、HED の [GPS] 節。

LD2MES から写した `ddd_generator.py`・`mes_writer.py` は 16 bit 固定の書き方を持つ。
それらは無改変のまま、32 bit の位置チャンネルは `ddd_generator.make_entry` が返す
`DddEntry` を作り直して足す（計画 D3）。書き出しの経路（mes_writer）はビット幅・gain・
`6=` の欄を entry から取るので、無改変のまま 32 bit を書ける。

符号化の倍率（D1）: DDD に書ける倍率は float32。名目の 1e-7 で符号化して float32 の倍率で読むと
読み戻しが最大 1.6e-6 度ずれる。符号化にも float32(1e-7) の実値を使い、DDD の倍率と一致させる。
2D の GPS ロガー自身の倍率も同じ `33D6BF95`。

北緯・東経（正の値）だけ対応（M1 の D11。M2 でも例外のまま。BOUND_PENDING B1）。mes_writer は符号なし 32 bit で書き、
負の値を 0 に切り上げて黙って壊すため、負の値があれば例外で止める。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

import numpy as np

from . import ddd_generator as dg
from . import mes_reader as mr

# ---------------------------------------------------------------- 32 bit の書き方
WIDE_BIT_WIDTH = 0x20
# 2D の GPS ロガーの Lat_dez・Lon_dez の `6=` 第 1 欄（実物 F4-02M-01.DDD。符号付き 4 byte と読める。推測）
WIDE_KEY6_FIRST = "FFFFFFFC"
# 位置の倍率 1e-7 度。DDD は float32 なので、符号化にも float32 の実値を使う（D1）
POSITION_GAIN = float(np.float32(1e-7))
POSITION_OFFSET = 0.0
KEY6_MARK_INDEX = 2  # `6=` の第 3 欄（機器の印）


class NegativeCoordinateError(ValueError):
    """南緯・西経は未対応（符号なし 32 bit で書くため、負の値を 0 に切り上げてしまう）。"""


def _hemisphere(name: str) -> str:
    """名前（Lat_dez／Latitude 系なら緯度）から、負のときの半球の言い方。"""
    return "southern" if name.lower().startswith("lat") else "western"


def make_wide_entry(
    idx: int, name: str, unit: str, values: np.ndarray, rate: int, base_hz: int, skipped: list[tuple[str, str]]
) -> mr.DddEntry:
    """32 bit の位置チャンネルの DddEntry（通し番号 idx は 1 始まり。節 ID と拡張子は make_entry と同じ式）。"""
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name}: non-finite values cannot be written")
    if float(np.min(values)) < 0.0:
        raise NegativeCoordinateError(
            f"{name}: negative coordinate ({_hemisphere(name)} hemisphere) is not supported yet. "
            "Nothing was written."
        )
    base = dg.make_entry(idx, name, unit, values, float(rate), base_hz, skipped)
    key6 = list(base.raw_key6)
    key6[0] = WIDE_KEY6_FIRST
    return dataclasses.replace(
        base,
        bit_width=WIDE_BIT_WIDTH,
        gain=POSITION_GAIN,
        offset=POSITION_OFFSET,
        raw_key6=key6,
    )


def apply_marks(entries: list[mr.DddEntry], marks: dict[str, str]) -> None:
    """名前に当たる entry の `6=` 第 3 欄（機器の印）を差し替える。DDD を書く前に呼ぶ。"""
    for e in entries:
        mark = marks.get(e.name)
        if mark is not None:
            key6 = list(e.raw_key6)
            key6[KEY6_MARK_INDEX] = mark
            e.raw_key6 = key6


# ---------------------------------------------------------------- HED の [GPS] 節
# (キー, 本ツールの値)。キーの順は実物（F4-02M-01.HED）と同じ。
# 意味が明らかなもの・読めないものは実物のまま。MSR は本ツールの基準 Hz(None で埋める)、ShiftTime は 0（計画 3.7）。
GPS_SECTION_ITEMS = (
    ("Rate", "10"),
    ("Version", "22.1213"),
    ("MaxDropOutTime", "0"),
    ("ChannelRate_Hi", "100"),
    ("ChannelRate_Lo", "10"),
    ("LeapSecond", "18"),
    ("ShiftTime", "0"),
    ("AverageMulti", "4"),
    ("LateralDynamics", "2"),
    ("MSR", None),  # 基準 Hz（rcz_timeline.BASE_HZ）で埋める
)
HED_ENCODING = "cp1252"
HED_NEWLINE = "\r\n"


def render_hed_gps(base_hz: int, overrides: dict[str, str] | None = None) -> bytes:
    """`.HED`（[GPS] 節のみ）。cp1252・CRLF・節の後に空行 1 行（実物と同じ）。"""
    overrides = overrides or {}
    lines = ["[GPS]"]
    for key, value in GPS_SECTION_ITEMS:
        if key in overrides:
            value = overrides[key]
        elif value is None:
            value = str(base_hz)
        lines.append(f"{key}={value}")
    lines.append("")
    return (HED_NEWLINE.join(lines) + HED_NEWLINE).encode(HED_ENCODING, errors="strict")


# ---------------------------------------------------------------- 変種
@dataclass(frozen=True)
class Variant:
    key: str
    summary: str
    rename: dict = field(default_factory=dict)  # 生の名前 -> この変種の名前
    write_hed: bool = False  # HED に [GPS] 節を足すか（[DOWNLOAD] 節は全変種で書く。M2 D3）
    marks: dict = field(default_factory=dict)  # この変種の名前 -> `6=` 第 3 欄


# 2D の GPS ロガーの実物（F4-02M-01.DDD）の機器の印
_RAW_MARKS = {
    "Lat_dez": "S227D9",
    "Lon_dez": "S227D10",
    "V_Sat": "S227D5",
    "Course": "S227D8",
    "Altitude": "S227D11",
    "HorAccu": "S227D14",
}
# 計算後の名前（種別 101）の実物の印。HorAccu は計算後に無いので生のまま
_CALC_RENAME = {"Lat_dez": "Latitude", "Lon_dez": "Longitude", "V_Sat": "V_GPS"}
_CALC_MARKS = {
    "Latitude": "S227D9",
    "Longitude": "S227D10",
    "V_GPS": "S227D5",
    "Course": "S227D8",
    "Altitude": "S227D11",
    "HorAccu": "S227D14",
}

VARIANTS = {
    "V1": Variant("V1", "raw names, no HED [GPS] section (trial; the [DOWNLOAD] section is always written)"),
    "V2": Variant("V2", "V1 + HED [GPS] section", write_hed=True),
    "V3": Variant("V3", "V2 + device marks (6= 3rd field) of the 2D GPS logger", write_hed=True,
                  marks=dict(_RAW_MARKS)),
    "V4": Variant("V4", "calculated names (Latitude/Longitude/V_GPS) + HED + marks", rename=dict(_CALC_RENAME),
                  write_hed=True, marks=dict(_CALC_MARKS)),
}
# 既定は V4（M1 の Analyzer の確認で、計算後の名前の V4 だけで地図が出ると分かった。B9）。V1〜V3 は試験用
DEFAULT_VARIANT = "V4"


def get_variant(key: str) -> Variant:
    try:
        return VARIANTS[key.upper()]
    except KeyError:
        raise ValueError(f"unknown variant {key!r}; choose from {', '.join(VARIANTS)}") from None
