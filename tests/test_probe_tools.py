# -*- coding: utf-8 -*-
"""窓の確認の道具 tests/gui/exe_window_probe.py の、窓を出さずに確かめられる部分（FB01 の 5）。

窓そのものを出す確認は away-gate の行列で流す（この試験は窓を出さない・画面に触れない）。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
import time

import pytest
from conftest import ROOT

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def load_probe():
    spec = importlib.util.spec_from_file_location("exe_window_probe", ROOT / "tests" / "gui" / "exe_window_probe.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def spawn_parent_with_child():
    """親が子を起こし、子の pid を標準出力へ出して待つ。onefile の exe（起動したプロセスの子が本体で窓を持つ）の形を模す。"""
    code = textwrap.dedent("""
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        print(child.pid, flush=True)
        time.sleep(60)
    """)
    parent = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    child_pid = int(parent.stdout.readline())
    return parent, child_pid


def test_descendants_include_the_child_that_owns_the_window():
    probe = load_probe()
    parent, child_pid = spawn_parent_with_child()
    try:
        time.sleep(0.3)
        pids = probe.descendants(parent.pid)
        assert parent.pid in pids and child_pid in pids  # 起動した PID だけを見ると、子が持つ窓を取り逃がす
        assert probe.descendants(child_pid) == {child_pid}
        assert probe.windows_of(pids) == []  # 窓を持たないプロセスでは何も出ない（他の窓に触れない）
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(parent.pid)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        parent.wait(timeout=15)


def test_the_process_table_sees_this_process_and_its_parent_link():
    probe = load_probe()
    import os

    rows = {pid: (ppid, name) for pid, ppid, name in probe.process_table()}
    assert os.getpid() in rows and rows[os.getpid()][0] == os.getppid()


def test_run_quiet_works_without_a_standard_input_handle_where_the_old_call_failed():
    """away-gate の子のように標準入力のハンドルが無いプロセスで、最初の版の subprocess.run(capture_output=True) は
    `OSError: [WinError 6]` で落ちた。run_quiet は標準入出力を明示するので落ちない。"""
    code = textwrap.dedent(f"""
        import ctypes, importlib.util, subprocess, sys
        STD_INPUT_HANDLE = -10
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1)  # 標準入力が無効な状態（away-gate の子の窓の無い起動と同じ）
        ctypes.windll.kernel32.SetStdHandle(STD_INPUT_HANDLE, INVALID_HANDLE_VALUE)
        spec = importlib.util.spec_from_file_location("p", r"{ROOT / 'tests' / 'gui' / 'exe_window_probe.py'}")
        probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
        try:
            subprocess.run(["cmd", "/c", "exit 0"], capture_output=True)
            old = "no error"
        except OSError as exc:
            old = f"OSError winerror={{exc.winerror}}"
        new = probe.run_quiet(["cmd", "/c", "exit 0"]).returncode
        print(old, "|", new)
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "OSError winerror=6 | 0"  # 直す前の呼び方は落ち、直した呼び方は通る


def test_count_probe_processes_is_zero_when_none_is_running():
    probe = load_probe()
    assert probe.count_probe_processes() == 0
