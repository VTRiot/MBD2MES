# -*- coding: utf-8 -*-
"""progress.py -- 変換の進み具合（FB02。B19 で薄い形に直した）。MBD2MES 固有の部分（段の名前と重み）だけを持つ。

計算・出来事・残りの目安の本体は mbd2mes/converter_progress/progress.py（tk-busy-progress-dialog の写し。docs/provenance.md）。
変換 1 本は 7 段。convert.convert_one は段の境目（と、重い段の中）で progress(step, frac) を呼ぶ（step = 1..7・frac = 段の中の進み 0..1）。
ここは CONFIG（段の名前と重み）を作り、今までの公開名（STEP_LABELS・STEP_COUNT・STEP_WEIGHTS・file_fraction・overall・make_event・
ProgressEvent ほか）を CONFIG に結んで出す。CLI は progress を渡さないので、出力は変わらない。tk は import しない。

重みは、標本（14.6 MB・30 分の周回）で各段の時間を測って決めた（tools/measure_steps.py。実測値は報告書）。合計は 1.0（ProgressConfig が検査する）。
"""

from __future__ import annotations

from functools import partial

from .converter_progress import progress as _cp
from .converter_progress.progress import (  # noqa: F401 -- 今までの公開名
    REMAINING_MIN_ELAPSED_S,
    REMAINING_MIN_FRACTION,
    ProgressConfig,
    ProgressEvent,
    estimate_remaining,
    format_clock,
)

STEP_LABELS = (
    "Reading the MBD file",
    "Converting channel values",
    "Preparing the GPS position",
    "Building channel definitions",
    "Writing channel data files",
    "Writing laps and checking the result",
    "Finishing",
)
# 各段が全体（1 本の変換）の何割か。標本での実測の時間の比（tools/measure_steps.py）。合計は 1.0
STEP_WEIGHTS = (0.70, 0.18, 0.01, 0.01, 0.08, 0.01, 0.01)

CONFIG = ProgressConfig(step_labels=STEP_LABELS, step_weights=STEP_WEIGHTS)
STEP_COUNT = CONFIG.step_count

file_fraction = partial(_cp.file_fraction, CONFIG)  # file_fraction(step, frac): 1 本の変換の中の進み（0..1）
overall = partial(_cp.overall, CONFIG)  # overall(file_index, file_count, step, frac): 全体の進み（0..1）
make_event = partial(_cp.make_event, CONFIG)  # make_event(file_index, file_count, file_name, step, frac)
make_progress_callback = partial(_cp.make_progress_callback, CONFIG)
