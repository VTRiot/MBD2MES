# -*- coding: utf-8 -*-
"""mbd2mes_app.py -- exe（PyInstaller）・`python mbd2mes_app.py` の入口。

引数なし -> GUI（mbd2mes.gui）。引数あり（CLI・.MBD の D&D）-> mbd2mes.__main__.main()。
引数ありのときだけ、windowed exe にコンソールを確保する（新しく作ったときだけ、終わりに Enter 待ち）。
引数なしの GUI 起動はコンソール関連の API を一切呼ばないので、窓の無いコンソールが一瞬でも出ることが構造的に無い。
`python -m mbd2mes` は CLI のまま（引数なしは使い方の誤り）。RCZ2MES の rcz2mes.py の入口と同じ作法。
"""

from __future__ import annotations

import sys
import traceback

EXIT_FAIL = 1
EXIT_OK = 0


def run_cli() -> int:
    from mbd2mes import console_io
    from mbd2mes.__main__ import main

    created = console_io.ensure_console_for_cli()
    code = EXIT_FAIL
    try:
        code = main()
    except SystemExit as exc:  # argparse の使い方の誤りなど。コンソールが消える前に読めるようにする
        code = exc.code if isinstance(exc.code, int) else (EXIT_FAIL if exc.code else EXIT_OK)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        code = EXIT_FAIL
    finally:
        if console_io.should_wait_for_enter(created):
            console_io.wait_for_enter()
    return code


def run() -> int:
    if len(sys.argv) <= 1:
        from mbd2mes import gui

        return gui.run()
    return run_cli()


if __name__ == "__main__":
    raise SystemExit(run())
