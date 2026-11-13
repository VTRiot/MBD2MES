# -*- coding: utf-8 -*-
"""convert.py -- .MBD 1 本から .MES 1 フォルダを作る（CLI はすべて convert_one() を通る）。

処理: 読む(mbd_reader) -> チャンネルの物理量(channels) -> 零次ホールドで格子へ(timeline)
      -> 16 bit は ddd_generator.build_entries、位置は gps_entries の 32 bit -> mes_writer で書く
      -> HED([DOWNLOAD]・[GPS]) -> ラップ(laps・lap_files) -> ddd_invariants -> 記録ファイル MBD2MES_record.txt
      -> 出力先の中の作業フォルダで完成させてから入れ替える（RCZ2MES convert_one と同じ作法）。

写した部分（mes_writer・ddd_generator・gps_entries ほか）は docs/provenance.md。
"""

from __future__ import annotations

import datetime
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import channels as chmod
from . import ddd_generator as dg
from . import ddd_invariants as di
from . import event_ini
from . import gps_entries as ge
from . import hed_download
from . import lap_files
from . import laps as lapmod
from . import mes_writer as mw
from . import timeline as tl
from .mbd_reader import SECONDS_PER_DAY, TICK_MS, MbdError, MbdFile, read_mbd

RECORD_NAME = "MBD2MES_record.txt"
RECORD_ENCODING = "utf-8"
STAGE_PREFIX = ".mbd2mes_stage_"  # 出力先の中の作業フォルダ（完成してから入れ替える）
OLD_NAME = "previous.MES"
VARIANT = ge.DEFAULT_VARIANT  # V4: Latitude/Longitude/V_GPS + HED [GPS] + 機器の印（RCZ2MES で地図が出た形）
SECONDS_PER_MINUTE = 60
UNIX_EPOCH = datetime.date(1970, 1, 1)
DAY_SEARCH = (-1, 0, 1)  # mtime から日付を決めるとき、近い日を探す範囲


class ConvertError(Exception):
    """変換できない（出力先が既にある、南緯・西経、書けるチャンネルが無い、など）。"""


class InvariantViolationError(ConvertError):
    def __init__(self, violations: list[str]):
        self.violations = list(violations)
        super().__init__("DDD invariant violations: %d\n%s" % (len(violations), "\n".join(f"  - {v}" for v in violations)))


@dataclass
class ChannelRecord:
    name: str
    unit: str
    rate: int
    divisor: int
    samples: int
    bits: int
    source: str
    lead_samples: int = 0  # 最初のレコードより前（最初の値で埋めた標本数）


@dataclass
class ConvertResult:
    mes_dir: Path
    mes_name: str
    t0_ms: int
    start_source: str
    span_ms: int
    base_hz: int
    channels: list[ChannelRecord]
    skipped: list[tuple[str, str]]
    warnings: list[str]
    violations: list[str]
    record_text: str
    lap_plan: lapmod.LapPlan | None
    lap_file_names: list[str]
    input_path: Path
    input_sha256: str


class ArraySource:
    """ddd_generator.build_entries に渡す入力の口（channel_meta／read_channel を持つ）。"""

    def __init__(self, rows: list[tuple[str, str, int, np.ndarray]]):
        self._rows = rows

    def channel_meta(self, path) -> list[dict]:  # noqa: ARG002
        return [{"name": n, "unit": u, "freq": float(r), "_index": i} for i, (n, u, r, _v) in enumerate(self._rows)]

    def read_channel(self, path, meta: dict) -> np.ndarray:  # noqa: ARG002
        return self._rows[meta["_index"]][3]


def sanitize_mes_name(stem: str) -> str:
    """[A-Za-z0-9-] 以外を - に、連続を畳み、前後の - を除く（RCZ2MES・LD2MES と同じ規則）。"""
    collapsed = re.sub(r"-+", "-", re.sub(r"[^A-Za-z0-9-]", "-", stem))
    return collapsed.strip("-") or "MBD"


