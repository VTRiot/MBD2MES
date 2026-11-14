# -*- coding: utf-8 -*-
"""channel_map.py -- チャンネル対応表（MBD の名前/単位/任意名/一次変換）の読み書き・適用。

RCZ2MES の channel_map.py（commit 5b31da8）からの写し（元は LD2MES の同名ファイル）。MBD2MES 用の改変（docs/provenance.md）:
  - パッケージ内の相対 import（`from . import config as cfgmod`・`from . import ddd_generator as gen`）。
  - 名前の置換: 退避先の %LOCALAPPDATA%\\MBD2MES\\・変換関数の名前（convert.convert_one）。ロジックは無改変。
  - 「出さない」の欄 output は持たない（頼まれていない）。保護する行は map_rules.py に置いた。

config.py と同じ「seed（同梱の初期値・読み取り専用）→実効ファイル（exe 横、書込不可なら
%LOCALAPPDATA%\\MBD2MES\\ へフォールバック）」の 2 層構造。対応表はキーを「MES に書く側のチャンネル名
（unique_names 適用前）」とする辞書。GUI・D&D・CLI の 3 経路とも、変換ワークフロー全体を 1 関数に閉じた
convert.convert_one() の中でのみ適用される。
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from . import config as cfgmod

_SCHEMA_VERSION = 1
_SEED_NAME = "channel_map.seed.json"
_MAP_NAME = "channel_map.json"
_OMITTED = object()


def validate_scaling_factors(raw_name: str, multiplier: any, offset: any) -> tuple[float, float]:
    """Multiplier と Offset の値を厳格に検証する（Ld2Mes-003 Codex F2 / 実装後 F2）。

    - 欠落時（_OMITTED）: 既定値 (1.0, 0.0) を補完（後方互換性 B-完3）。
    - 明示的な null（None）や不正値（文字列、nan, inf, -inf, bool, 0.0）:
      1.0/0.0 にサイレント置換せず ValueError を送出。
    """
    if multiplier is _OMITTED:
        m_val = 1.0
    elif multiplier is None:
        raise ValueError(f"{raw_name}: Multiplier cannot be null. Please specify a numeric value such as 1.0 (identity).")
    elif isinstance(multiplier, bool) or not isinstance(multiplier, (int, float, str)):
        raise ValueError(f"{raw_name}: Multiplier must be a numeric value: {multiplier!r}")
    else:
        try:
            m_val = float(multiplier)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{raw_name}: Cannot convert Multiplier to number: {multiplier!r}") from exc

    if not math.isfinite(m_val) or math.isnan(m_val):
        raise ValueError(f"{raw_name}: Multiplier must be a finite real number: {m_val!r}")
    if m_val == 0.0:
        raise ValueError(f"{raw_name}: Multiplier cannot be 0.0 (prevents physical data loss)")

    if offset is _OMITTED:
        o_val = 0.0
    elif offset is None:
        raise ValueError(f"{raw_name}: Offset cannot be null. Please specify a numeric value such as 0.0 (identity).")
    elif isinstance(offset, bool) or not isinstance(offset, (int, float, str)):
        raise ValueError(f"{raw_name}: Offset must be a numeric value: {offset!r}")
    else:
        try:
            o_val = float(offset)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{raw_name}: Cannot convert Offset to number: {offset!r}") from exc

    if not math.isfinite(o_val) or math.isnan(o_val):
        raise ValueError(f"{raw_name}: Offset must be a finite real number: {o_val!r}")

    return m_val, o_val


def get_channel_scaling(channel_map: dict, raw_name: str) -> tuple[float, float]:
    """チャンネルの (multiplier, offset) を取得する。未登録時は (1.0, 0.0) を返す。"""
    entry = channel_map.get("channels", {}).get(raw_name)
    if not isinstance(entry, dict):
        return 1.0, 0.0
    m = entry.get("multiplier", _OMITTED)
    o = entry.get("offset", _OMITTED)
    return validate_scaling_factors(raw_name, m, o)



def seed_path() -> Path:
    """frozen時: sys._MEIPASS配下のseed。非frozen時: app_base_dir()配下の同名ファイル。

    config.seed_path()と同じロジック（このファイル用の名前で複製。config.pyの
    seed_path()はmbd2mes_config.seed.json専用でハードコードされているため共有できない）。
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / _SEED_NAME
    return cfgmod.app_base_dir() / _SEED_NAME


