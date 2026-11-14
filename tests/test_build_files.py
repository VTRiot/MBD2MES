# -*- coding: utf-8 -*-
"""exe のビルド一式（spec・bat・版・アイコンの道具）の静的な確かめ。実際の exe の試験は test_exe.py。"""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
from pathlib import Path

import pytest
from conftest import ROOT

SPEC = ROOT / "dist_build" / "mbd2mes.spec"
BAT = ROOT / "dist_build" / "build_exe.bat"
ICO = ROOT / "Pic" / "ICON" / "MBD2MES.ico"
ICON_SIZES = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}  # 親が PNG から作った 7 段（依頼文の値）


def _load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bat_is_ascii_crlf_and_stops_on_missing_icon():
    raw = BAT.read_bytes()
    raw.decode("ascii")
    assert raw.count(b"\r\n") == raw.count(b"\n") and b"\r\n" in raw
    text = raw.decode("ascii")
    assert "if not exist Pic\\ICON\\MBD2MES.ico" in text and "exit /b 1" in text
    for step in ("write_build_info.py", "PyInstaller", "check_exe_version.py", "exe_icon.py"):
        assert step in text


class _Rec:
    def __init__(self, **kw):
        self.kw = kw
        self.pure = self.scripts = self.binaries = self.zipfiles = self.datas = []


def _exec_spec(spec_dir: Path):
    ns = {"SPECPATH": str(spec_dir), "Analysis": lambda *a, **k: _Rec(args=a, **k), "PYZ": lambda *a, **k: _Rec(),
          "EXE": lambda *a, **k: _Rec(args=a, **k)}
    exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), ns)
    return ns


def test_spec_bundles_seeds_and_icon_from_pic_icon():
    ns = _exec_spec(ROOT / "dist_build")
    datas = {Path(src).relative_to(ROOT).as_posix(): dst for src, dst in ns["a"].kw["datas"]}
    gif = datas.pop("Pic/anim/busy.gif", None)  # FB02: 窓の GIF は、置いてあるときだけ同梱（親が採用の 1 本を置いた後は同梱される）
    assert gif in (None, ".") and (gif is not None) == (ROOT / "Pic" / "anim" / "busy.gif").is_file()
    assert datas == {"mbd2mes_config.seed.json": ".", "channel_map.seed.json": ".", "Pic/ICON/MBD2MES.ico": "."}
    assert all((ROOT / p).is_file() for p in datas)
    assert Path(ns["exe"].kw["icon"]) == ICO and ns["exe"].kw["console"] is False
    assert Path(ns["a"].kw["args"][0][0]).name == "mbd2mes_app.py"


def test_spec_stops_when_icon_is_missing(tmp_path):
    fake = tmp_path / "dist_build"
    fake.mkdir()
    with pytest.raises(SystemExit, match="icon not found"):
        _exec_spec(fake)  # tmp_path には Pic\ICON が無い -> 既定のアイコンで黙って作らず止まる
    (tmp_path / "Pic" / "ICON").mkdir(parents=True)
    shutil.copy2(ICO, tmp_path / "Pic" / "ICON" / "MBD2MES.ico")
    _exec_spec(fake)  # あれば通る


def test_dirty_pathspecs_cover_what_goes_into_the_exe():
    wbi = _load_tool("write_build_info")
    specs = set(wbi.DIRTY_PATHSPECS)
    assert {":(glob)*.py", ":(glob)*.seed.json", "mbd2mes", "Pic/ICON/MBD2MES.ico", "dist_build", "tools"} <= specs
    out = wbi.render("abc1234", False, "2026-11-14")
    assert "COMMIT = 'abc1234'" in out and "DIRTY = False" in out and "BUILT = '2026-11-14'" in out


def test_git_calls_in_tools_are_read_only():
    forbidden = {"status", "add", "commit", "push", "pull", "checkout", "reset", "stash", "rebase", "merge", "branch", "rev-parse"}
    allowed = {"log", "diff", "ls-files", "show", "merge-base"}
    for path in (ROOT / "tools").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.List) and node.elts and isinstance(node.elts[0], ast.Constant) and node.elts[0].value == "git":
                words = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                assert not (set(words) & forbidden), (path.name, words)
                if len(words) > 1:  # ["git", *args] は subcommand が実行時に決まる（_git の呼び出し側を下で検査する）
                    assert set(words) & allowed, (path.name, words)
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_git" and node.args and isinstance(node.args[0], ast.List):
                first = node.args[0].elts[0]
                assert isinstance(first, ast.Constant) and first.value in allowed, (path.name, ast.dump(first))


