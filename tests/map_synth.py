# -*- coding: utf-8 -*-
"""対応表の試験用の合成 MBD と、期待値。期待値は生値からの手計算（変換器のコードを通さない）。

チャンネル（番号 = 並び）: 0 SysV / 1 GPS1 / 2 GPS2 / 3 Ne / 4 THP / 5 GYROAN / 6 GPSspd / 7 LAF
41 tick（205 ms・200 Hz）。GPS は 8 tick（25 Hz）ごとに 6 本。LAF の最初の記録は tick 6（先頭の 6 標本は最初の値で埋まる）。
"""

from __future__ import annotations

import numpy as np
import synth_mbd as sm

LAT0, LON0 = 208_800_000, 819_000_000  # 34.8 deg, 136.5 deg（1/6,000,000 度）
N_TICK = 41


def channels():
    return [
        sm.entry("SysV", "V"), sm.entry("GPS1"), sm.entry("GPS2"),
        sm.entry("Ne", "rpm", can_id=0x6A0),
        sm.entry("THP", "%", can_id=0x6A1, a=1000, b=10000, fmt=1, mode=3),
        sm.entry("GYROAN", "deg", can_id=0x6A5, a=1000, b=200000, fmt=5, mode=3),
        sm.entry("GPSspd", "km/h", a=1000, b=1000, mode=3),
        sm.entry("LAF", "afr", can_id=0x6A6, a=9000, b=255000, c=9000, fmt=2, mode=3),
    ]


def ticks():
    out = []
    for tk in range(N_TICK):
        recs = []
        if tk % 8 == 0:
            k = tk // 8
            recs.append((1, sm.gps_block(LAT0 + 1000 * k, LON0 + 2000 * k, 1000 * k, 564360 + 4 * k)))
        if tk == 0:
            recs += [(3, 3000), (4, 500), (5, 65535)]
        if tk == 6:
            recs.append((7, 13))
        if tk == 10:
            recs.append((3, 4000))
        if tk == 12:
            recs.append((7, 213))
        if tk == 20:
            recs.append((4, 1000))
        if tk == 25:
            recs.append((3, 5000))
        if tk == 30:
            recs.append((5, 1000))
        out.append(recs)
    return out


def write(path, course="test"):
    """course を変えると、同じ内容の別のファイル（SHA-256 が違う）になる。"""
    path.write_bytes(sm.build_mbd(channels(), ticks(), course=course))
    return path


def expected():
    """名前 -> 200 Hz の 41 標本の物理量（生値 -> 式 -> 零次ホールド。手計算）。"""
    ne = np.array([3000] * 10 + [4000] * 15 + [5000] * 16, float)
    thp = np.array([500] * 20 + [1000] * 21, float) * 1000 / 10000  # A/B = 1000/10000
    gyro = np.array([-1] * 30 + [1000] * 11, float) * 1000 / 200000  # 65535 は int16 で -1
    laf = np.array([13] * 12 + [213] * 29, float) * 9000 / 255000 + 9  # tick 6 より前は最初の値で埋まる
    sysv = np.zeros(N_TICK)
    return {"SysV": sysv, "Ne": ne, "THP": thp, "GYROAN": gyro, "LAF": laf}


def lead_of_laf() -> int:
    return 6