def map_path(base: Path | None = None, fallback_base: Path | None = None) -> Path:
    """base/channel_map.json。書込不可ならfallback_base(既定%LOCALAPPDATA%\\MBD2MES\\)へ。"""
    base = base if base is not None else cfgmod.settings_base_dir()
    if cfgmod.is_writable_dir(base):
        return base / _MAP_NAME
    fb = fallback_base if fallback_base is not None else cfgmod.local_appdata_dir()
    return fb / _MAP_NAME


def _set_aside(path: Path) -> bool:
    """壊れた／schema 違いの実効ファイルを上書きする前に、一意な名前で退避する（RCZ2MES で追加）。
    退避できたら True。できなければ False（呼び出し側は元のファイルを上書きしない）。"""
    try:
        shutil.copy2(path, path.with_name(f"{path.name}.corrupt_{os.getpid()}_{time.time_ns()}"))
        return True
    except OSError as exc:
        print(f"[WARN] could not set aside {path} ({exc}); it is left as it is and not overwritten", file=sys.stderr)
        return False


def _empty_map() -> dict:
    return {"schema": _SCHEMA_VERSION, "channels": {}}


def load_or_init_map(base: Path | None = None, fallback_base: Path | None = None) -> dict:
    """map_path()が無ければseed_path()からコピーして作成する。既存なら読み込む。

    schemaが無い/不一致なら空の対応表へ再初期化する（config.load_or_init_configの
    schema不一致処理と同型。対応表はoutput_dirのような単一の重要値を持たないため、
    移行救済ロジックは設けず単純に空へ倒す）。
    """
    path = map_path(base=base, fallback_base=fallback_base)
    seed = seed_path()

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if seed.exists():
            data = json.loads(seed.read_text(encoding="utf-8"))
        else:
            data = _empty_map()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}

    if data.get("schema") != _SCHEMA_VERSION or not isinstance(data.get("channels"), dict):
        print(f"[WARN] {path} のschemaが不正/不一致のため空の対応表へ再初期化します", file=sys.stderr)
        data = _empty_map()
        if _set_aside(path):  # 退避できたときだけ上書きする。できなければ元を残し、メモリ上の空の表で続ける
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    return data


def grow_channel_map(channel_map: dict, channel_metas: list[dict]) -> tuple[dict, int]:
    """対応表に未登録のチャンネルを素の状態（unit: None, custom_name: None）で追記する。

    unit: None とすることで、apply_channel_map において常に変換対象ログの生単位
    へフォールバック（完全パススルー）する意味論を保証する（Ld2Mes-001 重大1対応）。
    また raw_unit を初回観測時の生単位メタデータとして記録する。
    戻り値: (channel_map, 追記件数)
    """
    channels = channel_map.setdefault("channels", {})
    added = 0
    for meta in channel_metas:
        name = (meta.get("name") or "").strip()
        if not name:
            continue
        if name not in channels:
            raw_unit = (meta.get("unit") or "").strip()
            channels[name] = {
                "unit": None,
                "custom_name": None,
                "raw_unit": raw_unit,
                "multiplier": 1.0,
                "offset": 0.0,
            }
            added += 1
    return channel_map, added


def save_map(data: dict, base: Path | None = None, fallback_base: Path | None = None) -> Path:
    """対応表を保存する。GUIの保存ボタンなど、引数dataの全内容を正として保存する（GUI-master）。

    一意な一時ファイルへの書き込み完了後に os.replace でアトミック置換する。
    """
    path = map_path(base=base, fallback_base=fallback_base)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_data = {k: v for k, v in data.items() if not k.startswith("_")}
    if "channels" in clean_data and isinstance(clean_data["channels"], dict):
        clean_data["channels"] = {
            k: v for k, v in clean_data["channels"].items() if not k.startswith("_")
        }
    content = json.dumps(clean_data, ensure_ascii=False, indent=2)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.stem}_",
            suffix=".tmp",
            delete=False,
        ) as tf:
            tmp_path = Path(tf.name)
            tf.write(content)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
    return path


