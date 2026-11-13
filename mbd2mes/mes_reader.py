# -*- coding: utf-8 -*-
"""
mes_reader.py -- 2D Data Recording `.MES` の読み取り専用パーサ（検証用）。

`.MES` は実体がフォルダで、`<name>.DDD`（チャンネル定義INI, cp1252/CRLF）、
`<name>.A0x`/`<name>.C0x`（生データのバイナリ配列）、`<name>.HED`（メタ情報INI）
などで構成される。本モジュールはこの読み取りのみを行い、書き込みは行わない。

DDD のフィールド位置の意味は紙の資料だけでは確定できないため、
`tools/ddd_lockdown_probe.py` が本モジュールを使って実データ
（Demo-CAR.MES と、その純正コンバータ出力である X_Demo-CAR.csv）を
突き合わせて検証する。ここに実装したフィールド解釈はその検証結果を反映する。
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_ENCODING = "cp1252"


def _decode_line_value(raw: str) -> str:
    """DDDの値文字列を人間可読化する。0x7F(DEL)プレースホルダは空文字列扱い。"""
    return raw.replace("\x7f", "").strip()


def _split_fields(raw: str) -> list[str]:
    """カンマ区切りのフィールド分割。ダブルクォート内のカンマは分割しない。"""
    fields: list[str] = []
    buf = []
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


def _hex_to_float32_be(hex_str: str) -> float:
    """DDDのgain/offset表記: ビッグエンディアン IEEE754 float32 の16進文字列。"""
    hex_str = hex_str.strip()
    if not hex_str:
        return 0.0
    raw = bytes.fromhex(hex_str.zfill(8))
    return struct.unpack(">f", raw)[0]


@dataclass
class DddEntry:
    section_id: int  # DDDセクションの16進チャンネルID
    channel_index: int  # key6末尾: このMES内の通し番号(10進)
    name: str
    unit: str
    short: str
    gain: float
    offset: float
    divisor: int
    bit_width: int  # 16 or 32 (key1 6番目, hexで書かれた10進値)
    base_hz: float
    dtype_letter: str  # key6 2番目: W / I / F など
    data_ext: str  # key6 4番目: データファイルの拡張子 (例 A02)
    raw_key1: list[str]
    raw_key3: list[str]
    raw_key6: list[str]
    raw_keys: dict[str, str]  # セクション内の全キー("1".."7","A"等)の未加工文字列。全てstr統一

    @property
    def sample_hz(self) -> float:
        if self.divisor <= 0:
            return 0.0
        return self.base_hz / self.divisor


@dataclass
class DddExtraSection:
    """チャンネルセクションではない特殊セクション（例: `[Additional]` / `Stamp=`）。

    2026-09-04 Codexレビュー finding[1] の是正で `key'A'` を拾えるようにしたが、
    根本原因（数字以外の識別子を構造的に扱えない）は残っており、`[Additional]`
    セクションと `Stamp` キーが二重に（セクション認識・キー抽出の両方で）失われて
    いた（設計レーンレビュー r3 §1 で検出）。本クラスはそうした「チャンネル定義の
    形をしていないセクション」を素通しで保持・複製するための入れ物。
    """

    section_id: str  # 生のブラケット内文字列 (例: "Additional")
    keys: dict[str, str]  # セクション内の生キー→値 (例: {"Stamp": "1059790"})


_SECTION_RE = re.compile(r"^\[([^\[\]]+)\]$")  # 16進チャンネルIDに限定せず、任意の非空文字列を受理
_KEY_RE = re.compile(r"^([^=\r\n]+)=(.*)$")  # "=" より前の文字数・文字種を制限しない
# (旧) `_SECTION_RE = r"^\[([0-9A-Fa-f]+)\]$"` は `[Additional]` を、
# (旧) `_KEY_RE = r"^([0-9]+|[A-Za-z])=(.*)$"` は `Stamp=` を、それぞれ構造的に
# 読み捨てていた。個別に穴を塞ぐのではなく「セクション名・キー名の文字種を仮定
# しない」形へ一般化し、同型の取りこぼしを構造的に無くす。


def _parse_ddd_sections(path: Path) -> list[tuple[str, dict[str, str]]]:
    """`.DDD` を「セクション名(生文字列) -> {キー(生文字列): 値}」のリストへ分解する。

    ファイル中の出現順を保持する（`dict` は Python 3.7+ で挿入順を保持）。
    チャンネルか特殊セクションかの判定はここでは行わない（呼び出し側の責務）。
    """
    text = path.read_bytes().decode(_ENCODING, errors="strict")
    lines = text.split("\r\n")

    order: list[str] = []
    sections: dict[str, dict[str, str]] = {}
    cur: str | None = None
    for line in lines:
        m = _SECTION_RE.match(line)
        if m:
            cur = m.group(1)
            if cur not in sections:
                sections[cur] = {}
                order.append(cur)
            continue
        if cur is None:
            continue
        m = _KEY_RE.match(line)
        if m:
            sections[cur][m.group(1)] = m.group(2)
    return [(sec_id, sections[sec_id]) for sec_id in order]


def parse_ddd(path: Path) -> list[DddEntry]:
    """`.DDD` からチャンネルセクション（数値/16進IDかつ key1/4/6 を持つ）のみを構造化して返す。"""
    entries: list[DddEntry] = []
    for section_id_str, keys in _parse_ddd_sections(path):
        try:
            section_id = int(section_id_str, 16)
        except ValueError:
            continue  # "[Additional]" のような非16進セクションはチャンネルではない
        if "1" not in keys or "4" not in keys or "6" not in keys:
            continue
        f1 = _split_fields(keys["1"])
        f3 = _split_fields(keys.get("3", ""))
        f4 = [_decode_line_value(x) for x in _split_fields(keys["4"])]
        f6 = _split_fields(keys["6"])

        try:
            divisor = int(f1[4], 16)
            bit_width = int(f1[5], 16)
            base_hz = float(int(f1[6], 16))
        except (IndexError, ValueError):
            continue

        gain = _hex_to_float32_be(f3[3]) if len(f3) > 3 else 1.0
        offset = _hex_to_float32_be(f3[4]) if len(f3) > 4 else 0.0

        name = f4[0] if len(f4) > 0 else ""
        unit = f4[1] if len(f4) > 1 else ""
        short = f4[2] if len(f4) > 2 else ""

        dtype_letter = f6[1] if len(f6) > 1 else ""
        data_ext = f6[3] if len(f6) > 3 else ""
        try:
            channel_index = int(f6[5], 16) if len(f6) > 5 and f6[5] else section_id
        except ValueError:
            channel_index = section_id

        entries.append(
            DddEntry(
                section_id=section_id,
                channel_index=channel_index,
                name=name,
                unit=unit,
                short=short,
                gain=gain,
                offset=offset,
                divisor=divisor,
                bit_width=bit_width,
                base_hz=base_hz,
                dtype_letter=dtype_letter,
                data_ext=data_ext,
                raw_key1=f1,
                raw_key3=f3,
                raw_key6=f6,
                raw_keys=dict(keys),
            )
        )
    return entries


def parse_ddd_extra_sections(path: Path) -> list[DddExtraSection]:
    """チャンネルセクションとして解釈できなかったセクション（`[Additional]` 等）を返す。

    「16進IDでない」または「key1/4/6が揃っていない」セクションが対象。
    素通しで保持し、writer側がverbatim/reconstructed問わず複製できるようにする。
    """
    extras: list[DddExtraSection] = []
    for section_id_str, keys in _parse_ddd_sections(path):
        is_hex_channel = False
        try:
            int(section_id_str, 16)
            is_hex_channel = "1" in keys and "4" in keys and "6" in keys
        except ValueError:
            is_hex_channel = False
        if not is_hex_channel:
            extras.append(DddExtraSection(section_id=section_id_str, keys=dict(keys)))
    return extras


def _numpy_dtype(entry: DddEntry) -> np.dtype:
    """key6のdtype文字とkey1のビット幅からnumpy dtypeを決定する。

    設計正本の指摘どおり、文字(W/I/F)だけでは判定できず、
    key1の6番目(ビット幅16/32/64、16進表記だが値そのものが10進のbit数)
    と組み合わせて決める。実測(Demo-CAR.DDD)で64bit(0x40)の存在を確認済み
    （Longitude/Latitude、dtype文字'F'=float64）。
    """
    letter = entry.dtype_letter.upper()
    width = entry.bit_width
    if letter == "F":
        if width >= 64:
            return np.dtype("<f8")
        return np.dtype("<f4") if width >= 32 else np.dtype("<f2")
    if letter == "I":
        if width >= 64:
            return np.dtype("<u8")
        return np.dtype("<u4") if width >= 32 else np.dtype("<u2")
    # 既定: W (word) は符号なし整数。ビット幅で2/4/8byteを切り替える。
    if width >= 64:
        return np.dtype("<u8")
    return np.dtype("<u4") if width >= 32 else np.dtype("<u2")


def read_channel_data(mes_dir: Path, entry: DddEntry, mes_basename: str) -> np.ndarray:
    """`<mes_basename>.<data_ext>` を読み、gain/offset適用済みの物理値を返す。"""
    data_path = mes_dir / f"{mes_basename}.{entry.data_ext}"
    if not data_path.exists():
        raise FileNotFoundError(str(data_path))
    dtype = _numpy_dtype(entry)
    raw = np.fromfile(data_path, dtype=dtype).astype(np.float64)
    return raw * entry.gain + entry.offset


def load_mes(mes_dir: Path) -> dict[str, np.ndarray]:
    """MESフォルダ(`<name>.MES\\`)を丸ごと読み、name -> 物理値配列 の辞書を返す。"""
    mes_dir = Path(mes_dir)
    ddd_files = list(mes_dir.glob("*.DDD"))
    if not ddd_files:
        raise FileNotFoundError(f"DDD not found under {mes_dir}")
    ddd_path = ddd_files[0]
    mes_basename = ddd_path.stem
    entries = parse_ddd(ddd_path)

    result: dict[str, np.ndarray] = {}
    for e in entries:
        if not e.name or not e.data_ext:
            continue
        try:
            result[e.name] = read_channel_data(mes_dir, e, mes_basename)
        except FileNotFoundError:
            continue
    return result


if __name__ == "__main__":
    import sys

    p = Path(sys.argv[1])
    entries = parse_ddd(p)
    print(f"{len(entries)} channels parsed from {p}")
    for e in entries[:10]:
        print(
            f"[{e.section_id:X}] idx={e.channel_index} {e.name!r} unit={e.unit!r} "
            f"gain={e.gain} offset={e.offset} hz={e.sample_hz} "
            f"dtype={e.dtype_letter}{e.bit_width} ext={e.data_ext}"
        )
