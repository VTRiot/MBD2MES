# -*- coding: utf-8 -*-
"""変換中の画面の反応の実測（FB02）。標本を実際に GUI の経路（別スレッド）で変換し、主ループがどれだけ止まらずに回るかと、
バー・% の進み方を記録する。窓は出さない（親を withdraw。FB03 からはダイアログの表示を見る）。設定は一時フォルダ。

  python -I tools/measure_ui_responsiveness.py <標本の .MBD（SHA-256 照合済みのコピー）>

出力: 変換にかかった時間・主ループの最大の空き（連続する 2 回の after の間隔の最大・99 パーセンタイル）・進み具合の更新回数・
1 秒ごとの % と段。
"""
from __future__ import annotations

import os
import shutil
import statistics
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TICK_MS = 10  # 主ループが回っているかを見る間隔


def main() -> int:
    sample = Path(sys.argv[1])
    tmp = Path(tempfile.mkdtemp(prefix="mbd2mes_ui_"))
    os.environ["MBD2MES_SETTINGS_DIR"] = str(tmp / "settings")
    os.environ["MBD2MES_BUSY_GIF"] = str(tmp / "no.gif")
    from mbd2mes import config as cfgmod
    from mbd2mes import gui

    gui.renv.detect_output_dir = lambda *a, **k: (None, "", "stub")
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(gui.messagebox, name, lambda *a, **k: None)
    gui.messagebox.askyesno = lambda *a, **k: True
    out = tmp / "out"
    out.mkdir()
    root = tk.Tk()
    root.withdraw()
    try:
        app = gui.MbdGui(root)
        cfgmod.set_output_dir(out)
        app.selected_files.append(sample)
        gaps: list[float] = []
        marks: list[tuple[float, str, str]] = []
        last = [time.perf_counter()]
        updates = [0]
        t_start = time.perf_counter()
        next_mark = [1.0]
        real = app._on_progress
        last_seen = [("", "")]  # ダイアログに出ていた最後の % と段（ダイアログは終わると閉じる）

        def spy(ev):
            updates[0] += 1
            real(ev)
            if app._dialog is not None:
                last_seen[0] = (app._dialog.percent_var.get(), app._dialog.step_var.get())

        app._job._on_progress = spy

        def tick():
            now = time.perf_counter()
            gaps.append(now - last[0])
            last[0] = now
            el = now - t_start
            if el >= next_mark[0]:
                marks.append((el, *last_seen[0]))
                next_mark[0] += 1.0
            if app._busy or app._job.running:
                root.after(TICK_MS, tick)

        app._on_convert()
        root.after(TICK_MS, tick)
        app.wait_idle(600)
        total = time.perf_counter() - t_start
        gaps_ms = sorted(g * 1000 for g in gaps)
        print(f"sample: {sample.stat().st_size:,} bytes; conversion through the GUI path: {total:.2f} s")
        print(f"main loop gap while converting (tick every {TICK_MS} ms): median {statistics.median(gaps_ms):.1f} ms, "
              f"p99 {gaps_ms[int(len(gaps_ms) * 0.99) - 1]:.1f} ms, max {gaps_ms[-1]:.1f} ms over {len(gaps_ms)} ticks")
        print(f"progress updates delivered to the dialog: {updates[0]}; last shown in the dialog: {last_seen[0][0]} / {last_seen[0][1]}")
        print("per second (elapsed s, percent, step):")
        for el, pct, step in marks:
            print(f"  {el:5.1f}  {pct:>4}  {step}")
        print("output MES created:", sorted(p.name for p in out.glob("*.MES")))
    finally:
        root.destroy()
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