def merge_and_save_map(
    data: dict,
    base: Path | None = None,
    fallback_base: Path | None = None,
    *,
    log=print,
) -> tuple[Path | None, bool]:
    """変換時のauto-grow専用保存処理。ディスク上の既存内容に未登録行のみを追記マージして保存する。

    - ディスク上の最新ファイルを読込。JSON破損または読込エラー時は上書きを中止し元ファイルを保護（C2）。
    - ディスク上の channels に存在しないキーのみを data から追記。
    - 上書き前に既存ファイルの .bak を作成（同名 .bak が実在すれば上書きせず保護）。
    - 一意な一時ファイル書き込み後に os.replace でアトミック置換。
    - 例外発生時は log で警告を出力し、(path, False) を返却（例外送出なし、変換主機能を保護）。
    """
    tmp_path: Path | None = None
    try:
        path = map_path(base=base, fallback_base=fallback_base)
        path.parent.mkdir(parents=True, exist_ok=True)

        disk_data = None
        if path.exists():
            try:
                disk_data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                log(f"[WARN] Failed to read/parse channel map {path}. Aborting save to protect original file: {exc}")
                return path, False

            if not isinstance(disk_data, dict):
                log(f"[WARN] Channel map {path} top-level is not a dict. Aborting save to protect original file")
                return path, False

            if disk_data.get("schema") != _SCHEMA_VERSION or not isinstance(disk_data.get("channels"), dict):
                log(f"[WARN] Channel map {path} schema or channels is invalid. Aborting save to protect original file")
                return path, False

        if disk_data is None:
            merged_data = json.loads(json.dumps(data))
        else:
            merged_data = disk_data
            disk_channels = merged_data.setdefault("channels", {})
            for name, entry in data.get("channels", {}).items():
                if name not in disk_channels:
                    disk_channels[name] = dict(entry)

        # .bak 作成
        if path.exists():
            bak_path = path.with_suffix(path.suffix + ".bak")
            if not bak_path.exists():
                try:
                    shutil.copy2(path, bak_path)
                except OSError as exc:
                    log(f"[WARN] Failed to create .bak backup of channel map: {exc}")

        # アトミック書き込み（内部管理用キーを除外）
        clean_data = {k: v for k, v in merged_data.items() if not k.startswith("_")}
        if "channels" in clean_data and isinstance(clean_data["channels"], dict):
            clean_data["channels"] = {
                k: v for k, v in clean_data["channels"].items() if not k.startswith("_")
            }
        content = json.dumps(clean_data, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.stem}_",
            suffix=".tmp",
            delete=False,
        ) as tf:
            tmp_path = Path(tf.name)
            tf.write(content)

        os.replace(tmp_path, path)
        tmp_path = None
        return path, True
    except Exception as exc:  # noqa: BLE001
        log(f"[WARN] Failed to save channel map: {exc}")
        return None, False
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def update_entry(
    data: dict,
    raw_name: str,
    unit: str | None,
    custom_name: str | None,
    multiplier: any = _OMITTED,
    offset: any = _OMITTED,
) -> None:
    """GUI 等から1行の設定を更新する。raw_unit などの既存メタデータを維持する（Ld2Mes-001 重大4）。

    Multiplier / Offset は未指定(_OMITTED)時は既存値を維持する（Ld2Mes-003 Codex F8）。
    """
    channels = data.setdefault("channels", {})
    entry = channels.setdefault(raw_name, {})
    entry["unit"] = unit
    entry["custom_name"] = custom_name
    if multiplier is not _OMITTED:
        m_val, _ = validate_scaling_factors(raw_name, multiplier, 0.0)
        entry["multiplier"] = m_val
    elif "multiplier" not in entry:
        entry["multiplier"] = 1.0

    if offset is not _OMITTED:
        _, o_val = validate_scaling_factors(raw_name, 1.0, offset)
        entry["offset"] = o_val
    elif "offset" not in entry:
        entry["offset"] = 0.0


def reset_entry(data: dict, raw_name: str, seed_data: dict) -> None:
    """1行を初期値に戻す。

    - seed にある行: seed の内容（初期値）に戻す。
    - seed にない追記行: 削除せず保持し、unit: None（生単位追従）, custom_name: None に初期化（重大3、オーナー決定4）。
      raw_unit はそのまま保持し、multiplier=1.0, offset=0.0 に戻す。
    """
    seed_channels = seed_data.get("channels", {})
    channels = data.setdefault("channels", {})
    if raw_name in seed_channels:
        channels[raw_name] = dict(seed_channels[raw_name])
    elif raw_name in channels:
        raw_unit = channels[raw_name].get("raw_unit", "")
        channels[raw_name] = {
            "unit": None,
            "custom_name": None,
            "raw_unit": raw_unit,
            "multiplier": 1.0,
            "offset": 0.0,
        }


def delete_entry(data: dict, raw_name: str, seed_data: dict) -> bool:
    """行を対応表から明示的に削除する（オーナーによる手動削除用）。

    seed に存在する初期同梱行は削除不可（Falseを返却）。
    seed に存在しない追記行のみ削除可能（Trueを返却）。
    """
    seed_channels = seed_data.get("channels", {})
    if raw_name in seed_channels:
        return False
    channels = data.get("channels", {})
    if raw_name in channels:
        del channels[raw_name]
        return True
    return False


