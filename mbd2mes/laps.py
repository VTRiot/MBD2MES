# -*- coding: utf-8 -*-
"""laps.py -- ヘッダのコントロールライン（docs/mbd_format.md §2 [実測]）を GPS 軌跡が横切る時刻から、ラップの境目を作る。

MBD にラップタイムのレコードは無い（§7.2）。境目 = 線を横切った時刻の標本番号 + その時の累積距離（.IXR の語）。
形は RCZ2MES の lap_sections.plan_laps と同じ（境目 N 本 = Analyzer の一覧は N + 1 本。先頭は最初の通過より前、末尾は最後の通過より後）。
横切る向きは、いちばん多い向きだけを数える（逆向きの通過は警告して捨てる）。セクターは MBD に無いので書かない。
標本番号 = floor(t * Hz + 0.5)。距離は GPS 点列の弦長の累積（基準点は最初の測位。§5 の経路長の確認と同じ方法）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import lap_files
from .timeline import sample_count

EARTH_RADIUS_M = 6371008.8  # 物理の定数（RCZ2MES lap_sections.EARTH_RADIUS_M と同じ値）
ROUND_HALF = 0.5  # floor(x + 0.5) の四捨五入


@dataclass
class LapPlan:
    boundaries: list[tuple[int, int]] = field(default_factory=list)  # (標本番号, 累積距離 m)
    end_sample: int = 0
    end_dist_m: int = 0
    sections: list[tuple[int, int]] = field(default_factory=list)  # MBD にセクターは無い（常に空）
    crossing_times_s: list[float] = field(default_factory=list)  # 境目の時刻（t = 0 から。標本への丸め前）
    lap_times_s: list[float] = field(default_factory=list)  # 隣り合う通過の間隔
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def analyzer_count(self) -> int:
        return len(self.boundaries) + 1 if self.boundaries else 0


def _project(lat: np.ndarray, lon: np.ndarray, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    """緯度経度（度）を、(lat0, lon0) を原点とする平面（東・北 m）へ。線の周りの小さな範囲での近似。"""
    x = np.radians(lon - lon0) * math.cos(math.radians(lat0)) * EARTH_RADIUS_M
    y = np.radians(lat - lat0) * EARTH_RADIUS_M
    return x, y


def cumulative_distance_m(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """最初の測位から各測位までの累積距離 [m]（隣り合う点の弦長。区間ごとの中間の緯度で東西を縮める）。"""
    dx = np.radians(np.diff(lon)) * np.cos(np.radians((lat[1:] + lat[:-1]) / 2)) * EARTH_RADIUS_M
    dy = np.radians(np.diff(lat)) * EARTH_RADIUS_M
    return np.concatenate([[0.0], np.cumsum(np.hypot(dx, dy))])


def find_crossings(lat, lon, t_s, line) -> list[tuple[float, float, int]]:
    """線 (緯度 A, 経度 A, 緯度 B, 経度 B) を軌跡が横切る点の (時刻 s, 累積距離 m, 向き ±1)。

    隣り合う 2 測位が線の両側に分かれ、交点が線分 AB の上にあるものだけ。時刻と距離は 2 測位の間を線形補間する。
    """
    lat = np.asarray(lat, dtype=np.float64)
    lon = np.asarray(lon, dtype=np.float64)
    if len(lat) < 2:
        return []
    a_lat, a_lon, b_lat, b_lon = line
    lat0, lon0 = (a_lat + b_lat) / 2, (a_lon + b_lon) / 2
    x, y = _project(lat, lon, lat0, lon0)
    ax, ay = _project(np.array([a_lat]), np.array([a_lon]), lat0, lon0)
    bx, by = _project(np.array([b_lat]), np.array([b_lon]), lat0, lon0)
    ex, ey = float(bx[0] - ax[0]), float(by[0] - ay[0])  # 線の向き
    length2 = ex * ex + ey * ey
    if length2 == 0:
        return []
    side = ex * (y - ay[0]) - ey * (x - ax[0])  # 線のどちら側か（外積）
    neg = side < 0
    cum = cumulative_distance_m(lat, lon)
    out: list[tuple[float, float, int]] = []
    for i in np.nonzero(neg[:-1] != neg[1:])[0]:
        frac = side[i] / (side[i] - side[i + 1])
        px = x[i] + frac * (x[i + 1] - x[i])
        py = y[i] + frac * (y[i + 1] - y[i])
        u = ((px - ax[0]) * ex + (py - ay[0]) * ey) / length2  # 線分 AB の上の位置（0..1）
        if not 0.0 <= u <= 1.0:
            continue
        t = float(t_s[i] + frac * (t_s[i + 1] - t_s[i]))
        d = float(cum[i] + frac * (cum[i + 1] - cum[i]))
        out.append((t, d, 1 if side[i + 1] > side[i] else -1))
    return out


def plan_laps(lat, lon, t_s, line, base_hz: int, span_ms: int) -> LapPlan:
    plan = LapPlan()
    plan.end_sample = sample_count(span_ms, base_hz)
    if len(lat) < 2:
        plan.notes.append("no lap boundary: fewer than 2 GPS fixes")
        return plan
    cum = cumulative_distance_m(np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64))
    plan.end_dist_m = int(round(float(cum[-1])))
    crossings = find_crossings(lat, lon, t_s, line)
    if crossings:
        forward = sum(1 for c in crossings if c[2] > 0)
        keep = 1 if forward * 2 >= len(crossings) else -1  # 同数なら + 向き
        dropped = [c for c in crossings if c[2] != keep]
        crossings = [c for c in crossings if c[2] == keep]
        if dropped:
            plan.warnings.append(f"{len(dropped)} control-line crossing(s) in the opposite direction were not used "
                                 f"(times: {', '.join(f'{c[0]:.1f}s' for c in dropped)})")
    last = -1
    for t, d, _dir in crossings:
        sample = math.floor(t * base_hz + ROUND_HALF)
        if sample < 0 or sample > plan.end_sample:
            plan.warnings.append(f"a control-line crossing at {t:.3f} s is outside the recording; not used")
            continue
        if sample <= last:
            plan.warnings.append(f"a control-line crossing at {t:.3f} s falls on the same sample as the previous one; not used")
            continue
        plan.boundaries.append((sample, int(round(d))))
        plan.crossing_times_s.append(t)
        last = sample
    if len(plan.boundaries) > lap_files.MAX_BOUNDARIES:
        plan.warnings.append(f"{len(plan.boundaries)} boundaries exceed the .IXR limit {lap_files.MAX_BOUNDARIES}; laps not written")
        plan.boundaries.clear()
        plan.crossing_times_s.clear()
    plan.lap_times_s = [b - a for a, b in zip(plan.crossing_times_s[:-1], plan.crossing_times_s[1:])]
    if len(plan.boundaries) < 2:
        plan.notes.append("fewer than 2 control-line crossings: no completed lap; .IXR not written")
        plan.boundaries.clear()
        plan.crossing_times_s.clear()
    return plan