def recording_start_ms(utc0_s: float | None, duration_s: float, date: datetime.date | None, mtime_s: float,
                       offset_min: int = hed_download.JST_OFFSET_MIN) -> tuple[int, str]:
    """tick 0 の時刻（UTC の Unix ms）と、その決め方の説明。

    日付は MBD の中に無い（docs/mbd_format.md §2）。時刻（UTC の時分秒）は GPS から取る。
      date 指定あり : date は現地（offset_min）の日付。GPS の時刻と組み合わせる
      date なし     : 入力ファイルの更新時刻（記録の終わり付近のはず）に最も近い日を選ぶ
      GPS なし      : 更新時刻 - 記録の長さ
    """
    if utc0_s is None:
        return int(round((mtime_s - duration_s) * 1000)), "file modification time (no GPS time in the file)"
    tod = utc0_s % SECONDS_PER_DAY
    if date is not None:
        local_tod = tod + offset_min * SECONDS_PER_MINUTE
        if local_tod >= SECONDS_PER_DAY:
            local_tod -= SECONDS_PER_DAY  # date は現地の日付のまま（記録は現地の同じ日の中に収まるとみなす）
        local_epoch = (date - UNIX_EPOCH).days * SECONDS_PER_DAY + local_tod
        return int(round((local_epoch - offset_min * SECONDS_PER_MINUTE) * 1000)), f"--date {date.isoformat()} (local) + GPS time of day"
    base_day = int(mtime_s // SECONDS_PER_DAY)
    best = min((d for d in (base_day + k for k in DAY_SEARCH)),
               key=lambda d: abs(d * SECONDS_PER_DAY + tod + duration_s - mtime_s))
    return int(round((best * SECONDS_PER_DAY + tod) * 1000)), "date from file modification time + GPS time of day (pass --date to set it)"


def _build_record(res_input: Path, sha: str, mbd: MbdFile, name: str, t0_ms: int, start_source: str, start_local: str,
                  span_ms: int, base_hz: int, records: list[ChannelRecord], skipped, warnings, utc0_s, gps_info: str,
                  plan: lapmod.LapPlan | None, violations: list[str]) -> str:
    L = ["MBD2MES record", f"Input: {res_input}", f"Input SHA-256: {sha}", f"MBD version: {mbd.version}  course: {mbd.course}",
         f"MES name: {name}", f"Variant: {VARIANT}",
         f"t0: {t0_ms} ms (UTC {datetime.datetime.fromtimestamp(t0_ms / tl.MS_PER_S, tz=datetime.timezone.utc).isoformat(timespec='milliseconds')})",
         f"Start in HED [DOWNLOAD]: {start_local} (UTC{hed_download.format_timezone(hed_download.JST_OFFSET_MIN)}); date source: {start_source}"]
    if utc0_s is not None:
        L.append(f"GPS time of day at tick 0: {utc0_s % SECONDS_PER_DAY:.3f} s UTC")
    L += [f"Ticks: {mbd.n_ticks} ({TICK_MS} ms each)", f"Length T: {span_ms / tl.MS_PER_S:.3f} s", f"Base Hz: {base_hz}",
          gps_info, f"Channels written: {len(records)}"]
    for c in records:
        lead = f" | first {c.lead_samples} samples hold the first value" if c.lead_samples else ""
        L.append(f"  {c.name} | {c.unit or '-'} | {c.rate} Hz | divisor {c.divisor} | {c.samples} samples | {c.bits} bit | {c.source}{lead}")
    if mbd.warnings or warnings:
        L.append(f"Warnings: {len(mbd.warnings) + len(warnings)}")
        L += [f"  {w}" for w in mbd.warnings + warnings]
    L.append(f"Channels not written: {len(skipped)}")
    L += [f"  {n}: {why}" for n, why in skipped]
    L.append("Laps (control line from the MBD header crossed by the GPS track):")
    if plan is None or not plan.boundaries:
        L.append("  none")
        if plan is not None:
            L += [f"  {x}" for x in plan.notes]
    else:
        L.append(f"  boundaries: {len(plan.boundaries)} -> Analyzer lists {plan.analyzer_count} laps "
                 f"(#0 = before the first crossing, #{plan.analyzer_count - 1} = after the last)")
        for i, (s, d) in enumerate(plan.boundaries):
            L.append(f"    boundary {i}: sample {s} ({s / base_hz:.3f} s), distance {d} m")
        for i, lt in enumerate(plan.lap_times_s, start=1):
            L.append(f"    Analyzer #{i}: {lt:.3f} s")
        L.append(f"  record end: sample {plan.end_sample}, distance {plan.end_dist_m} m")
        L.append("  not written: sectors (none in MBD), .LAP, HED [SectionTimes]")
    L.append("Invariant check: " + ("PASS" if not violations else "FAIL"))
    L += [f"  {v}" for v in violations]
    return "\n".join(L) + "\n"


def convert_one(mbd_path, out_dir, *, mes_name: str | None = None, force: bool = False,
                date: datetime.date | None = None, log=None) -> ConvertResult:
    log = log or (lambda _t: None)
    mbd_path, out_dir = Path(mbd_path), Path(out_dir)
    mbd = read_mbd(mbd_path)
    name = sanitize_mes_name(mes_name if mes_name is not None else mbd_path.stem)
    warnings: list[str] = []

    def warn(text: str) -> None:
        warnings.append(text)
        log(text)

    var = ge.get_variant(VARIANT)
    name_lat, name_lon, name_spd = (var.rename[k] for k in ("Lat_dez", "Lon_dez", "V_Sat"))
    span_ms = mbd.duration_ms
    plans, skipped, chan_warnings = chmod.plan_channels(mbd)
    for w in chan_warnings:
        warn(w)

    # ---- 16 bit のチャンネル（車両系は 1 標本 = 1 tick）
    narrow_rows: list[tuple[str, str, int, np.ndarray]] = []
    narrow_src: list[str] = []
    narrow_lead: list[int] = []
    n_tick_grid = tl.sample_count(span_ms, tl.TICK_RATE_HZ)
    for p in plans:
        values, lead = tl.hold_ticks(p.ticks, p.values, n_tick_grid, tl.TICK_RATE_HZ)
        narrow_rows.append((p.name, p.unit, tl.TICK_RATE_HZ, values))
        narrow_src.append(p.source)
        narrow_lead.append(lead)

    # ---- GPS（Latitude / Longitude は 32 bit、V_GPS は 16 bit）
    g = mbd.gps
    utc0 = None
    wide_rows: list[tuple[str, str, int, np.ndarray]] = []
    t_gps = None
    gps_info = "GPS: none"
    if len(g) >= 2:
        if not (g.north_only and g.east_only):
            raise ConvertError("GPS fixes in the southern or western hemisphere are not supported (Nothing was written)")
        # tick 0 の UTC: 全測位の (UTC - tick*5ms) の中央値（docs/mbd_format.md §7.2）
        utc0 = float(np.median(g.utc_s - g.tick * TICK_MS / tl.MS_PER_S))
        t_gps = g.utc_s - utc0
        steps = np.diff(g.utc_s)
        steps = steps[steps > 0]
        if len(steps) == 0:
            raise ConvertError("GPS times do not increase; cannot decide the GPS rate")
        gps_rate = tl.choose_rate(float(np.median(steps)))
        n_gps = tl.sample_count(span_ms, gps_rate)
        narrow_rows.append((name_spd, "km/h", gps_rate, tl.hold_fixes(t_gps, g.speed_kmh, n_gps, gps_rate)))
        narrow_src.append("GPS block speed (0.01 km/h units)")
        narrow_lead.append(0)
        wide_rows.append((name_lat, "deg", gps_rate, tl.hold_fixes(t_gps, g.lat_deg, n_gps, gps_rate)))
        wide_rows.append((name_lon, "deg", gps_rate, tl.hold_fixes(t_gps, g.lon_deg, n_gps, gps_rate)))
        gps_info = (f"GPS: {len(g)} fixes, written at {gps_rate} Hz (median fix interval {np.median(steps):.3f} s); "
                    "fix time = GPS UTC - tick-0 UTC")
    else:
        warn("[WARN] fewer than 2 GPS fixes: Latitude/Longitude/V_GPS and laps are not written (no map)")
    if not narrow_rows:
        raise ConvertError("no channel can be written (all channels are empty)")

    source = ArraySource(narrow_rows)
    result = dg.build_entries(source, mbd_path)
    entries = list(result.entries)
    values_by_name = dict(result.values_by_name)
    base_hz = result.base_hz
    if base_hz != tl.BASE_HZ:
        raise ConvertError(f"base Hz {base_hz} differs from the fixed {tl.BASE_HZ}; a channel rate does not divide it")
    if len(entries) != len(narrow_rows):
        raise ConvertError(f"build_entries wrote {len(entries)} of {len(narrow_rows)} channels: {result.skipped}")
    skipped_gen = list(result.skipped)
    for row, e in zip(narrow_rows, entries):
        if e.name != row[0]:
            warn(f"[WARN] channel name {row[0]!r} was written as {e.name!r}")
    layout = list(zip(entries, narrow_rows, narrow_src, narrow_lead))
    for nm, unit, rate, values in wide_rows:
        if nm in values_by_name:
            raise ConvertError(f"channel name {nm!r} is duplicated")
        entry = ge.make_wide_entry(len(entries) + 1, nm, unit, values, rate, base_hz, skipped_gen)
        entries.append(entry)
        values_by_name[nm] = values
        layout.append((entry, (nm, unit, rate, values), "GPS block position (1/6,000,000 deg units)", 0))
    skipped.extend(skipped_gen)
    ge.apply_marks(entries, var.marks)

    # ---- 開始日時
    mtime_s = mbd_path.stat().st_mtime
    t0_ms, start_source = recording_start_ms(utc0, span_ms / tl.MS_PER_S, date, mtime_s)
    start_local = hed_download.start_text(t0_ms)

    # ---- 書き出し先
    final_dir = out_dir / f"{name}.MES"
    if final_dir.exists():
        if not force:
            raise ConvertError(f"output already exists: {final_dir} (use --force to replace)")
        if not any(final_dir.glob("*.DDD")):
            raise ConvertError(f"refusing to replace {final_dir}: it does not look like a MES (no .DDD)")
    out_dir.mkdir(parents=True, exist_ok=True)
    for text in event_ini.check(out_dir, name_lat, name_lon):
        warn(text)

    stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=out_dir))
    keep_stage = False
    try:
        staged = mw.write_reconstructed_mes(stage, name, entries, values_by_name)
        (staged / f"{name}.HED").write_bytes(hed_download.render_hed(t0_ms, base_hz, var.write_hed and t_gps is not None))
        plan, lap_written = _write_laps(mbd, g, t_gps, staged, name, base_hz, span_ms, warn)
        violations = di.check_ddd_invariants(staged / f"{name}.DDD", staged, name)
        if violations:
            raise InvariantViolationError(violations)
        records = [ChannelRecord(e.name, e.unit, rate, e.divisor, len(values), e.bit_width, src, lead)
                   for e, (_n, _u, rate, values), src, lead in layout]
        record = _build_record(mbd_path, mbd.sha256, mbd, name, t0_ms, start_source, start_local, span_ms, base_hz,
                               records, skipped, warnings, utc0, gps_info, plan, violations)
        (staged / RECORD_NAME).write_bytes(record.encode(RECORD_ENCODING))
        if final_dir.exists():
            final_dir.rename(stage / OLD_NAME)
            try:
                staged.rename(final_dir)
            except OSError:
                try:
                    (stage / OLD_NAME).rename(final_dir)
                except OSError as rollback_exc:
                    keep_stage = True
                    raise ConvertError(f"could not replace {final_dir} and could not restore the previous MES; "
                                       f"it is kept at {stage / OLD_NAME} ({rollback_exc})") from rollback_exc
                raise
        else:
            staged.rename(final_dir)
    finally:
        if not keep_stage:
            shutil.rmtree(stage, ignore_errors=True)
    return ConvertResult(final_dir, name, t0_ms, start_source, span_ms, base_hz, records, skipped, warnings, violations,
                         record, plan, lap_written, mbd_path, mbd.sha256)


