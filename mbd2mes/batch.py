# -*- coding: utf-8 -*-
"""batch.py -- 一発変換（Convert Unconverted）の走査・実行・画面用の文（FB01）。

RCZ2MES の rcz_batch.py（commit 5b31da8。元は LD2MES の batch_converter.py）からの写し。MBD2MES 用の改変（docs/provenance.md）:
  - 名前: .rcz -> .MBD、RCZ2MES -> MBD2MES、台帳は出力先の .mbd2mes_manifest.json、記録は MBD2MES_record.txt。
  - 「セッションか」の見分けは、MBD の先頭のマジック（4OEL V）と大きさ（ヘッダ + チャネル表 = 0x2000 byte 以上）だけ。
    中身は読まない（走査は軽く保つ）。マジックが違えば NOT_SESSION、短ければ UNREADABLE（コピー中の可能性。次回やり直す）。
  - ファイル全体の読み込みをやめ、SHA-256 は 1 MiB ずつの逐次読み（標本は 14 MB 級で、フォルダに何本もあるため）。
  - 変換は app_convert.convert_many -> convert.convert_one（GUI の Convert と同じ経路）。公開の直前のガードは before_replace。
  - 記録日（HED の日付）: date（GUI の欄・任意）があれば全部に使い、無ければ 1 本ずつファイル名から読む（dates.choose）。
    読めなければ更新時刻（警告つき）。確認の画面に 1 本ごとの日付と出どころを出す（confirm_text）。
走査 scan_mbd_directory は出力先と MBD のフォルダを読むだけ（書かない・消さない）。tk は import しない
（判定と文は全部ここに置き、GUI から切り離して試験する）。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from . import app_convert as ac
from . import config as cfgmod
from . import convert as cv
from . import dates
from . import ddd_invariants as di
from .mbd_reader import DATA_OFFSET, MAGIC

MANIFEST_NAME = ".mbd2mes_manifest.json"  # 出力先の中の台帳（RCZ2MES の .rcz2mes_manifest.json と別名）
MANIFEST_SCHEMA = 1
DIALOG_LIST_MAX = 10  # 確認の画面の一覧に出す件数。全件はログに出す
RECORD_HEAD_BYTES = 8192  # 記録ファイルの先頭から読む量（1〜3 行目だけ使う。convert._build_record）
RECORD_FIRST_LINE = "MBD2MES record"
RECORD_INPUT_PREFIX = "Input: "
RECORD_SHA_PREFIX = "Input SHA-256: "
MBD_SUFFIX = ".mbd"
HASH_CHUNK = 1 << 20  # SHA-256 を逐次に読む単位（1 MiB）

# 1 本ごとの行き先
NEW = "NEW"
OVERWRITE = "OVERWRITE"
ALREADY = "ALREADY"
OLDER = "OLDER"
PROTECTED = "PROTECTED"
NOT_SESSION = "NOT_SESSION"
UNREADABLE = "UNREADABLE"

# 持ち主の判定の答え
OWNER_SELF = "self"
OWNER_OTHER = "other"
OWNER_NONE = "none"
OWNER_CONFLICT = "conflict"


@dataclass
class MbdItem:
    """1 本の MBD の判定。"""

    path: Path
    mes_name: str = ""
    key: str = ""
    action: str = ""
    reason: str = ""
    sha256: str = ""
    size: int = 0
    mtime_ns: int = 0
    ctime_ns: int = 0
    target_existed: bool = False
    target_fingerprint: dict | None = None  # OVERWRITE のとき、走査の時点の MES の指紋
    previously_failed: bool = False


@dataclass
class ScanResult:
    source_dir: Path
    out_dir: Path
    scan_started_at_ns: int = 0
    convert_all: bool = False
    had_checkpoint: bool = False
    previous_failed: list[str] = field(default_factory=list)  # 前回の起点に残っていた失敗のファイル名
    items: list[MbdItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # 画面・ログに出す注（残骸・台帳の破損など）

    def _by(self, *actions: str) -> list[MbdItem]:
        return [i for i in self.items if i.action in actions]

    @property
    def to_convert(self) -> list[MbdItem]:
        return self._by(NEW, OVERWRITE)

    @property
    def new_items(self) -> list[MbdItem]:
        return self._by(NEW)

    @property
    def overwrite_items(self) -> list[MbdItem]:
        return self._by(OVERWRITE)

    @property
    def already(self) -> list[MbdItem]:
        return self._by(ALREADY)

    @property
    def older(self) -> list[MbdItem]:
        return self._by(OLDER)

    @property
    def protected(self) -> list[MbdItem]:
        return self._by(PROTECTED)

    @property
    def not_session(self) -> list[MbdItem]:
        return self._by(NOT_SESSION)

    @property
    def unreadable(self) -> list[MbdItem]:
        return self._by(UNREADABLE)


@dataclass
class BatchReport:
    total_candidates: int = 0
    converted: list[Path] = field(default_factory=list)
    failed_items: list[tuple[Path, str]] = field(default_factory=list)  # 変換の失敗＋読めなかった物（理由つき）
    externally_changed: list[Path] = field(default_factory=list)  # 公開の直前に出力先が変わっていて、公開をやめた物
    protected_count: int = 0
    already_count: int = 0
    older_count: int = 0
    not_session_count: int = 0
    saved_failed_files: list[str] = field(default_factory=list)  # 起点に保存した失敗の一覧
    map_saved: bool = True  # 対応表の自動成長を保存できたか（1 本でも保存に失敗したら False）
    checkpoint_saved: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def converted_count(self) -> int:
        return len(self.converted)

    @property
    def failed_count(self) -> int:
        return len(self.failed_items)


class ExternalChange(cv.ConvertError):
    """走査のあとに外部が出力先の MES を変えた。公開をやめる（外部の資産を守る）。"""


# ============================================================ 部品
PEEK_OK, PEEK_NOT_MBD, PEEK_SHORT = "ok", "not_mbd", "short"


def peek_kind(head: bytes, size: int) -> str:
    """先頭の byte と大きさだけで、MBD として扱えるかを見る（中身は読まない。docs/mbd_format.md §1・§2）。"""
    if not head.startswith(MAGIC):
        return PEEK_NOT_MBD
    return PEEK_SHORT if size < DATA_OFFSET else PEEK_OK


def _sha256_and_head(path: Path) -> tuple[str, bytes]:
    """SHA-256（1 MiB ずつ逐次）と先頭 16 byte。"""
    h = hashlib.sha256()
    head = b""
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(HASH_CHUNK)
            if not chunk:
                break
            if not head:
                head = chunk[:16]
            h.update(chunk)
    return h.hexdigest(), head


def mes_fingerprint(mes_dir: Path) -> dict:
    """MES フォルダの全ファイルの相対名・大きさ・SHA-256（フォルダ自身の更新時刻は含めない）。無ければ {}。"""
    if not mes_dir.is_dir():
        return {}
    files: dict[str, list] = {}
    try:
        for p in sorted(mes_dir.rglob("*")):
            if p.is_file():
                files[p.relative_to(mes_dir).as_posix()] = [p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()]
    except OSError:
        files["<unreadable>"] = [-1, ""]
    return {"files": files}


def is_mes_healthy(mes_dir: Path, mes_name: str) -> bool:
    """MES が完全で、DDD の不変量を満たすか（.DDD と .CAL が揃い、違反が 0）。"""
    if not mes_dir.is_dir():
        return False
    ddd, cal = mes_dir / f"{mes_name}.DDD", mes_dir / f"{mes_name}.CAL"
    if not (ddd.is_file() and cal.is_file()):
        return False
    try:
        return not di.check_ddd_invariants(ddd, mes_dir, mes_name)
    except Exception:  # noqa: BLE001 -- 検査で落ちる MES は健全とみなさない
        return False


def read_record(mes_dir: Path) -> dict | None:
    """MES の記録 MBD2MES_record.txt の Input: と Input SHA-256: を読む。読めない・形が違えば None。"""
    try:
        with open(mes_dir / cv.RECORD_NAME, "rb") as fh:
            head = fh.read(RECORD_HEAD_BYTES)
    except OSError:
        return None
    lines = head.decode(cv.RECORD_ENCODING, errors="replace").splitlines()
    if not lines or lines[0].strip() != RECORD_FIRST_LINE:
        return None
    input_text = sha = None
    for line in lines[1:3]:
        if line.startswith(RECORD_INPUT_PREFIX):
            input_text = line[len(RECORD_INPUT_PREFIX):].strip()
        elif line.startswith(RECORD_SHA_PREFIX):
            sha = line[len(RECORD_SHA_PREFIX):].strip().lower()
    if not input_text or not sha:
        return None
    win = PureWindowsPath(input_text)
    return {"input": input_text, "filename": win.name, "folder": str(win.parent), "sha256": sha}


@dataclass
class Ledger:
    entries: dict = field(default_factory=dict)
    corrupt: bool = False
    reason: str = ""


def load_manifest(out_dir: Path) -> Ledger:
    """台帳を読む。無ければ空。壊れていれば空として返し corrupt を立てる（判定には使わず、保存の前に退避する）。"""
    path = out_dir / MANIFEST_NAME
    if not path.exists():
        return Ledger()
    if not path.is_file():
        return Ledger(corrupt=True, reason="not a regular file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Ledger(corrupt=True, reason=f"unreadable ({exc})")
    if not isinstance(data, dict) or data.get("schema") != MANIFEST_SCHEMA or not isinstance(data.get("entries"), dict):
        return Ledger(corrupt=True, reason="unexpected content or schema")
    return Ledger(entries={k: v for k, v in data["entries"].items() if isinstance(v, dict)})


def _norm_dir(text: str | Path) -> str:
    try:
        resolved = Path(text).resolve()
    except (OSError, ValueError, RuntimeError):
        resolved = Path(text)
    return os.path.normcase(os.path.normpath(str(resolved)))


def _owner_views(item: MbdItem, entry: dict | None, record: dict | None, source_dir_norm: str):
    """(台帳の見立て, 記録の見立て)。各々 None（証拠なし）か (OWNER_SELF|OWNER_OTHER, 他の名前)。"""
    name_cf = item.path.name.casefold()
    ledger_view = None
    if entry:
        sf = entry.get("source_filename")
        if isinstance(sf, str) and sf:
            if sf.casefold() != name_cf:
                ledger_view = (OWNER_OTHER, sf)
            else:
                # 名前だけでは持ち主にしない（別のフォルダの同名ファイルが、他の MBD の MES を上書きしないように）。
                # 記録と同じく、中身（SHA-256）か MBD のフォルダのどちらかが台帳の行と合うこと
                src_path = entry.get("source_path")
                same_folder = isinstance(src_path, str) and bool(src_path) and _norm_dir(Path(src_path).parent) == source_dir_norm
                same_sha = isinstance(entry.get("source_sha256"), str) and entry["source_sha256"].lower() == item.sha256
                if same_folder or same_sha:
                    ledger_view = (OWNER_SELF, "")
                else:
                    ledger_view = (OWNER_OTHER, f"{sf} (another folder, different content)")
    record_view = None
    if record:
        rf = record["filename"]
        if rf.casefold() != name_cf:
            record_view = (OWNER_OTHER, rf)
        elif record["sha256"] == item.sha256 or _norm_dir(record["folder"]) == source_dir_norm:
            record_view = (OWNER_SELF, "")
        else:
            record_view = (OWNER_OTHER, f"{rf} (another folder, different content)")
    return ledger_view, record_view


def judge_owner(item: MbdItem, entry: dict | None, record: dict | None, source_dir: Path) -> tuple[str, str]:
    """この MBD が、出力先の MES を作った持ち主か。台帳と記録の 2 つの証拠で見る。(答え, 説明)。

    答え: self（この MBD）／other（別の MBD。説明は元のファイル名）／none（証拠なし）／conflict（2 つが食い違う）。
    食い違うとき・証拠が無いときは、呼び出し側が保護する（開けて確かめられない所は閉める）。
    """
    ledger_view, record_view = _owner_views(item, entry, record, _norm_dir(source_dir))
    views = [v for v in (ledger_view, record_view) if v is not None]
    if not views:
        return OWNER_NONE, ""
    if len(views) == 1:
        return views[0][0], views[0][1]
    (a_kind, a_name), (b_kind, b_name) = views
    if a_kind == b_kind == OWNER_SELF:
        return OWNER_SELF, ""
    if a_kind == b_kind == OWNER_OTHER and a_name.casefold() == b_name.casefold():
        return OWNER_OTHER, a_name
    left = "this file" if a_kind == OWNER_SELF else a_name
    right = "this file" if b_kind == OWNER_SELF else b_name
    return OWNER_CONFLICT, f"the ledger says '{left}' but the MES record says '{right}'"


def _stage_leftovers(out_dir: Path) -> list[str]:
    try:
        return sorted(p.name for p in out_dir.iterdir() if p.is_dir() and p.name.startswith(cv.STAGE_PREFIX))
    except OSError:
        return []


# ============================================================ 走査（読むだけ）
def scan_mbd_directory(
    source_dir: str | Path,
    out_dir: str | Path,
    *,
    convert_all: bool = False,
    checkpoint: dict | None = None,
    scan_started_at_ns: int | None = None,
) -> ScanResult:
    """MBD のフォルダ直下の .MBD を 1 本ずつ判定する（3.2 の判定表）。出力先とフォルダは読むだけ。

    checkpoint は config.get_batch_checkpoint の形（scan_started_at_ns・failed_files）。None なら起点なし。
    「新しい」= max(更新時刻, 作成時刻) >= 起点（LD2MES と同じ）。
    """
    source_dir, out_dir = Path(source_dir), Path(out_dir)
    started = scan_started_at_ns if scan_started_at_ns is not None else time.time_ns()
    cp_ns = None
    failed_before: list[str] = []
    if cfgmod.checkpoint_is_valid(checkpoint):  # 形が不正な起点は無い物として扱う（例外にしない）
        cp_ns = int(checkpoint["scan_started_at_ns"])
        failed_before = [str(f) for f in (checkpoint.get("failed_files") or [])]
    failed_cf = {Path(f).name.casefold() for f in failed_before}
    scan = ScanResult(source_dir, out_dir, started, convert_all, cp_ns is not None, failed_before)

    ledger = load_manifest(out_dir)
    if ledger.corrupt:
        scan.notes.append(f"[WARN] The ledger {MANIFEST_NAME} in the output folder is damaged ({ledger.reason}); "
                          "it is ignored and set aside before the next save. Ownership is checked from the MES records.")
    leftovers = _stage_leftovers(out_dir)
    if leftovers:
        scan.notes.append(f"[WARN] {len(leftovers)} work folder(s) left in the output folder ({', '.join(leftovers[:3])}"
                          f"{', ...' if len(leftovers) > 3 else ''}); a previous MES may be inside. Nothing was touched.")

    try:
        files = sorted((p for p in source_dir.iterdir() if p.suffix.lower() == MBD_SUFFIX and not p.is_dir()),
                       key=lambda p: p.name.casefold())
    except OSError as exc:
        scan.notes.append(f"[ERROR] Cannot list {source_dir}: {exc}")
        return scan

    sessions: list[MbdItem] = []
    for path in files:
        item = MbdItem(path)
        try:
            st = path.stat()
            item.sha256, head = _sha256_and_head(path)
        except OSError as exc:
            item.action, item.reason = UNREADABLE, f"cannot read the file: {exc}"
            scan.items.append(item)
            continue
        item.size, item.mtime_ns, item.ctime_ns = st.st_size, st.st_mtime_ns, st.st_ctime_ns
        kind = peek_kind(head, item.size)
        if kind == PEEK_NOT_MBD:
            item.action, item.reason = NOT_SESSION, "not an MBD log: the file does not start with the MBDA2 magic (4OEL V)"
        elif kind == PEEK_SHORT:
            item.action = UNREADABLE
            item.reason = "too short to be an MBD log (incomplete, empty, or still being copied); it will be retried next time"
        else:
            item.mes_name = cv.sanitize_mes_name(path.stem)
            item.key = item.mes_name.casefold()
            item.previously_failed = path.name.casefold() in failed_cf
            sessions.append(item)
        scan.items.append(item)

    groups: dict[str, list[MbdItem]] = {}
    for item in sessions:
        groups.setdefault(item.key, []).append(item)
    for key, group in groups.items():
        _judge_group(scan, group, ledger, cp_ns, convert_all)
    return scan


def _newer(item: MbdItem, cp_ns: int | None) -> bool:
    return cp_ns is not None and max(item.mtime_ns, item.ctime_ns) >= cp_ns


def _judge_group(scan: ScanResult, group: list[MbdItem], ledger: Ledger, cp_ns: int | None, convert_all: bool) -> None:
    first = group[0]
    mes_dir = scan.out_dir / f"{first.mes_name}.MES"
    entry = ledger.entries.get(first.key)
    record = read_record(mes_dir) if mes_dir.is_dir() else None
    verdicts = {id(i): judge_owner(i, entry, record, scan.source_dir) for i in group}

    if len(group) > 1:
        owners = [i for i in group if verdicts[id(i)][0] == OWNER_SELF]
        names = ", ".join(i.path.name for i in group)
        conflict = f"MES name conflict: {len(group)} .MBD files map to '{first.mes_name}.MES' ({names})"
        for i in group:
            if not owners or i is not owners[0]:
                i.action, i.reason = PROTECTED, conflict
        group = [i for i in group if i.action != PROTECTED]
        if not group:
            return
    for item in group:
        item.target_existed = mes_dir.exists()
        _judge_one(scan, item, mes_dir, verdicts[id(item)], entry, record, cp_ns, convert_all)


def _judge_one(scan, item: MbdItem, mes_dir: Path, verdict: tuple[str, str], entry, record, cp_ns, convert_all) -> None:
    name = item.mes_name
    owner, detail = verdict
    if not mes_dir.exists():
        # 行 1: MES が無い
        if convert_all or cp_ns is None or item.previously_failed or _newer(item, cp_ns):
            item.action = NEW
            item.reason = ("Previously failed file; MES directory does not exist; scheduled for re-conversion"
                           if item.previously_failed and not convert_all else "MES directory does not exist")
        else:
            item.action = OLDER
            item.reason = ('Older than the checkpoint; not converted by this button '
                           '(tick "Convert all .MBD files" to include it)')
        return
    if not mes_dir.is_dir():
        item.action, item.reason = PROTECTED, f"'{name}.MES' exists but is not a folder"
        return
    healthy = is_mes_healthy(mes_dir, name)
    if healthy:
        if owner == OWNER_OTHER:
            item.action, item.reason = PROTECTED, f"MES name conflict: '{name}.MES' was converted from '{detail}'"
        elif owner == OWNER_CONFLICT:
            item.action = PROTECTED
            item.reason = f"'{name}.MES' has conflicting origin evidence ({detail}); protected (use Convert after checking)"
        elif owner == OWNER_NONE:
            item.action = PROTECTED
            item.reason = (f"'{name}.MES' exists without a ledger entry or an MBD2MES record; origin unknown "
                           "(use Convert to overwrite it after checking)")
        else:
            _judge_owned_healthy(scan, item, entry, record, cp_ns, convert_all, mes_dir)
        return
    # 壊れた MES
    if owner != OWNER_SELF:
        item.action = PROTECTED
        item.reason = f"Existing incomplete folder '{name}.MES' exists without verifiable ownership; protected"
    elif not any(mes_dir.glob("*.DDD")):
        item.action = PROTECTED
        item.reason = (f"'{name}.MES' has no .DDD; cannot be replaced safely "
                       "(remove the folder, or use Convert)")
    else:
        item.action = OVERWRITE
        item.reason = "Existing MES is incomplete or corrupted (owner verified); scheduled for re-conversion"
        item.target_fingerprint = mes_fingerprint(mes_dir)


def _signature_same(entry: dict | None, item: MbdItem) -> bool:
    """台帳の署名（名前・大きさ・更新時刻 ns）が今のファイルと全部同じか（D6）。"""
    if not entry:
        return False
    sf = entry.get("source_filename")
    return (isinstance(sf, str) and sf.casefold() == item.path.name.casefold()
            and entry.get("source_size") == item.size and entry.get("source_mtime_ns") == item.mtime_ns)


def _judge_owned_healthy(scan, item: MbdItem, entry, record, cp_ns, convert_all, mes_dir: Path) -> None:
    """行 6: 健全な MES・持ち主はこの MBD。時刻の規則（上から順に当てる）。"""
    signature_same = _signature_same(entry, item)
    if convert_all:
        item.action, item.reason = OVERWRITE, "Convert all selected; scheduled for re-conversion and overwrite"
    elif item.previously_failed:
        item.action, item.reason = OVERWRITE, "Previously failed file; scheduled for re-conversion"
    elif signature_same:
        item.action, item.reason = ALREADY, "Already converted; the file is unchanged since (ledger)"
        return
    elif _newer(item, cp_ns):
        item.action = OVERWRITE
        item.reason = "Source file created or modified after the checkpoint; scheduled for re-conversion and overwrite"
    else:
        known_sha = record["sha256"] if record else (entry or {}).get("source_sha256", "")
        differs = bool(known_sha) and known_sha != item.sha256
        if cp_ns is None and differs:
            item.action = OVERWRITE
            item.reason = ("No checkpoint yet and the MBD differs from the one converted (SHA-256); "
                           "scheduled for re-conversion")
        elif cp_ns is None:
            item.action, item.reason = ALREADY, "Already converted (verified by the MES record)"
            return
        elif differs:
            item.action = ALREADY
            item.reason = ('Already converted, but the MES was made from different content; '
                           'tick "Convert all .MBD files" to rebuild')
            return
        else:
            item.action, item.reason = ALREADY, "Already converted (older than the checkpoint)"
            return
    item.target_fingerprint = mes_fingerprint(mes_dir)


# ============================================================ 実行
def _entry_for(item: MbdItem, sha256: str, res: cv.ConvertResult) -> dict:
    return {
        "mes_name": item.mes_name,
        "mes_dir": str(res.mes_dir),
        "source_path": str(item.path.resolve()),
        "source_filename": item.path.name,
        "source_sha256": sha256,
        "source_size": item.size,
        "source_mtime_ns": item.mtime_ns,
        "status": "committed",
        "converted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # 書く直前に測る
    }


class _LedgerWriter:
    """台帳を 1 行ずつ原子的に保存する。壊れていた台帳は、最初の保存の前に退避する。退避できなければ書かない。"""

    def __init__(self, out_dir: Path, ledger: Ledger, log) -> None:
        self.path = out_dir / MANIFEST_NAME
        self.entries = dict(ledger.entries)
        self.corrupt = ledger.corrupt
        self.writable = True
        self.log = log

    def put(self, key: str, entry: dict) -> None:
        self.entries[key] = entry
        if not self.writable:
            return
        if self.corrupt:
            if not cfgmod._set_aside(self.path):  # noqa: SLF001 -- M2 で足した退避の関数
                self.writable = False
                self.log(f"[WARN] The damaged ledger {self.path.name} could not be set aside; it is left as it is and not overwritten")
                return
            self.corrupt = False
        try:
            cfgmod._atomic_write_json(self.path, {"schema": MANIFEST_SCHEMA, "entries": self.entries})  # noqa: SLF001
        except OSError as exc:
            self.log(f"[WARN] Could not save the ledger {self.path.name} ({exc}); the MES record still identifies the owner")


def convert_unconverted(
    scan: ScanResult,
    *,
    log=None,
    progress_cb=None,
    channel_map_data=ac.USE_DEFAULT_MAP,
    update_checkpoint: bool = True,
    date=None,
    date_label: str = dates.SOURCE_FIELD,
) -> BatchReport:
    """走査で決めた NEW・OVERWRITE を 1 本ずつ変換する。変換は convert_many -> convert_one（GUI の Convert と同じ経路）。
    date: 明示の記録日（GUI の欄。全部に使う。date_label = 出どころの名前）。None ならファイル名から 1 本ずつ読む。

    1 本の失敗で止めない。成功したらその場で台帳に 1 行を書く。候補が 1 本以上あったときだけ、最後に起点を保存する。
    """
    log = log or (lambda _t: None)
    report = BatchReport(total_candidates=len(scan.to_convert), protected_count=len(scan.protected),
                         already_count=len(scan.already), older_count=len(scan.older),
                         not_session_count=len(scan.not_session))
    for item in scan.unreadable:
        report.failed_items.append((item.path, item.reason))
    todo = scan.to_convert
    if not todo:
        return report
    ledger = _LedgerWriter(scan.out_dir, load_manifest(scan.out_dir), log)
    changed_names: set[str] = set()

    for idx, item in enumerate(todo):
        if progress_cb:
            progress_cb(idx, len(todo), item.path)
        try:
            st = item.path.stat()
        except OSError as exc:
            report.failed_items.append((item.path, f"cannot read the file: {exc}"))
            continue
        if st.st_size != item.size or st.st_mtime_ns != item.mtime_ns:
            reason = "changed since the scan; it will be retried"
            log(f"[ERROR] {item.path.name}: {reason}")
            report.failed_items.append((item.path, reason))
            continue
        def guard(target: Path, _item: MbdItem = item) -> None:
            if _item.action == NEW:
                if target.exists():
                    raise ExternalChange(f"'{target.name}' appeared after the scan; not replaced")
            elif mes_fingerprint(target) != _item.target_fingerprint:
                raise ExternalChange(f"'{target.name}' was changed after the scan; not replaced")

        outcome = ac.convert_many([item.path], scan.out_dir, mes_name=item.mes_name,
                                  force=(item.action == OVERWRITE), channel_map_data=channel_map_data, log=log,
                                  before_replace=guard, date=date, date_label=date_label)
        if outcome.results:
            res = outcome.results[0]
            sha = res.input_sha256 or item.sha256
            ledger.put(item.key, _entry_for(item, sha, res))
            report.converted.append(item.path)
            if not res.map_saved:
                report.map_saved = False
        else:
            reason = outcome.failed[0][1] if outcome.failed else "conversion failed"
            if "after the scan; not replaced" in reason:
                report.externally_changed.append(item.path)
                changed_names.add(item.path.name)
            report.failed_items.append((item.path, reason))

    if update_checkpoint:
        failed_names = {p.name for p, _ in report.failed_items}
        protected_names = {i.path.name.casefold() for i in scan.protected}
        carried = {f for f in scan.previous_failed if Path(f).name.casefold() in protected_names}
        report.saved_failed_files = sorted(failed_names | {Path(f).name for f in carried})
        try:
            cfgmod.set_batch_checkpoint(scan.source_dir, scan.scan_started_at_ns, report.saved_failed_files)
            report.checkpoint_saved = True
        except OSError as exc:
            log(f"[WARN] Could not save the checkpoint: {exc}")
    return report


# ============================================================ 画面用の文
_TAGS = {NEW: "[NEW]", OVERWRITE: "[OVERWRITE]", ALREADY: "[SKIP]", OLDER: "[SKIP]", PROTECTED: "[PROTECTED]",
         NOT_SESSION: "[NOT SESSION]", UNREADABLE: "[UNREADABLE]"}


def scan_report_lines(scan: ScanResult) -> list[str]:
    """走査のログ。全部の行き先と理由を出す（画面の一覧が 10 件で切れても、ここに全件ある）。"""
    lines = list(scan.notes)
    lines.append(f"[INFO] Scanned {len(scan.items)} .MBD file(s) in {scan.source_dir}"
                 + ("" if scan.had_checkpoint else " (no checkpoint yet for this folder)"))
    for item in scan.items:
        lines.append(f"{_TAGS[item.action]} {item.path.name}: {item.reason}")
    return lines


def _bulleted(items: list[str], limit: int = DIALOG_LIST_MAX) -> str:
    shown = [f"  - {t}" for t in items[:limit]]
    if len(items) > limit:
        shown.append(f"  ... and {len(items) - limit} more file(s) (all of them are in the log)")
    return "\n".join(shown)


def date_lines(scan: ScanResult, date=None, date_label: str = dates.SOURCE_FIELD) -> list[str]:
    """変換する物ごとの「記録日とその出どころ」の行（確認の画面・ログ用）。更新時刻に頼る物には警告の語を付ける。"""
    return [f"{i.path.name}: {dates.choose(i.path, date, date_label).describe()}" for i in scan.to_convert]


def confirm_text(scan: ScanResult, date=None, date_label: str = dates.SOURCE_FIELD) -> str:
    """実行前の確認の画面の本文（新規・上書き・保護・飛ばす物・1 本ごとの記録日）。"""
    new_n, ow_n = len(scan.new_items), len(scan.overwrite_items)
    head = f"Found {len(scan.to_convert)} .MBD file(s) to convert in:\n{scan.source_dir}\n\n"
    head += f"{new_n} new MES will be created.\n"
    if ow_n:
        head += f"{ow_n} existing MES will be OVERWRITTEN.\n"
    if not scan.had_checkpoint:
        head += "No checkpoint yet for this folder: every .MBD without a verified MES is included.\n"
    if scan.convert_all:
        head += "Convert all is on: already-converted MES will be rebuilt.\n"
    targets = [i.path.name + (" (overwrites existing MES)" if i.action == OVERWRITE else "") for i in scan.to_convert]
    body = "\nTarget files:\n" + _bulleted(targets) + "\n"
    dl = date_lines(scan, date, date_label)
    body += "\nRecording date (HED) and where it comes from:\n" + _bulleted(dl) + "\n"
    n_mtime = sum(1 for i in scan.to_convert if dates.choose(i.path, date, date_label).date is None)
    if n_mtime:
        body += (f"WARNING: {n_mtime} file(s) have no date in the name; the file modification time will be used "
                 "(it may be the day the file was copied). Set the Date field to override.\n")
    if scan.protected:
        body += (f"\nProtected, not touched ({len(scan.protected)}):\n"
                 + _bulleted([f"{i.path.name}: {i.reason}" for i in scan.protected]) + "\n")
    skipped = (f"\nSkipped: already converted {len(scan.already)}, older than the checkpoint {len(scan.older)}, "
               f"not a session {len(scan.not_session)}, unreadable {len(scan.unreadable)}.\n")
    notes = ("\n" + "\n".join(scan.notes) + "\n") if scan.notes else ""
    return head + body + skipped + notes + f"\nOutput directory:\n{scan.out_dir}\n\nDo you want to proceed with conversion?"


def nothing_text(scan: ScanResult) -> str:
    """変換する物が 0 本のときの案内。"""
    text = (f"Nothing to convert in:\n{scan.source_dir}\n\n"
            f"Already converted: {len(scan.already)}\n"
            f"Older than the checkpoint (not converted by this button): {len(scan.older)}\n"
            f"Protected: {len(scan.protected)}\n"
            f"Not a session: {len(scan.not_session)}\n"
            f"Unreadable: {len(scan.unreadable)}\n")
    if scan.protected:
        text += "\nProtected (not touched):\n" + _bulleted([f"{i.path.name}: {i.reason}" for i in scan.protected]) + "\n"
    if scan.unreadable:
        text += "\nUnreadable:\n" + _bulleted([f"{i.path.name}: {i.reason}" for i in scan.unreadable]) + "\n"
    if scan.older:
        text += '\nTo convert older files too, check "Convert all .MBD files".'
    return text


def summary_text(report: BatchReport) -> str:
    text = (f"Batch conversion finished.\n\n"
            f"Successfully converted: {report.converted_count}\n"
            f"Already converted: {report.already_count}\n"
            f"Skipped (older than the checkpoint): {report.older_count}\n"
            f"Protected: {report.protected_count}\n"
            f"Not a session: {report.not_session_count}\n"
            f"Failed: {report.failed_count}")
    if report.failed_count or report.protected_count:
        text += "\n\nFailed or protected file(s) remain in the list for inspection."
    return text


def remaining_after(scan: ScanResult, report: BatchReport) -> list[Path]:
    """実行後に一覧へ残す物: 失敗した物（先）と保護した物。"""
    failed = [p for p, _ in report.failed_items]
    return failed + [i.path for i in scan.protected if i.path not in failed]
