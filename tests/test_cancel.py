# -*- coding: utf-8 -*-
"""Cancel（FB03）の核: 止めても、出力先・既存の MES・対応表・台帳・起点が壊れない。公開の最中は止めない。残りの一発変換もやめる。

期待値は、試す側が別の出どころで作る: 変換前の出力先の写し（ファイルごとの SHA-256）・同じ入力を別の出力先へ素で変換した MES・
手で組んだ台帳/起点の状態。止めたあとに変換器の判定を再利用して期待値を作らない。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import threading
from pathlib import Path

import map_synth as ms
import pytest
from conftest import fresh_settings

from mbd2mes import app_convert as ac
from mbd2mes import batch
from mbd2mes import channel_map as cm
from mbd2mes import config as cfgmod
from mbd2mes import convert as cv
from mbd2mes import progress as prg

DAY = datetime.date(2026, 11, 8)
PAST_NS = 946684800 * 10**9  # 2000-01-01（どのファイルも起点より新しい）


def snapshot(d: Path) -> dict:
    """フォルダの中の全ファイル（相対名 -> SHA-256）と、空のフォルダ。"""
    if not d.exists():
        return {}
    snap = {}
    for p in sorted(d.rglob("*")):
        key = p.relative_to(d).as_posix()
        snap[key] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<dir>"
    return snap


def cancel_at(step: int, frac: float = 0.0):
    """step の frac 以降の最初の通知で旗を立てる（その通知の直後に止まる）。(旗, progress 関数)。"""
    event = threading.Event()

    def progress(s: int, f: float) -> None:
        if s == step and f >= frac:
            event.set()

    return event, progress


@pytest.fixture()
def env(tmp_path, monkeypatch):
    settings = fresh_settings(tmp_path, monkeypatch)
    return tmp_path, settings, ms.write(tmp_path / "a.MBD", course="a")


# 止める場面: 読み取り中・値の展開・定義作り・書き出し中・ラップと検査・公開の直前
POINTS = [(1, 0.3, "reading"), (2, 0.5, "values"), (4, 0.5, "definitions"), (5, 0.4, "writing"), (6, 0.4, "checks"), (7, 0.0, "before publish")]


@pytest.mark.parametrize("step, frac, _name", POINTS, ids=[p[2] for p in POINTS])
def test_cancel_into_a_new_output_leaves_nothing_behind(env, step, frac, _name):
    tmp, settings, mbd = env
    out = tmp / "out"
    out.mkdir()
    cmap = json.loads(cm.seed_path().read_text(encoding="utf-8"))
    del cmap["channels"]["THP"]  # 変換が成功すれば自動成長で表を保存する行（止めたら保存しない）
    settings_before, out_before = snapshot(settings), snapshot(out)
    event, progress = cancel_at(step, frac)
    with pytest.raises(cv.Cancelled) as ei:
        cv.convert_one(mbd, out, date=DAY, channel_map_data=cmap, progress=progress, cancel=event)
    assert ei.value.step_label == prg.STEP_LABELS[step - 1]  # 止めた段が分かる
    assert snapshot(out) == out_before == {}  # 作りかけの MES も作業フォルダも残らない
    assert not list(out.glob(cv.STAGE_PREFIX + "*"))
    assert snapshot(settings) == settings_before  # 対応表も（自動成長の保存も）変わらない


@pytest.mark.parametrize("step, frac, _name", POINTS, ids=[p[2] for p in POINTS])
def test_cancel_never_changes_an_existing_mes(env, step, frac, _name):
    tmp, settings, mbd = env
    out = tmp / "out"
    cv.convert_one(mbd, out, date=DAY)  # 既にある MES
    before = snapshot(out)
    assert before  # 写しは、止める前の出力先
    event, progress = cancel_at(step, frac)
    with pytest.raises(cv.Cancelled):
        cv.convert_one(mbd, out, date=DAY, force=True, progress=progress, cancel=event)  # 置き換えようとして止める
    assert snapshot(out) == before  # 既にある MES は 1 byte も変わらない・作業フォルダも残らない


def test_cancel_before_anything_starts(env):
    tmp, _s, mbd = env
    event = threading.Event()
    event.set()
    with pytest.raises(cv.Cancelled) as ei:
        cv.convert_one(mbd, tmp / "out", cancel=event)  # progress なしでも旗は見る
    assert ei.value.step_label == prg.STEP_LABELS[0] and not (tmp / "out").exists()


def test_cancel_during_publish_waits_for_the_swap_and_says_so(env, monkeypatch):
    """公開（作業フォルダから最終の位置への入れ替え）の最中は止めない。入れ替えが終わってから、そのことをログに出す。"""
    tmp, _s, mbd = env
    out = tmp / "out"
    first = cv.convert_one(mbd, out, date=DAY)
    old_record = (first.mes_dir / cv.RECORD_NAME).read_bytes()
    event, logs = threading.Event(), []
    cancel_during_swap(monkeypatch, event, "a")  # 入れ替えの最中（既存の MES を退避した後・新しい MES を置く直前）に Cancel が押された
    res = cv.convert_one(mbd, out, date=datetime.date(2026, 11, 9), force=True, cancel=event, log=logs.append)
    assert (res.mes_dir / cv.RECORD_NAME).read_bytes() != old_record  # 入れ替えは終わっている（新しい MES が最終の位置にある）
    assert (res.mes_dir / f"{res.mes_name}.DDD").is_file() and not list(out.glob(cv.STAGE_PREFIX + "*"))
    assert sorted(p.name for p in out.iterdir()) == ["a.MES"]  # 退避した古い MES の残りも無い
    assert any("Cancel was requested while the MES was being published" in x for x in logs)


def test_cancel_during_the_guard_or_right_after_it_still_stops_before_publishing(env):
    """ガード（before_replace。一発変換が走査のあとの外部の変更を確かめる所）の最中・直後は、まだ公開ではない。止まり、何も変わらない
    （Codex の FB03 レビュー [1]: 以前は、ガードの前から「公開の最中」扱いで止められなかった）。"""
    tmp, _s, mbd = env
    out = tmp / "out"
    cv.convert_one(mbd, out, date=DAY)
    before = snapshot(out)
    event = threading.Event()
    with pytest.raises(cv.Cancelled) as ei:
        cv.convert_one(mbd, out, date=DAY, force=True, cancel=event, before_replace=lambda _final: event.set())
    assert ei.value.step_label == prg.STEP_LABELS[-1] and snapshot(out) == before  # 既存の MES は不変・作業フォルダも残らない
    fresh = tmp / "fresh"
    event2 = threading.Event()
    with pytest.raises(cv.Cancelled):
        cv.convert_one(mbd, fresh, date=DAY, cancel=event2, before_replace=lambda _final: event2.set())
    assert snapshot(fresh) == {}  # 新しい出力先にも何も残らない


def test_a_cancel_that_arrives_after_the_publish_does_not_undo_it(env):
    tmp, _s, mbd = env
    event = threading.Event()

    def progress(step, frac):
        if step == 7 and frac == 1.0:
            event.set()  # 最後の通知（公開は終わっている）で押された

    res = cv.convert_one(mbd, tmp / "out", date=DAY, progress=progress, cancel=event)
    assert (res.mes_dir / "a.DDD").is_file()


def test_without_cancel_nothing_changes(env):
    tmp, _s, mbd = env
    a = cv.convert_one(mbd, tmp / "a", date=DAY)
    b = cv.convert_one(mbd, tmp / "b", date=DAY, cancel=threading.Event())  # 旗はあるが立たない
    assert snapshot(a.mes_dir) == snapshot(b.mes_dir)


# ---------------------------------------------------------------- 複数本
def cancel_during_swap(monkeypatch, event, mes_name: str):
    """入れ替えの最中に Cancel を押す: 作業フォルダの <mes_name>.MES を最終の位置へ rename する直前（= 公開の最中）に旗を立てる。"""
    real_rename = Path.rename

    def rename(self, target):
        if self.name == f"{mes_name}.MES" and self.parent.name.startswith(cv.STAGE_PREFIX):
            event.set()
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)


def three(tmp):
    return [ms.write(tmp / f"{n}.MBD", course=n) for n in "abc"]


def cancel_during_file(name: str, step: int = 5, frac: float = 0.3):
    """name の変換の途中で旗を立てる。(旗, convert_one の差し替えに使う progress フック)。"""
    event = threading.Event()
    real = cv.convert_one

    def wrapped(path, *a, **k):
        user_progress = k.get("progress")

        def hook(s, f):
            if user_progress is not None:
                user_progress(s, f)
            if path.name == name and s == step and f >= frac:
                event.set()

        k["progress"] = hook
        return real(path, *a, **k)

    return event, wrapped


def test_cancel_in_the_second_file_keeps_the_first_and_stops_the_rest(env, monkeypatch):
    tmp, _s, _m = env
    a, b, c = three(tmp)
    out = tmp / "out"
    cv.convert_one(a, tmp / "reference", date=DAY)  # 期待値: 1 本目だけを素で変換した MES（別の出力先）
    event, wrapped = cancel_during_file("b.MBD")
    monkeypatch.setattr(cv, "convert_one", wrapped)
    logs = []
    outcome = ac.convert_many([a, b, c], out, channel_map_data=None, date=DAY, cancel=event, log=logs.append)
    assert [r.mes_name for r in outcome.results] == ["a"] and outcome.cancelled_file == b and outcome.not_started == [c]
    assert outcome.cancel_requested and outcome.cancelled_step == prg.STEP_LABELS[4] and not outcome.failed
    assert snapshot(out / "a.MES") == snapshot(tmp / "reference" / "a.MES")  # 終わった 1 本目は、素の変換と 1 byte も違わない
    assert sorted(p.name for p in out.iterdir()) == ["a.MES"]  # 止めた 2 本目の作りかけ・3 本目は無い・作業フォルダも無い
    text = "\n".join(logs)
    assert "[CANCEL] b.MBD: cancelled while \"Writing channel data files\"; nothing was written for it" in text
    assert "[CANCEL] The remaining 1 file(s) were not started: c.MBD" in text and "[CANCEL] Cancelled. Finished before the cancel: a.MBD" in text
    assert "Cancelled by the user." in ac.outcome_text(outcome, 3) and "Stopped: b.MBD" in ac.outcome_text(outcome, 3)


def test_cancel_before_the_first_file_starts_nothing(env):
    tmp, _s, _m = env
    a, b, c = three(tmp)
    event = threading.Event()
    event.set()
    outcome = ac.convert_many([a, b, c], tmp / "out", channel_map_data=None, cancel=event)
    assert outcome.results == [] and outcome.not_started == [a, b, c] and outcome.cancelled_file is None and not (tmp / "out").exists()


def test_cancel_during_the_publish_of_the_second_file_finishes_it_and_skips_the_third(env, monkeypatch):
    tmp, _s, _m = env
    a, b, c = three(tmp)
    out = tmp / "out"
    event = threading.Event()
    cancel_during_swap(monkeypatch, event, "b")  # b の入れ替えの最中に押された
    logs = []
    outcome = ac.convert_many([a, b, c], out, channel_map_data=None, date=DAY, cancel=event, log=logs.append)
    assert [r.mes_name for r in outcome.results] == ["a", "b"] and outcome.not_started == [c] and outcome.cancelled_file is None
    assert sorted(p.name for p in out.iterdir()) == ["a.MES", "b.MES"]  # b は入れ替えが終わってから止まった
    assert any("published; the publish was finished first" in x or "the publish was finished first" in x for x in logs)


def test_cancel_at_the_guard_of_the_second_file_keeps_the_first_and_changes_nothing_else(env):
    tmp, _s, _m = env
    a, b, c = three(tmp)
    out = tmp / "out"
    event = threading.Event()
    outcome = ac.convert_many([a, b, c], out, channel_map_data=None, date=DAY, cancel=event,
                              before_replace=lambda final: event.set() if final.name == "b.MES" else None)  # b のガードの最中に Cancel
    assert [r.mes_name for r in outcome.results] == ["a"] and outcome.cancelled_file == b and outcome.not_started == [c]
    assert sorted(p.name for p in out.iterdir()) == ["a.MES"]  # b の MES は公開されていない・作業フォルダも無い


# ---------------------------------------------------------------- 一発変換: 台帳と起点
def batch_setup(tmp):
    src, out = tmp / "src", tmp / "out"
    src.mkdir()
    out.mkdir()
    for n in "abc":
        ms.write(src / f"{n}.MBD", course=n)
    return src, out


def test_batch_cancel_keeps_finished_files_recorded_and_the_rest_unrecorded(env, monkeypatch):
    tmp, _s, _m = env
    src, out = batch_setup(tmp)
    cfgmod.set_batch_checkpoint(src, PAST_NS, [])  # 起点: ずっと前（全部「新しい」= 候補）
    before_cp = cfgmod.get_batch_checkpoint(src)
    scan = batch.scan_mbd_directory(src, out, checkpoint=before_cp)
    assert [i.path.name for i in scan.to_convert] == ["a.MBD", "b.MBD", "c.MBD"]
    event, wrapped = cancel_during_file("b.MBD")
    monkeypatch.setattr(cv, "convert_one", wrapped)
    logs = []
    report = batch.convert_unconverted(scan, channel_map_data=None, cancel=event, log=logs.append)
    assert [p.name for p in report.converted] == ["a.MBD"] and report.cancel_requested
    assert [p.name for p in report.cancelled_items] == ["b.MBD", "c.MBD"] and report.cancelled_step == prg.STEP_LABELS[4]
    assert sorted(p.name for p in out.iterdir() if not p.name.startswith(".")) == ["a.MES"]  # b・c の MES も作業フォルダも無い
    ledger = json.loads((out / batch.MANIFEST_NAME).read_text(encoding="utf-8"))["entries"]
    assert list(ledger) == ["a"]  # 止めた b・始めなかった c を「変換済み」と記録しない
    assert ledger["a"]["source_sha256"] == hashlib.sha256((src / "a.MBD").read_bytes()).hexdigest()
    assert cfgmod.get_batch_checkpoint(src) == before_cp and report.checkpoint_saved is False  # 起点は動かさない
    assert any("[CANCEL] Batch conversion cancelled." in x and "Finished (kept as converted): a.MBD" in x and "Stopped in the middle (nothing written): b.MBD" in x
               and "Not started: c.MBD" in x for x in logs)
    assert batch.remaining_after(scan, report) == [src / "b.MBD", src / "c.MBD"]  # 一覧に残る（もう一度押せる）
    assert "Cancelled by the user. Not converted: 2" in batch.summary_text(report)
    # もう一度: a は済み（台帳）、b・c が候補に残っていて、最後まで変換できる
    monkeypatch.undo()
    fresh = batch.scan_mbd_directory(src, out, checkpoint=cfgmod.get_batch_checkpoint(src))
    names = {i.path.name: i.action for i in fresh.items}
    assert names["b.MBD"] == batch.NEW and names["c.MBD"] == batch.NEW
    done = batch.convert_unconverted(fresh, channel_map_data=None)
    assert {p.name for p in done.converted} >= {"b.MBD", "c.MBD"} and not done.cancel_requested


def test_batch_cancel_during_publish_records_that_file_and_skips_the_rest(env, monkeypatch):
    tmp, _s, _m = env
    src, out = batch_setup(tmp)
    scan = batch.scan_mbd_directory(src, out)
    event = threading.Event()
    cancel_during_swap(monkeypatch, event, "b")  # b の入れ替えの最中に Cancel
    report = batch.convert_unconverted(scan, channel_map_data=None, cancel=event)
    assert [p.name for p in report.converted] == ["a.MBD", "b.MBD"] and [p.name for p in report.cancelled_items] == ["c.MBD"]
    ledger = json.loads((out / batch.MANIFEST_NAME).read_text(encoding="utf-8"))["entries"]
    assert set(ledger) == {"a", "b"} and report.cancelled_step == ""  # b は公開まで終わったので変換済み。c は始めない
    assert report.failed_items == []  # 始めなかった c は失敗ではない
    assert sorted(p.name for p in out.glob("*.MES")) == ["a.MES", "b.MES"]


def test_batch_cancel_with_existing_mes_changes_only_what_finished(env, monkeypatch):
    """「全部変換」で上書きの途中に Cancel: 終わった 1 本目だけが作り直され、止めた 2 本目の既存の MES は 1 byte も変わらない。"""
    tmp, _s, _m = env
    src, out = batch_setup(tmp)
    ac.convert_many([src / "a.MBD", src / "b.MBD", src / "c.MBD"], out, channel_map_data=None, date=DAY)  # 全部変換済み
    before = {n: snapshot(out / f"{n}.MES") for n in "abc"}
    scan = batch.scan_mbd_directory(src, out, convert_all=True)
    assert [i.action for i in scan.items] == [batch.OVERWRITE] * 3
    event, wrapped = cancel_during_file("b.MBD", step=5, frac=0.5)
    monkeypatch.setattr(cv, "convert_one", wrapped)
    report = batch.convert_unconverted(scan, channel_map_data=None, cancel=event)
    assert [p.name for p in report.converted] == ["a.MBD"] and [p.name for p in report.cancelled_items] == ["b.MBD", "c.MBD"]
    assert snapshot(out / "b.MES") == before["b"] and snapshot(out / "c.MES") == before["c"]  # 止めた物・残りの既存の MES は不変
    assert not list(out.glob(cv.STAGE_PREFIX + "*"))


def test_batch_cancel_before_the_first_file_converts_nothing_and_keeps_everything(env):
    tmp, _s, _m = env
    src, out = batch_setup(tmp)
    scan = batch.scan_mbd_directory(src, out)
    event = threading.Event()
    event.set()
    report = batch.convert_unconverted(scan, channel_map_data=None, cancel=event)
    assert report.converted == [] and len(report.cancelled_items) == 3 and snapshot(out) == {}
    assert cfgmod.get_batch_checkpoint(src) is None and not (out / batch.MANIFEST_NAME).exists()


# ---------------------------------------------------------------- 残りの目安・時計の書式（手で書いた値）
def test_estimate_remaining_and_clock_format():
    assert prg.estimate_remaining(10.0, 0.25) == pytest.approx(30.0)  # 10 秒で 25% -> 残り 30 秒
    assert prg.estimate_remaining(60.0, 0.5) == pytest.approx(60.0)
    assert prg.estimate_remaining(2.0, 0.5) is None  # 始めのうちは当てにならない
    assert prg.estimate_remaining(10.0, 0.01) is None and prg.estimate_remaining(10.0, 1.0) is None
    assert [prg.format_clock(s) for s in (0, 5, 65, 599.6, 3725)] == ["0:00", "0:05", "1:05", "10:00", "1:02:05"]
