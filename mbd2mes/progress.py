# -*- coding: utf-8 -*-
"""progress.py -- 変換の進み具合（FB02）。段（step）の名前と重み・全体の % の計算・画面へ渡す出来事。

変換 1 本は 7 段に分ける。convert.convert_one は段の境目（と、重い段の中）で progress(step, frac) を呼ぶ（step = 1..7・
frac = その段の中の進み 0..1）。ここは、それを「全体の %」にする（複数のファイルなら File k/n を含める）。
CLI は progress を渡さないので、出力は変わらない。tk は import しない（試験しやすいよう、画面から切り離してある）。

重み STEP_WEIGHTS は、標本（14.6 MB・30 分の周回）で各段の時間を測って決めた（tools/measure_steps.py。実測値は報告書）。
読み取り（1）と値の展開（2）のように重い段は、段の中でも進む（frac が動く）。
"""

from __future__ import annotations

from dataclasses import dataclass

STEP_LABELS = (
    "Reading the MBD file",
    "Converting channel values",
    "Preparing the GPS position",
    "Building channel definitions",
    "Writing channel data files",
    "Writing laps and checking the result",
    "Finishing",
)
STEP_COUNT = len(STEP_LABELS)
# 各段が全体（1 本の変換）の何割か。標本での実測の時間の比（tools/measure_steps.py）。合計は 1.0
STEP_WEIGHTS = (0.70, 0.18, 0.01, 0.01, 0.08, 0.01, 0.01)

_CUMULATIVE = tuple(sum(STEP_WEIGHTS[:i]) for i in range(STEP_COUNT + 1))


def file_fraction(step: int, frac: float) -> float:
    """1 本の変換の中の進み（0..1）。step は 1 始まり、frac はその段の中の進み。"""
    step = min(max(step, 1), STEP_COUNT)
    frac = min(max(frac, 0.0), 1.0)
    return _CUMULATIVE[step - 1] + STEP_WEIGHTS[step - 1] * frac


def overall(file_index: int, file_count: int, step: int, frac: float) -> float:
    """全体の進み（0..1）。file_index は 1 始まり（File k/n の k）。"""
    n = max(file_count, 1)
    k = min(max(file_index, 1), n)
    return ((k - 1) + file_fraction(step, frac)) / n


@dataclass(frozen=True)
class ProgressEvent:
    """画面へ渡す 1 つの出来事。"""

    file_index: int  # 1 始まり
    file_count: int
    file_name: str
    step: int  # 1..STEP_COUNT
    step_count: int
    label: str
    step_fraction: float  # その段の中の進み 0..1
    overall: float  # 全体の進み 0..1

    @property
    def percent(self) -> int:
        return int(self.overall * 100 + 1e-9)

    def step_text(self) -> str:
        return f"Step {self.step}/{self.step_count}: {self.label}"

    def file_text(self) -> str:
        return f"File {self.file_index}/{self.file_count}: {self.file_name}"


def make_event(file_index: int, file_count: int, file_name: str, step: int, frac: float) -> ProgressEvent:
    step = min(max(step, 1), STEP_COUNT)
    frac = min(max(frac, 0.0), 1.0)
    return ProgressEvent(file_index, file_count, file_name, step, STEP_COUNT, STEP_LABELS[step - 1], frac,
                         overall(file_index, file_count, step, frac))
