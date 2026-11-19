# -*- coding: utf-8 -*-
"""progress.py -- 変換の進み具合の計算。段（step）の名前と重み・全体の %・残りの目安・画面へ渡す出来事。tk は import しない。

アプリ側で決めること:
  - 段の名前の並びと重み。重みは、標本で各段の時間を測った比で決める（推測で決めない）。
    ProgressConfig(step_labels=..., step_weights=...) を 1 つ作ってアプリが持ち、各関数へ渡す。既定値は持たない
    （他のアプリの段を黙って使うと、% が嘘になる）。重みの合計は 1.0 でなければ ProgressConfig が ValueError を出す
  - 変換の関数は、段の境目（と重い段の中）で progress(step, frac) を呼ぶ。step は 1 始まり、frac はその段の中の進み 0..1。
    make_progress_callback がこの形の関数を作る。複数ファイルなら File k/n を含めて全体の % にする

踏んだ地雷:
  - 段の中の進み frac は 0..1 に丸める。範囲外・順序の乱れが来ても、全体の % は 0..100 に収まる
  - 条件で重みが大きく変わる変換（例: 付加処理の有無で時間の大半が別の段になる）は、設定を 2 つ作って場合分けする
    （ProgressConfig は不変。どちらを使うかはアプリが決め、make_event の最初の引数で渡す）
  - バーが戻らない保証は、このモジュールではなく画面（progress_dialog）が持つ（古い通知が遅れて届くため）
"""

from __future__ import annotations

from dataclasses import dataclass

WEIGHT_SUM_EXPECTED = 1.0  # 重みの合計（全体 = 100%）
WEIGHT_SUM_TOLERANCE = 1e-9  # 小数の足し算の誤差の許容（これを超えて外れたら、設定の誤り）
PERCENT_SCALE = 100  # 0..1 を % にする倍率（% の定義）
PERCENT_EPSILON = 1e-9  # int() で 0.29999... が 29 に落ちるのを避ける小さな足し
REMAINING_MIN_ELAPSED_S = 3.0  # 残りの目安を出し始める経過時間（始めのうちは当てにならない）
REMAINING_MIN_FRACTION = 0.03  # 同じく進み
SECONDS_PER_MINUTE = 60  # 時計の定義
SECONDS_PER_HOUR = 3600


@dataclass(frozen=True)
class ProgressConfig:
    """アプリが渡す設定: 段の名前の並びと、各段が全体の何割かの並び（合計 1.0）。"""

    step_labels: tuple[str, ...]
    step_weights: tuple[float, ...]

    def __post_init__(self) -> None:
        labels, weights = tuple(self.step_labels), tuple(self.step_weights)
        object.__setattr__(self, "step_labels", labels)
        object.__setattr__(self, "step_weights", weights)
        if not labels:
            raise ValueError("step_labels must not be empty")
        if len(labels) != len(weights):
            raise ValueError(f"step_labels ({len(labels)}) and step_weights ({len(weights)}) must have the same length")
        if any(w <= 0 for w in weights):
            raise ValueError("every step weight must be positive")
        total = sum(weights)
        if abs(total - WEIGHT_SUM_EXPECTED) > WEIGHT_SUM_TOLERANCE:
            raise ValueError(f"step weights must sum to {WEIGHT_SUM_EXPECTED} (got {total!r})")

    @property
    def step_count(self) -> int:
        return len(self.step_labels)

    def cumulative(self) -> tuple[float, ...]:
        """各段の始まりまでの重みの合計（長さ step_count + 1。最後は 1.0）。"""
        return tuple(sum(self.step_weights[:i]) for i in range(self.step_count + 1))


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def file_fraction(config: ProgressConfig, step: int, frac: float) -> float:
    """1 本の変換の中の進み（0..1）。step は 1 始まり、frac はその段の中の進み。範囲外は丸める。"""
    step = int(_clamp(step, 1, config.step_count))
    frac = _clamp(frac, 0.0, 1.0)
    return config.cumulative()[step - 1] + config.step_weights[step - 1] * frac


def overall(config: ProgressConfig, file_index: int, file_count: int, step: int, frac: float) -> float:
    """全体の進み（0..1）。file_index は 1 始まり（File k/n の k）。"""
    n = max(file_count, 1)
    k = int(_clamp(file_index, 1, n))
    return ((k - 1) + file_fraction(config, step, frac)) / n


@dataclass(frozen=True)
class ProgressEvent:
    """画面へ渡す 1 つの出来事。"""

    file_index: int  # 1 始まり
    file_count: int
    file_name: str
    step: int  # 1..step_count
    step_count: int
    label: str
    step_fraction: float  # その段の中の進み 0..1
    overall: float  # 全体の進み 0..1

    @property
    def percent(self) -> int:
        return int(self.overall * PERCENT_SCALE + PERCENT_EPSILON)

    def step_text(self) -> str:
        return f"Step {self.step}/{self.step_count}: {self.label}"

    def file_text(self) -> str:
        return f"File {self.file_index}/{self.file_count}: {self.file_name}"


def estimate_remaining(elapsed_s: float, overall_fraction: float) -> float | None:
    """残りの目安（秒）。ここまでの進みの速さが続くとみなす（経過時間 / 進み x 残りの進み）。まだ当てにならない間は None。"""
    if elapsed_s < REMAINING_MIN_ELAPSED_S or overall_fraction < REMAINING_MIN_FRACTION or overall_fraction >= 1.0:
        return None
    return elapsed_s / overall_fraction * (1.0 - overall_fraction)


def format_clock(seconds: float) -> str:
    """m:ss（1 時間を超えたら h:mm:ss）。"""
    s = max(int(round(seconds)), 0)
    h, rem = divmod(s, SECONDS_PER_HOUR)
    m, sec = divmod(rem, SECONDS_PER_MINUTE)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def make_event(config: ProgressConfig, file_index: int, file_count: int, file_name: str, step: int, frac: float) -> ProgressEvent:
    step = int(_clamp(step, 1, config.step_count))
    frac = _clamp(frac, 0.0, 1.0)
    return ProgressEvent(file_index, file_count, file_name, step, config.step_count, config.step_labels[step - 1], frac,
                         overall(config, file_index, file_count, step, frac))


def make_progress_callback(config: ProgressConfig, emit, file_index: int, file_count: int, file_name: str):
    """変換の関数へ渡す progress(step, frac) を作る。emit は ProgressEvent を受ける関数（JobRunner の Emitter.progress を渡す）。
    ファイルが替わるたびに作り直す（file_index・file_name が違うため）。"""

    def progress(step: int, frac: float) -> None:
        emit(make_event(config, file_index, file_count, file_name, step, frac))

    return progress
