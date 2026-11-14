# -*- coding: utf-8 -*-
"""python -m mbd2mes <入力.MBD>... [-o <出力先>] [--name NAME] [--date YYYY-MM-DD] [--force] [--no-map]

-o を省くと、設定（GUI で決めた出力先。mbd2mes_config.json の output_dir）を使う。どちらも無ければ使い方の誤り。
対応表（channel_map.json）は GUI と同じ物を使う。--no-map で表を使わず、対応表が入る前と同じ結果にする。
引数なしは使い方の誤り（GUI は mbd2mes_app.py／exe の引数なし起動だけが開く）。
終了コード: 0 = 成功、1 = 変換の失敗（複数本は 1 本でも失敗があれば 1）、2 = 使い方の誤り、4 = MBD として読めない（1 本のとき）。
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from . import app_convert as ac
from . import config as cfgmod
from . import convert as cv
from .version import version_string

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_CORRUPT = ac.EXIT_OK, ac.EXIT_FAIL, ac.EXIT_USAGE, ac.EXIT_CORRUPT


def _log(text: str) -> None:
    print(text, file=sys.stderr if text.startswith(("[ERROR]", "[FAIL]")) else sys.stdout)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="mbd2mes", description="Convert MBDA2 .MBD logs to 2D Analyzer .MES folders.")
    ap.add_argument("mbd", type=Path, nargs="*", help="input .MBD file(s)")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="output folder (the <name>.MES folder is created inside). Default: output_dir in the config file (set in the GUI)")
    ap.add_argument("--name", default=None, help="MES name (one input only; default: the input file name, sanitized)")
    ap.add_argument("--date", type=datetime.date.fromisoformat, default=None, metavar="YYYY-MM-DD",
                    help="local (+09:00) recording date for HED [DOWNLOAD], used for every input (highest priority). The MBD has "
                         "no date; default: the date in the input file name (e.g. 26.11.8...), else the file modification time (warns)")
    ap.add_argument("--force", action="store_true", help="replace an existing <name>.MES folder")
    ap.add_argument("--no-map", action="store_true", help="do not use the channel map (same result as before the map existed)")
    ap.add_argument("--version", action="store_true", help="print the version and exit")
    ap.add_argument("--version-file", type=Path, default=None, metavar="PATH",
                    help="write the version to a file and exit (for a windowed exe; the build check uses it)")
    args = ap.parse_args(argv)
    if args.version or args.version_file is not None:
        text = version_string()
        if args.version_file is not None:
            args.version_file.write_text(text + "\n", encoding="utf-8")
        if args.version:
            print(text)
        return EXIT_OK
    if not args.mbd:
        ap.error("no input .MBD given")
    if args.name is not None and len(args.mbd) > 1:
        ap.error("--name can be used with one input only")
    out_dir = args.out
    if out_dir is None:
        out_dir = cfgmod.get_output_dir(cfgmod.load_or_init_config())
        if out_dir is None:
            ap.error(f"-o/--out is required (or set the output folder in the GUI; config file: {cfgmod.config_path()})")

    outcome = ac.convert_many(args.mbd, out_dir, mes_name=args.name, force=args.force, date=args.date,
                              channel_map_data=None if args.no_map else ac.USE_DEFAULT_MAP, log=_log)
    for res in outcome.results:
        for line in cv.summary_lines(res):
            print(line)
    if outcome.map_save_failed:
        _log("[WARN] the channel map could not be saved (conversion itself succeeded)")
    return ac.exit_code_for(outcome, len(args.mbd))


if __name__ == "__main__":
    raise SystemExit(main())
