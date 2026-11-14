# -*- coding: utf-8 -*-
"""REL01: 配布 ZIP と README.html と正式版の配置（tools/make_release.py・tools/build_readme.py）の試験。

期待値は、試す側とは別の出どころから作る: 許可リストの名前・個人の語は試験側に書く（道具の定数を使い回さない）/ ZIP は zipfile で開き直す /
ハッシュは hashlib で別に取る。実 exe を使う試験は、環境変数 MBD2MES_EXE があるときだけ。
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import build_readme  # noqa: E402
import make_release as mr  # noqa: E402
from mbd2mes import version  # noqa: E402

PRIVATE_FILE = ROOT / "tests" / "private_needles.local.txt"
DIST_EXE = os.environ.get("MBD2MES_EXE")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def private_words() -> list[str]:
    if not PRIVATE_FILE.is_file():
        return []
    return [ln.strip() for ln in PRIVATE_FILE.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def make_zip_from(tmp: Path, files: dict[str, bytes], name: str = "z.zip") -> list[zipfile.ZipInfo]:
    p = tmp / name
    with zipfile.ZipFile(p, "w") as z:
        for n, data in files.items():
            zi = zipfile.ZipInfo(n)
            zi.external_attr = (0o100644) << 16
            z.writestr(zi, data)
    with zipfile.ZipFile(p) as z:
        return z.infolist()


# ---------------------------------------------------------------- 版
def test_version_is_0_3_0():
    assert version.APP_VERSION == "0.3.0"
    assert version.format_version(False, None) == "MBD2MES v0.3.0 (dev)"
    assert mr.parse_version_string("MBD2MES v0.3.0 (abc1234, built 2026-11-14)") == ("0.3.0", "abc1234", False, "2026-11-14")
    assert mr.parse_version_string("MBD2MES v0.3.0 (abc1234+dirty, built 2026-11-14)")[2] is True
    with pytest.raises(mr.ReleaseError):
        mr.parse_version_string("MBD2MES v0.3.0 (unknown, built unknown)")


def test_a_dirty_exe_or_a_wrong_version_is_not_fresh():
    with pytest.raises(mr.ReleaseError, match="dirty"):
        mr.check_exe_fresh("MBD2MES v0.3.0 (0000000+dirty, built 2026-11-14)")
    with pytest.raises(mr.ReleaseError, match="APP_VERSION"):
        mr.check_exe_fresh("MBD2MES v0.2.0 (0000000, built 2026-11-14)")


# ---------------------------------------------------------------- ZIP の中身（許可リスト）
GOOD = {"mbd2mes.exe": b"MZ", "README.html": b"<html></html>"}


def test_zip_with_exactly_the_allowed_files_is_clean(tmp_path):
    assert mr.zip_entry_problems(make_zip_from(tmp_path, GOOD)) == []


@pytest.mark.parametrize("extra", ["mbd2mes_config.json", "channel_map.json", "sample.MBD", "x.MES", "mbd2mes.exe.bak", "notes.md", "dist/x.txt", "tools/a.py"])
def test_anything_beyond_the_allow_list_is_rejected(tmp_path, extra):
    probs = mr.zip_entry_problems(make_zip_from(tmp_path, {**GOOD, extra: b"x"}))
    assert any("許可リストに無い" in p for p in probs)


def test_missing_duplicate_backslash_absolute_and_non_ascii_names_are_rejected(tmp_path):
    assert any("ZIP に無い" in p for p in mr.zip_entry_problems(make_zip_from(tmp_path, {"README.html": b"x"})))
    assert any("ASCII" in p for p in mr.zip_entry_problems(make_zip_from(tmp_path, {**GOOD, "説明.txt": b"x"}, "a.zip")))
    # ZipFile は、読むとき Windows でバックスラッシュをスラッシュに直す。直った名前が、許可リストの外として落ちる
    backslash_name = "a" + chr(92) + "b.txt"
    assert any("許可リストに無い" in p for p in mr.zip_entry_problems(make_zip_from(tmp_path, {**GOOD, backslash_name: b"x"}, "b.zip")))
    assert any("絶対パス" in p for p in mr.zip_entry_problems(make_zip_from(tmp_path, {**GOOD, "/abs.txt": b"x"}, "c.zip")))
    assert any("重複" in p for p in mr.zip_entry_problems(make_zip_from(tmp_path, {**GOOD, "readme.html": b"y"}, "d.zip")))


def test_stage_and_make_zip_hold_only_the_allowed_files_and_are_reproducible(tmp_path):
    exe = tmp_path / "mbd2mes.exe"
    exe.write_bytes(b"MZ" + b"\0" * 100)
    sd1, sd2 = tmp_path / "s1", tmp_path / "s2"
    sd1.mkdir(); sd2.mkdir()
    mr.stage(sd1, exe)
    mr.stage(sd2, exe)
    commit = subprocess.run(["git", "log", "-1", "--format=%H"], cwd=str(ROOT), capture_output=True, text=True).stdout.strip()
    z1, z2 = tmp_path / "MBD2MES_v0.3.0.zip", tmp_path / "again.zip"
    mr.make_zip(sd1, z1, commit)
    mr.make_zip(sd2, z2, commit)
    assert sha(z1) == sha(z2)  # 同じ入力から同じ ZIP
    with zipfile.ZipFile(z1) as z:
        assert sorted(z.namelist()) == ["README.html", "mbd2mes.exe"]  # 試験側に書いた期待値
        assert z.read("README.html") == (ROOT / "docs" / "readme_ja.html").read_bytes()
        assert z.read("mbd2mes.exe") == exe.read_bytes()
    assert mr.zip_entry_problems(zipfile.ZipFile(z1).infolist()) == []


def test_inject_cannot_replace_an_allowed_name(tmp_path):
    exe = tmp_path / "mbd2mes.exe"
    exe.write_bytes(b"MZ")
    bad = tmp_path / "x" / "README.html"
    bad.parent.mkdir()
    bad.write_text("evil")
    sd = tmp_path / "s"
    sd.mkdir()
    with pytest.raises(mr.ReleaseError, match="衝突"):
        mr.stage(sd, exe, inject=bad)


# ---------------------------------------------------------------- 個人情報
def test_needles_include_the_private_file_and_see_utf16():
    needles = mr.all_needles()
    for w in private_words():
        assert w in needles  # git に入れない語も、道具が使っている
    for w in ("i_a" + "m_", "C:\\Us" + "ers", "RACE" + "DATA"):
        assert w in needles
    assert mr.needle_hits_in_bytes(("xx C:\\Us" + "ers\\a").encode("utf-16-le"), ("C:\\Us" + "ers",))
    assert mr.needle_hits_in_bytes(b"abc", ("C:\\Us" + "ers",)) == []
    assert mr.needle_hits_in_bytes(b"ABC", ("abc",))  # 大文字小文字を畳む


def test_private_needles_file_is_read_line_by_line(tmp_path):
    f = tmp_path / "n.txt"
    f.write_text("# comment\n\n  word1 \nword2\n", encoding="utf-8")
    assert mr.private_needles(f) == ("word1", "word2")
    assert mr.private_needles(tmp_path / "none.txt") == ()


def test_readme_has_no_personal_words_internal_words_or_real_file_names():
    html = (ROOT / "docs" / "readme_ja.html").read_bytes()
    text = html.decode("utf-8")
    assert mr.needle_hits_in_bytes(html) == []
    assert mr.internal_word_hits(text) == []
    for w in private_words():
        assert w.lower() not in text.lower()
    for bad in ("鈴鹿", "サンデー", "26.11.8鈴", "Race" + "Data", "\\Us" + "ers\\"):
        assert bad not in text


# ---------------------------------------------------------------- README.html
def test_readme_is_fresh_and_names_the_version():
    assert build_readme.main.__module__ == "build_readme"
    assert subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "build_readme.py"), "--check"], capture_output=True).returncode == 0
    text = (ROOT / "docs" / "readme_ja.html").read_text(encoding="utf-8")
    assert f"MBD2MES v{version.APP_VERSION}" in text and "{{" not in text


def test_readme_is_one_self_contained_page():
    text = (ROOT / "docs" / "readme_ja.html").read_text(encoding="utf-8")
    assert mr.readme_problems(text) == []
    refs = re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", text, re.I)
    assert refs and all(r.startswith("data:image/png;base64,") for r in refs)  # 外を指す参照は 0 本・画像は埋め込み
    assert not re.search(r"<link|<script|@import|https?://", text, re.I)
    # 埋め込んだ画像が、docs/img の PNG と同じ（別に base64 を戻して比べる）
    import base64
    embedded = base64.b64decode(re.search(r"data:image/png;base64,([A-Za-z0-9+/=]+)", text).group(1))
    assert embedded == (ROOT / "docs" / "img" / "progress_dialog.png").read_bytes()


@pytest.mark.parametrize("bad", ['<img src="a.png">', '<link rel="stylesheet" href="x.css">', "<script>1</script>", '<a href="https://example.com/">x</a>',
                                 "<style>@import url(x.css);</style>", '<div style="background:url(a.png)"></div>'])
def test_readme_problems_catches_external_things(bad):
    html = '<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>' + bad + "</body></html>"
    assert mr.readme_problems(html)


def test_readme_covers_the_requested_sections():
    text = (ROOT / "docs" / "readme_ja.html").read_text(encoding="utf-8")
    for h in ("必要なもの", "最初の変換", "Channel Map", "Convert Unconverted", "Use This", "日付の決まり方", "変換中のダイアログと Cancel",
              "設定の置き場所", "版を上げるとき", "困ったとき", "版の変更点"):
        assert f"<h2>{h}" in text or h in re.findall(r"<h2>([^<]*)", text) or any(h in t for t in re.findall(r"<h2>([^<]*)", text)), h
    assert "<h3>0.3.0</h3>" in text and "<h3>0.2.0</h3>" in text and "<h3>0.1.0</h3>" in text


# ---------------------------------------------------------------- 配置・設定の引き継ぎ
def fake_release(tmp: Path):
    exe = tmp / "src" / "mbd2mes.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ-new")
    zp = tmp / "MBD2MES_v0.3.0.zip"
    zp.write_bytes(b"zipbytes")
    settings = tmp / "settings"
    settings.mkdir()
    (settings / "mbd2mes_config.json").write_text('{"a": 1}', encoding="utf-8")
    (settings / "channel_map.json").write_text('{"b": 2}', encoding="utf-8")
    return exe, zp, settings


def test_publish_places_exe_readme_zip_and_copies_settings_with_equal_hashes(tmp_path):
    exe, zp, settings = fake_release(tmp_path)
    rel = tmp_path / "release"
    mr.publish(zp, exe, rel, settings)
    final = rel / "MBD2MES"
    assert sorted(p.name for p in final.iterdir()) == ["README.html", "channel_map.json", "mbd2mes.exe", "mbd2mes_config.json"]
    assert sha(final / "mbd2mes.exe") == sha(exe) and sha(final / "README.html") == sha(ROOT / "docs" / "readme_ja.html")
    for n in ("mbd2mes_config.json", "channel_map.json"):
        assert sha(final / n) == sha(settings / n)
    assert sorted(p.name for p in rel.iterdir()) == ["MBD2MES", "MBD2MES_v0.3.0.zip"] and sha(rel / "MBD2MES_v0.3.0.zip") == sha(zp)


def test_publish_does_not_overwrite_settings_already_in_the_final_folder_and_is_idempotent(tmp_path):
    exe, zp, settings = fake_release(tmp_path)
    rel = tmp_path / "release"
    mr.publish(zp, exe, rel, settings)
    (rel / "MBD2MES" / "channel_map.json").write_text('{"user edit": 3}', encoding="utf-8")  # 利用者が正式版で育てた対応表
    mr.publish(zp, exe, rel, settings)
    assert (rel / "MBD2MES" / "channel_map.json").read_text(encoding="utf-8") == '{"user edit": 3}'
    assert sha(rel / "MBD2MES" / "mbd2mes.exe") == sha(exe)


def test_publish_without_settings_adds_none_and_a_missing_setting_fails(tmp_path):
    exe, zp, settings = fake_release(tmp_path)
    rel = tmp_path / "release"
    mr.publish(zp, exe, rel, None)
    assert not (rel / "MBD2MES" / "mbd2mes_config.json").exists()
    (settings / "channel_map.json").unlink()
    rel2 = tmp_path / "rel2"
    with pytest.raises(mr.ReleaseError, match="引き継ぐ設定を読めません"):
        mr.publish(zp, exe, rel2, settings)
    assert not rel2.exists()  # 設定がそろわないときは、正式版にも ZIP にも、何も置かない（部分更新なし）


def test_publish_refuses_a_same_name_zip_with_different_content_and_changes_nothing(tmp_path):
    exe, zp, _s = fake_release(tmp_path)
    rel = tmp_path / "release"
    rel.mkdir()
    (rel / "MBD2MES_v0.3.0.zip").write_bytes(b"other")
    with pytest.raises(mr.ReleaseError, match="内容が違う"):
        mr.publish(zp, exe, rel, None)
    assert not (rel / "MBD2MES" / "mbd2mes.exe").exists() and (rel / "MBD2MES_v0.3.0.zip").read_bytes() == b"other"


# ---------------------------------------------------------------- 道具の振る舞い
def test_a_missing_or_empty_private_needles_file_fails_closed(tmp_path):
    with pytest.raises(mr.ReleaseError, match="針のファイル"):
        mr.require_private_needles(tmp_path / "none.txt")
    empty = tmp_path / "e.txt"
    empty.write_text("# only a comment\n\n", encoding="utf-8")
    with pytest.raises(mr.ReleaseError):
        mr.require_private_needles(empty)
    ok = tmp_path / "ok.txt"
    ok.write_text("word\n", encoding="utf-8")
    mr.require_private_needles(ok)


def test_main_refuses_without_the_private_needles_file_unless_explicitly_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(mr, "PRIVATE_NEEDLES_FILE", tmp_path / "none.txt")
    rel = tmp_path / "rel"
    assert mr.main(["--exe", str(tmp_path / "x.exe"), "--release-dir", str(rel)]) == 1  # 針のファイルが無い -> 失敗（exe の有無より前）
    assert not rel.exists()


def test_tracked_changes_block_the_release(monkeypatch):
    class P:
        stdout = "mbd2mes/gui.py\ndocs/x.md\n"
        returncode = 0
        stderr = ""

    monkeypatch.setattr(mr, "_git", lambda args, check=True: P())
    with pytest.raises(mr.ReleaseError, match="コミットしていない変更"):
        mr.check_tracked_clean()
    P.stdout = ""
    mr.check_tracked_clean()


def test_main_fails_without_touching_release_when_the_exe_is_missing(tmp_path):
    rel = tmp_path / "rel"
    assert mr.main(["--exe", str(tmp_path / "none.exe"), "--release-dir", str(rel), "--allow-no-private-needles"]) == 1
    assert not rel.exists()


def test_make_release_uses_only_read_only_git_commands():
    tree = ast.parse((ROOT / "tools" / "make_release.py").read_text(encoding="utf-8"))
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_git" and node.args and isinstance(node.args[0], ast.List):
            first = node.args[0].elts[0]
            assert isinstance(first, ast.Constant)
            used.add(first.value)
    assert used and used <= {"log", "diff", "ls-files", "merge-base", "show"}, used


def test_release_folder_is_git_ignored():
    for rel in ("release/MBD2MES/mbd2mes.exe", "release/MBD2MES/README.html", "release/MBD2MES/mbd2mes_config.json", "release/MBD2MES_v0.3.0.zip"):
        r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=str(ROOT))
        assert r.returncode == 0, rel


@pytest.mark.skipif(not DIST_EXE, reason="MBD2MES_EXE（実 exe）が要る")
def test_the_real_exe_has_no_personal_strings_even_inside_its_compressed_code():
    hits, unchecked = mr.scan_exe(Path(DIST_EXE))
    assert hits == [] and unchecked == []


@pytest.mark.skipif(not DIST_EXE, reason="MBD2MES_EXE（実 exe）が要る")
def test_scan_exe_really_finds_a_planted_word(tmp_path):
    hits, _u = mr.scan_exe(Path(DIST_EXE), needles=("mbd_reader",))  # exe の中に確かにある語を針にすると、見つかる（検査が空振りでない）
    assert hits


@pytest.mark.parametrize("extra", ["mbd2mes_config.json", "channel_map.json", "sample.MBD", "x.MES", "mbd2mes.exe.bak", "notes.md", "dist/x.txt", "tools/a.py"])
def test_each_forbidden_thing_is_named_by_the_deny_list_too(tmp_path, extra):
    probs = mr.zip_entry_problems(make_zip_from(tmp_path, {**GOOD, extra: b"x"}))
    assert any("拒否リスト" in p for p in probs), probs