def test_version_string_forms():
    from mbd2mes import version as v

    assert v.format_version(False, None) == "MBD2MES v0.3.0 (dev)"
    assert v.format_version(True, {"commit": "abc1234", "dirty": True, "built": "2026-11-14"}) == "MBD2MES v0.3.0 (abc1234+dirty, built 2026-11-14)"
    assert v.format_version(True, {"commit": "abc1234", "dirty": False, "built": "2026-11-14"}) == "MBD2MES v0.3.0 (abc1234, built 2026-11-14)"
    assert v.format_version(True, None) == "MBD2MES v0.3.0 (unknown, built unknown)"
    assert v.is_well_formed_version(v.APP_VERSION)


# ---------------------------------------------------------------- アイコン
def test_ico_has_the_seven_sizes():
    ei = _load_tool("exe_icon")
    imgs = ei.ico_images(ICO)
    assert {(w, h) for w, h, _b, _s in imgs} == ICON_SIZES and len(imgs) == 7
    assert not (ROOT / "ICON").exists()  # 正本は Pic\ICON のみ。リポ直下に ICON\ を作らない


def test_exe_icon_compare_detects_a_different_icon(tmp_path):
    """道具そのものの確かめ: ICO の中身を変えると不一致になる（exe_icon.compare が「必ず一致」を返す道具でないこと）。"""
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows only")
    ei = _load_tool("exe_icon")
    exe = Path(sys.executable)  # python.exe にもアイコンのリソースがある
    own = ei.exe_icons(exe)
    assert own, "python.exe should carry an icon resource"
    ok, _ = ei.compare(exe, ICO)
    assert ok is False  # python のアイコンは MBD2MES の ICO と違う


PRIVATE_NEEDLES_FILE = ROOT / "tests" / "private_needles.local.txt"  # git に入れない（.gitignore）。1 行に 1 語


def _private_needles() -> list[str]:
    """公開リポに書けない語（提供者の名前・ローカルのユーザー名）は、git に入れないファイルから読む。"""
    if not PRIVATE_NEEDLES_FILE.is_file():
        return []
    lines = PRIVATE_NEEDLES_FILE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def test_no_personal_strings_in_new_files():
    needles = ["\\Us" + "ers\\", "/Us" + "ers/", "Race" + "Data"] + _private_needles()
    files = [p for d in ("mbd2mes", "tools", "dist_build", "tests") for p in (ROOT / d).rglob("*") if p.suffix in (".py", ".bat", ".spec", ".json")]
    files += [ROOT / "mbd2mes_app.py", ROOT / "channel_map.seed.json", ROOT / "mbd2mes_config.seed.json"]
    for p in files:
        if "__pycache__" in p.parts or "_gen" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for n in needles:
            assert n not in text, (p.relative_to(ROOT).as_posix(), n)
    json.loads((ROOT / "channel_map.seed.json").read_text(encoding="utf-8"))


def test_spec_bundles_the_busy_gif_only_when_it_exists(tmp_path):
    """FB02: 窓の端の GIF は、あれば busy.gif として _MEIPASS 直下へ同梱し、無ければ何も足さない（アプリは GIF なしで動く）。"""
    fake = tmp_path / "dist_build"
    fake.mkdir()
    (tmp_path / "Pic" / "ICON").mkdir(parents=True)
    shutil.copy2(ICO, tmp_path / "Pic" / "ICON" / "MBD2MES.ico")
    without = {Path(s).name: d for s, d in _exec_spec(fake)["a"].kw["datas"]}
    assert "busy.gif" not in without and set(without) == {"mbd2mes_config.seed.json", "channel_map.seed.json", "MBD2MES.ico"}
    (tmp_path / "Pic" / "anim").mkdir()
    (tmp_path / "Pic" / "anim" / "busy.gif").write_bytes(b"GIF89a")
    with_gif = {Path(s).name: d for s, d in _exec_spec(fake)["a"].kw["datas"]}
    assert with_gif["busy.gif"] == "." and set(with_gif) == set(without) | {"busy.gif"}
    from mbd2mes import busy_animation

    assert busy_animation.GIF_FROZEN_NAME == "busy.gif" and busy_animation.GIF_RELATIVE_PATH[-1] == "busy.gif"
