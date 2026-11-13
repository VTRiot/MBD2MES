# -*- coding: utf-8 -*-
"""timeline.py -- 変化点（tick, 値）と GPS の測位を、t = 0 から一定レートの格子へ零次ホールドで並べる。

MES は「各チャンネルが t=0 から一定のレートで並ぶ」形しか持てない。MBD は値が変わったときだけ書く差分記録なので、
時刻 t の値 = t 以前の最後のレコードの値（docs/mbd_format.md §4.3）。補間はしない（元が階段状の記録）。
標本数は RCZ2MES と同じ n = ceil(T * レート / 1000)（rcz_timeline.sample_count。全チャンネルが T を覆う。地雷 1）。
"""

from __future__ import annotations

import math

import numpy as np

from .mbd_reader import TICK_MS

MS_PER_S = 1000  # 物理の定数
BASE_HZ = 400  # 基準 Hz。Analyzer の受理実績がある唯一の値（RCZ2MES rcz_timeline.BASE_HZ。docs/mes_format.md §2-3）
RATE_MAX_HZ = 200  # tick のレート（1000 / TICK_MS）。基準 Hz の約数で、これより速い標本は元に無い
TICK_RATE_HZ = MS_PER_S // TICK_MS  # 200 Hz: 1 標本 = 1 tick。5 ms の記録を欠けなく写す最低のレート
RATE_CANDIDATES = tuple(r for r in range(1, RATE_MAX_HZ + 1) if BASE_HZ % r == 0)


class TimelineError(ValueError):
    pass


def sample_count(span_ms: int, rate_hz: int) -> int:
    """標本数 n = ceil(T * レート / 1000)（整数演算）。T = 0 でも 1 本は持つ。"""
    return max(1, -(-span_ms * rate_hz // MS_PER_S))


def choose_rate(interval_s: float) -> int:
    """標本間隔（秒）に、対数で最も近いレート（基準 Hz の約数）。"""
    if not interval_s > 0:
        raise TimelineError("cannot choose a rate from a non-positive interval")
    hz = 1.0 / interval_s
    return min(RATE_CANDIDATES, key=lambda c: abs(math.log(c / hz)))


def hold_ticks(ticks: np.ndarray, values: np.ndarray, n: int, rate_hz: int = TICK_RATE_HZ) -> tuple[np.ndarray, int]:
    """tick 時刻の変化点を rate_hz の格子 n 点へ。(値, 最初のレコードより前の標本数)。

    格子の k 番目の時刻 = k / rate_hz 秒。レコードの時刻 = tick * TICK_MS ms。値は「時刻が以下の最後のレコード」。
    最初のレコードより前は最初の値を保つ（何も記録が無い区間。戻り値の 2 つめで数を知らせる）。
    """
    if len(ticks) == 0:
        raise TimelineError("no records")
    t_ms = ticks.astype(np.int64) * TICK_MS
    grid_ms = np.arange(n, dtype=np.int64) * MS_PER_S  # 整数のまま比べる: k/rate*1000 = k*1000/rate
    # 格子 k の時刻 k*1000/rate ms 以下のレコード <=> t_ms * rate <= k * 1000
    idx = np.searchsorted(t_ms * rate_hz, grid_ms, side="right") - 1
    before = int(np.count_nonzero(idx < 0))
    idx = np.maximum(idx, 0)
    return np.asarray(values, dtype=np.float64)[idx], before


def hold_fixes(t_s: np.ndarray, values: np.ndarray, n: int, rate_hz: int) -> np.ndarray:
    """GPS の測位（時刻 t_s 秒・昇順）を rate_hz の格子 n 点へ。

    測位 i は格子の round(t_s[i] * rate) 番へ置く（測位は厳密に等間隔なので 1 標本に 1 本になる）。
    値は「その標本以前の最後の測位」。最初の測位より前は最初の値を保つ。n 以上は置かない。
    """
    if len(t_s) == 0:
        raise TimelineError("no GPS fixes")
    slot = np.maximum(np.rint(np.asarray(t_s) * rate_hz).astype(np.int64), 0)  # 0 より前は 0 番へ寄せる
    which = np.full(n, -1, dtype=np.int64)
    ok = slot < n
    # 同じ標本に複数あれば後ろの測位が勝つ（代入は後の要素が残る）
    which[slot[ok]] = np.nonzero(ok)[0]
    which = np.maximum.accumulate(which)
    which = np.maximum(which, 0)
    return np.asarray(values, dtype=np.float64)[which]
