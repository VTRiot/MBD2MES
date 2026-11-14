# -*- coding: utf-8 -*-
"""config.py -- MBD2MES の実行時設定（RCZ2MES の config.py（commit 5b31da8）からの写し。MBD2MES 用に改変）。

frozen（PyInstaller exe 化後）/非 frozen（python 実行）の両方で、「exe 横（またはリポ直下）」を一意に判定する。
seed（同梱の初期値）を実効 config へコピーする際、exe 横が書込不可なら %LOCALAPPDATA%\\MBD2MES\\ へフォールバックする
（書込プローブで実測して判定する）。開発実行時に生成される mbd2mes_config.json・channel_map.json はリポジトリに含めない（.gitignore）。

RCZ2MES からの改変の要点（docs/provenance.md）:
  - 名前を MBD2MES に（seed・config・プローブ・%LOCALAPPDATA% のフォルダ・環境変数）。last_rcz_dir -> last_mbd_dir。
  - 非 frozen の app_base_dir() はパッケージの 1 つ上（リポ直下）。パッケージの中にある本ファイルの親は mbd2mes\\ なので。
  - default_rcz_dir と一発変換の台帳（batch_checkpoints）一式を削除した（MBD2MES には無い機能）。
  - 環境変数 MBD2MES_SETTINGS_DIR があれば、設定・対応表の置き場をそこへ替える（試験の隔離。subprocess にも効く）。
    seed の位置（app_base_dir / _MEIPASS）は替えない。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

_SCHEMA_VERSION = 1
_SEED_NAME = "mbd2mes_config.seed.json"
_CONFIG_NAME = "mbd2mes_config.json"
_APP_DIR_NAME = "MBD2MES"
_PROBE_NAME = ".mbd2mes_write_probe.tmp"
# 設定・対応表の置き場を替える環境変数（試験の隔離用。tests/conftest.py が設定する）
SETTINGS_ENV = "MBD2MES_SETTINGS_DIR"


def _atomic_write_json(path: Path, data: dict) -> None:
    """一意な一時ファイルへ書き込み、fsync を経て原子的に置換する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}_{time.time_ns()}.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def _set_aside(path: Path) -> bool:
    """壊れた／schema 違いの実効ファイルを上書きする前に、一意な名前で退避する。
    退避できたら True。できなければ False（呼び出し側は元のファイルを上書きしない）。"""
    try:
        shutil.copy2(path, path.with_name(f"{path.name}.corrupt_{os.getpid()}_{time.time_ns()}"))
        return True
    except OSError as exc:
        print(f"[WARN] could not set aside {path} ({exc}); it is left as it is and not overwritten", file=sys.stderr)
        return False


def app_base_dir() -> Path:
    """frozen 時: dirname(sys.executable)。非 frozen 時: リポ直下（このパッケージの 1 つ上）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def settings_base_dir() -> Path:
    """設定・対応表を置く基準のフォルダ。環境変数 MBD2MES_SETTINGS_DIR があればそこ、無ければ app_base_dir()。"""
    override = os.environ.get(SETTINGS_ENV)
    if override:
        return Path(override)
    return app_base_dir()


def seed_path() -> Path:
    """frozen 時: sys._MEIPASS 配下の seed。非 frozen 時: app_base_dir() 配下の同名ファイル。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / _SEED_NAME
    return app_base_dir() / _SEED_NAME


def is_writable_dir(d: Path) -> bool:
    """d への書込プローブ（一時マーカーファイルの作成試行）。実測で判定する。"""
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / _PROBE_NAME
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def local_appdata_dir() -> Path:
    """書込不可のときの退避先。環境変数で置き場を替えているときは、その下（実際の %LOCALAPPDATA% に触れない）。"""
    if os.environ.get(SETTINGS_ENV):
        return settings_base_dir() / "localappdata"
    localappdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    return localappdata / _APP_DIR_NAME


def config_path(base: Path | None = None, fallback_base: Path | None = None) -> Path:
    """base/mbd2mes_config.json。書込不可なら fallback_base（既定 %LOCALAPPDATA%\\MBD2MES\\）へ。
    base/fallback_base は試験用の注入ポイント。"""
    base = base if base is not None else settings_base_dir()
    if is_writable_dir(base):
        return base / _CONFIG_NAME
    fb = fallback_base if fallback_base is not None else local_appdata_dir()
    return fb / _CONFIG_NAME


def _default_config() -> dict:
    return {"schema": _SCHEMA_VERSION, "output_dir": None, "last_mbd_dir": None}


def load_or_init_config(base: Path | None = None, fallback_base: Path | None = None) -> dict:
    """config_path() が無ければ seed_path() からコピーして作成する。既存なら読み込む。

    schema が無い/不一致なら再初期化するが、既存の output_dir・last_mbd_dir が実在ディレクトリなら引き継ぐ
    （手編集ミス等からの復旧時に設定済みの出力先を失わないため）。警告を stderr へ出す。
    """
    path = config_path(base=base, fallback_base=fallback_base)
    seed = seed_path()

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if seed.exists():
            data = json.loads(seed.read_text(encoding="utf-8"))
        else:
            data = _default_config()
        _atomic_write_json(path, data)
        return data

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    if data.get("schema") != _SCHEMA_VERSION:
        print(f"[WARN] {path} has an invalid or mismatched schema; re-initializing", file=sys.stderr)
        can_overwrite = _set_aside(path)
        fresh = _default_config()
        for key in ("output_dir", "last_mbd_dir"):
            old = data.get(key)
            if old and Path(old).is_dir():
                fresh[key] = old
                print(f"[WARN] kept {key} because it is an existing directory: {old}", file=sys.stderr)
        if isinstance(data.get("batch_checkpoints"), dict):  # 一発変換の起点は schema が変わっても失わない
            fresh["batch_checkpoints"] = data["batch_checkpoints"]
        data = fresh
        if can_overwrite:  # 退避できなかったときは元のファイルを残し、メモリ上の値で続ける
            _atomic_write_json(path, data)

    return data


