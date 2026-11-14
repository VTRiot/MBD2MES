# -*- coding: utf-8 -*-
"""机の試験（away-gate 経由で流す）: ビルドした exe を起動し、窓が出ること・標題・アイコンが付くことを確かめ、自分が起こしたプロセスを止める。

  python -I tests/gui/exe_window_probe.py <dist\\mbd2mes.exe>      # 窓の確認だけ。pytest の対象ではない（画面に窓が出るため）

- exe は一時フォルダへ別名（mbd2mes_awaygate_probe.exe）で写して起動する。dist\\ に設定を作らない。設定の置き場は一時フォルダ。
- 窓の所有者は、起こしたプロセスと**その子孫**の PID で特定する（他のウィンドウには触れない）。
  onefile の exe は、起動したプロセス（ブートローダ）が一時フォルダへ展開した本体を子プロセスとして起こし、窓は子が持つ
  （FB01 の 5: 最初の版は起動した PID だけを探して「窓なし」と誤判定した。標題が取れなかった原因は子孫を見ていなかったこと）。
- 終わりに、自分の子孫の木を止め、別名のプロセスが 0 本であることを数える。標準入力の無い起動（away-gate の子）でも、
  子プロセスの標準入出力は明示して渡す（FB01 の 5: taskkill の起動が `OSError: [WinError 6]` で落ちた原因）。
- 一時フォルダは、成功・失敗・例外のどれでも最後に消す（消せなければ場所を出力する）。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

PROBE_NAME = "mbd2mes_awaygate_probe.exe"
EXPECT_TITLE_PREFIX = "MBD2MES v"
WAIT_WINDOW_S = 40  # onefile の展開と Tk の初期化の待ち（実測で足りない場合だけ見直す）
POLL_S = 0.5
SETTLE_S = 1.0  # プロセスの終了が一覧に反映されるのを待つ
WM_GETICON = 0x007F
ICON_SMALL, ICON_BIG = 0, 1
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def process_table() -> list[tuple[int, int, str]]:
    """(pid, 親の pid, 実行ファイル名) の一覧（Toolhelp のスナップショット）。"""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap in (None, INVALID_HANDLE_VALUE):
        raise OSError(f"CreateToolhelp32Snapshot failed ({ctypes.get_last_error()})")
    rows = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            rows.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return rows


def descendants(root_pid: int, table: list[tuple[int, int, str]] | None = None) -> set[int]:
    """root_pid 自身とその子孫の pid の集合（親子の線をたどる。親が先に死んで切れた物は拾わない）。"""
    table = process_table() if table is None else table
    found = {root_pid}
    grew = True
    while grew:
        grew = False
        for pid, ppid, _name in table:
            if ppid in found and pid not in found:
                found.add(pid)
                grew = True
    return found


def windows_of(pids: set[int]) -> list[tuple[int, int, str, bool]]:
    """pids が持つ最上位の窓: (hwnd, pid, 標題, 見えているか)。"""
    found = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _lp):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            found.append((hwnd, pid.value, buf.value, bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(enum_proc(cb), 0)
    return found


def count_probe_processes() -> int:
    return sum(1 for _pid, _ppid, name in process_table() if name.lower() == PROBE_NAME)


def run_quiet(cmd: list[str]) -> subprocess.CompletedProcess:
    """標準入出力を全部明示して渡す（away-gate の子など、標準入力が無い起動でも落ちない）。"""
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def main() -> int:
    exe = Path(sys.argv[1]).resolve()
    tmp = Path(tempfile.mkdtemp(prefix="mbd2mes_probe_"))
    ok = False
    proc = None
    try:
        copy = tmp / PROBE_NAME
        shutil.copy2(exe, copy)
        env = dict(os.environ)
        env["MBD2MES_SETTINGS_DIR"] = str(tmp / "settings")
        proc = subprocess.Popen([str(copy)], cwd=str(tmp), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        deadline = time.time() + WAIT_WINDOW_S
        title, owner, big, small = None, None, 0, 0
        while time.time() < deadline and title is None:
            time.sleep(POLL_S)
            pids = descendants(proc.pid)  # 子（展開した本体）が起きるのは少し後なので、毎回取り直す
            for hwnd, pid, text, visible in windows_of(pids):
                if visible and text.startswith(EXPECT_TITLE_PREFIX):
                    title, owner = text, pid
                    big = user32.SendMessageW(hwnd, WM_GETICON, ICON_BIG, 0)
                    small = user32.SendMessageW(hwnd, WM_GETICON, ICON_SMALL, 0)
        print(f"window title: {title!r} (owner pid {'launched process' if owner == proc.pid else 'a descendant' if owner else 'none'})")
        print(f"icon handles: big={'set' if big else 'none'} small={'set' if small else 'none'}")
        ok = title is not None and bool(big) and bool(small)
    finally:
        if proc is not None:
            run_quiet(["taskkill", "/F", "/T", "/PID", str(proc.pid)])
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass
        time.sleep(SETTLE_S)
        left = count_probe_processes()
        print(f"processes left: {left}")
        shutil.rmtree(tmp, ignore_errors=True)
        if tmp.exists():
            print(f"temp folder could not be removed: {tmp}")
        ok = ok and left == 0 and not tmp.exists()
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
