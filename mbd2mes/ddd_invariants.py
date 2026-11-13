# -*- coding: utf-8 -*-
"""ddd_invariants.py -- 生成 DDD の不変量チェック（LD2MES_Converter Phase2 CP1 A-2）。

`mes_reader.parse_ddd()` を使わず、DDD テキストを独自の正規表現で直読みする
（reader がスキップした行も検査対象にするため。Phase1 の教訓: 「未検証の
基準物との一致は無意味」）。

保証範囲: DDD テキストの内部整合とデータファイルの実在を検査する。
2D Analyzer が実際にどう解釈・表示するかは保証しない。本チェックの `1=`
第1判定は**自ツール出力専用**（実走 2D ファイルは `20`/`100`/`102` 等も
使うため、他ツール由来の DDD には適用できない）。
"""

from __future__ import annotations

import re
from pathlib import Path

_SECTION_RE = re.compile(r'^\[([^\[\]]+)\]$')
_KEY_RE = re.compile(r'^([^=\r\n]+)=(.*)$')

_VISIBLE_TYPE = "4"  # 本ツール（ddd_generator）が常にこの値を書く（自ツール出力専用の前提）
_DATA_EXT_RE = re.compile(r'^A[0-9A-Z]{2}$')  # data_ext_for() が生成する形式


def _split_fields(raw: str) -> list[str]:
    """カンマ区切りのフィールド分割。ダブルクォート内のカンマは分割しない。

    mes_reader._split_fields と同一ロジック（直読み方針のため独立実装）。
    """
    fields: list[str] = []
    buf: list[str] = []
    in_quotes = False
    for ch in raw:
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == "," and not in_quotes:
            fields.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    fields.append("".join(buf))
    return [f.strip() for f in fields]


def parse_raw_sections(ddd_path: Path) -> list[dict]:
    """DDD を [{"id": str, "keys": {key: value_str}}] のリストへ変換する。順序保持。"""
    text = ddd_path.read_bytes().decode("cp1252", errors="strict")
    sections: list[dict] = []
    cur: dict | None = None
    for line in text.split("\r\n"):
        m = _SECTION_RE.match(line)
        if m:
            cur = {"id": m.group(1), "keys": {}}
            sections.append(cur)
            continue
        if cur is None or not line.strip():
            continue
        m = _KEY_RE.match(line)
        if m:
            cur["keys"][m.group(1)] = m.group(2)
    return sections


