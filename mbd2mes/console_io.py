# -*- coding: utf-8 -*-
"""console_io.py -- windowed exe を引数つき（CLI・D&D）で起動したときのコンソール確保。

RCZ2MES の rcz2mes.py（commit 5b31da8）の `_NullWriter`・`_stream_is_usable`・`ensure_console_for_cli`・
`should_wait_for_enter`・`wait_for_enter` を、このファイルへ切り出して写した（元は LD2MES から。docs/provenance.md）。
中身は無改変（コメントの語だけ MBD2MES に）。

GUI 起動時（引数なし）は本モジュールの関数を一切呼ばないため、windowed exe でコンソール窓が一瞬でも出ることが構造的に無い。
"""

from __future__ import annotations

import sys


class _NullWriter:
    """コンソール確保に失敗した場合のフォールバック（クラッシュより無音を優先）。"""

    def write(self, s: str) -> int:
        return len(s)

    def flush(self) -> None:
        pass


def _stream_is_usable(stream, *, readable: bool = False) -> bool:
    """stream が None でなく、実際に使える（有効なハンドルに繋がっている）か確認する。stdin は readable() で調べる。"""
    if stream is None:
        return False
    try:
        if readable:
            return bool(stream.readable())
        stream.write("")
        return True
    except (OSError, ValueError, AttributeError):
        return False


def ensure_console_for_cli() -> bool:
    """console=False（windowed）でビルドした exe が CLI/D&D（引数あり）で起動されたときに、ログ表示用コンソールを確保する。
    **新しいコンソールを作ったとき True を返す**。

    stdout/stderr/stdin は**個別に** usable 判定し、usable でないものだけを差し替える（リダイレクト・パイプで起動されたときに、
    その出力先を壊さない）。親のコンソールに AttachConsole できたときは、新しいコンソールではないので False。
    Explorer のダブルクリック/D&D（親コンソール無し）では AllocConsole で新しく作るので True
    （終了と同時にコンソールが消えてログが読めなくなるのを、呼び出し側が Enter 待ちで防ぐ）。
    非 frozen 実行（`python -m mbd2mes`）では呼び出し元のコンソールが既に存在するため何もしない。
    """
    if not getattr(sys, "frozen", False):
        return False
    if sys.platform != "win32":
        return False
    stdout_ok = _stream_is_usable(sys.stdout)
    stderr_ok = _stream_is_usable(sys.stderr)
    stdin_ok = _stream_is_usable(sys.stdin, readable=True)
    if stdout_ok and stderr_ok and stdin_ok:
        return False
    created = False
    stdin_attached = False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        ATTACH_PARENT_PROCESS = -1  # Win32 の定数（AttachConsole の引数）
        if not kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
            kernel32.AllocConsole()
            created = True
        if not stdout_ok:
            sys.stdout = open("CONOUT$", "w", errors="replace")
        if not stderr_ok:
            sys.stderr = open("CONOUT$", "w", errors="replace")
        if not stdin_ok:
            sys.stdin = open("CONIN$", "r")
            stdin_attached = True
    except OSError:
        if not stdout_ok:
            sys.stdout = _NullWriter()
        if not stderr_ok:
            sys.stderr = _NullWriter()
    # Enter 待ちは、読む側（stdin）を実際のコンソールへ繋いだときだけ。stdin がパイプのままなら待たない（ハング防止）
    return created and stdin_attached


def should_wait_for_enter(created_new_console: bool) -> bool:
    """終わりに Enter 待ちをするか。新しいコンソールを作ったときだけ。"""
    return bool(created_new_console)


def wait_for_enter(prompt: str = "Press Enter to close...") -> None:
    try:
        input(prompt)
    except (EOFError, OSError, ValueError):
        pass
