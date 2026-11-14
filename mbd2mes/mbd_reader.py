# -*- coding: utf-8 -*-
"""mbd_reader.py -- MBDA2 の .MBD を読む（形式は docs/mbd_format.md。参照実装は mbd_dump.py）。

読むだけで何も書かない。構造（§1〜§5）:
    0x000〜0x1FF ヘッダ / 0x200〜0xDFF チャネル表（48 byte x 最大 64）/ 0x2000〜 タグ付きレコードの列
    タグ 0 (SysV) が現れるたびに 1 tick（= 5 ms）進む。タグ 1 は GPS ブロック（33 byte）、他は uint16 の値（big-endian）
    SysV 以外のチャネルは値が変わったときだけ書かれる（零次ホールドで読む）
確度は標本 1 本からの解析（[実測]/[推定]/[未確認] は docs/mbd_format.md の各節）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ---- 形式の定数（根拠は docs/mbd_format.md の節）----
MAGIC = b"4OEL V"  # §2
HEADER_SIZE = 0x200  # §1
TABLE_OFFSET = 0x200  # §1
TABLE_END = 0xE00  # §1。この先 0x2000 までは未使用
ENTRY_SIZE = 48  # §3
TABLE_MAX_ENTRIES = (TABLE_END - TABLE_OFFSET) // ENTRY_SIZE  # 64
DATA_OFFSET = 0x2000  # §1
LAST_INDEX_OFFSET = 0x10  # §2: チャネル表の最終番号（本数 - 1）らしい [推定]
VERSION_SLICE = slice(5, 10)  # §2: "V0003"
COURSE_SLICE = slice(0x70, 0x80)  # §2: コース名（ASCII・NUL 埋め）
CONTROL_LINE_OFFSET = 0x30  # §2: 緯度 A・経度 A・緯度 B・経度 B（uint32 x 4）[実測]
TICK_MS = 5  # §7: 1 tick = 5 ms [実測]
TAG_TICK = 0  # SysV。毎 tick の先頭
TAG_GPS = 1  # GPS1。タグの後に GPS_BLOCK_LEN byte
GPS_BLOCK_LEN = 33  # §4.1
VALUE_LEN = 2  # §4.1: 値は uint16
LATLON_UNITS_PER_DEG = 6_000_000  # §5: 1/100,000 分 [実測]
GPS_SPEED_UNITS_PER_KMH = 100  # §5: 0.01 km/h 単位 [実測]
FORMAT_SIGNED_MIN = 5  # §6.2: [14] >= 5 は符号付き 16 bit と読める [推定]
ASCII_NORTH = ord("N")
ASCII_EAST = ord("E")
# 時刻（§5）は十進の hhmmss.cc。時分秒への換算は物理の定数（1 時間 = 3600 s など）
SECONDS_PER_HOUR = 3600
SECONDS_PER_MINUTE = 60
SECONDS_PER_DAY = 86400
CENTI = 100


class MbdError(ValueError):
    """MBD として読めない（マジック不一致・短すぎる・未知のタグ）。"""


def _clean_ascii(raw: bytes) -> str:
    """§3: NUL 終端。NUL 以降は残りかす。0xFE 埋めも落とす。"""
    raw = raw.split(b"\x00")[0].rstrip(b"\xfe")
    return raw.decode("ascii", "replace").strip()


def _be_uint(block: np.ndarray, start: int, length: int) -> np.ndarray:
    """block (N, 列数) の uint8 から、start から length byte を big-endian の整数として取り出す。"""
    out = np.zeros(block.shape[0], dtype=np.int64)
    for k in range(length):
        out = (out << 8) | block[:, start + k].astype(np.int64)
    return out


@dataclass(frozen=True)
class ChannelDef:
    """チャネル表の 1 項目（§3）。"""

    index: int
    kind: int
    can_id: int
    mask: int
    width_code: int
    bit_offset: int
    decimals: int  # [14]。符号の有無とは別物だが §6.2 の検査に使う
    calc_mode: int  # [15]。0 = Direct、3 = Y = a1*X/a2 + b
    name: str
    unit: str
    a: int
    b: int
    c: int


@dataclass
class GpsFixes:
    """GPS ブロックの列（§5）。配列はどれも長さ N。"""

    tick: np.ndarray  # 各ブロックが現れた tick
    lat_deg: np.ndarray
    lon_deg: np.ndarray
    speed_kmh: np.ndarray
    sats: np.ndarray
    status: np.ndarray
    utc_s: np.ndarray  # その日の 0 時からの UTC 秒（uint24 は UTC 16:46 までしか入らないので真夜中を跨ぐことは無い。§5）
    north_only: bool  # 全件 'N' か
    east_only: bool  # 全件 'E' か

    def __len__(self) -> int:
        return len(self.tick)


@dataclass
class MbdFile:
    path: Path
    size: int
    sha256: str
    version: str
    course: str
    control_line: tuple[float, float, float, float]  # 緯度 A・経度 A・緯度 B・経度 B（度）
    channels: list[ChannelDef]
    n_ticks: int
    ticks: list[np.ndarray]  # チャネル番号 -> 値が書かれた tick（昇順）
    raws: list[np.ndarray]  # チャネル番号 -> 生値 (uint16)
    gps: GpsFixes
    end_pos: int
    warnings: list[str] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return self.n_ticks * TICK_MS


def _parse_channels(d: bytes, count: int) -> list[ChannelDef]:
    chans = []
    for i in range(count):
        o = TABLE_OFFSET + i * ENTRY_SIZE
        e = d[o:o + ENTRY_SIZE]
        chans.append(ChannelDef(
            index=i,
            kind=int.from_bytes(e[0:2], "big"),
            can_id=int.from_bytes(e[6:8], "big"),
            mask=int.from_bytes(e[8:10], "big"),
            width_code=e[10],
            bit_offset=e[11],
            decimals=e[14],
            calc_mode=e[15],
            name=_clean_ascii(e[16:24]),
            unit=_clean_ascii(e[24:32]),
            a=int.from_bytes(e[32:36], "big", signed=True),
            b=int.from_bytes(e[36:40], "big", signed=True),
            c=int.from_bytes(e[40:44], "big", signed=True),
        ))
    return chans


def _parse_gps(blocks: list[bytes], ticks: list[int]) -> GpsFixes:
    if not blocks:
        empty = np.zeros(0)
        return GpsFixes(empty.astype(np.int64), empty, empty, empty, empty.astype(np.int64),
                        empty.astype(np.int64), empty, True, True)
    a = np.frombuffer(b"".join(blocks), dtype=np.uint8).reshape(-1, GPS_BLOCK_LEN)
    c = _be_uint(a, 20, 3)  # §5 [20:23]
    cc = c % CENTI
    ss = (c // CENTI) % CENTI
    mm = (c // (CENTI * CENTI)) % CENTI
    hh = c // (CENTI * CENTI * CENTI)
    utc = hh * SECONDS_PER_HOUR + mm * SECONDS_PER_MINUTE + ss + cc / CENTI
    return GpsFixes(
        tick=np.asarray(ticks, dtype=np.int64),
        lat_deg=_be_uint(a, 2, 4) / LATLON_UNITS_PER_DEG,
        lon_deg=_be_uint(a, 7, 4) / LATLON_UNITS_PER_DEG,
        speed_kmh=_be_uint(a, 12, 2) / GPS_SPEED_UNITS_PER_KMH,
        sats=a[:, 18].astype(np.int64),
        status=a[:, 1].astype(np.int64),
        utc_s=utc,
        north_only=bool(np.all(a[:, 6] == ASCII_NORTH)),
        east_only=bool(np.all(a[:, 11] == ASCII_EAST)),
    )


REPORT_STEPS = 100  # データ領域の走査の進みを知らせる回数（1% ごと）


def read_mbd(path: str | Path, progress=None) -> MbdFile:
    """.MBD を読む。形式が合わなければ MbdError。末尾の中途半端なレコードは警告して捨てる。

    progress(frac): 省略できる。データ領域の走査の進み（0..1）を 1% ごとに知らせる（画面の進み具合用。結果には影響しない）。
    """
    path = Path(path)
    d = path.read_bytes()
    sha = hashlib.sha256(d).hexdigest()
    if len(d) < DATA_OFFSET:
        raise MbdError(f"too short for an MBD ({len(d)} bytes; the data area starts at 0x{DATA_OFFSET:X})")
    if d[:len(MAGIC)] != MAGIC:
        raise MbdError("not an MBD (magic mismatch)")
    warnings: list[str] = []

    last_index = int.from_bytes(d[LAST_INDEX_OFFSET:LAST_INDEX_OFFSET + 2], "big")
    count = last_index + 1
    if not 2 <= count <= TABLE_MAX_ENTRIES:
        raise MbdError(f"channel count {count} (header 0x{LAST_INDEX_OFFSET:X}) is outside 2..{TABLE_MAX_ENTRIES}")
    if count != TABLE_MAX_ENTRIES:
        warnings.append(f"channel table has {count} entries (the only sample had {TABLE_MAX_ENTRIES}); "
                        "this is outside what was verified")
    channels = _parse_channels(d, count)
    cl_words = [int.from_bytes(d[CONTROL_LINE_OFFSET + 4 * i:CONTROL_LINE_OFFSET + 4 * i + 4], "big")
                for i in range(4)]
    control_line = tuple(w / LATLON_UNITS_PER_DEG for w in cl_words)

    n = len(d)
    p = DATA_OFFSET
    tick = -1
    ch_ticks: list[list[int]] = [[] for _ in range(count)]
    ch_vals: list[list[int]] = [[] for _ in range(count)]
    gps_blocks: list[bytes] = []
    gps_ticks: list[int] = []
    gps_step = 1 + GPS_BLOCK_LEN
    val_step = 1 + VALUE_LEN
    first_tag_checked = False
    report_every = max((n - DATA_OFFSET) // REPORT_STEPS, 1)
    next_report = DATA_OFFSET + report_every
    while p < n:
        if progress is not None and p >= next_report:
            progress((p - DATA_OFFSET) / max(n - DATA_OFFSET, 1))
            next_report = p + report_every
        t = d[p]
        if t >= count:
            raise MbdError(f"unknown tag 0x{t:02X} at 0x{p:X} (the table has {count} channels)")
        if not first_tag_checked:
            first_tag_checked = True
            if t != TAG_TICK:
                warnings.append(f"the first record is tag 0x{t:02X}, not the tick tag 0x{TAG_TICK:02X}")
        if t == TAG_TICK:
            tick += 1
        if t == TAG_GPS:
            end = p + gps_step
            if end > n:
                warnings.append(f"truncated GPS block at 0x{p:X}; the rest of the file was ignored")
                break
            gps_blocks.append(d[p + 1:end])
            gps_ticks.append(max(tick, 0))
            p = end
        else:
            end = p + val_step
            if end > n:
                warnings.append(f"truncated record at 0x{p:X}; the rest of the file was ignored")
                break
            ch_ticks[t].append(max(tick, 0))
            ch_vals[t].append((d[p + 1] << 8) | d[p + 2])
            p = end
    if tick < 0:
        raise MbdError("no tick record (tag 0x00) in the data area")

    return MbdFile(
        path=path, size=n, sha256=sha,
        version=d[VERSION_SLICE].decode("ascii", "replace").strip(),
        course=_clean_ascii(d[COURSE_SLICE]),
        control_line=control_line, channels=channels, n_ticks=tick + 1,
        ticks=[np.asarray(x, dtype=np.int64) for x in ch_ticks],
        raws=[np.asarray(x, dtype=np.uint16) for x in ch_vals],
        gps=_parse_gps(gps_blocks, gps_ticks), end_pos=p, warnings=warnings,
    )
