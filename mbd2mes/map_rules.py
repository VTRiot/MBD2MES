# -*- coding: utf-8 -*-
"""map_rules.py -- 対応表（channel_map）の MBD2MES 固有の決まり: 保護する行と、変換への橋渡し。

RCZ2MES の map_rules.py（commit 5b31da8）から、必要な部分だけを写して直した（docs/provenance.md の「改変の要点」）:
  - 残した: PROTECTED_NAMES・is_protected・protected_warnings・make_apply_fn（保護する行を恒等に・候補の絞り込みを足した）・
    make_scaling_fn・grow_with_defaults（default_output を使わない形に）・load_map。
  - 削った: 「出す／出さない」の欄 output（頼まれていない）・CAN_<id> の行の移し替え（RCZ の固有）。

保護する行（PROTECTED_NAMES）: Latitude・Longitude・V_GPS。名前・倍率・オフセットのどれを変えても 2D Analyzer で地図が出なくなる
（docs/lessons_rcz.md・mes_format_Part2.md §7）ので、GUI で変えられなくし、対応表のファイルを手で書き換えられていても変換では
無視して警告する。
"""

from __future__ import annotations

import math

from . import channel_map as cmapmod
from . import ddd_generator as dg

PROTECTED_NAMES = ("Latitude", "Longitude", "V_GPS")
FIXED_MESSAGE = "Fixed: this channel is required for the map in 2D Analyzer."


def is_protected(name: str) -> bool:
    return name in PROTECTED_NAMES


def _entry(channel_map: dict | None, name: str) -> dict | None:
    if not isinstance(channel_map, dict):
        return None
    entry = channel_map.get("channels", {}).get(name)
    return entry if isinstance(entry, dict) else None


def _as_float(value, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def protected_warnings(channel_map: dict | None) -> list[str]:
    """保護する行に、既定と違う設定（単位・任意名・倍率・オフセット）が入っているときの警告の文。"""
    out: list[str] = []
    for name in PROTECTED_NAMES:
        entry = _entry(channel_map, name)
        if entry is None:
            continue
        custom = entry.get("custom_name")
        unit = entry.get("unit")
        raw_unit = entry.get("raw_unit")
        deviates = (
            (isinstance(custom, str) and custom != "")
            or (isinstance(unit, str) and unit != raw_unit)
            or _as_float(entry.get("multiplier", 1.0), 1.0) != 1.0
            or _as_float(entry.get("offset", 0.0), 0.0) != 0.0
        )
        if deviates:
            out.append(f"[WARN] {name}: the channel map setting is ignored (fixed channel)")
    return out


def _name_writable(name: str) -> bool:
    """build_entries と同じ判定: sanitize_name の結果が cp1252 で書けるか（判定は写した ddd_generator の関数そのもの）。"""
    try:
        dg.sanitize_name(name).encode("cp1252", errors="strict")
    except UnicodeEncodeError:
        return False
    return True


def make_apply_fn(channel_map: dict | None, calls: list, dropped: list):
    """build_entries に渡す apply_map_fn。保護する行と、対応表が無いときは恒等。

    cp1252 で書けない候補は、build_entries が捨てる前にここで取り除く（取り除いた列がそのまま entry の並びになるので、
    convert.py が entry と元の行の対応を作り直すときに、build_entries の規則を再実装せずに済む）。
    取り除いた候補は dropped へ (生の名前, 候補の名前) で記録する。
    呼ばれた順に (生の名前, 残した [(名前, 単位), ...], 各候補が任意名のコピーか [bool, ...]) を calls へ記録する。
    """

    def apply_fn(raw_name: str, raw_unit: str) -> list[tuple[str, str]]:
        if channel_map is None or is_protected(raw_name):
            candidates = [(raw_name, raw_unit)]
        else:
            candidates = cmapmod.apply_channel_map(raw_name, raw_unit, channel_map)
        kept = []
        is_copy = []
        for i, (cand_name, cand_unit) in enumerate(candidates):
            # 元の候補（i == 0）の名前の判定は build_entries と同じく raw_name で行う
            if _name_writable(raw_name if i == 0 else cand_name):
                kept.append((cand_name, cand_unit))
                is_copy.append(i != 0)
            else:
                dropped.append((raw_name, cand_name))
        calls.append((raw_name, kept, is_copy))
        return kept

    return apply_fn


def make_scaling_fn(channel_map: dict | None):
    """build_entries に渡す get_scaling_fn。保護する行と、対応表が無いときは (1.0, 0.0)。"""

    def scale_fn(raw_name: str) -> tuple[float, float]:
        if channel_map is None or is_protected(raw_name):
            return 1.0, 0.0
        return cmapmod.get_channel_scaling(channel_map, raw_name)

    return scale_fn


def grow_with_defaults(channel_map: dict, rows) -> int:
    """書いた（書こうとした）チャンネルの名前のうち、対応表に無いものを素の状態で足す（自動成長）。
    rows は (名前, 単位, ...) の列。戻り値は足した行数。"""
    metas = [{"name": r[0], "unit": r[1]} for r in rows]
    _, added = cmapmod.grow_channel_map(channel_map, metas)
    return added


def load_map(base=None, fallback_base=None) -> dict:
    """対応表を読む（無ければ seed から作る。壊れていれば退避して空で続ける。channel_map.load_or_init_map の写し）。"""
    return cmapmod.load_or_init_map(base=base, fallback_base=fallback_base)


def save_map_preserving_others(data: dict, deleted: set[str] | frozenset[str] = frozenset(), base=None, fallback_base=None):
    """GUI の保存。ディスクの最新を読み直し、GUI がまだ見ていない行（ディスクにあって data に無く、この窓で削除もしていない行）を
    保ってから、data の全内容を保存する（GUI-master。他プロセスの自動成長が足した行を、古いメモリで消さない）。
    ディスクが読めない・壊れているときは、data だけを保存する。保存した Path を返す。"""
    import json

    merged = json.loads(json.dumps({k: v for k, v in data.items() if not k.startswith("_")}))
    channels = merged.setdefault("channels", {})
    try:
        disk = json.loads(cmapmod.map_path(base=base, fallback_base=fallback_base).read_text(encoding="utf-8"))
        disk_channels = disk.get("channels") if isinstance(disk, dict) else None
    except (OSError, ValueError):
        disk_channels = None
    if isinstance(disk_channels, dict):
        for name, entry in disk_channels.items():
            if name not in channels and name not in deleted and not name.startswith("_") and isinstance(entry, dict):
                channels[name] = entry
    return cmapmod.save_map(merged, base=base, fallback_base=fallback_base)
