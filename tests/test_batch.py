# -*- coding: utf-8 -*-
"""一発変換（Convert Unconverted。FB01 の 1）の走査と実行。

期待値は試す側が組み立てる: 「変換済み」の MES は、台帳も走査も通らない素の変換（app_convert.convert_many）で作り、
「未変換」はファイルを置くだけで作る。どれが候補になるべきかは、その組み立てから決まる（走査の判定を再利用して期待値を作らない）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

import map_synth as ms
import pytest
from conftest import fresh_settings

from mbd2mes import app_convert as ac
from mbd2mes import batch
from mbd2mes import config as cfgmod
from mbd2mes import convert as cv

HOUR_NS = 3600 * 10**9


@pytest.fixture()
def env(tmp_path, monkeypatch):
    settings = fresh_settings(tmp_path, monkeypatch)
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    out.mkdir()
    return src, out, settings


def mk(src: Path, name: str, mtime_s: float | None = None) -> Path:
    p = ms.write(src / name, course=Path(name).stem[:12])  # 名前ごとに中身が違う
    if mtime_s is not None:
        os.utime(p, (mtime_s, mtime_s))
    return p


def plain_convert(paths, out):
    """台帳も走査も通らない素の変換（GUI の Convert と同じ経路）で「変換済み」を作る。"""
    outcome = ac.convert_many(paths, out, channel_map_data=None)
    assert not outcome.failed
    return outcome


def actions(scan) -> dict:
    return {i.path.name: i.action for i in scan.items}


def tree(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.rglob("*")) if p.is_file()}


def cp(ns: int, failed=()):
    return {"scan_started_at_ns": ns, "failed_files": list(failed)}


FUTURE = lambda: time.time_ns() + HOUR_NS  # 起点が今より後 = どのファイルも「起点より古い」  # noqa: E731
PAST = 946684800 * 10**9  # 2000-01-01 = どのファイルも「起点より新しい」


# ---------------------------------------------------------------- 走査（読むだけ）
def test_mixed_folder_only_unconverted_files_are_candidates(env):
    """変換済み 2 本・未変換 2 本・MBD でない物 2 本が混ざったフォルダで、候補になるのは未変換の 2 本だけ。"""
    src, out, _ = env
    a, b, c, d = (mk(src, f"{n}.MBD") for n in "abcd")
    plain_convert([a, b], out)  # a・b は変換済み
    (src / "notes.txt").write_text("not an mbd")
    (src / "fake.MBD").write_bytes(b"this is not an MBDA2 log" * 1000)  # マジックが違う
    scan = batch.scan_mbd_directory(src, out)
    assert actions(scan) == {"a.MBD": batch.ALREADY, "b.MBD": batch.ALREADY, "c.MBD": batch.NEW, "d.MBD": batch.NEW,
                             "fake.MBD": batch.NOT_SESSION}
    assert [i.path.name for i in scan.to_convert] == ["c.MBD", "d.MBD"]
    assert "Already converted" in scan.already[0].reason


def test_short_file_is_unreadable_and_never_converted(env):
    src, out, _ = env
    mk(src, "good.MBD")
    (src / "copying.MBD").write_bytes(b"4OEL V0003".ljust(16, b" ") + b"\x00" * 100)  # マジックはあるが 0x2000 byte に足りない
    scan = batch.scan_mbd_directory(src, out)
    assert actions(scan) == {"copying.MBD": batch.UNREADABLE, "good.MBD": batch.NEW}
    assert "retried next time" in scan.unreadable[0].reason


def test_only_mbd_files_directly_in_the_folder_in_name_order(env):
    src, out, _ = env
    (src / "sub").mkdir()
    mk(src / "sub", "inner.MBD")
    mk(src, "b.mbd")  # 小文字の拡張子も対象
    mk(src, "A.MBD")
    scan = batch.scan_mbd_directory(src, out)
    assert [i.path.name for i in scan.items] == ["A.MBD", "b.mbd"]


def test_missing_source_folder_is_a_note_not_an_exception(env):
    _src, out, _ = env
    scan = batch.scan_mbd_directory(out / "nowhere", out)
    assert scan.items == [] and any("Cannot list" in n for n in scan.notes)


def test_scan_writes_nothing(env):
    src, out, settings = env
    a, b = mk(src, "a.MBD"), mk(src, "b.MBD")
    plain_convert([a], out)
    before = (tree(src), tree(out), tree(settings))
    batch.scan_mbd_directory(src, out, checkpoint=cp(FUTURE()))
    assert (tree(src), tree(out), tree(settings)) == before


# ---------------------------------------------------------------- 起点（checkpoint）の規則
def test_checkpoint_rules_for_files_without_a_mes(env):
    src, out, _ = env
    mk(src, "old.MBD")
    # 起点が今より後: 起点より古い -> OLDER（このボタンでは変換しない）
    scan = batch.scan_mbd_directory(src, out, checkpoint=cp(FUTURE()))
    assert actions(scan) == {"old.MBD": batch.OLDER} and "Older than the checkpoint" in scan.older[0].reason
    # 起点が過去: 起点より新しい -> NEW
    assert actions(batch.scan_mbd_directory(src, out, checkpoint=cp(PAST))) == {"old.MBD": batch.NEW}
    # 起点が今より後でも、前回失敗したファイルは NEW に戻る
    scan = batch.scan_mbd_directory(src, out, checkpoint=cp(FUTURE(), failed=["old.MBD"]))
    assert actions(scan) == {"old.MBD": batch.NEW} and "Previously failed" in scan.new_items[0].reason
    # 「全部変換」は古くても NEW
    assert actions(batch.scan_mbd_directory(src, out, checkpoint=cp(FUTURE()), convert_all=True)) == {"old.MBD": batch.NEW}


def test_checkpoint_rules_for_files_with_an_owned_healthy_mes(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    plain_convert([a], out)
    assert actions(batch.scan_mbd_directory(src, out, checkpoint=cp(FUTURE()))) == {"a.MBD": batch.ALREADY}  # 古い -> 済み
    assert actions(batch.scan_mbd_directory(src, out, checkpoint=cp(PAST))) == {"a.MBD": batch.OVERWRITE}  # 起点より新しい -> 作り直し
    assert actions(batch.scan_mbd_directory(src, out, checkpoint=cp(FUTURE()), convert_all=True)) == {"a.MBD": batch.OVERWRITE}
    assert actions(batch.scan_mbd_directory(src, out, checkpoint=cp(FUTURE(), failed=["a.MBD"]))) == {"a.MBD": batch.OVERWRITE}
    # 起点なしで中身が同じ -> 済み。中身が変わっていれば（SHA-256 が記録と違う）作り直し
    assert actions(batch.scan_mbd_directory(src, out)) == {"a.MBD": batch.ALREADY}
    mk(src, "a.MBD").write_bytes(a.read_bytes() + b"\x00" * 16)
    assert actions(batch.scan_mbd_directory(src, out)) == {"a.MBD": batch.OVERWRITE}


# ---------------------------------------------------------------- 名前の衝突・出どころ・壊れた MES の保護
def test_two_files_mapping_to_one_mes_name_are_protected_unless_one_owns_it(env):
    src, out, _ = env
    mk(src, "r 1.MBD")
    mk(src, "r-1.MBD")  # どちらも r-1.MES になる
    scan = batch.scan_mbd_directory(src, out)
    assert sorted(actions(scan).values()) == [batch.PROTECTED, batch.PROTECTED]  # 持ち主が決められないので、どちらも触らない
    assert all("name conflict" in i.reason for i in scan.protected)
    # どちらかが MES の持ち主（記録に出る）なら、持ち主だけが処理され、もう一方は保護される
    plain_convert([src / "r-1.MBD"], out)
    scan = batch.scan_mbd_directory(src, out)
    assert actions(scan)["r 1.MBD"] == batch.PROTECTED and actions(scan)["r-1.MBD"] == batch.ALREADY


def test_healthy_mes_without_any_evidence_is_protected_even_with_convert_all(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    plain_convert([a], out)
    (out / "a.MES" / cv.RECORD_NAME).unlink()  # 記録（出どころの証拠）を消した = 出どころ不明の MES
    for convert_all in (False, True):
        scan = batch.scan_mbd_directory(src, out, convert_all=convert_all)
        assert actions(scan) == {"a.MBD": batch.PROTECTED} and "origin unknown" in scan.protected[0].reason


def test_healthy_mes_of_another_mbd_is_protected(env):
    src, out, _ = env
    mk(src, "x.MBD")
    other = mk(src, "other.MBD")
    plain_convert([other], out)
    shutil.copytree(out / "other.MES", out / "x.MES")  # x.MES の中身は other.MBD から作った物（記録がそう言う）
    for f in (out / "x.MES").iterdir():
        if f.name.startswith("other"):
            f.rename(f.with_name("x" + f.name[len("other"):]))
    scan = batch.scan_mbd_directory(src, out)
    assert actions(scan)["x.MBD"] == batch.PROTECTED and "other.MBD" in next(i for i in scan.protected if i.path.name == "x.MBD").reason


def test_broken_mes_is_repaired_only_when_the_owner_is_verified(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    plain_convert([a], out)
    (out / "a.MES" / "a.CAL").unlink()  # 壊れた MES（不完全）
    scan = batch.scan_mbd_directory(src, out)
    assert actions(scan) == {"a.MBD": batch.OVERWRITE} and "incomplete" in scan.overwrite_items[0].reason  # 持ち主は記録で確認できる
    (out / "a.MES" / cv.RECORD_NAME).unlink()
    scan = batch.scan_mbd_directory(src, out)
    assert actions(scan) == {"a.MBD": batch.PROTECTED}  # 証拠が無い壊れた MES は触らない
    for f in (out / "a.MES").glob("*.DDD"):
        f.unlink()
    assert actions(batch.scan_mbd_directory(src, out)) == {"a.MBD": batch.PROTECTED}


def test_a_ledger_name_alone_is_not_ownership(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    plain_convert([a], out)
    (out / "a.MES" / cv.RECORD_NAME).unlink()
    elsewhere = src.parent / "elsewhere"
    elsewhere.mkdir()
    (out / batch.MANIFEST_NAME).write_text(json.dumps({"schema": 1, "entries": {"a": {
        "source_filename": "a.MBD", "source_path": str(elsewhere / "a.MBD"), "source_sha256": "0" * 64}}}), encoding="utf-8")
    scan = batch.scan_mbd_directory(src, out)
    assert actions(scan) == {"a.MBD": batch.PROTECTED}  # 名前が同じでも、フォルダも中身も違う台帳の行は持ち主の証拠にしない


def test_damaged_ledger_warns_is_ignored_and_set_aside_before_the_next_save(env):
    src, out, _ = env
    mk(src, "a.MBD")
    (out / batch.MANIFEST_NAME).write_bytes(b"{ broken")
    scan = batch.scan_mbd_directory(src, out)
    assert any("damaged" in n for n in scan.notes) and actions(scan) == {"a.MBD": batch.NEW}
    report = batch.convert_unconverted(scan, channel_map_data=None)
    assert report.converted_count == 1
    asides = list(out.glob(batch.MANIFEST_NAME + ".corrupt_*"))
    assert len(asides) == 1 and asides[0].read_bytes() == b"{ broken"
    assert json.loads((out / batch.MANIFEST_NAME).read_text(encoding="utf-8"))["schema"] == 1


def test_work_folder_leftovers_are_noted_and_never_touched(env):
    src, out, _ = env
    mk(src, "a.MBD")
    (out / (cv.STAGE_PREFIX + "abc")).mkdir()
    before = tree(out)
    scan = batch.scan_mbd_directory(src, out)
    assert any("work folder" in n for n in scan.notes) and tree(out) == before


# ---------------------------------------------------------------- 実行
def test_first_converts_all_second_does_nothing_third_converts_only_the_new_file(env):
    src, out, settings = env
    for n in ("a", "b", "c"):
        mk(src, f"{n}.MBD")
    # 1 回目: 起点が無い = 未変換を全部（確認の画面は GUI。ここでは走査 -> 実行）
    scan = batch.scan_mbd_directory(src, out, checkpoint=cfgmod.get_batch_checkpoint(src))
    assert not scan.had_checkpoint and [i.path.name for i in scan.to_convert] == ["a.MBD", "b.MBD", "c.MBD"]
    report = batch.convert_unconverted(scan, channel_map_data=None)
    assert report.converted_count == 3 and report.checkpoint_saved and sorted(p.name for p in out.glob("*.MES")) == ["a.MES", "b.MES", "c.MES"]
    ledger = json.loads((out / batch.MANIFEST_NAME).read_text(encoding="utf-8"))["entries"]
    assert set(ledger) == {"a", "b", "c"} and ledger["a"]["source_sha256"] == hashlib.sha256((src / "a.MBD").read_bytes()).hexdigest()
    # 2 回目: 何も変わらない
    scan2 = batch.scan_mbd_directory(src, out, checkpoint=cfgmod.get_batch_checkpoint(src))
    assert scan2.had_checkpoint and scan2.to_convert == [] and sorted(actions(scan2).values()) == [batch.ALREADY] * 3
    # 3 回目: 起点より後に届いた 1 本だけ
    time.sleep(0.05)
    mk(src, "d.MBD")
    scan3 = batch.scan_mbd_directory(src, out, checkpoint=cfgmod.get_batch_checkpoint(src))
    assert [i.path.name for i in scan3.to_convert] == ["d.MBD"]
    report3 = batch.convert_unconverted(scan3, channel_map_data=None)
    assert report3.converted_count == 1 and report3.already_count == 3


def test_a_nothing_to_convert_run_does_not_move_the_checkpoint(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    plain_convert([a], out)
    scan = batch.scan_mbd_directory(src, out)
    assert scan.to_convert == []
    report = batch.convert_unconverted(scan, channel_map_data=None)
    assert report.total_candidates == 0 and not report.checkpoint_saved and cfgmod.get_batch_checkpoint(src) is None


def test_batch_mes_equals_the_mes_a_plain_convert_makes(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    scan = batch.scan_mbd_directory(src, out)
    batch.convert_unconverted(scan, channel_map_data=None)
    other = out.parent / "plain_out"
    plain_convert([a], other)
    assert tree(out / "a.MES") == tree(other / "a.MES")  # 記録ファイルを含め 1 byte も違わない


def test_a_failed_file_is_remembered_and_retried_even_when_old(env):
    src, out, _ = env
    mk(src, "good.MBD")
    # マジックと大きさは通るが、チャンネル表が壊れていて読めない
    bad = src / "bad.MBD"
    bad.write_bytes(b"4OEL V0003".ljust(15, b" ") + b"\x00" + b"\xff" * 0x2100)
    scan = batch.scan_mbd_directory(src, out)
    assert actions(scan) == {"bad.MBD": batch.NEW, "good.MBD": batch.NEW}
    report = batch.convert_unconverted(scan, channel_map_data=None)
    assert report.converted_count == 1 and [p.name for p, _ in report.failed_items] == ["bad.MBD"]
    cp_now = cfgmod.get_batch_checkpoint(src)
    assert cp_now["failed_files"] == ["bad.MBD"]
    # 次回: 起点より古くても、失敗したファイルは NEW に戻る。済みの good は触らない
    scan2 = batch.scan_mbd_directory(src, out, checkpoint=cp_now)
    assert actions(scan2) == {"bad.MBD": batch.NEW, "good.MBD": batch.ALREADY}
    assert batch.remaining_after(scan, report) == [bad]  # 一覧に残るのは失敗した物


def test_a_file_that_changes_after_the_scan_is_a_failure_to_retry(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    scan = batch.scan_mbd_directory(src, out)
    a.write_bytes(a.read_bytes() + b"\x00" * 8)  # 走査のあとに変わった
    report = batch.convert_unconverted(scan, channel_map_data=None)
    assert report.converted_count == 0 and "changed since the scan" in report.failed_items[0][1]
    assert not list(out.glob("*.MES"))


def test_guard_cancels_a_new_mes_when_the_folder_appears_before_publishing(env, monkeypatch):
    """変換の途中（作業フォルダへ書いた直後・公開の直前）に、外部が同名のフォルダを作った。公開せず、外部の物はそのまま残る。"""
    src, out, _ = env
    a = mk(src, "a.MBD")
    scan = batch.scan_mbd_directory(src, out)
    precious = out / "a.MES"
    real_write = cv.mw.write_reconstructed_mes

    def write_then_someone_creates_the_folder(*args, **kwargs):
        result = real_write(*args, **kwargs)
        precious.mkdir()
        (precious / "keep.txt").write_text("external asset")
        return result

    monkeypatch.setattr(cv.mw, "write_reconstructed_mes", write_then_someone_creates_the_folder)
    report = batch.convert_unconverted(scan, channel_map_data=None)
    assert report.converted_count == 0 and report.externally_changed == [a]
    assert (precious / "keep.txt").read_text() == "external asset" and not list(out.glob(cv.STAGE_PREFIX + "*"))
    assert [p.name for p in precious.iterdir()] == ["keep.txt"]


def test_a_mes_that_exists_before_the_conversion_starts_is_a_plain_failure_not_replaced(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    scan = batch.scan_mbd_directory(src, out)
    precious = out / "a.MES"
    precious.mkdir()
    (precious / "keep.txt").write_text("external asset")  # 走査のあと・変換の前に外部が作った
    report = batch.convert_unconverted(scan, channel_map_data=None)
    assert report.converted_count == 0 and [p for p, _ in report.failed_items] == [a]
    assert [p.name for p in precious.iterdir()] == ["keep.txt"]


def test_guard_cancels_an_overwrite_when_the_mes_changed_after_the_scan(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    plain_convert([a], out)
    scan = batch.scan_mbd_directory(src, out, convert_all=True)
    assert actions(scan) == {"a.MBD": batch.OVERWRITE}
    (out / "a.MES" / "extra.txt").write_text("added by someone after the scan")
    before = tree(out)
    report = batch.convert_unconverted(scan, channel_map_data=None)
    assert report.externally_changed == [a] and tree(out) == before  # 外部の変更ごと残る


def test_a_raising_hook_keeps_the_existing_mes_and_leaves_no_work_folder(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    plain_convert([a], out)
    before = tree(out)

    def boom(_final):
        raise cv.ConvertError("stop")

    with pytest.raises(cv.ConvertError):
        cv.convert_one(a, out, force=True, before_replace=boom)
    assert tree(out) == before and not list(out.glob(cv.STAGE_PREFIX + "*"))


def test_the_hook_is_called_for_a_new_mes_too_and_without_it_nothing_changes(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    seen = []
    cv.convert_one(a, out, before_replace=seen.append)
    assert seen == [out / "a.MES"]
    with pytest.raises(cv.ConvertError, match="already exists"):
        cv.convert_one(a, out)  # フック無しでも、既存は force が無ければ置き換えない


def test_the_checkpoint_goes_only_to_the_isolated_settings(env):
    src, out, settings = env
    mk(src, "a.MBD")
    batch.convert_unconverted(batch.scan_mbd_directory(src, out), channel_map_data=None)
    cfg = json.loads((settings / "mbd2mes_config.json").read_text(encoding="utf-8"))
    assert list(cfg["batch_checkpoints"]) == [cfgmod.normalize_checkpoint_key(src)]


def test_batch_reads_each_date_from_the_name_and_a_given_date_overrides_all(env):
    """FB01 の 4（案 C）: 一発変換でも、名前の日付が 1 本ずつ効く。欄（date）があれば全部がそれになる。"""
    import datetime

    src, out, _ = env
    mk(src, "26.11.8named.MBD")  # 名前の日付 = 2026-11-08（手で書いた期待値）
    mk(src, "2026-10-04_other.MBD")  # = 2026-10-04
    scan = batch.scan_mbd_directory(src, out)
    batch.convert_unconverted(scan, channel_map_data=None)
    start = {n: (out / n / (n[:-4] + ".HED")).read_text(encoding="cp1252") for n in sorted(p.name for p in out.glob("*.MES"))}
    assert "Start of download=08.11.2026 09:56:43" in start["26-11-8named.MES"]
    assert "Start of download=04.10.2026 09:56:43" in start["2026-10-04-other.MES"]
    rec = (out / "26-11-8named.MES" / cv.RECORD_NAME).read_text(encoding="utf-8")
    assert "date source: file name 2026-11-08 (local) + GPS time of day" in rec
    # 欄の日付が全部に効く（出どころは date field）
    out2 = out.parent / "out2"
    out2.mkdir()
    scan2 = batch.scan_mbd_directory(src, out2)
    batch.convert_unconverted(scan2, channel_map_data=None, date=datetime.date(2026, 1, 2), date_label="date field")
    for n in ("26-11-8named", "2026-10-04-other"):
        assert "Start of download=02.01.2026 09:56:43" in (out2 / f"{n}.MES" / f"{n}.HED").read_text(encoding="cp1252")
    assert "date field 2026-01-02 (local)" in (out2 / "26-11-8named.MES" / cv.RECORD_NAME).read_text(encoding="utf-8")


def test_confirm_text_lists_each_date_with_its_source_and_warns_about_the_modification_time(env):
    import datetime

    src, out, _ = env
    mk(src, "26.11.8a.MBD")
    mk(src, "nodate.MBD")
    scan = batch.scan_mbd_directory(src, out)
    text = batch.confirm_text(scan)
    assert "26.11.8a.MBD: 2026-11-08 (file name)" in text
    assert "nodate.MBD: from the file modification time -- CHECK: no date in the file name" in text
    assert "WARNING: 1 file(s) have no date in the name" in text
    over = batch.confirm_text(scan, datetime.date(2026, 11, 9), "date field")
    assert "26.11.8a.MBD: 2026-11-09 (date field)" in over and "nodate.MBD: 2026-11-09 (date field)" in over and "WARNING" not in over


def test_mes_fingerprint_sees_every_file(env):
    src, out, _ = env
    a = mk(src, "a.MBD")
    plain_convert([a], out)
    fp = batch.mes_fingerprint(out / "a.MES")
    (out / "a.MES" / "extra.txt").write_text("x")
    assert batch.mes_fingerprint(out / "a.MES") != fp and batch.mes_fingerprint(out / "nope.MES") == {}


def test_batch_module_does_not_import_tk():
    import ast

    tree_ = ast.parse((Path(batch.__file__)).read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree_) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module or "" for n in ast.walk(tree_) if isinstance(n, ast.ImportFrom)}
    assert not any(x.startswith("tkinter") for x in names)


# ---------------------------------------------------------------- Codex FB01 [2]: 壊れた起点は「無い」として扱う
BAD_CHECKPOINTS = [
    {"scan_started_at_ns": "x"}, {"scan_started_at_ns": None}, {"scan_started_at_ns": True},
    {"scan_started_at_ns": 1.5}, {"scan_started_at_ns": 5, "failed_files": 1},
    {"scan_started_at_ns": 5, "failed_files": [1, 2]}, {"scan_started_at_ns": 5, "failed_files": "a.MBD"}, {}, "text", [], 7,
]


@pytest.mark.parametrize("bad", BAD_CHECKPOINTS, ids=lambda v: repr(v)[:40])
def test_a_damaged_checkpoint_is_treated_as_none_by_the_scan_and_the_config(env, bad):
    src, out, _ = env
    a = mk(src, "a.MBD")
    plain_convert([a], out)
    mk(src, "b.MBD")
    scan = batch.scan_mbd_directory(src, out, checkpoint=bad)  # 例外にしない
    assert not scan.had_checkpoint and actions(scan) == {"a.MBD": batch.ALREADY, "b.MBD": batch.NEW}  # 起点なしと同じ判定
    # 設定のファイルに書かれた壊れた値も、読み取りで None になる
    cfg_path = cfgmod.config_path()
    cfgmod.set_batch_checkpoint(src, 5, [])
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["batch_checkpoints"][cfgmod.normalize_checkpoint_key(src)] = bad
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    assert cfgmod.get_batch_checkpoint(src) is None


def test_a_valid_checkpoint_is_still_read(env):
    src, _out, _ = env
    cfgmod.set_batch_checkpoint(src, 123, ["x.MBD"])
    cp_ = cfgmod.get_batch_checkpoint(src)
    assert cp_["scan_started_at_ns"] == 123 and cp_["failed_files"] == ["x.MBD"]
    assert cfgmod.checkpoint_is_valid({"scan_started_at_ns": 0}) and cfgmod.checkpoint_is_valid({"scan_started_at_ns": 5, "failed_files": None})
