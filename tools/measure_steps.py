# -*- coding: utf-8 -*-
"""変換の各段の実測時間（FB02）。標本の .MBD（SHA-256 照合済みのコピー）を数回変換し、段ごとの時間と、全体に対する比を出す。

  python -I tools/measure_steps.py <標本の .MBD> [回数 = 3]

出力は progress.STEP_WEIGHTS を決める根拠（重みは、ここで出た比の平均を丸めた物）。一時フォルダへ書き、終わりに消す。
段の時間 = その段の最初の通知から、次の段の最初の通知までの経過。最後の段は、変換が戻るまで。
"""
from __future__ import annotations

import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mbd2mes import convert as cv  # noqa: E402
from mbd2mes import progress as prg  # noqa: E402


def one_run(sample: Path, out_dir: Path) -> tuple[list[float], float, int]:
    first_seen: dict[int, float] = {}
    events = 0

    def cb(step: int, frac: float) -> None:
        nonlocal events
        events += 1
        first_seen.setdefault(step, time.perf_counter())

    t0 = time.perf_counter()
    cv.convert_one(sample, out_dir, force=True, channel_map_data=None, progress=cb)
    t_end = time.perf_counter()
    starts = [first_seen[s] for s in range(1, prg.STEP_COUNT + 1)]
    ends = starts[1:] + [t_end]
    return [e - s for s, e in zip(starts, ends)], t_end - t0, events


def main() -> int:
    sample = Path(sys.argv[1])
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    tmp = Path(tempfile.mkdtemp(prefix="mbd2mes_measure_"))
    try:
        results = [one_run(sample, tmp) for _ in range(runs)]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"sample: {sample.stat().st_size:,} bytes, runs: {runs}")
    print(f"{'step':>4}  {'label':<40} {'median s':>9} {'share':>7} {'weight in progress.py':>22}")
    med = [statistics.median(r[0][i] for r in results) for i in range(prg.STEP_COUNT)]
    total = sum(med)
    for i, m in enumerate(med):
        print(f"{i + 1:>4}  {prg.STEP_LABELS[i]:<40} {m:>9.3f} {m / total:>6.1%} {prg.STEP_WEIGHTS[i]:>22.2f}")
    print(f"total (sum of step medians): {total:.3f} s; whole convert_one (median): {statistics.median(r[1] for r in results):.3f} s; "
          f"progress events per run: {results[0][2]}")
    print("per-run totals:", [round(r[1], 3) for r in results])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
