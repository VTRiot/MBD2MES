# -*- coding: utf-8 -*-
"""
mes_writer.py -- 2D Data Recording `.MES` ライタ。

本モジュールには目的の異なる2種類の writer が入っている。

1. **verbatim系**（`render_ddd_text` / `write_channel_slice` / `write_poc_mes`）:
   元DDDのキー文字列・生バイトをそのまま複製する。これで検証できるのは
   「2D Analyzerが要求するMESフォルダの構造」だけであり、Phase0で解読した
   フィールド（除数・ビット幅・ベースHz・gain/offset・dtype文字等）が
   正しく書けることの証明にはならない（実機確認 09-04 で指摘済み）。

2. **reconstructed系**（`render_ddd_text_reconstructed` / `encode_channel_data` /
   `write_reconstructed_mes`）: Phase0で解読した構造化フィールド
   （divisor / bit_width / base_hz / gain / offset / dtype_letter / data_ext /
   channel_index / name / unit / short）から独立にDDDテキストとバイナリを
   組み立てる。まだ意味が分かっていないフィールド（key1の他の位置・key2・
   key5・key7・key4の flag/comment・key6の flag/未知コード/グループ名・key'A'
   内部の値そのもの）は元エントリの値をそのまま複製する（=これらについては
   「値が正しい」ことを主張しない。分かっている範囲だけを組み立てる）。
   ただし key'A' というキー自体は 09-04 Codexレビュー以降、数値キーと同様に
   保持・複製される（以前は非数値キーとして静かに読み捨てられていた）。
   さらに09-04 設計レーンレビュー r3 で、`[Additional]`セクション（`Stamp=`
   キーを持つ、チャンネル定義の形をしていない特殊セクション）も同種の理由で
   二重に読み捨てられていたと判明し、`extra_sections`引数で複製できるように
   修正した（`mes_reader.DddExtraSection` / `parse_ddd_extra_sections`）。

   `tools/phase1_reconstruction_validate.py` がこの reconstructed 版を、
   実機の2D Analyzerで開けることが確認済みの `PoC-Test.MES`（verbatim版）と
   バイト単位で突き合わせ、Phase0のフィールド解釈が正しいかを実機無しで検証する。

Phase 2以降で `choose_base_rate` / `dedupe_channel_names` / 単位マッピング等を
使った一般化されたwriterに拡張する。
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from . import mes_reader as mr

_ENCODING = "cp1252"


def n_samples_for_duration(hz: float, duration_seconds: float) -> int:
    """時間長基準でサンプル数を求める。

    2026-09-04 実機確認で判明した Phase2 設計制約: MES の各チャンネルは
    「レート × 時間長」のサンプル数を持たねばならない。全チャンネルを
    同じサンプル数で一律に切り出すと、レートの異なるチャンネル間で
    実収録時間長が食い違い、HED の Lap 宣言より短いチャンネルは
    2D Analyzer にエラー無く黙って捨てられる（V_Sat 消失として実測済み）。
    """
    return round(hz * duration_seconds)


# ============================================================
# verbatim系: 元のDDDキー・生バイトをそのまま複製する（構造要件PoC用）
# ============================================================


def _sort_keys(raw_keys: dict[str, str]) -> list[str]:
    """DDDキーの出力順: 数値キー(1..7)を昇順、その後に文字キー('A'/'Stamp'等)を昇順。

    2026-09-04 Codexレビュー finding[1] 以降、キーは全て文字列で保持する
    （数値に見えるキーも文字列 "1".."7" として扱う）。数値として解釈できる
    キーを優先して数値順に、それ以外は辞書順に出す。
    """

    def sort_key(k: str) -> tuple[int, object]:
        return (0, int(k)) if k.isdigit() else (1, k)

    return sorted(raw_keys, key=sort_key)


def _render_extra_sections(extra_sections: list[mr.DddExtraSection] | None) -> list[str]:
    """`[Additional]` 等、チャンネル定義でない特殊セクションを素通しで出力する行列を作る。

    2026-09-04 設計レーンレビュー r3 §1 で検出: `_SECTION_RE`/`_KEY_RE` の
    旧実装は `[Additional]` セクションと `Stamp=` キーを二重に読み捨てていた。
    reader側の一般化に合わせ、writer側もこれらを複製できるようにする。
    各セクションの後に空行を1行入れる（下記 render_ddd_text* と同じ規約。
    2026-09-04 実機確認レビュー[指摘B]で、元DDDが各セクション末尾に空行を
    持つことが判明し、これを欠いた出力は元ファイルとバイト一致しなかった）。
    """
    lines: list[str] = []
    for sec in extra_sections or []:
        lines.append(f"[{sec.section_id}]")
        for key_id in sorted(sec.keys):
            lines.append(f"{key_id}={sec.keys[key_id]}")
        lines.append("")
    return lines


def render_ddd_text(
    entries: list[mr.DddEntry], extra_sections: list[mr.DddExtraSection] | None = None
) -> bytes:
    """DDDセクション群を、元のキー文字列をそのまま使って再構成する（改変なし複製）。

    検証できるのは「MESフォルダの構造要件」のみ。フィールド解釈の正しさは
    証明しない（`render_ddd_text_reconstructed` が担う）。`extra_sections` を
    渡すと `[Additional]` のような特殊セクションもチャンネル定義の後に複製する。
    各セクションの後に空行を1行入れる（元DDDの実際の書式。2026-09-04
    実機確認レビュー[指摘B]の外形diff検証で、これを欠くと元ファイルと
    バイト一致しないと判明。3ch程度のPoCでは目立たなかった）。
    """
    lines: list[str] = []
    for e in sorted(entries, key=lambda x: x.section_id):
        lines.append(f"[{e.section_id:X}]")
        for key_id in _sort_keys(e.raw_keys):
            lines.append(f"{key_id}={e.raw_keys[key_id]}")
        lines.append("")
    lines.extend(_render_extra_sections(extra_sections))
    text = "\r\n".join(lines) + "\r\n"
    return text.encode(_ENCODING, errors="strict")


def write_cal(path: Path) -> None:
    path.write_bytes(b"")


def write_channel_slice(
    dst_path: Path, source_mes_dir: Path, entry: mr.DddEntry, source_basename: str, n_samples: int
) -> int:
    """元の生データファイルから先頭 n_samples 分をそのままバイト複製する（改変なし複製）。"""
    src = source_mes_dir / f"{source_basename}.{entry.data_ext}"
    raw = src.read_bytes()
    dtype = mr._numpy_dtype(entry)  # noqa: SLF001 (同一パッケージ内での意図的な内部利用)
    itemsize = dtype.itemsize
    n_avail = len(raw) // itemsize
    n = min(n_samples, n_avail)
    dst_path.write_bytes(raw[: n * itemsize])
    return n


def write_poc_mes(
    out_dir: Path,
    mes_name: str,
    source_mes_dir: Path,
    source_basename: str,
    entries: list[mr.DddEntry],
    duration_seconds: float,
    extra_sections: list[mr.DddExtraSection] | None = None,
) -> Path:
    """構造要件PoC用のMESフォルダを1つ作る（verbatim複製、DDD+生データ+空CALのみ）。

    2026-09-04 実機確認で判明: 全チャンネルへ同一サンプル数を割り当てると
    レート差で実収録時間長が食い違い、短いチャンネルがAnalyzerに黙って
    捨てられる。`duration_seconds`は全チャンネル共通の時間長で、
    各チャンネルのサンプル数は`n_samples_for_duration(hz, duration_seconds)`
    で個別に算出する。
    """
    mes_dir = out_dir / f"{mes_name}.MES"
    mes_dir.mkdir(parents=True, exist_ok=True)

    ddd_path = mes_dir / f"{mes_name}.DDD"
    ddd_path.write_bytes(render_ddd_text(entries, extra_sections))

    for e in entries:
        dst = mes_dir / f"{mes_name}.{e.data_ext}"
        n_samples = n_samples_for_duration(e.sample_hz, duration_seconds)
        write_channel_slice(dst, source_mes_dir, e, source_basename, n_samples)

    write_cal(mes_dir / f"{mes_name}.CAL")
    return mes_dir


# ============================================================
# reconstructed系: Phase0で解読した構造化フィールドから独立に組み立てる
# ============================================================


def _format_hex(value: int) -> str:
    """DDDの16進表記(先頭ゼロ埋めなし・大文字)に合わせる。"""
    return f"{value:X}"


def _encode_gain_offset_hex(value: float) -> str:
    """gain/offsetのDDD表記: ビッグエンディアン IEEE754 float32の16進、大文字・先頭ゼロ省略。

    他の16進フィールド(除数/ビット幅/ベースHz)と同じ「先頭ゼロを詰めない」規則。
    非ゼロのgainは先頭桁が0になることが少なく8桁に見えるだけで、offset=0.0 のような
    値は "00000000" ではなく "0" と書かれる（実機確認済みground truthとの突合で判明）。
    """
    hex_str = struct.pack(">f", value).hex().upper()
    stripped = hex_str.lstrip("0")
    return stripped if stripped else "0"


def _encode_empty(value: str) -> str:
    """DDDの空フィールド表記(0x7F プレースホルダ)に戻す。"""
    return value if value else "\x7f"


class DddFieldLayoutError(ValueError):
    """テンプレートDDDエントリのフィールド数が、組み立てに必要な最小数に満たない場合。

    2026-09-04 Codexレビュー finding[5]: 元エントリのフィールド数が想定より
    少ないと素の IndexError になっていた。Phase2で複製元(テンプレート)を
    持たない新規チャンネルを組み立てる際に無言でクラッシュしないよう、
    原因が分かるメッセージ付きで明示的に失敗させる。
    """


def _require_min_fields(fields: list[str], min_len: int, key_label: str, entry: mr.DddEntry) -> None:
    if len(fields) < min_len:
        raise DddFieldLayoutError(
            f"{entry.name!r}(section {entry.section_id:X}) の {key_label} は "
            f"{len(fields)} フィールドしか無く、組み立てに必要な最小 {min_len} に満たない。"
            "テンプレートの無いDDDセクションを渡していないか確認すること。"
        )


def render_key1_reconstructed(entry: mr.DddEntry) -> str:
    """key1のうち解読済み位置(5:除数, 6:ビット幅, 7:ベースHz)を構造値から組み立てる。

    他の位置(1-4, 8-10)は意味が未解読のため元エントリの値をそのまま複製する。
    """
    fields = list(entry.raw_key1)
    _require_min_fields(fields, 7, "key1", entry)
    fields[4] = _format_hex(entry.divisor)
    fields[5] = _format_hex(entry.bit_width)
    fields[6] = _format_hex(int(entry.base_hz))
    return ",".join(fields)


def render_key3_reconstructed(entry: mr.DddEntry) -> str:
    """key3のうち解読済み位置(4:gain, 5:offset)を構造値から組み立てる。他は複製。"""
    fields = list(entry.raw_key3)
    _require_min_fields(fields, 5, "key3", entry)
    fields[3] = _encode_gain_offset_hex(entry.gain)
    fields[4] = _encode_gain_offset_hex(entry.offset)
    return ",".join(fields)


def render_key4_reconstructed(entry: mr.DddEntry) -> str:
    """key4のうち解読済み位置(1:name, 2:unit, 3:short)を構造値から組み立てる。他は複製。"""
    fields = list(mr._split_fields(entry.raw_keys["4"]))  # noqa: SLF001
    _require_min_fields(fields, 1, "key4", entry)
    fields[0] = _encode_empty(entry.name)
    if len(fields) > 1:
        fields[1] = _encode_empty(entry.unit)
    if len(fields) > 2:
        fields[2] = _encode_empty(entry.short)
    return ",".join(fields)


def render_key6_reconstructed(entry: mr.DddEntry) -> str:
    """key6のうち解読済み位置(2:dtype文字, 4:データ拡張子, 6:チャンネル通し番号)を組み立てる。他は複製。"""
    fields = list(entry.raw_key6)
    _require_min_fields(fields, 6, "key6", entry)
    fields[1] = entry.dtype_letter
    fields[3] = entry.data_ext
    fields[5] = _format_hex(entry.channel_index)
    return ",".join(fields)


def render_ddd_text_reconstructed(
    entries: list[mr.DddEntry], extra_sections: list[mr.DddExtraSection] | None = None
) -> bytes:
    """DDDセクション群を、Phase0で解読した構造化フィールドから組み立てる。

    key2/key5/key7/key'A' 全体、および key1/key3/key4/key6 のうち未解読の
    位置は元エントリの値をそのまま複製する(=これらの正しさは主張しない)。
    数値キー以外（'A'等）も出力に含める(finding[1]対応)。`extra_sections` を
    渡すと `[Additional]` のような特殊セクションも末尾に複製する（同finding、
    設計レーンレビュー r3 §1 で「二重の取りこぼし」として追加指摘された分）。
    """
    lines: list[str] = []
    for e in sorted(entries, key=lambda x: x.section_id):
        lines.append(f"[{e.section_id:X}]")
        for key_id in _sort_keys(e.raw_keys):
            if key_id == "1":
                value = render_key1_reconstructed(e)
            elif key_id == "3":
                value = render_key3_reconstructed(e)
            elif key_id == "4":
                value = render_key4_reconstructed(e)
            elif key_id == "6":
                value = render_key6_reconstructed(e)
            else:
                value = e.raw_keys[key_id]
            lines.append(f"{key_id}={value}")
        lines.append("")
    lines.extend(_render_extra_sections(extra_sections))
    text = "\r\n".join(lines) + "\r\n"
    return text.encode(_ENCODING, errors="strict")


def encode_channel_data(values: np.ndarray, entry: mr.DddEntry) -> bytes:
    """物理値配列を、Phase0で解読したgain/offset/dtypeの逆変換でバイナリへ戻す。

    `mes_reader.read_channel_data` (raw*gain+offset) の厳密な逆演算。

    gain=0 は原理的に非可逆（reader側は全rawを同一のoffset値へ潰すため、
    物理値だけからrawを一意に復元できない）。2026-09-04 Codexレビュー finding[3]
    指摘のとおり、以前は `gain or 1.0` で黙って別の式にすり替えており、
    誤ったバイト列を検知不能なまま書き出していた。ここでは明示的に失敗させる。
    """
    dtype = mr._numpy_dtype(entry)  # noqa: SLF001
    if entry.gain == 0:
        raise ValueError(
            f"{entry.name!r}(section {entry.section_id:X}) は gain=0 で非可逆。"
            "物理値からrawを一意に復元できないため書き出せない。元rawを別途渡すこと。"
        )
    physical = (values.astype(np.float64) - entry.offset) / entry.gain

    if dtype.kind == "f":
        raw = physical.astype(dtype)
    else:
        info = np.iinfo(dtype)
        rounded = np.round(physical)
        clipped = np.clip(rounded, info.min, info.max)
        raw = clipped.astype(dtype)
    return raw.tobytes()


def write_reconstructed_mes(
    out_dir: Path,
    mes_name: str,
    entries: list[mr.DddEntry],
    values_by_name: dict[str, np.ndarray],
    extra_sections: list[mr.DddExtraSection] | None = None,
) -> Path:
    """Phase0で解読した構造化フィールドから独立に組み立てたMESフォルダを作る。"""
    mes_dir = out_dir / f"{mes_name}.MES"
    mes_dir.mkdir(parents=True, exist_ok=True)

    ddd_path = mes_dir / f"{mes_name}.DDD"
    ddd_path.write_bytes(render_ddd_text_reconstructed(entries, extra_sections))

    for e in entries:
        values = values_by_name[e.name]
        raw_bytes = encode_channel_data(values, e)
        (mes_dir / f"{mes_name}.{e.data_ext}").write_bytes(raw_bytes)

    write_cal(mes_dir / f"{mes_name}.CAL")
    return mes_dir