def _write_laps(mbd: MbdFile, g, t_gps, staged: Path, name: str, base_hz: int, span_ms: int, warn):
    """ラップ（.IXR）を作業フォルダへ書く。(計画, 書いたファイル名)。想定外の失敗でもチャンネルは書く（黙って省かず警告）。"""
    if t_gps is None:
        return None, []
    try:
        plan = lapmod.plan_laps(g.lat_deg, g.lon_deg, t_gps, mbd.control_line, base_hz, span_ms)
        written = lap_files.write_lap_files(staged, name, plan, base_hz)
    except Exception as exc:  # noqa: BLE001 -- ラップの失敗でチャンネルの変換を止めない
        (staged / f"{name}.IXR").unlink(missing_ok=True)
        warn(f"[WARN] Laps were not written: {exc!r}")
        return None, []
    for text in plan.warnings:
        warn(f"[WARN] {text}")
    return plan, written


def summary_lines(res: ConvertResult) -> list[str]:
    plan = res.lap_plan
    laps = "Laps           : none" if plan is None or not plan.boundaries else \
        f"Laps           : {len(plan.boundaries)} boundaries ({plan.analyzer_count} in Analyzer)"
    return [f"Input          : {res.input_path}", f"Output         : {res.mes_dir}", f"Channels       : {len(res.channels)}",
            f"Base Hz        : {res.base_hz}", f"Start (HED)    : {hed_download.start_text(res.t0_ms)} [{res.start_source}]",
            f"Not written    : {len(res.skipped)}", laps,
            "Invariant check: " + ("PASS" if not res.violations else f"FAIL ({len(res.violations)})")]


__all__ = ["ConvertError", "InvariantViolationError", "ConvertResult", "convert_one", "summary_lines",
           "sanitize_mes_name", "recording_start_ms", "MbdError"]
