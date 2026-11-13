# -*- coding: utf-8 -*-
"""lap_files.py -- MES のラップ（.IXR）とセクター（.STI）のファイルの符号化と書き出し（M3a）。

形の出どころ: LD2MES の Ld2Mes-013 でらいおが Analyzer で確かめた P4（Ld2Mes_013_owner_check.md 3 章）の仕様。
013 の試作のコードは写していない。形の仕様だけから書いた（docs/provenance.md に「参照のみ」で記録）。

.IXR（int32 リトルエンディアンの語の列）:
    0, 0                                   記録の先頭（標本 0・距離 0）
    (標本番号, 累積距離 m) x N             ラップの境目 N 本（標本番号の昇順）
    (記録の終わりの標本, 全体の距離 m)
    (N << 16) | offset                     offset = 8 + 8 * (N + 1)  -- 16 bit に収まる範囲が N の上限
    MainSamplingRate, N, 0
Analyzer の一覧は「境目の数 + 1」本（先頭と末尾は記録の前後の区間）。

.STI（int32）:
    件数, MainSamplingRate, 0
    (標本番号, 区間の番号 0 始まり, -1, -1) x 件数      時刻順
"""

from __future__ import annotations

import numbers
import struct
from pathlib import Path

WORD_FORMAT = "<i"  # int32 リトルエンディアン
WORD_BYTES = struct.calcsize(WORD_FORMAT)
STI_PAD = -1  # .STI の 3・4 語目。013 で調べた実物 1026 件が全部 (-1, -1)
IXR_HEAD_WORDS = 2  # 先頭の (0, 0)
IXR_TAIL_WORDS = 4  # (N<<16 | offset), MainSamplingRate, N, 0
IXR_PAIR_WORDS = 2  # (標本番号, 距離)
IXR_OFFSET_BASE = 8  # offset = 8 + 8 * (N + 1) の 8（バイト数の固定部分）
IXR_OFFSET_PER_PAIR = 8  # 1 組 = 2 語 = 8 バイト
IXR_COUNT_SHIFT = 16  # N と offset を 16 bit ずつ 1 語に詰める
WORD16_MAX = 0xFFFF
# offset が 16 bit に収まる N の最大: 8 + 8 * (N + 1) <= 0xFFFF
MAX_BOUNDARIES = (WORD16_MAX - IXR_OFFSET_BASE) // IXR_OFFSET_PER_PAIR - 1


INT32_MIN = -(2 ** 31)
INT32_MAX = 2 ** 31 - 1


def _pack(words) -> bytes:
    """int32 に収まらない語は ValueError（struct.error の実装依存の文言にしない）。"""
    out = []
    for w in words:
        if isinstance(w, bool) or not isinstance(w, numbers.Integral):
            raise ValueError(f"value {w!r} is not an integer")  # 浮動小数を黙って切り捨てない
        v = int(w)
        if not INT32_MIN <= v <= INT32_MAX:
            raise ValueError(f"value {v} does not fit in int32")
        out.append(struct.pack(WORD_FORMAT, v))
    return b"".join(out)


def ixr_offset(n: int) -> int:
    return IXR_OFFSET_BASE + IXR_OFFSET_PER_PAIR * (n + 1)


def encode_ixr(boundaries, end_sample: int, end_dist_m: int, sampling_rate: int) -> bytes:
    """boundaries は (標本番号, 累積距離 m) の列。標本番号は昇順（同じ値の重複は呼び出し側で除く）。"""
    n = len(boundaries)
    if n > MAX_BOUNDARIES:
        raise ValueError(f"too many lap boundaries: {n} (max {MAX_BOUNDARIES})")
    samples = [s for s, _d in boundaries]
    if any(b <= a for a, b in zip(samples[:-1], samples[1:])) or (samples and samples[0] < 0):
        raise ValueError(f"boundary samples must be non-negative and strictly increasing: {samples[:5]}...")
    if samples and end_sample < samples[-1]:
        raise ValueError(f"record end {end_sample} is before the last boundary {samples[-1]}")
    words = [0, 0]
    for sample, dist in boundaries:
        words += [sample, dist]
    words += [end_sample, end_dist_m]
    words += [(n << IXR_COUNT_SHIFT) | ixr_offset(n), sampling_rate, n, 0]
    return _pack(words)


def encode_sti(sections, sampling_rate: int) -> bytes:
    """sections は (標本番号, 区間の番号 0 始まり) の列（時刻順）。"""
    words = [len(sections), sampling_rate, 0]
    for sample, idx in sections:
        words += [sample, idx, STI_PAD, STI_PAD]
    return _pack(words)


def write_lap_files(mes_dir: Path, name: str, plan, sampling_rate: int) -> list[str]:
    """plan（lap_sections.LapPlan）の内容を mes_dir に書く。書いたファイル名の列を返す。

    境目が 0 本なら .IXR を書かない（空のファイルを作らない）。セクターが 0 件なら .STI を書かない。
    """
    written: list[str] = []
    if plan.boundaries:
        (mes_dir / f"{name}.IXR").write_bytes(
            encode_ixr(plan.boundaries, plan.end_sample, plan.end_dist_m, sampling_rate))
        written.append(f"{name}.IXR")
    if plan.sections:
        (mes_dir / f"{name}.STI").write_bytes(encode_sti(plan.sections, sampling_rate))
        written.append(f"{name}.STI")
    return written
