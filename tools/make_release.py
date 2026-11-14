# -*- coding: utf-8 -*-
"""tools/make_release.py -- 配布 ZIP（MBD2MES_v<版>.zip）を作り、正式版のフォルダ release/MBD2MES/ へ置く。

RCZ2MES の tools/make_release.py（commit bc558de）からの写しを小さくした物。写した要点:
  許可リスト・拒否リストでの ZIP の検査 / 個人の語の針（exe の圧縮された Python のコードまで展開して検査）/ exe の鮮度（版の文字列）/
  同じ入力から同じ ZIP になる（並びと日時を固定）/ 作った ZIP を別のフォルダへ展開して検査し直す。
  省いた物: 版ごとの変更点の文書・マニュアル・ロックと old\\ への退避（古い ZIP は人が消す）・commit 名つきの ZIP 名。
  足した物: 正式版のフォルダへの配置（exe と README.html の入れ替え）と、設定の引き継ぎ（写して、ハッシュで一致を確かめる）。
  git は、状態を変えない読むだけの呼び方（log・diff・ls-files・merge-base）だけを使う。

    python tools/make_release.py --settings-from dist/fb03     # 検査 -> ZIP -> release/ へ配置（設定を引き継ぐ）

**検査が 1 つでも落ちたら release/ には何も置かない**（全て一時フォルダで作り、最後の配置だけが release/ を触る）。
ZIP の中身は mbd2mes.exe と README.html だけ。設定（mbd2mes_config.json・channel_map.json）は入らない。

検査の動作確認用の引数（製品の動作には影響しない）: --release-dir / --exe / --inject / --skip-fresh（鮮度の検査だけを飛ばす。試験用）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import types
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from mbd2mes import version as version_mod  # noqa: E402
import write_build_info as wbi  # noqa: E402

RELEASE_DIR = ROOT / "release"
FINAL_DIRNAME = "MBD2MES"                      # release/MBD2MES/ が正式版のフォルダ
EXE_NAME = "mbd2mes.exe"
README_NAME = "README.html"
README_SOURCE = ROOT / "docs" / "readme_ja.html"
ZIP_PREFIX = "MBD2MES"
ZIP_COMPRESSLEVEL = 9                          # deflate の最大（配る ZIP を小さく）
SETTINGS_FILES = ("mbd2mes_config.json", "channel_map.json")   # 引き継ぐ設定（ZIP には入れない）
PRIVATE_NEEDLES_FILE = ROOT / "tests" / "private_needles.local.txt"   # git に入れない。1 行に 1 語

# ZIP に入れてよいファイル（ZIP の中の名前）。ここに無い物は入らない
ALLOWED = (EXE_NAME, README_NAME)

# 混ざったら検出して止める名前（許可リストの外に、別に持つ）。小文字で比べる
DENY_BASENAMES = tuple(n.lower() for n in SETTINGS_FILES) + ("channel_map.json.bak", ".mbd2mes_manifest.json", "claude.md", "claude.local.md")
DENY_DIRS = ("scratch", "_prompt", "tests", "dist", "build", "dist_build", "tools", "pic", "docs")
DENY_SUFFIXES = (".mbd", ".mes", ".bak", ".py", ".pyc", ".spec", ".md", ".sha256")
DENY_NAME_PARTS = (".corrupt_", ".mbd2mes_write_probe")

# 個人の情報・開発環境のパス。どこにあっても失敗する語（個人のユーザー名・開発のパス・実データの置き場）。提供者の名前などは、git に入れないファイルから足す
PERSONAL_NEEDLES_BASE = ("i_a" + "m_","RACEDATA", "C:\\_Prog", "C:/_Prog", "C:\\Users", "C:/Users")
ENCODINGS = ("utf-8", "utf-16-le", "utf-16-be")
# numpy 自身のビルド時のパス 1 件だけを、モジュール名と文字列の先頭の完全一致で許可する
EXEMPT_CONSTS = (("numpy.__config__", "C:\\Us" + "ers\\runneradmin\\"),("numpy.__config__", "C:/Us" + "ers/runneradmin/"))  # 語を分けて書く（この道具自身が個人の語の検査に当たらないように）

# 利用者向けの文書に書いてはいけない内部の言葉（NFKC 正規化・大小無視・書式文字と空白の除去のうえで見る）
INTERNAL_WORDS = ("らいお", "指揮役", "設計レーン", "実装レーン", "確認待ち", "the owner", "design lane", "implementation lane", "codex", "実装ai", "設計ai")

# exe に入る物の鮮度の検査が読む、版の名前の形（version.format_version）
VERSION_RE = re.compile(r"^MBD2MES v(\d+\.\d+\.\d+) \(([0-9a-f]{%d})(\+dirty)?, built (\d{4}-\d{2}-\d{2})\)$" % wbi.COMMIT_ABBREV)


class ReleaseError(Exception):
    """検査が落ちた・配置できなかった。release/ は変わらない（変わった場合は、メッセージにそう書く）。"""


def private_needles(path: Path | None = None) -> tuple[str, ...]:
    """git に入れないファイルの語（提供者の名前など）を読む。無ければ空。"""
    p = PRIVATE_NEEDLES_FILE if path is None else path
    if not p.is_file():
        return ()
    lines = p.read_text(encoding="utf-8").splitlines()
    return tuple(ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#"))


def all_needles() -> tuple[str, ...]:
    return PERSONAL_NEEDLES_BASE + private_needles()


def require_private_needles(path: Path | None = None) -> None:
    """実際の配布では、git に入れない針のファイル（提供者の名前などのローカルの語）が、あって空でないことを必須にする（無いと、その語の検査が丸ごと空振りになる）。"""
    p = PRIVATE_NEEDLES_FILE if path is None else path
    if not private_needles(p):
        raise ReleaseError(f"個人の語の針のファイルが無い・空です: {p}（このファイルが無い環境では、提供者の名前などの検査ができないので、配布の ZIP を作らない）")


# ============================================================
# 文字列・名前の検査
# ============================================================

def normalize_for_words(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in t if unicodedata.category(ch) != "Cf" and not ch.isspace())


def internal_word_hits(text: str) -> list[str]:
    t = normalize_for_words(re.sub(r"data:image/png;base64,[A-Za-z0-9+/=]+", "", text))
    return [w for w in INTERNAL_WORDS if normalize_for_words(w) in t]


def needle_hits_in_bytes(data: bytes, needles: tuple[str, ...] | None = None) -> list[str]:
    """語を、UTF-8・UTF-16LE・UTF-16BE のバイト列で探す。"""
    hits = []
    low = data.lower()
    for n in (all_needles() if needles is None else needles):
        for enc in ENCODINGS:
            if n.lower().encode(enc) in low:
                hits.append(f"{n!r} ({enc})")
    return hits


def zip_entry_problems(infos: list[zipfile.ZipInfo]) -> list[str]:
    """ZIP のエントリの衛生: 危険な名前・属性・重複を拒否し、名前の集合が許可リストと完全に一致することを見る。"""
    probs: list[str] = []
    seen: dict[str, str] = {}
    names: set[str] = set()
    for zi in infos:
        raw = zi.filename
        n = raw.replace("\\", "/")
        if raw != n:
            probs.append(f"バックスラッシュを含む名前: {raw!r}")
        if zi.is_dir() or n.endswith("/"):
            probs.append(f"ディレクトリのエントリ: {raw!r}")
            continue
        parts = n.split("/")
        if n.startswith("/") or re.match(r"^[A-Za-z]:", n):
            probs.append(f"絶対パス: {raw!r}")
        if any(p in ("", ".", "..") for p in parts):
            probs.append(f"危険な要素（空・.・..）を含む名前: {raw!r}")
        if not raw.isascii():
            probs.append(f"ASCII でない名前（文字化けの元。日本語のファイル名は入れない）: {raw!r}")
        mode = (zi.external_attr >> 16) & 0xFFFF
        if mode and not stat.S_ISREG(mode):
            probs.append(f"通常のファイルでない属性（リンク・特殊ファイル）: {raw!r}")
        key = n.casefold()
        if key in seen:
            probs.append(f"重複（大文字小文字の違いを含む）: {raw!r} と {seen[key]!r}")
        seen[key] = raw
        names.add(n)
    missing = sorted(set(ALLOWED) - names)
    extra = sorted(names - set(ALLOWED))
    if missing:
        probs.append(f"許可リストにあるのに ZIP に無い: {missing}")
    if extra:
        probs.append(f"許可リストに無いファイルが ZIP にある: {extra}")
    for n in names:
        low = n.lower()
        parts = low.split("/")
        if parts[-1] in DENY_BASENAMES or any(p in DENY_DIRS for p in parts[:-1]) or low.endswith(DENY_SUFFIXES) \
                or any(part in parts[-1] for part in DENY_NAME_PARTS):
            probs.append(f"入れてはいけない物（拒否リスト）: {n!r}")
    return probs


# ============================================================
# exe の中の検査（圧縮された Python のコードまで展開する）
# ============================================================

def _walk_code(code: types.CodeType, mod: str, hits: list[str], needles: tuple[str, ...]) -> None:
    for s in (code.co_filename, code.co_name):
        for n in needles:
            if n.casefold() in s.casefold():
                hits.append(f"{mod}: co_filename/co_name {s[:70]!r} に {n!r}")
    for c in code.co_consts:
        _walk_const(c, mod, hits, needles)


def _walk_const(c, mod: str, hits: list[str], needles: tuple[str, ...]) -> None:
    """定数 1 つを検査する。tuple・frozenset の中の定数も、入れ子のまま全部見る。"""
    if isinstance(c, str):
        for n in needles:
            if n.casefold() in c.casefold() and not any(mod == m and c.casefold().startswith(p.casefold()) for m, p in EXEMPT_CONSTS):
                hits.append(f"{mod}: 文字列定数に {n!r}: {c[:70]!r}")
    elif isinstance(c, (bytes, bytearray)):
        hits += [f"{mod}: バイト列定数に {h}" for h in needle_hits_in_bytes(bytes(c), needles)]
    elif isinstance(c, types.CodeType):
        _walk_code(c, mod, hits, needles)
    elif isinstance(c, (tuple, frozenset, list)):
        for item in c:
            _walk_const(item, mod, hits, needles)


def scan_exe(exe: Path, needles: tuple[str, ...] | None = None) -> tuple[list[str], list[str]]:
    """exe の全エントリと、PYZ の全 code object を検査する。戻り値: (見つかった語, 検査できなかったエントリ)。"""
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    nd = all_needles() if needles is None else needles
    hits: list[str] = []
    unchecked: list[str] = []
    hits += [f"exe の生のバイト列に {h}" for h in needle_hits_in_bytes(exe.read_bytes(), nd)]
    ar = CArchiveReader(str(exe))
    for name in ar.toc:
        try:
            data = ar.extract(name)
        except Exception:                                                   # noqa: BLE001
            unchecked.append(name)
            continue
        if isinstance(data, tuple):
            data = data[-1]
        if not isinstance(data, (bytes, bytearray)):
            unchecked.append(name)
            continue
        hits += [f"{name}: {h}" for h in needle_hits_in_bytes(bytes(data), nd)]
        if name.lower().endswith(".pyz"):
            with tempfile.TemporaryDirectory(prefix="mbd2mes_pyz_") as td:
                pyz = Path(td) / "x.pyz"
                pyz.write_bytes(bytes(data))
                z = ZlibArchiveReader(str(pyz))
                for mod in list(z.toc):
                    try:
                        code = z.extract(mod)
                    except Exception:                                       # noqa: BLE001
                        unchecked.append(f"{name}:{mod}")
                        continue
                    if isinstance(code, types.CodeType):
                        _walk_code(code, mod, hits, nd)
                    else:
                        unchecked.append(f"{name}:{mod}")
    return hits, unchecked


# ============================================================
# exe の版・鮮度（git は状態を変えない読むだけの呼び方だけ）
# ============================================================

def _git(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    if check and p.returncode != 0:
        raise ReleaseError(f"git {' '.join(args)} が失敗: {p.stderr.strip()[:200]}")
    return p


def uncommitted_in(pathspecs) -> list[str]:
    """pathspecs の中で、今の HEAD と違う物と、追跡されていない物（無視されない物）。"""
    changed = _git(["diff", "--name-only", "HEAD", "--", *pathspecs]).stdout.split()
    untracked = _git(["ls-files", "--others", "--exclude-standard", "--", *pathspecs]).stdout.split()
    return sorted(set(changed) | set(untracked))


def read_exe_version(exe: Path) -> str:
    """exe を一時フォルダへ写し、`--version-file` で版の名前を取る（exe の隣に設定を作らせない）。"""
    if not exe.is_file():
        raise ReleaseError(f"exe がありません: {exe}")
    with tempfile.TemporaryDirectory(prefix="mbd2mes_ver_") as td:
        copy = Path(td) / exe.name
        shutil.copy2(exe, copy)
        out = Path(td) / "version.txt"
        p = subprocess.run([str(copy), "--version-file", str(out)], cwd=td, capture_output=True, timeout=120)
        if p.returncode != 0 or not out.is_file():
            raise ReleaseError(f"exe の --version-file が失敗（終了コード {p.returncode}）")
        return out.read_text(encoding="utf-8").strip()


def parse_version_string(s: str) -> tuple[str, str, bool, str]:
    m = VERSION_RE.match(s)
    if not m:
        raise ReleaseError(f"exe の版の名前の形が想定と違います: {s!r}")
    return m.group(1), m.group(2), bool(m.group(3)), m.group(4)


def check_exe_fresh(vstr: str) -> str:
    """exe が今のソースから作られた物かを見る。通れば、exe の commit の完全な ID を返す。"""
    version, short, dirty, _built = parse_version_string(vstr)
    probs = []
    if version != version_mod.APP_VERSION:
        probs.append(f"exe の版 {version} が APP_VERSION {version_mod.APP_VERSION} と食い違う")
    if dirty:
        probs.append("exe の版の名前に +dirty がある（コミットしていない変更を含む exe は配らない）")
    full = None
    p = _git(["log", "-1", "--format=%H", short, "--"], check=False)
    if p.returncode != 0 or not p.stdout.strip():
        probs.append(f"exe の commit {short} がこのリポジトリに無い")
    else:
        full = p.stdout.strip()
        if _git(["merge-base", "--is-ancestor", full, "HEAD"], check=False).returncode != 0:
            probs.append(f"exe の commit {short} が今の HEAD の祖先でない（別のブランチの exe）")
        else:
            moved = _git(["diff", "--name-only", full, "HEAD", "--", *wbi.DIRTY_PATHSPECS]).stdout.split()
            if moved:
                probs.append(f"exe の commit {short} から今までに、exe に入る物が変わっている（exe を作り直す）: {moved}")
    pending = uncommitted_in(wbi.DIRTY_PATHSPECS)
    if pending:
        probs.append("exe に入る物に、コミットしていない変更がある:\n    " + "\n    ".join(pending))
    if probs:
        raise ReleaseError("exe の鮮度の検査が落ちた:\n  - " + "\n  - ".join(probs))
    assert full
    return full


def check_tracked_clean() -> None:
    """追跡している全ファイルが HEAD と同じこと（コミットしていない変更を含んだまま配らない。無視される物・追跡されていない物は見ない）。"""
    changed = _git(["diff", "--name-only", "HEAD"]).stdout.split()
    if changed:
        raise ReleaseError("追跡しているファイルに、コミットしていない変更がある（先にコミットする）:\n    " + "\n    ".join(sorted(changed)))


def check_readme_fresh() -> None:
    """配る README.html が、原稿と今の版から作り直された物か（tools/build_readme.py --check と同じ）。"""
    import build_readme
    if build_readme.render() != README_SOURCE.read_text(encoding="utf-8"):
        raise ReleaseError("docs/readme_ja.html が原稿・版から作り直されていない（python tools/build_readme.py）")
    pending = uncommitted_in(["docs/readme_ja.html", "docs/readme_ja.src.html", "docs/img"])
    if pending:
        raise ReleaseError(f"README の原稿・生成物にコミットしていない変更がある: {pending}")


# ============================================================
# 組み立て・ZIP・検査
# ============================================================

def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(stage_dir: Path, exe: Path, inject: Path | None = None) -> None:
    """許可リストのファイルだけを、一時フォルダへ集める。"""
    for name, src in ((EXE_NAME, exe), (README_NAME, README_SOURCE)):
        if not src.is_file():
            raise ReleaseError(f"入れるファイルがありません: {src}")
        shutil.copy2(src, stage_dir / name)
    if inject is not None:                                                  # 検査の動作確認用。許可リストの名前とは衝突させない
        if inject.name.casefold() in {a.casefold() for a in ALLOWED}:
            raise ReleaseError(f"--inject のファイル名 {inject.name!r} が、許可リストの名前と衝突する（検査済みの物を差し替えるため拒否）")
        shutil.copy2(inject, stage_dir / inject.name)


def make_zip(stage_dir: Path, zip_path: Path, commit_full: str) -> None:
    """並びと日時を固定して作る（同じ入力から同じ ZIP）。ファイル名は ASCII だけ。"""
    iso = _git(["show", "-s", "--format=%cI", commit_full]).stdout.strip()
    dt = datetime.fromisoformat(iso)
    date_time = (max(dt.year, 1980), dt.month, dt.day, dt.hour, dt.minute, dt.second - dt.second % 2)
    files = sorted((p for p in stage_dir.rglob("*") if p.is_file()), key=lambda p: p.relative_to(stage_dir).as_posix())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=ZIP_COMPRESSLEVEL) as z:
        for p in files:
            zi = zipfile.ZipInfo(p.relative_to(stage_dir).as_posix(), date_time)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(zi, p.read_bytes())


def readme_problems(html: str) -> list[str]:
    """README.html が 1 枚で完結しているか（外の物を読まない）と、内部の言葉・個人の語が無いか。"""
    probs = []
    for m in re.finditer(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", html, re.I):
        ref = m.group(1)
        if not (ref.startswith("data:image/") or ref.startswith("#")):
            probs.append(f"外の物を参照している: {ref[:60]!r}")
    if re.search(r"<link\b|<script\b|@import|url\(\s*[\"']?(?!data:)", html, re.I):
        probs.append("<link>・<script>・@import・外の url() がある")
    if not re.match(r"<!DOCTYPE html>", html, re.I) or 'charset="utf-8"' not in html.lower().replace("'", '"'):
        probs.append("DOCTYPE か charset=utf-8 が無い")
    return probs


def verify_zip(zip_path: Path, expected_vstr: str, exe_sha: str | None = None) -> dict:
    """作った ZIP そのものを、別の一時フォルダへ展開して検査し直す。問題があれば ReleaseError。"""
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        probs = zip_entry_problems(infos)
        if probs:
            raise ReleaseError("ZIP の中身の検査が落ちた:\n  - " + "\n  - ".join(probs))
        if z.testzip() is not None:
            raise ReleaseError("ZIP が壊れている（testzip）")
        with tempfile.TemporaryDirectory(prefix="mbd2mes_zipcheck_") as td:
            tdp = Path(td)
            for zi in infos:                                                 # 名前は検査済み（安全）。自前で書き出す
                (tdp / zi.filename).write_bytes(z.read(zi))
            problems: list[str] = []
            readme = (tdp / README_NAME).read_bytes()
            problems += [f"{README_NAME}: {h}" for h in needle_hits_in_bytes(readme)]
            text = readme.decode("utf-8")
            problems += [f"{README_NAME}: 利用者向けの文書に内部の言葉 {w!r}" for w in internal_word_hits(text)]
            problems += [f"{README_NAME}: {p}" for p in readme_problems(text)]
            if parse_version_string(expected_vstr)[0] not in text:
                problems.append(f"{README_NAME} に版 {parse_version_string(expected_vstr)[0]} が書かれていない")
            if exe_sha is not None and sha256_of(tdp / EXE_NAME) != exe_sha:
                problems.append("ZIP の exe が、鮮度を確認した exe と同じバイト列でない（確認と格納の間に差し替えられた）")
            hits, unchecked = scan_exe(tdp / EXE_NAME)
            problems += [f"{EXE_NAME}: {h}" for h in hits]
            if unchecked:
                problems.append(f"{EXE_NAME}: 検査できなかったエントリ {len(unchecked)} 件（未検査は失敗）: {unchecked[:5]}")
            got = read_exe_version(tdp / EXE_NAME)
            if got != expected_vstr:
                problems.append(f"展開した exe の版の名前 {got!r} が、検査した exe と違う")
            if zip_path.name != f"{ZIP_PREFIX}_v{parse_version_string(expected_vstr)[0]}.zip":
                problems.append(f"ZIP の名前 {zip_path.name!r} が、版の形になっていない")
            if problems:
                raise ReleaseError("ZIP の検査が落ちた:\n  - " + "\n  - ".join(problems))
            return {"entries": [zi.filename for zi in infos], "exe_unchecked": unchecked}


# ============================================================
# 配置（正式版のフォルダ・ZIP・設定の引き継ぎ）
# ============================================================

def _replace_file(src: Path, dst: Path) -> None:
    """同じフォルダの一時名へ写してから入れ替える（途中の状態を見せない）。使用中の exe は置き換えられないので、そのまま失敗させる。"""
    tmp = dst.with_name(f".{dst.name}.new")
    shutil.copy2(src, tmp)
    try:
        tmp.replace(dst)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ReleaseError(f"{dst} を置き換えられない（使用中か）: {exc}") from exc


def install_settings(settings_from: Path, final_dir: Path) -> list[str]:
    """引き継ぐ設定を、正式版のフォルダへ写し、写した後にハッシュで一致を確かめる。正式版に既にある設定は上書きしない（利用者の最新の物を守る）。"""
    done = []
    for name in SETTINGS_FILES:
        src = settings_from / name
        dst = final_dir / name
        if not src.is_file():
            raise ReleaseError(f"引き継ぐ設定がありません: {src}")
        if dst.is_file():
            done.append(f"{name}: 正式版に既にあるので写さない")
            continue
        shutil.copy2(src, dst)
        if sha256_of(src) != sha256_of(dst):
            dst.unlink(missing_ok=True)
            raise ReleaseError(f"{name} を写した後のハッシュが一致しない")
        done.append(f"{name}: 写した（SHA-256 一致）")
    return done


def publish(zip_path: Path, exe: Path, release_dir: Path, settings_from: Path | None) -> list[str]:
    """ZIP を release/ へ、exe と README.html を正式版のフォルダへ置く。同じ名前の ZIP が既にあれば、同じ内容でなければ失敗する。"""
    log = []
    if settings_from is not None:  # 何かを置く前に、引き継ぐ設定がそろって読めることを確かめる（置いた後で失敗して、正式版が部分更新にならないように）
        for name in SETTINGS_FILES:
            try:
                (settings_from / name).read_bytes()
            except OSError as exc:
                raise ReleaseError(f"引き継ぐ設定を読めません: {settings_from / name}（{exc}）") from exc
    release_dir.mkdir(parents=True, exist_ok=True)
    final = release_dir / FINAL_DIRNAME
    final.mkdir(exist_ok=True)
    target_zip = release_dir / zip_path.name
    if target_zip.is_file() and sha256_of(target_zip) != sha256_of(zip_path):
        raise ReleaseError(f"同じ名前の ZIP が release にあり、内容が違う（同じ入力から同じ ZIP が作れていない）: {target_zip}")
    # 正式版: exe の入れ替えが失敗しても、README だけ新しい状態にならないよう、exe を先に
    _replace_file(exe, final / EXE_NAME)
    _replace_file(README_SOURCE, final / README_NAME)
    for name, src in ((EXE_NAME, exe), (README_NAME, README_SOURCE)):
        if sha256_of(final / name) != sha256_of(src):
            raise ReleaseError(f"正式版の {name} を置いた後のハッシュが一致しない")
    log.append(f"正式版: {final}（{EXE_NAME}・{README_NAME}）")
    if settings_from is not None:
        log += install_settings(settings_from, final)
    if not target_zip.is_file():
        _replace_file(zip_path, target_zip)
    log.append(f"ZIP: {target_zip}（SHA-256 {sha256_of(target_zip)}）")
    return log


# ============================================================
# main
# ============================================================

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="配布 ZIP を作り、正式版のフォルダへ置く（検査が落ちたら何も置かない）")
    ap.add_argument("--exe", type=Path, default=ROOT / "dist" / EXE_NAME, help="配る exe（鮮度を検査する）")
    ap.add_argument("--release-dir", type=Path, default=RELEASE_DIR, help="置き場（試験用に差し替えられる）")
    ap.add_argument("--settings-from", type=Path, default=None, help="正式版のフォルダへ引き継ぐ設定（mbd2mes_config.json・channel_map.json）のあるフォルダ")
    ap.add_argument("--inject", type=Path, default=None, help="検査の動作確認用: ZIP の根へ混ぜるファイル")
    ap.add_argument("--allow-no-private-needles", action="store_true", help="検査の動作確認用: 針のファイルが無くても進む（配布では使わない）")
    ap.add_argument("--skip-fresh", action="store_true", help="検査の動作確認用: exe・README の鮮度の検査だけを飛ばす")
    a = ap.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="mbd2mes_release_") as td:
            td_p = Path(td)
            print("[1/5] 状態と exe の鮮度")
            if not a.allow_no_private_needles:
                require_private_needles()
            tracked = [ln for ln in _git(["ls-files", "release"]).stdout.splitlines() if ln and ln != "release/README.md"]
            if tracked:
                raise ReleaseError(f"release の中に、git が追跡している物がある（README.md 以外は追跡しない）: {tracked}")
            if not a.exe.is_file():
                raise ReleaseError(f"exe がありません: {a.exe}")
            iso = td_p / "iso" / a.exe.name                                  # exe は 1 回だけ隔離コピーし、以降は全部このコピーを使う
            iso.parent.mkdir()
            shutil.copy2(a.exe, iso)
            exe_sha = sha256_of(iso)
            if exe_sha != sha256_of(a.exe):
                raise ReleaseError("exe のコピー中に元のファイルが変わった（もう一度実行してください）")
            vstr = read_exe_version(iso)
            version = parse_version_string(vstr)[0]
            if a.skip_fresh:
                commit_full = _git(["log", "-1", "--format=%H"]).stdout.strip()
            else:
                commit_full = check_exe_fresh(vstr)
                check_tracked_clean()
                check_readme_fresh()
            print(f"      exe: {vstr}")
            print("[2/5] 組み立て")
            sd = td_p / "stage"
            sd.mkdir()
            stage(sd, iso, a.inject)
            zip_path = td_p / f"{ZIP_PREFIX}_v{version}.zip"
            print("[3/5] ZIP を作る")
            make_zip(sd, zip_path, commit_full)
            print("[4/5] ZIP そのものを展開して検査し直す")
            info = verify_zip(zip_path, vstr, exe_sha)
            if sha256_of(a.exe) != exe_sha:
                raise ReleaseError("検査の途中で、元の exe が変更された（もう一度実行してください）")
            print(f"      入っているもの: {info['entries']}")
            print("[5/5] 配置")
            for line in publish(zip_path, iso, a.release_dir, a.settings_from):
                print(f"      {line}")
        return 0
    except ReleaseError as exc:
        print(f"\n[失敗] 置かれていません（release は変わっていません。配置の途中の失敗なら、メッセージを見てください）。\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
