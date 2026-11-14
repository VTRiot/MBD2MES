# -*- coding: utf-8 -*-
"""dates.py -- 記録の日付の決め方（FB01 の 4・案 C）。

MBD の中に日付は無い（docs/mbd_format.md §2。FB01 で標本に対して全探索して再確認）。ファイルの更新時刻はダウンロードした日などで、
レースの日とは限らない。そこで、日付は次の順で決める（上が優先）:
  1. 明示の指定: CLI の `--date`・GUI の日付の欄（空 = 自動）。変換する全部の入力に使う
  2. ファイル名から読む（本ファイルの parse_date_from_name）。基準は標本の名前 `26.11.8鈴鹿…`（YY.M.D）
  3. どれも無ければ、ファイルの更新時刻（変換側で決める）。このときは警告を出す（確認の画面・ログ・記録）

ファイル名の型（上から順に当て、日付として成り立つ最初の物。年は 2000〜2099 に限る）:
  - YYYY-MM-DD・YYYY.MM.DD・YYYY/MM/DD・YYYY_MM_DD（月日は 1〜2 桁）
  - YY.M.D・YY-M-D・YY_M_D（年は 2 桁。月日は 1〜2 桁。標本の `26.11.8` が基準）
  - YYYYMMDD（8 桁。MBDA2 の元の名前 `MMDDHHMM` と取り違えないよう、年が 2000〜2099 で月日が成り立つ物だけ）
読めない名前（日付の無い名前・月日が成り立たない名前・MBDA2 の元の名前など）は None を返し、更新時刻へ落とす。
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path

YEAR_MIN, YEAR_MAX = 2000, 2099  # 年として受け入れる範囲（2 桁の年は 20YY として読む）
_SEP = r"[-./_]"
_PATTERNS = (  # (正規表現, 年の桁数)。左は英数字（ASCII）が続かない所から、右は数字が続かない所まで（`FWv26.11.8`・`build2026-11-08` の ID は読まない）
    (re.compile(rf"(?<![0-9A-Za-z])(\d{{4}}){_SEP}(\d{{1,2}}){_SEP}(\d{{1,2}})(?!\d)"), 4),
    (re.compile(rf"(?<![0-9A-Za-z])(\d{{2}}){_SEP}(\d{{1,2}}){_SEP}(\d{{1,2}})(?!\d)"), 2),
    (re.compile(r"(?<![0-9A-Za-z])(\d{4})(\d{2})(\d{2})(?!\d)"), 4),
)

SOURCE_OPTION = "--date"
SOURCE_FIELD = "date field"
SOURCE_NAME = "file name"
SOURCE_MTIME = "file modification time"


@dataclass(frozen=True)
class DateChoice:
    date: datetime.date | None  # None = 更新時刻（変換側が GPS の時刻と合わせて決める）
    source: str
    warning: str | None = None

    def describe(self) -> str:
        """確認の画面・ログ用の 1 つの文。"""
        if self.date is not None:
            return f"{self.date.isoformat()} ({self.source})"
        return f"from the {self.source} -- CHECK: no date in the file name"


def _valid(year: int, month: int, day: int) -> datetime.date | None:
    if not YEAR_MIN <= year <= YEAR_MAX:
        return None
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def parse_date_from_name(name: str) -> datetime.date | None:
    """ファイル名（拡張子つきでよい）から日付を読む。読めなければ None。"""
    stem = Path(name).stem if Path(name).suffix.lower() == ".mbd" else name
    for pattern, year_digits in _PATTERNS:
        for m in pattern.finditer(stem):
            y, mo, d = (int(g) for g in m.groups())
            if year_digits == 2:
                y += 2000
            found = _valid(y, mo, d)
            if found is not None:
                return found
    return None


def mtime_warning(file_name: str) -> str:
    return (f"[WARN] {file_name}: the recording date is not in the MBD file or its name; the file modification time "
            "is used (it may be the day the file was copied, not the race day). Set the Date field, name the file "
            "like 26.11.8..., or pass --date")


def choose(path, override: datetime.date | None = None, label: str = SOURCE_OPTION) -> DateChoice:
    """この入力の記録日の決め方。override（CLI の --date・GUI の欄）があれば最優先。"""
    if override is not None:
        return DateChoice(override, label)
    from_name = parse_date_from_name(Path(path).name)
    if from_name is not None:
        return DateChoice(from_name, SOURCE_NAME)
    return DateChoice(None, SOURCE_MTIME, mtime_warning(Path(path).name))


def parse_date_text(text: str) -> datetime.date | None:
    """日付の欄の文字列（YYYY-MM-DD）。空 = None（自動）。不正なら ValueError。"""
    text = (text or "").strip()
    if not text:
        return None
    return datetime.date.fromisoformat(text)
