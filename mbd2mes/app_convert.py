# -*- coding: utf-8 -*-
"""app_convert.py -- GUI・CLI（D&D を含む）が共通で使う「複数本を順に変換する」層。

実際の変換は convert.convert_one() だけ（3 経路で同一のコードパス）。ここは 1 件の失敗で止めない順次処理・
対応表の読み込み・上書きの確認・失敗の分類（終了コード）だけを持つ。RCZ2MES の convert_many の骨格（元は LD2MES の GUI）。
"""

from __future__ import annotations

import datetime
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import convert as cv
from . import dates
from . import gps_entries as ge
from . import map_rules
from . import progress as prg
from .mbd_reader import MbdError

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_CORRUPT = 0, 1, 2, 4

# channel_map_data の既定: 実際の対応表（exe の隣の channel_map.json。無ければ seed から作る）を読む。None は「表を使わない」
USE_DEFAULT_MAP = object()


@dataclass
class Outcome:
    results: list[cv.ConvertResult] = field(default_factory=list)
    failed: list[tuple[Path, str, int]] = field(default_factory=list)  # (入力, 理由, 終了コード)
    declined: list[Path] = field(default_factory=list)  # 上書きを断られた入力

    @property
    def map_save_failed(self) -> bool:
        return any(not r.map_saved for r in self.results)


def target_mes_dir(path, out_dir, mes_name: str | None = None) -> Path:
    """この入力から作る MES フォルダの場所（convert_one と同じ名前の決め方）。"""
    path = Path(path)
    return Path(out_dir) / f"{cv.sanitize_mes_name(mes_name if mes_name is not None else path.stem)}.MES"


def convert_many(paths, out_dir, *, mes_name: str | None = None, force: bool = False, date: datetime.date | None = None,
                 channel_map_data=USE_DEFAULT_MAP, log=None, confirm_overwrite=None, before_replace=None,
                 date_label: str = dates.SOURCE_OPTION, progress=None, file_offset: int = 0, file_total: int | None = None) -> Outcome:
    """paths を順に convert_one する。1 件の失敗で止めない。

    confirm_overwrite(入力, 既存の MES フォルダ) -> bool: 同名の MES があり force でないとき、置き換えてよいかを聞く関数。
    None なら聞かず、convert_one が「already exists」で失敗させる（CLI の既定）。False を返した入力は declined に入り、変換しない。
    before_replace(MES フォルダ) は convert_one へそのまま渡す（一発変換のガード）。
    progress(ProgressEvent): 省略できる（画面の進み具合用）。1 本ごとに段の進みを全体の % にして渡す。file_offset・file_total は、
    呼び出し側が 1 本ずつ呼ぶとき（一発変換）の File k/n の数え方（k = file_offset + このループの番号）。
    date は明示の記録日（CLI の --date・GUI の欄）で、あれば全部の入力に使う（date_label = その出どころの名前）。
    None なら 1 本ずつ、ファイル名から読む（dates.choose）。読めなければ更新時刻（convert_one が警告する）。
    """
    log = log or (lambda _t: None)
    cmap = map_rules.load_map() if channel_map_data is USE_DEFAULT_MAP else channel_map_data
    out = Outcome()
    paths = [Path(p) for p in paths]
    total = file_total if file_total is not None else len(paths)
    for idx, path in enumerate(paths):
        this_force = force
        file_index = file_offset + idx + 1

        def report(step: int, frac: float, _fi: int = file_index, _name: str = path.name) -> None:
            if progress is not None:
                progress(prg.make_event(_fi, total, _name, step, frac))

        def finish(_report=report) -> None:  # 失敗・見送りでも、この 1 本は終わったので全体の進みを進める
            _report(prg.STEP_COUNT, 1.0)

        mes_dir = target_mes_dir(path, out_dir, mes_name)
        if not force and confirm_overwrite is not None and mes_dir.exists():
            if not confirm_overwrite(path, mes_dir):
                out.declined.append(path)
                log(f"[SKIP] {path.name}: {mes_dir.name} already exists (not replaced)")
                finish()
                continue
            this_force = True
        choice = dates.choose(path, date, date_label)
        log(f"[INFO] {path.name}: recording date {choice.describe()}")
        try:
            res = cv.convert_one(path, out_dir, mes_name=mes_name, force=this_force, date=choice.date, channel_map_data=cmap, log=log,
                                 before_replace=before_replace, date_label=choice.source,
                                 progress=report if progress is not None else None)
        except MbdError as exc:
            log(f"[ERROR] {path.name}: {exc}")
            out.failed.append((path, str(exc), EXIT_CORRUPT))
            finish()
        except (cv.ConvertError, ge.NegativeCoordinateError, OSError, ValueError) as exc:
            log(f"[ERROR] {path.name}: {exc}")
            out.failed.append((path, str(exc), EXIT_FAIL))
            finish()
        except Exception as exc:  # noqa: BLE001 -- 1 本の想定外の失敗で残りを止めない
            log(f"[ERROR] {path.name}: {exc!r}")
            log(traceback.format_exc())
            out.failed.append((path, repr(exc), EXIT_FAIL))
            finish()
        else:
            out.results.append(res)
    return out


def exit_code_for(outcome: Outcome, n_inputs: int) -> int:
    """CLI の終了コード: 0 = 成功、1 = 変換の失敗（複数本は 1 本でも失敗があれば 1）、4 = MBD として読めない（1 本のとき）。"""
    if outcome.failed:
        return outcome.failed[0][2] if n_inputs == 1 else EXIT_FAIL
    return EXIT_OK


def outcome_text(outcome: Outcome, n_inputs: int) -> str:
    """GUI の完了ダイアログ・ログ用の 1 つの文（件数と、失敗・見送りの内訳）。"""
    lines = [f"Converted {len(outcome.results)} of {n_inputs} file(s)."]
    if outcome.declined:
        lines.append(f"Skipped (existing MES kept): {len(outcome.declined)}")
    if outcome.failed:
        lines.append(f"Failed: {len(outcome.failed)}")
        lines += [f"  - {p.name}: {reason.splitlines()[0] if reason else ''}" for p, reason, _c in outcome.failed[:10]]
    return "\n".join(lines)