def _get_dir(cfg: dict, key: str) -> Path | None:
    raw = cfg.get(key)
    if not raw or not isinstance(raw, str):
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def get_output_dir(cfg: dict) -> Path | None:
    """cfg["output_dir"] があり実在ディレクトリなら Path を返す。無ければ None。"""
    return _get_dir(cfg, "output_dir")


def get_last_mbd_dir(cfg: dict) -> Path | None:
    """cfg["last_mbd_dir"] があり実在ディレクトリなら Path を返す。無ければ None。"""
    return _get_dir(cfg, "last_mbd_dir")


def _set_key(key: str, value: Path, base: Path | None, fallback_base: Path | None) -> Path:
    path = config_path(base=base, fallback_base=fallback_base)
    cfg = load_or_init_config(base=base, fallback_base=fallback_base)
    cfg[key] = str(value)
    _atomic_write_json(path, cfg)
    return path


def set_output_dir(output_dir: Path, base: Path | None = None, fallback_base: Path | None = None) -> Path:
    """GUI から出力先を設定・永続化する。CLI/D&D 経路（-o 省略）も同じファイルから読む。"""
    return _set_key("output_dir", Path(output_dir), base, fallback_base)


def set_last_mbd_dir(last_mbd_dir: Path, base: Path | None = None, fallback_base: Path | None = None) -> Path:
    """GUI から最後に参照した .MBD のフォルダを設定・永続化する。"""
    return _set_key("last_mbd_dir", Path(last_mbd_dir).resolve(), base, fallback_base)


# ---------------------------------------------------------------- 一発変換（Convert Unconverted）の起点（checkpoint）
# RCZ2MES の config.py（commit 5b31da8）の同名の関数からの写し（元は LD2MES）。フォルダごとに「前に走査を始めた時刻」と
# 「前回失敗したファイル名」を持つ。キーはフォルダのパスを正規化した文字列。
def normalize_checkpoint_key(source_dir: str | Path) -> str:
    """Windows のパス表現差や大文字小文字による起点のキーの分裂を防ぐ。"""
    return os.path.normcase(str(Path(source_dir).resolve()))


def get_batch_checkpoint(source_dir: str | Path, base: Path | None = None, fallback_base: Path | None = None) -> dict | None:
    """source_dir の起点を取得する。形: {"scan_started_at_ns": int, "scan_started_at_iso": str, "failed_files": [source_dir からの名前]}。
    無い・形が不正なら None。"""
    cfg = load_or_init_config(base=base, fallback_base=fallback_base)
    checkpoints = cfg.get("batch_checkpoints")
    if not isinstance(checkpoints, dict):
        return None
    cp = checkpoints.get(normalize_checkpoint_key(source_dir))
    return cp if checkpoint_is_valid(cp) else None


def checkpoint_is_valid(cp) -> bool:
    """起点の形の検査: scan_started_at_ns が整数（bool は不可）で、failed_files があれば文字列のリスト。
    手で書き換えられた・壊れた起点は「無い」として扱う（初回と同じ = 検証できない物を黙って飛ばさない）。"""
    if not isinstance(cp, dict):
        return False
    ns = cp.get("scan_started_at_ns")
    if isinstance(ns, bool) or not isinstance(ns, int):
        return False
    failed = cp.get("failed_files", [])
    return failed is None or (isinstance(failed, list) and all(isinstance(f, str) for f in failed))


def set_batch_checkpoint(source_dir: str | Path, scan_started_at_ns: int, failed_files: list[str] | None = None,
                         base: Path | None = None, fallback_base: Path | None = None) -> Path:
    """source_dir の起点を設定・永続化する。"""
    from datetime import datetime, timezone

    path = config_path(base=base, fallback_base=fallback_base)
    cfg = load_or_init_config(base=base, fallback_base=fallback_base)
    checkpoints = cfg.get("batch_checkpoints")
    if not isinstance(checkpoints, dict):
        checkpoints = {}
        cfg["batch_checkpoints"] = checkpoints
    norm_failed = sorted({Path(f).as_posix() for f in (failed_files or []) if f})
    checkpoints[normalize_checkpoint_key(source_dir)] = {
        "scan_started_at_ns": int(scan_started_at_ns),
        "scan_started_at_iso": datetime.fromtimestamp(scan_started_at_ns / 1e9, tz=timezone.utc).isoformat(),
        "failed_files": norm_failed,
    }
    _atomic_write_json(path, cfg)
    return path


def clear_batch_checkpoint(source_dir: str | Path, base: Path | None = None, fallback_base: Path | None = None) -> Path:
    """source_dir の起点を削除する（試験・再初期化用）。"""
    path = config_path(base=base, fallback_base=fallback_base)
    cfg = load_or_init_config(base=base, fallback_base=fallback_base)
    checkpoints = cfg.get("batch_checkpoints")
    if isinstance(checkpoints, dict) and normalize_checkpoint_key(source_dir) in checkpoints:
        del checkpoints[normalize_checkpoint_key(source_dir)]
        _atomic_write_json(path, cfg)
    return path
