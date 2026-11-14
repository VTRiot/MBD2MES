# -*- coding: utf-8 -*-
"""tools/exe_icon.py -- exe に埋まったアイコンのリソースを取り出し、ICO の中身と突き合わせる道具（Windows 専用）。

  python -I tools/exe_icon.py <exe> <ico>        # 一致なら 0、違えば 1

exe は `LoadLibraryExW(LOAD_LIBRARY_AS_DATAFILE)` で開く（実行しない）。RT_GROUP_ICON の項目（寸法・bit 数）と、各 RT_ICON の
画像のバイト列を取り、ICO の項目と比べる。比べるのは (幅, 高さ, bit 数, 画像のバイト列の SHA-256) の集合。
"""
from __future__ import annotations

import ctypes
import hashlib
import struct
import sys
from ctypes import wintypes
from pathlib import Path

RT_ICON = 3
RT_GROUP_ICON = 14
LOAD_LIBRARY_AS_DATAFILE = 0x2
ICO_FULL = 256  # ICO の項目で、幅・高さ 0 は 256 を表す（ICO 形式の定義）


def _dim(v: int) -> int:
    return ICO_FULL if v == 0 else v


def ico_images(path: Path) -> list[tuple[int, int, int, str]]:
    """ICO の項目: (幅, 高さ, bit 数, 画像のバイト列の SHA-256) のリスト（並びはファイルのまま）。"""
    data = Path(path).read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or kind != 1:
        raise ValueError(f"not an ICO file: {path}")
    out = []
    for i in range(count):
        w, h, _colors, _res, _planes, bpp, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        out.append((_dim(w), _dim(h), bpp, hashlib.sha256(data[offset:offset + size]).hexdigest()))
    return out


def _setup(k32):
    k32.LoadLibraryExW.restype = wintypes.HMODULE
    k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE, wintypes.DWORD]
    k32.FreeLibrary.argtypes = [wintypes.HMODULE]
    k32.FindResourceW.restype = wintypes.HRSRC
    k32.FindResourceW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p]
    k32.LoadResource.restype = wintypes.HGLOBAL
    k32.LoadResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]
    k32.LockResource.restype = ctypes.c_void_p
    k32.LockResource.argtypes = [wintypes.HGLOBAL]
    k32.SizeofResource.restype = wintypes.DWORD
    k32.SizeofResource.argtypes = [wintypes.HMODULE, wintypes.HRSRC]


def _read(k32, h, name, rtype) -> bytes:
    res = k32.FindResourceW(h, name, rtype)
    if not res:
        raise OSError(f"resource not found: type={rtype} name={name!r}")
    ptr = k32.LockResource(k32.LoadResource(h, res))
    return ctypes.string_at(ptr, k32.SizeofResource(h, res))


def exe_icons(exe: Path) -> list[tuple[int, int, int, str]]:
    """exe の最初の RT_GROUP_ICON が指す画像: (幅, 高さ, bit 数, SHA-256) のリスト。アイコンが無ければ空。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _setup(k32)
    h = k32.LoadLibraryExW(str(exe), None, LOAD_LIBRARY_AS_DATAFILE)
    if not h:
        raise OSError(f"cannot open {exe} (error {ctypes.get_last_error()})")
    try:
        names: list = []
        enum_cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

        def cb(_h, _type, name, _param):
            names.append(name if name is not None and name <= 0xFFFF else ctypes.wstring_at(name))
            return True

        k32.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ctypes.c_void_p, enum_cb, ctypes.c_void_p]
        k32.EnumResourceNamesW(h, RT_GROUP_ICON, enum_cb(cb), None)
        if not names:
            return []
        grp = _read(k32, h, names[0] if isinstance(names[0], int) else names[0], RT_GROUP_ICON)
        _res, _kind, count = struct.unpack_from("<HHH", grp, 0)
        out = []
        for i in range(count):
            w, hh, _c, _r, _planes, bpp, _size, rid = struct.unpack_from("<BBBBHHIH", grp, 6 + 14 * i)
            img = _read(k32, h, rid, RT_ICON)
            out.append((_dim(w), _dim(hh), bpp, hashlib.sha256(img).hexdigest()))
        return out
    finally:
        k32.FreeLibrary(h)


def compare(exe: Path, ico: Path) -> tuple[bool, str]:
    """(一致か, 説明)。段の数・寸法・bit 数・画像のバイト列がすべて同じなら一致。"""
    want, have = ico_images(ico), exe_icons(exe)
    if not have:
        return False, "the exe has no icon resource"
    if sorted(want) == sorted(have):
        return True, f"match: {len(have)} sizes {sorted((w, h) for w, h, _b, _s in have)}"
    return False, f"MISMATCH ico={[(w, h, b) for w, h, b, _s in want]} exe={[(w, h, b) for w, h, b, _s in have]}; " \
                  f"same dims={sorted((w, h) for w, h, _b, _s in want) == sorted((w, h) for w, h, _b, _s in have)}"


def main() -> int:
    ok, text = compare(Path(sys.argv[1]), Path(sys.argv[2]))
    print(("PASS " if ok else "FAIL ") + text)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