def reset_all(seed_data: dict, current_data: dict | None = None) -> dict:
    """対応表全体を初期化する。

    - seed の内容をディープコピー。
    - current_data に存在するが seed にない追記行は、削除せず素の状態
      （unit: None, custom_name: None, raw_unit 保持, multiplier: 1.0, offset: 0.0）で引き継ぐ（オーナー決定4）。
    """
    res = json.loads(json.dumps(seed_data))
    if current_data and isinstance(current_data.get("channels"), dict):
        seed_channels = seed_data.get("channels", {})
        res_channels = res.setdefault("channels", {})
        for raw_name, entry in current_data["channels"].items():
            if raw_name not in seed_channels and isinstance(entry, dict):
                res_channels[raw_name] = {
                    "unit": None,
                    "custom_name": None,
                    "raw_unit": entry.get("raw_unit", ""),
                    "multiplier": 1.0,
                    "offset": 0.0,
                }
    return res


def apply_channel_map(raw_name: str, raw_unit: str, channel_map: dict) -> list[tuple[str, str]]:
    """生チャンネル名・生単位に対応表を適用し、出力すべき(name, unit)のリストを返す。

    指示書r2（オーナー09-06追加指示）: 任意名Cは「置換」ではなく「元チャンネルを
    残したまま同一データを追加チャンネルとして出力する」。戻り値がリストなのはこのため。

    - 対応表に無いチャンネル → `[(raw_name, raw_unit)]`（完全パススルー）
    - custom_name未設定（null/空） → `[(raw_name, effective_unit)]`（1件。単位のみ上書き）
    - custom_name設定あり → `[(raw_name, effective_unit), (custom_name, effective_unit)]`
      （2件。元チャンネルは残し、同じ単位の追加チャンネルを足す）

    【B-完2 整合性ガード (Codex F3)】:
    Multiplier != 1.0 または Offset != 0.0（一次変換が設定されている）にもかかわらず
    unit が None（生単位追従）のままの場合、変換後の値に未変換の生単位が付く危険を防止するため、
    ValueError を送出して変換を停止する。
    """
    entry = channel_map.get("channels", {}).get(raw_name)
    if not isinstance(entry, dict):
        return [(raw_name, raw_unit)]

    m = entry.get("multiplier", _OMITTED)
    o = entry.get("offset", _OMITTED)
    m_val, o_val = validate_scaling_factors(raw_name, m, o)
    is_scaling = (m_val != 1.0 or o_val != 0.0)

    # B-完2 ガード: 一次変換設定時は変換後の単位明示（有効な文字列）が必須（Codex impl F1）
    target_unit = entry.get("unit")
    if is_scaling:
        if not isinstance(target_unit, str):
            raise ValueError(
                f"{raw_name}: Linear scaling (Multiplier={m_val}, Offset={o_val}) is configured, but a valid unit string is not specified (unit={target_unit!r}). "
                'Please specify the converted unit explicitly (or specify empty string "" to intentionally omit unit).'
            )
        unit = target_unit
    else:
        if isinstance(target_unit, str):
            unit = target_unit
        else:
            unit = raw_unit

    custom_name = entry.get("custom_name")
    if not isinstance(custom_name, str) or not custom_name:
        return [(raw_name, unit)]
    return [(raw_name, unit), (custom_name, unit)]



def validate_map_entry(name: str | None, unit: str | None) -> list[str]:
    """name/unitがDDD制約(sanitize_name/sanitize_unitの既存ロジック)を無傷で通るか検証する。

    review_r7 finding[1]反映: 独自の禁止文字リストを新設せず、既存の正規のサニタイズ
    処理に通した結果が入力と一致するかどうかで判定する（一致しなければ「変換時に
    黙って変わる」ことを意味するため警告対象にする）。戻り値: 警告メッセージのリスト
    （空 = 問題なし）。
    """
    from . import ddd_generator as gen

    warnings: list[str] = []
    if name:
        sanitized = gen.sanitize_name(name)
        if sanitized != name:
            warnings.append(f"Name {name!r} will be automatically replaced with {sanitized!r} during conversion.")
    if unit:
        sanitized_unit, reason = gen.sanitize_unit(unit)
        if sanitized_unit != unit:
            warnings.append(f"Unit {unit!r} will be replaced with {sanitized_unit!r} during conversion ({reason}).")
    return warnings
