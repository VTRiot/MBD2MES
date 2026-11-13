# -*- coding: utf-8 -*-
"""python -m mbd2mes <入力.MBD>... -o <出力先> [--name NAME] [--date YYYY-MM-DD] [--force]

終了コード: 0 = 成功、1 = 変換の失敗（複数本は 1 本でも失敗があれば 1）、2 = 使い方の誤り、4 = MBD として読めない（1 本のとき）。
"""

from __future__ import annotations

import argparse
import datetime
import sys
import traceback
from pathlib import Path

from . import convert as cv
from . import gps_entries as ge
from .mbd_reader import MbdError
from .version import version_string

EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_CORRUPT = 0, 1, 2, 4


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
    ap.add_argument("-o", "--out", type=Path, default=None, help="output folder (the <name>.MES folder is created inside)")
    ap.add_argument("--name", default=None, help="MES name (one input only; default: the input file name, sanitized)")
    ap.add_argument("--date", type=datetime.date.fromisoformat, default=None, metavar="YYYY-MM-DD",
                    help="local (+09:00) recording date for HED [DOWNLOAD]. The MBD has no date; "
                         "default: the input file's modification time")
    ap.add_argument("--force", action="store_true", help="replace an existing <name>.MES folder")
    ap.add_argument("--version", action="store_true", help="print the version and exit")
    args = ap.parse_args(argv)
    if args.version:
        print(version_string())
        return EXIT_OK
    if not args.mbd:
        ap.error("no input .MBD given")
    if args.out is None:
        ap.error("-o/--out is required")
    if args.name is not None and len(args.mbd) > 1:
        ap.error("--name can be used with one input only")

    failed: list[tuple[Path, int]] = []
    for path in args.mbd:
        try:
            res = cv.convert_one(path, args.out, mes_name=args.name, force=args.force, date=args.date, log=_log)
        except MbdError as exc:
            _log(f"[ERROR] {path.name}: {exc}")
            failed.append((path, EXIT_CORRUPT))
        except (cv.ConvertError, ge.NegativeCoordinateError, OSError, ValueError) as exc:
            _log(f"[ERROR] {path.name}: {exc}")
            failed.append((path, EXIT_FAIL))
        except Exception as exc:  # noqa: BLE001 -- 1 本の想定外の失敗で残りを止めない
            _log(f"[ERROR] {path.name}: {exc!r}")
            _log(traceback.format_exc())
            failed.append((path, EXIT_FAIL))
        else:
            for line in cv.summary_lines(res):
                print(line)
    if failed:
        return failed[0][1] if len(args.mbd) == 1 else EXIT_FAIL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