def check_ddd_invariants(
    ddd_path: Path,
    mes_dir: Path | None = None,
    mes_basename: str | None = None,
) -> list[str]:
    """違反メッセージのリストを返す（空 = PASS）。

    mes_dir/mes_basename を渡すと不変量#2のデータファイル実在チェックも行う
    （省略時はそのチェックのみスキップする）。
    """
    violations: list[str] = []
    sections = parse_raw_sections(ddd_path)

    # チャンネル節 = 1=/4=/6= を持つ節（mes_reader.parse_ddd と同じ判定基準）
    chan_secs = [s for s in sections if all(k in s["keys"] for k in ("1", "4", "6"))]

    # #1: 1= 第1フィールドが本ツール可視種別と一致し、かつ 1000x 系(>=10000)が0件
    for s in chan_secs:
        f1 = _split_fields(s["keys"]["1"])
        v1_str = f1[0] if f1 else ""
        if v1_str != _VISIBLE_TYPE:
            violations.append(f"[{s['id']}] 1= 1st field is not {_VISIBLE_TYPE!r}: {v1_str!r}")
        # 1= 第1フィールド（表示種別）は10進表記（実測: "1"/"2"/"4"/"20"/"100"/
        # "101"/"102"/"104"/"1000"/"10001"/"10002"/"10004" 等、常に純粋な10進数字列）。
        try:
            v1_int = int(v1_str)
        except ValueError:
            v1_int = None
        if v1_int is not None and v1_int >= 10000:
            violations.append(f"[{s['id']}] 1= 1st field is hidden/internal (>=10000): {v1_str!r}")

    # #2: 6= 第4フィールド（データ拡張子）の一意性 + ファイル実在
    # r2 コードレビュー finding[1]: ext="" を「非重複なら無罪」にすると
    # 1ch だけ拡張子欠落した壊れた DDD を検出できない。空欄・形式不正は
    # ここで即違反にする（data_ext_for が生成する形式 A[0-9A-Z]{2} が正）。
    ext_owners: dict[str, list[str]] = {}
    for s in chan_secs:
        f6 = _split_fields(s["keys"]["6"])
        ext = f6[3] if len(f6) > 3 else ""
        if not ext:
            violations.append(f"[{s['id']}] 6= 4th field (data extension) is empty")
            continue
        if not _DATA_EXT_RE.match(ext):
            violations.append(f"[{s['id']}] 6= 4th field (data extension) invalid format: {ext!r}")
        ext_owners.setdefault(ext, []).append(s["id"])
    for ext, ids in ext_owners.items():
        if len(ids) > 1:
            violations.append(f"6= 4th field (data extension) {ext!r} duplicated: section {ids}")
        if mes_dir is not None and mes_basename is not None:
            data_file = mes_dir / f"{mes_basename}.{ext}"
            if not data_file.exists():
                violations.append(f"6= 4th field (data extension) {ext!r} data file does not exist: {data_file}")

    # #3: 4= 第1フィールド（name）の一意性
    name_owners: dict[str, list[str]] = {}
    for s in chan_secs:
        f4 = _split_fields(s["keys"]["4"])
        name = f4[0] if f4 else ""
        name_owners.setdefault(name, []).append(s["id"])
    for name, ids in name_owners.items():
        if len(ids) > 1:
            violations.append(f"4= 1st field (name) {name!r} duplicated: section {ids}")

    # #4: 6= 第6フィールド（通し番号・16進）の集合が {1..N} と一致
    indices: list[int] = []
    for s in chan_secs:
        f6 = _split_fields(s["keys"]["6"])
        idx_str = f6[5] if len(f6) > 5 else ""
        if not idx_str:
            violations.append(f"[{s['id']}] 6= 6th field (sequence number) is empty")
            continue
        try:
            indices.append(int(idx_str, 16))
        except ValueError:
            violations.append(f"[{s['id']}] 6= 6th field (sequence number) cannot be parsed as hex: {idx_str!r}")
    if indices:
        n = len(chan_secs)
        expected = set(range(1, n + 1))
        got = set(indices)
        if got != expected:
            missing = sorted(expected - got)
            extra = sorted(got - expected)
            violations.append(
                f"6= 6th field (sequence number) set does not match 1..{n}: missing={missing} extra={extra}"
            )

    # #5: セクション ID の一意性（チャンネル節・非チャンネル節を問わず全体）。
    # r2 コードレビュー finding[3]: 文字列一致だけでは "300"/"0300" のような
    # 表記違いの実質衝突を見逃す。セクション ID は 16進数として解釈できる
    # 前提（本ツールは 0x300 起点の連番を書く）なので、数値正規化後の
    # 重複も別途検査する。
    all_ids = [s["id"] for s in sections]
    seen: set[str] = set()
    dup: set[str] = set()
    for i in all_ids:
        if i in seen:
            dup.add(i)
        seen.add(i)
    if dup:
        violations.append(f"Section ID duplicated: {sorted(dup)}")

    numeric_owners: dict[int, list[str]] = {}
    for i in all_ids:
        try:
            numeric_owners.setdefault(int(i, 16), []).append(i)
        except ValueError:
            continue
    for n, reps in numeric_owners.items():
        if len(set(reps)) > 1:
            violations.append(f"Section ID duplicated after hex normalization: {sorted(set(reps))} (=0x{n:X})")

    return violations
