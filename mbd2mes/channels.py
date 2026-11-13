# -*- coding: utf-8 -*-
"""channels.py -- MBD のチャネルを、MES に書く物理量の系列（tick の変化点）にする。

換算は docs/mbd_format.md §6:
    calc_mode 3 : 物理量 = 生値 * A / B + C / 1000      [実測]
    calc_mode 0 : 生値のまま（Ne・GearPos・ステータス）   [実測]
    符号: 下の SIGNED_NAMES の 11 本は int16 で読む。[14] >= 5 の規則と食い違ったら警告する    [未確認: §6.2]
    GPSspd は MES に書かない（GPS ブロックの速度と同値。V_GPS として GPS から書く）
    THGRPADJ は A = 0 で式が成立しない。生値のまま出す（未解明。§6.3）
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .mbd_reader import FORMAT_SIGNED_MIN, TAG_GPS, MbdFile

# §6.2: 符号付きで読むと物理的に妥当になる 11 本（名前で持つ。チャネル表の並びは標本固有）
SIGNED_NAMES = frozenset({
    "GYROAN", "SLIP", "DSLIP", "GYPIAN", "PIANWIL", "GYPIRA", "GYXAC",
    "SLIPTRG", "SLPTRGOF", "SLPTRGEB", "IGTRQRTD",
})
CALC_DIRECT = 0  # §3 [15]
CALC_RATIO = 3  # §3 [15]: Y = a1*X/a2 + b
GPS_SPEED_NAME = "GPSspd"  # §6.3: GPS ブロックの速度の再掲
UNRESOLVED_NAMES = {  # §6.3: 換算が未解明で、生値のまま出すもの
    "THGRPADJ": "conversion unresolved (A = 0); written as the raw value",
}
INT16_SPAN = 1 << 16  # uint16 を int16 へ読み替える（二の補数。物理の定数）
INT16_SIGN_BIT = 1 << 15


@dataclass
class ChannelPlan:
    index: int
    name: str
    unit: str
    ticks: np.ndarray  # 値が書かれた tick
    values: np.ndarray  # 物理量（float64）
    source: str  # 記録に出す説明


def _to_physical(raw: np.ndarray, signed: bool, calc_mode: int, a: int, b: int, c: int) -> np.ndarray:
    v = raw.astype(np.int64)
    if signed:
        v = np.where(v >= INT16_SIGN_BIT, v - INT16_SPAN, v)
    v = v.astype(np.float64)
    if calc_mode == CALC_RATIO and a != 0 and b != 0:
        return v * a / b + c / 1000.0
    return v


def plan_channels(mbd: MbdFile) -> tuple[list[ChannelPlan], list[tuple[str, str]], list[str]]:
    """(書くチャンネル, 書かないチャンネルと理由, 警告)。GPS ブロック（タグ 1）は別経路。"""
    plans: list[ChannelPlan] = []
    skipped: list[tuple[str, str]] = []
    warnings: list[str] = []
    for ch in mbd.channels:
        name = ch.name or f"CH{ch.index}"
        if ch.index == TAG_GPS:
            continue  # GPS ブロック。convert 側が Latitude / Longitude / V_GPS として書く
        raw = mbd.raws[ch.index]
        if len(raw) == 0:
            skipped.append((name, "no value records"))
            continue
        if ch.name == GPS_SPEED_NAME:
            skipped.append((name, "same as the GPS block speed; written as V_GPS"))
            continue
        signed = ch.name in SIGNED_NAMES
        source_note = ""
        if signed != (ch.decimals >= FORMAT_SIGNED_MIN):
            if not signed and int(raw.max()) < INT16_SIGN_BIT:
                # [14] >= 5 だが、全レコードが 0x8000 未満なので符号付きで読んでも値は同じ（食い違いは無害）
                source_note = " ([14]>=5 but no raw value >= 0x8000: signedness has no effect)"
            else:
                warnings.append(
                    f"{name}: signed rule disagrees (name list: {'signed' if signed else 'unsigned'}, "
                    f"[14]={ch.decimals}); the name list is used")
        if ch.calc_mode not in (CALC_DIRECT, CALC_RATIO):
            if ch.name in UNRESOLVED_NAMES:
                warnings.append(f"{name}: {UNRESOLVED_NAMES[ch.name]}")
            else:
                warnings.append(f"{name}: unknown conversion mode {ch.calc_mode}; written as the raw value")
        elif ch.calc_mode == CALC_RATIO and (ch.a == 0 or ch.b == 0):
            warnings.append(f"{name}: " + UNRESOLVED_NAMES.get(ch.name, "A or B is 0; written as the raw value"))
        values = _to_physical(raw, signed, ch.calc_mode, ch.a, ch.b, ch.c)
        plans.append(ChannelPlan(
            index=ch.index, name=name, unit=ch.unit, ticks=mbd.ticks[ch.index], values=values,
            source=f"tag 0x{ch.index:02X} CAN 0x{ch.can_id:04X}{' signed' if signed else ''}{source_note}"))
    return plans, skipped, warnings
