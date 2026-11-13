# -*- coding: utf-8 -*-
"""ddd_generator.py -- .ld のチャンネルメタ + 記述法の定数だけから DDD エントリを生成する。

2026-09-05（LD2MES_Converter Phase2 CP1・r6・FB r1 反映）:
    旧 ld2mes.py は Demo-CAR.DDD の i 番目エントリをテンプレートとして
    dataclasses.replace で書き換える「位置継承」方式だった。この方式は
    テンプレート側の意味不明な値（非表示フラグ・表示色・レンジ等）を
    無関係なチャンネルへ機械的に貼り付ける構造的欠陥を持ち、実際に
    83ch 中 37ch が非表示フラグ付きのまま出力される事故を起こした
    （読み戻し検証では検出できない類型）。

    本モジュールはテンプレートを一切参照せず、各 DDD フィールドを
    「.ld から生成する」か「定数で埋めて由来を明記する」かのどちらかで
    組み立てる。未解読の定数は出所（実測の多数決）と Analyzer 受理の
    確認状況（A/B テスト待ち）をコメントに残す（下記 定数台帳 参照）。

Codex レビュー r1（`Report\\CC\\260905_LD2MES_Converter_Phase2\\review\\`）
の裁定を反映済み: ConversionResult 明示化・key3_field2 の境界ガード・
定数の層別ドキュメント化。詳細は review_r1_adjudication.md 参照。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import struct

import numpy as np


from . import mes_reader as mr
from . import mes_writer as mw

# ============================================================
# 定数台帳（各値: 出所 / Analyzer 受理 / A/B 代替値）
# 全 chapter 共通の DDD 記述規則。「未確認」は AnzApp 実機での A/B
# テスト待ちを意味する（本 CP1 では検証できない）。
# ============================================================

_KEY1_TYPE = "4"
# 出所: Demo-CAR.DDD 種別4節 38/43 一致、旧テンプレート方式出力(83ch)でも 57/83 一致。
# Analyzer受理: 未確認。A/B代替値: 実走M130ログの種別4最頻 "18DCF,C0,0"（34/60節）。
# 意味は未解読（LDD由来のフラグ群と推定）。
_KEY1_FLAGS_2_4 = ("8CB", "C0", "0")
_KEY1_TAIL_8_10 = ("0", "0", "0")  # 出所: 実走・Demo とも全節この値。意味未解読。

_KEY2_ALL_ZERO = ("0",) * 7
# 出所: 2025実走 156/156ch が全ゼロ、Demo-CAR は 28/114 のみ全ゼロ（他はダッシュ表示位置と推定）。
# 実走ログでは全ゼロが標準的挙動と判断。Analyzer受理: 未確認。

_KEY5_FIELD2 = "51"
# 出所: 全節最頻値であり真の多数決ではない（Demo 32/114, 2025実走 74/156）。
# 種別4&2,W に限定した層別分布: Demo "72"(11/43) が最頻、2025実走 "10"(15/60) が最頻。
# 上記の全節最頻"51"と種別4限定最頻が食い違う点に注意。意味未解読のため確証度は低い。
# Analyzer受理: 未確認。A/B代替値: "72"（Demo種別4限定）／"10"（2025実走種別4限定）。
_KEY5_OTHER_ZERO = ("0", "0", "0", "0")  # 出所: 全節この値（第1,3,4,5,6フィールド）

_KEY6_BYTE_WIDTH = "2"  # bit_width=0x10(16bit)=2byte に対応する固定値
_KEY6_DTYPE_LETTER = "W"
_KEY6_FIELD3 = "2D"
# 出所: 種別4&2,W に限定すると Demo 43/43・2025実走 60/60 が "2D" で一致（意味未解読）。
# Analyzer受理: 未確認。A/B代替値: 通し番号の16進、または空。

_KEY7_ALL_ZERO = ("0",) * 5
# 出所: 2025実走 156/156ch が全ゼロ、2018実走も86/86が全ゼロ。実走では全ゼロが標準。
# Demo-CARは67/114が非ゼロ（表示色・レンジと推定）だが実走慣行に合わせる。

_KEY3_FIELD1 = "1"  # 出所: 2025実走 135/156 で一致
_KEY3_FIELD3 = "0"
_KEY3_FIELD6 = "0"
_KEY3_FIELD7 = "3F800000"  # IEEE754 float32 = 1.0
_KEY3_FIELD8 = "0"
_KEY3_FIELD9 = "0"  # 出所: Demo-CAR 全節(43/43)がこの値。A/B代替値: "FFFFFFFF"（2025実走 34/60）

_BIT_WIDTH = 0x10  # 16bit固定（全ch u16）
_BASE_HZ_CANDIDATES = (400, 800, 1000, 2000)
# 出所: base_hz=800(0x320) は 2023/2025 の実走ログで受理実績あり（1=第7フィールド）。
# 1000/2000 は未検証の候補。


# DDD の空欄プレースホルダ（0x7F=DEL）。cp1252 の "空欄" 表現規則。4= 第5(グループ名/説明)
# は引用符付き DEL、第7(未解読) は素の DEL という組み合わせが実データ全数で一致していた
# （Demo-CAR 114/114・旧テンプレート出力 83/83・2025実走 156/156）。
_DEL = "\x7f"


@dataclass
class ConversionResult:
    """.ld -> DDD 変換の結果一式（Codex レビュー r1 finding[3] の裁定を反映）。

    1 チャンネル = 1 レコードで meta -> 正規化名 -> 物理値 -> DddEntry を
    保持してから values_by_name を組み立てるため、skip や名前衝突が
    あっても entries と values_by_name の対応がずれない。
    """

    entries: list[mr.DddEntry]
    values_by_name: dict[str, np.ndarray]
    base_hz: int
    skipped: list[tuple[str, str]]
    metas: list[dict] = field(default_factory=list)
    # Ld2Mes-007: 派生チャンネルの (定義上の名前, 一意化後の DDD 名)。派生を足さない経路では空
    derived_names: list[tuple[str, str]] = field(default_factory=list)


def sanitize_name(raw: str) -> str:
    """`,` `"` および制御文字(0x00-0x1F, 0x7F)を `_` に置換する。

    DDD はカンマ区切り・ダブルクォート特殊扱いのテキスト形式のため、
    チャンネル名にこれらの文字が混入すると `4=` 行のフィールドがずれる
    （Codex レビュー r1 finding[7] 相当。実データ9本×84名では該当0件を
    A-3 で実測済みだが、将来別ロガーのデータで混入し得るため防御する）。
    """
    out = []
    for ch in raw:
        if ch in (",", '"') or ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append("_")
        else:
            out.append(ch)
    return "".join(out)


def sanitize_unit(raw_unit: str) -> tuple[str, str | None]:
    """cp1252 でエンコード可能ならそのまま返す。不可能なら (空文字, 理由) を返す。

    実データ（9本×84ch、うち32ch が非空単位）は全て ASCII で cp1252 安全である
    ことを実測済み（本チェックは防御的な保険）。
    """
    try:
        raw_unit.encode("cp1252", errors="strict")
        return raw_unit, None
    except UnicodeEncodeError as exc:
        return "", f"Unit {raw_unit!r} cannot be encoded in cp1252: {exc}"


def choose_base_hz(rates: list[float]) -> tuple[int, dict[float, str]]:
    """全 ch のレートが整数で割り切る最小候補を _BASE_HZ_CANDIDATES から選ぶ。

    戻り値: (採用 base_hz, {rate: スキップ理由})。

    実装方針（全候補で割り切れない rate が残る場合の tie-break。計画には
    明記が無かったため実装時に決定）: 候補ごとに「割り切れない rate の数」
    を数え、**最も少ない候補**を採る。同数なら**候補リストの先頭（最小の
    base_hz）**を優先する。これにより (a) 割り切れる候補が存在する通常
    ケースでは従来どおり最小の完全一致候補を選び、(b) 一つも完全一致が
    無い退化ケースでもスキップ数を最小化し、かつ根拠なく大きな base_hz
    を選ばない。
    """
    unique_rates = sorted(set(r for r in rates if r > 0))
    best_base_hz = _BASE_HZ_CANDIDATES[0]
    best_bad: dict[float, str] = {}
    best_bad_count: int | None = None
    for base_hz in _BASE_HZ_CANDIDATES:
        bad: dict[float, str] = {}
        for rate in unique_rates:
            if rate > base_hz or base_hz % rate != 0:
                bad[rate] = f"rate={rate}Hz not evenly divisible by base_hz={base_hz}"
        if best_bad_count is None or len(bad) < best_bad_count:
            best_base_hz, best_bad, best_bad_count = base_hz, bad, len(bad)
        if not bad:
            break
    return best_base_hz, best_bad


def key3_field2(gain: float) -> str:
    """`3=` 第2フィールド。常に定数 `"1"` を返す（計画 r7・§2-e）。

    設計経緯（r5-1 → r7 の訂正）: 当初 r5-1 は「`1/gain` が整数（許容 ±0.1%）
    ならその16進、それ以外は "1"」という条件判定を計画していた。実装時の
    スモークテストで、この判定がスケール非依存に実装できないことが判明した:
    - `1/gain` への相対誤差判定は 1/gain が大きい ch（分解能の細かい ch）で
      緩みすぎ、range-fit の偶然の近似値まで「整数」と誤判定する
      （実測: Throttle.Aim で 1/gain=655.35 が rel_tol=0.1% で "28F" と誤判定）。
    - 積 `round(1/gain)*gain` の絶対誤差判定に変えても、誤差は
      `丸め誤差(≤0.5) × span/65535` に比例するため、span（`hi-lo`）が
      小さい ch では常に「整数」と判定されてしまう（実測: tol=1e-4 で
      span<13.1 のとき常に真。83ch 中 40ch が誤って非"1"値を持った）。

    根本原因: 本ツールの gain は `gain_offset_for` のレンジフィット
    （`(hi-lo)/65535`）で毎回合成する値であり、実機メーカーが記録する
    「真の較正定数」（r5-1 が実測した Demo-CAR/実走 DDD の値、float32
    格納誤差 ~1e-7 のみ）とは生成過程が異なる。したがって
    「`1/gain` が整数なら較正定数由来」という r5-1 の観察（96% 一致）は
    本ツールの合成 gain には適用できない。実機メーカー自身も
    `V_GPS`/`A_Lon_GPS`/`GPS_Yaw`/`Course` 等で float gain と `N=1` の
    組み合わせを使う実例があり、`mes_reader`/`mes_writer` とも本フィールドを
    機能的に読み書きしないため（gain/offset は第4/5フィールドで独立に扱う）、
    `N=1` 固定は roundtrip・不変量のいずれにも影響しない。
    """
    return "1"


def _key1_fields(divisor_placeholder: str, bitwidth_placeholder: str, basehz_placeholder: str) -> list[str]:
    """raw_key1（11要素）。writer が [4]=divisor [5]=bit_width [6]=base_hz を
    _format_hex() で上書きするため、該当位置はプレースホルダで良い。"""
    return [
        _KEY1_TYPE,
        *_KEY1_FLAGS_2_4,
        divisor_placeholder,
        bitwidth_placeholder,
        basehz_placeholder,
        *_KEY1_TAIL_8_10,
        "",
    ]


def _key3_fields(gain_n_field: str, gain_placeholder: str, offset_placeholder: str) -> list[str]:
    """raw_key3（10要素）。writer が [3]=gain [4]=offset を上書きする。"""
    return [
        _KEY3_FIELD1,
        gain_n_field,
        _KEY3_FIELD3,
        gain_placeholder,
        offset_placeholder,
        _KEY3_FIELD6,
        _KEY3_FIELD7,
        _KEY3_FIELD8,
        _KEY3_FIELD9,
        "",
    ]


def _key4_string(name_placeholder: str, unit_placeholder: str, short_placeholder: str) -> str:
    """raw_keys["4"]（8要素の文字列）。writer が [0]=name [1]=unit [2]=short を
    _encode_empty() 経由で上書きする（空文字なら 0x7F 化）。第5(=index4)は
    引用符付き DEL、第7(=index6)は素の DEL が実データ全数で一致していた慣行。
    """
    return f'{name_placeholder},{unit_placeholder},{short_placeholder},0,"{_DEL}",0,{_DEL},'


def _key6_fields(ext_placeholder: str, idx_placeholder: str) -> list[str]:
    """raw_key6（7要素）。writer が [1]=dtype_letter [3]=data_ext [5]=channel_index を上書きする。"""
    return [
        _KEY6_BYTE_WIDTH,
        _KEY6_DTYPE_LETTER,  # プレースホルダ（writer が entry.dtype_letter で上書き）
        _KEY6_FIELD3,
        ext_placeholder,
        "",
        idx_placeholder,
        "",
    ]


_BASE36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def data_ext_for(index1: int) -> str:
    """1始まりの通し番号 -> データファイル拡張子 (A01/A02/../A0Z/A10/..)。

    ld2mes.py（旧実装）と同一ロジック（Demo-CAR.MES の実データで検証済み）。
    """
    if not 1 <= index1 <= 36 * 36 - 1:
        raise ValueError(f"Channel index out of range for extension: {index1}")
    hi, lo = divmod(index1, 36)
    return f"A{_BASE36[hi]}{_BASE36[lo]}"


def unique_names(raw_names: list[str], limit: int = 32) -> list[str]:
    """DDD の name 欄長(32byte)で切り詰めた結果の衝突を、末尾アンダーバー反復で解消する。

    - 衝突なし: 元の名前（左右空白除去後、limitで切り詰め。空なら 'CH'）
    - 1回目の衝突: base[:limit-1] + '_'
    - 2回目の衝突: base[:limit-2] + '__'
    - k回目の衝突: base[:limit-k] + ('_' * k) (1 <= k <= limit)
    - 再衝突への対応: 切り詰め後の名前が既存の名前と衝突した場合でも、
      while ループにより k が進み、さらに '_' が重ねられた候補が試行される。
    - 停止性と空間枯渇: k が limit を超えても一意な名前が見つからない場合
      （例: すべて '_' で埋まった名前も既に使われている極限状態）、
      32byte 制約下ではこれ以上一意化が不可能なため ValueError を送出して
      無限ループを構造的に防止する。
    """
    if limit < 1:
        raise ValueError(f"limit must be 1 or greater: {limit}")

    used: set[str] = set()
    out: list[str] = []
    for nm in raw_names:
        raw_str = (nm or "").strip()
        base = (raw_str or "CH")[:limit]
        cand = base
        k = 0
        while cand in used:
            k += 1
            if k > limit:
                raise ValueError(
                    f"Channel name uniqueness limit exceeded ({limit} char space): {nm!r}"
                )
            suffix = "_" * k
            cand = base[: limit - k] + suffix
        used.add(cand)
        out.append(cand)
    return out


def gain_offset_for(dtype_letter: str, bit_width: int, values: np.ndarray) -> tuple[float, float]:
    """dtype で物理値を最良精度で格納できる gain/offset を決める。

    ld2mes.py の旧実装からロジック無改変で本ファイルへ移設（第1引数を
    DddEntry から dtype_letter/bit_width の直接指定に変更しただけ。
    Codex レビュー r1 finding[5] 関連: gain_offset_for 自体は本 CP1 では
    u16 固定でしか呼ばれないため W/16bit 以外の経路は現状未使用）。

    浮動小数dtypeなら恒等変換 (gain=1, offset=0) で完全可逆。
    整数dtypeなら実レンジ [lo,hi] を型レンジ [info.min,info.max] へ線形写像する。
    """
    if dtype_letter.upper() == "F":
        return 1.0, 0.0

    dtype = _numpy_dtype_for(dtype_letter, bit_width)
    if dtype.kind == "f":
        return 1.0, 0.0

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 1.0, 0.0

    lo = float(np.min(finite))
    hi = float(np.max(finite))
    if not (hi > lo):
        # 定数チャンネル。gain=0 は encode 側で明示的に拒否されるため 1.0 を使い、
        # offset に定数値を載せて raw=0 で復元されるようにする。
        return 1.0, lo

    info = np.iinfo(dtype)
    span_raw = float(info.max) - float(info.min)
    gain = (hi - lo) / span_raw
    offset = lo - gain * float(info.min)
    return gain, offset


def _numpy_dtype_for(dtype_letter: str, bit_width: int) -> np.dtype:
    """mes_reader._numpy_dtype と同じロジック（entry 経由ではなく直接指定版）。"""
    letter = dtype_letter.upper()
    width = bit_width
    if letter == "F":
        if width >= 64:
            return np.dtype("<f8")
        return np.dtype("<f4") if width >= 32 else np.dtype("<f2")
    if letter == "I":
        if width >= 64:
            return np.dtype("<u8")
        return np.dtype("<u4") if width >= 32 else np.dtype("<u2")
    if width >= 64:
        return np.dtype("<u8")
    return np.dtype("<u4") if width >= 32 else np.dtype("<u2")


def _default_apply_map(raw_name: str, raw_unit: str) -> list[tuple[str, str]]:
    """channel_map未指定時の既定動作: 完全パススルー（納品Cで追加した拡張点の既定値）。"""
    return [(raw_name, raw_unit)]


def _default_scaling_fn(raw_name: str) -> tuple[float, float]:
    """スケーリング未指定時の既定動作: 恒等変換 (1.0, 0.0)（Ld2Mes-003 新設）。"""
    return 1.0, 0.0


def make_entry(
    idx: int, nm: str, unit_raw: str, values: np.ndarray, rate: float, base_hz: int, skipped: list[tuple[str, str]]
) -> mr.DddEntry:
    """1 チャンネル分の `DddEntry` を作る（通し番号 idx は 1 始まり）。`build_entries` の全チャンネルと、
    Ld2Mes-008 の「既存 MES への派生の追加」（`derived_fix`）が**同じ関数**を通る（節 ID = 0x300 + idx - 1）。
    unit が cp1252 で書けないときは単位だけを落とし、理由を skipped に足す。
    """
    divisor = max(1, int(round(base_hz / rate))) if rate > 0 else 1
    gain, offset = gain_offset_for(_KEY6_DTYPE_LETTER, _BIT_WIDTH, values)
    try:
        g_f32 = struct.unpack(">f", struct.pack(">f", gain))[0]
        o_f32 = struct.unpack(">f", struct.pack(">f", offset))[0]
    except (struct.error, OverflowError) as exc:
        raise ValueError(f"{nm}: Post-scaling calibration value is out of float32 range: gain={gain}, offset={offset}") from exc

    # F5: gain が 0 または非有限、または float32 で 0.0 化する場合の事前拒否
    # （writer 実行前の事前チェックにより一部ファイル書き出し後の破損停止を防止）
    if not math.isfinite(gain) or gain <= 0.0 or g_f32 <= 0.0:
        raise ValueError(f"{nm}: Post-scaling gain is invalid or underflows in float32 (0.0 / unrepresentable): gain={gain}, float32={g_f32}")

    # F4: offset が非有限、または 0 でないのに float32 でアンダーフロー(0.0化)する場合の事前拒否
    if not math.isfinite(offset):
        raise ValueError(f"{nm}: Post-scaling offset is non-finite: {offset}")
    if offset != 0.0 and o_f32 == 0.0:
        raise ValueError(f"{nm}: Post-scaling offset underflows in float32 (0.0): offset={offset}")

    n_field = key3_field2(gain)
    unit, unit_reason = sanitize_unit(unit_raw)
    if unit_reason:
        # 単位だけを落とし、チャンネル自体はスキップしない（推測で埋めないが、
        # 単位以外の変換価値まで捨てない）。
        skipped.append((f"{nm} (unit only)", unit_reason))
    short = nm[:8]
    data_ext = data_ext_for(idx)
    section_id = 0x300 + (idx - 1)

    entry = mr.DddEntry(
        section_id=section_id,
        channel_index=idx,
        name=nm,
        unit=unit,
        short=short,
        gain=gain,
        offset=offset,
        divisor=divisor,
        bit_width=_BIT_WIDTH,
        base_hz=float(base_hz),
        dtype_letter=_KEY6_DTYPE_LETTER,
        data_ext=data_ext,
        raw_key1=_key1_fields("0", "0", "0"),
        raw_key3=_key3_fields(n_field, "0", "0"),
        raw_key6=_key6_fields("", ""),
        raw_keys={
            "1": "",
            "2": ",".join(_KEY2_ALL_ZERO) + ",",
            "3": "",
            "4": _key4_string(nm, unit, short),
            "5": ",".join(("0", _KEY5_FIELD2) + _KEY5_OTHER_ZERO) + ",",
            "6": "",
            "7": ",".join(_KEY7_ALL_ZERO) + ",",
        },
    )
    return entry


def build_entries(
    reader_module,
    ld_path: Path,
    apply_map_fn=_default_apply_map,
    get_scaling_fn=_default_scaling_fn,
    derived=None,
) -> ConversionResult:
    """.ld の全 ch を DddEntry 列へ変換する（テンプレート非依存）。

    apply_map_fn: (raw_name, raw_unit) -> list[(name, unit)] のコールバック
    get_scaling_fn: (raw_name) -> tuple[multiplier, offset] のコールバック（Ld2Mes-003）
    derived: 派生チャンネル（`derived_channels.DerivedChannel` の列。name/unit/values/rate を持つ）。
        既存の全チャンネルの**後ろ**へ同じ経路（名前の一意化・gain/offset・DDD 生成）で足す。基準周波数
        （base_hz）は既存の記録の速さだけから選ぶので、派生を足しても変わらない（Ld2Mes-007 承認条件 C3）。
        対応表（apply_map_fn）と Multiplier/Offset は派生に適用しない（承認条件 C2）。None なら今の処理と同一。
    """
    metas = [c for c in reader_module.channel_meta(ld_path) if (c.get("name") or "").strip()]

    skipped: list[tuple[str, str]] = []

    base_sanitized = [sanitize_name(m["name"]) for m in metas]
    combined_names: list[str] = list(base_sanitized)

    # 1ch=1レコードで values を先に確定し、読み込み不能(dtype未対応)な ch を除外する。
    records: list[dict] = []
    for i, meta in enumerate(metas):
        try:
            values = np.asarray(reader_module.read_channel(ld_path, meta), dtype=np.float64)
        except ValueError as exc:
            skipped.append((meta.get("name", "?"), str(exc)))
            continue

        raw_name = meta.get("name") or ""
        m, o = get_scaling_fn(raw_name)
        if m == 1.0 and o == 0.0:
            # 恒等変換: 浮動小数点演算パイプラインを一切通さず、生配列参照を完全パススルー（B-完1保証）
            scaled_values = values
        else:
            scaled_values = values * m + o
            if not np.all(np.isfinite(scaled_values)):
                raise ValueError(f"{raw_name}: Post-scaling data contains non-finite values (NaN/Inf)")

        records.append({"meta": meta, "values": scaled_values, "meta_index": i})

    if not records:
        return ConversionResult(entries=[], values_by_name={}, base_hz=_BASE_HZ_CANDIDATES[0], skipped=skipped)

    rates = [float(r["meta"].get("freq") or 0.0) for r in records]
    base_hz, bad_rates = choose_base_hz(rates)

    # 対応表を適用し、1レコードから1〜2件の出力候補（同一valuesを共有）を作る。
    # 基本候補（対応表適用前のraw_name）は上で予約済みのスロット(meta_index)を
    # そのまま使う。追加候補（custom_name）だけがcombined_namesへ新規スロットを
    # 追加する。
    #
    # 2026-09-06（納品C CP1）: sanitize_name()はカンマ・制御文字しか防がず、cp1252で
    # エンコード不能な文字（日本語等）はチェックしないため、対応表のcustom_nameに
    # そのような文字が入るとDDD全体のエンコードでUnicodeEncodeErrorが起きクラッシュ
    # する実バグを発見した（本ツールの実装テストで実際に再現）。ここでcp1252安全性を
    # 検査し、不能ならそのcandidate（元チャンネルなら基本スロットのunitのみ空欄化、
    # 追加チャンネルならスロット自体を作らずスキップ）を理由付きでスキップする
    # （combined_namesに追加する前に落とすため、スキップされた名前が他の衝突解消の
    # ~2/~3付与へ影響することはない）。
    pending: list[dict] = []
    for rec in records:
        meta = rec["meta"]
        meta_index = rec["meta_index"]
        rate = float(meta.get("freq") or 0.0)
        if rate in bad_rates:
            skipped.append((meta.get("name", "?"), bad_rates[rate]))
            continue
        raw_name = meta["name"]
        raw_unit = (meta.get("unit") or "").strip()
        candidate_specs: list[dict] = []
        for cand_idx, (candidate_name, candidate_unit) in enumerate(apply_map_fn(raw_name, raw_unit)):
            if cand_idx == 0:
                # 基本候補: 予約済みスロット(meta_index)をそのまま使う。sanitize_name
                # は既にbase_sanitized[meta_index]で計算済み（candidate_name==raw_name
                # のはずだが、apply_map_fnの契約を信頼しすぎず改めてcp1252検査は行う）。
                sanitized_name = base_sanitized[meta_index]
                try:
                    sanitized_name.encode("cp1252", errors="strict")
                except UnicodeEncodeError as exc:
                    skipped.append((candidate_name, f"Name cannot be encoded in cp1252: {exc}"))
                    continue
                candidate_specs.append({"slot": meta_index, "unit_raw": candidate_unit})
                continue

            sanitized_name = sanitize_name(candidate_name)
            try:
                sanitized_name.encode("cp1252", errors="strict")
            except UnicodeEncodeError as exc:
                skipped.append((candidate_name, f"Name cannot be encoded in cp1252: {exc}"))
                continue
            slot = len(combined_names)
            combined_names.append(sanitized_name)
            candidate_specs.append({"slot": slot, "unit_raw": candidate_unit})

        if candidate_specs:
            pending.append({"values": rec["values"], "rate": rate, "candidates": candidate_specs})

    # Ld2Mes-007: 派生チャンネルを既存の後ろへ足す（unique_names は入力の順に衝突を解消するので、既存の名前は動かない）
    derived_slots: list[tuple[str, int]] = []
    for dc in derived or []:
        d_sanitized = sanitize_name(dc.name)
        try:
            d_sanitized.encode("cp1252", errors="strict")
        except UnicodeEncodeError as exc:
            skipped.append((dc.name, f"Derived channel name cannot be encoded in cp1252: {exc}"))
            continue
        d_rate = float(dc.rate)
        if not (0 < d_rate <= base_hz and base_hz % d_rate == 0):
            skipped.append((dc.name, f"Derived channel rate={d_rate}Hz not evenly divisible by base_hz={base_hz}"))
            continue
        d_slot = len(combined_names)
        combined_names.append(d_sanitized)
        pending.append({"values": np.asarray(dc.values, dtype=np.float64), "rate": d_rate,
                        "candidates": [{"slot": d_slot, "unit_raw": dc.unit}]})
        derived_slots.append((dc.name, d_slot))

    unique = unique_names(combined_names)

    entries: list[mr.DddEntry] = []
    values_by_name: dict[str, np.ndarray] = {}
    idx = 0
    for rec in pending:
        values = rec["values"]
        rate = rec["rate"]
        for spec in rec["candidates"]:
            nm = unique[spec["slot"]]

            idx += 1
            entry = make_entry(idx, nm, spec["unit_raw"], values, rate, base_hz, skipped)
            entries.append(entry)
            values_by_name[nm] = values

    return ConversionResult(
        entries=entries,
        values_by_name=values_by_name,
        base_hz=base_hz,
        skipped=skipped,
        metas=metas,
        derived_names=[(req, unique[slot]) for req, slot in derived_slots],
    )
