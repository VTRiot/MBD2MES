# -*- coding: utf-8 -*-
"""合成 MBD を手で組む（docs/mbd_format.md §1〜§5 のバイト配置から直接。mbd2mes の読み取りコードを通さない）。"""

from __future__ import annotations

import struct

HEADER = 0x200
TABLE = 0x200
DATA = 0x2000
ENTRY = 48


def entry(name: str, unit: str = "", *, can_id: int = 0, a: int = 1, b: int = 1, c: int = 0, fmt: int = 0, mode: int = 0) -> bytes:
    e = bytearray(ENTRY)
    e[6:8] = can_id.to_bytes(2, "big")
    e[14] = fmt
    e[15] = mode
    e[16:16 + len(name)] = name.encode("ascii")
    e[24:24 + len(unit)] = unit.encode("ascii")
    e[32:36] = struct.pack(">i", a)
    e[36:40] = struct.pack(">i", b)
    e[40:44] = struct.pack(">i", c)
    return bytes(e)


def gps_block(lat_units: int, lon_units: int, speed_raw: int, utc_dec: int, ns: str = "N", ew: str = "E") -> bytes:
    """GPS ブロック 33 byte（タグの次から）。utc_dec は十進 hhmmss.cc を整数にしたもの（例 564360 = 00:56:43.60）。"""
    b = bytearray(33)
    b[0] = 1
    b[1] = ord("2")
    b[2:6] = lat_units.to_bytes(4, "big")
    b[6] = ord(ns)
    b[7:11] = lon_units.to_bytes(4, "big")
    b[11] = ord(ew)
    b[12:14] = speed_raw.to_bytes(2, "big")
    b[16:18] = b"\x02\x02"
    b[18] = 12
    b[20:23] = utc_dec.to_bytes(3, "big")
    return bytes(b)


def build_mbd(channels: list[bytes], ticks: list[list[tuple[int, object]]], *, control_line_units=(0, 0, 0, 0),
              count: int | None = None, course: str = "test") -> bytes:
    """channels: entry() の列（番号 = 並び）。ticks: tick ごとのレコードの列 [(タグ, 値 または GPS ブロックの bytes)]。
    各 tick の先頭に SysV（タグ 0・値 0）を自動で置く。"""
    count = count or len(channels)
    d = bytearray(DATA)
    d[0:16] = b"4OEL V0003".ljust(15, b" ") + b"\x00"
    d[0x10:0x12] = (count - 1).to_bytes(2, "big")
    for i, v in enumerate(control_line_units):
        d[0x30 + 4 * i:0x34 + 4 * i] = v.to_bytes(4, "big")
    d[0x70:0x70 + len(course)] = course.encode("ascii")
    for i, e in enumerate(channels):
        d[TABLE + ENTRY * i:TABLE + ENTRY * (i + 1)] = e
    out = bytearray(d)
    for recs in ticks:
        out += bytes([0]) + (0).to_bytes(2, "big")  # SysV
        for tag, val in sorted(recs, key=lambda r: r[0]):
            out += bytes([tag])
            out += val if isinstance(val, bytes) else int(val).to_bytes(2, "big")
    return bytes(out)
