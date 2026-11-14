# -*- coding: utf-8 -*-
"""gui.py -- 引数なし起動時の GUI（Convert・Channel Map・Other の 3 タブ）。

RCZ2MES の rcz2mes_gui.py（commit 5b31da8。元は LD2MES の ld2mes_gui.py）から写して直した。改変の要点（docs/provenance.md）:
  - .rcz・RaceChrono・イベントフォルダ候補・一発変換・マニュアル・Output 列・RaceChrono Channel 列を持たない（頼まれていない）。
  - 対応表の表は「MBD Name / MBD Unit / Unit / Custom Name / Multiplier / Offset」。保護する行（Latitude・Longitude・V_GPS）は
    編集・初期化・削除できない。Multiplier / Offset は MBD の換算の後の物理量にかかる（列の見出しの横に書く）。
  - 保存は map_rules.save_map_preserving_others（他プロセスの自動成長が足した行を古いメモリで消さない）。
  - 表の並び・検査・保存の判断は Tk を使わない関数に分けた（試験しやすいように）。Tk の部品は薄い。

実際の変換は app_convert.convert_many -> convert.convert_one() だけを呼ぶ（GUI・D&D・CLI で同一コードパス）。tkinter 標準ライブラリのみ。
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import app_convert as ac
from . import batch
from . import channel_map as cmapmod
from . import config as cfgmod
from . import dates
from . import map_rules
from . import race_env as renv
from . import version

# Windows のプロセスのアプリ ID。これを設定しないと、タスクバーは python.exe のアイコンにまとめる（開発起動）
APP_USER_MODEL_ID = "MBD2MES.Converter"
APP_TITLE = version.APP_NAME
ICON_NAME = "MBD2MES.ico"
ICON_REL_DIR = ("Pic", "ICON")  # 正本の置き場（リポ直下の Pic/ICON/MBD2MES.ico）。frozen では spec が _MEIPASS 直下へ同梱する
SCALING_HINT = "Multiplier / Offset are applied after the MBD conversion (value x Multiplier + Offset)."


def set_app_user_model_id(set_fn=None, app_id: str = APP_USER_MODEL_ID) -> bool:
    """プロセスのアプリ ID を設定する。Tk の窓を作る前に呼ぶ。set_fn は試験用の差し替え口。
    Windows 以外・設定に失敗したときは何もせず False（起動は止めない）。"""
    if set_fn is None:
        if sys.platform != "win32":
            return False
        import ctypes

        set_fn = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    try:
        result = set_fn(app_id)
    except (OSError, AttributeError):
        return False
    return result in (0, None)  # S_OK


def resolve_icon_path() -> Path:
    """アプリアイコン（.ico）の場所。frozen 時は _MEIPASS 配下、開発起動は Pic/ICON/。ファイルの有無は見ない。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / ICON_NAME
    return cfgmod.app_base_dir().joinpath(*ICON_REL_DIR, ICON_NAME)


# ================================================================ Tk を使わない部分（試験する）
def dialog_start_dir(get_dir, cfg: dict) -> str | None:
    """選ぶ画面の始まりのフォルダ（LD2MES の Ld2Mes-016 `_dialog_start_dir` からの写し）。get_dir は config の読み取り関数。

    設定のフォルダが実在して中を開ければ文字列、無い・もう無い・届かない・読めないなら None。None は tkinter が Tk へ送らない
    （渡さないのと同じ）ので、Windows がこのアプリで前に使ったフォルダから始める。Browse と Change は別々の設定から引く
    （Browse = 前に .MBD を選んだフォルダ・Change = 今の出力先）。引数を渡さないと 2 つの画面が Windows の「前に使ったフォルダ」
    の記憶を共有して連動して見える（FB01 の 3）。
    """
    try:
        p = get_dir(cfg)
        if p is None or not os.path.isdir(p):
            return None
        with os.scandir(p):
            pass
        return str(p)
    except (OSError, ValueError):
        return None


def format_scaling(val) -> str:
    """係数表示用。丸めによる精度損失や非有限値での例外を防ぐ。"""
    try:
        f_val = float(val)
        if not math.isfinite(f_val):
            return str(val)
        if f_val.is_integer():
            return f"{f_val:.1f}"
        return str(f_val)
    except (ValueError, TypeError, OverflowError):
        return str(val) if val is not None else ""


def sorted_channel_rows(map_data: dict) -> list[tuple[str, str, str, str, str, str]]:
    """表の行（名前・MBD の単位・単位・任意名・倍率・オフセット）。単位が空欄の行を先頭にする並び順。"""
    rows = []
    for raw_name, entry in map_data.get("channels", {}).items():
        entry = entry if isinstance(entry, dict) else {}
        raw_unit = entry.get("raw_unit") if isinstance(entry.get("raw_unit"), str) else ""
        unit = entry.get("unit") if isinstance(entry.get("unit"), str) else ""
        custom = entry.get("custom_name") if isinstance(entry.get("custom_name"), str) else ""
        rows.append((raw_name, raw_unit, unit, custom, format_scaling(entry.get("multiplier", 1.0)),
                     format_scaling(entry.get("offset", 0.0))))
    rows.sort(key=lambda r: (r[2] != "", r[0]))
    return rows


def row_matches_filter(query: str, raw_name: str, custom_name: str) -> bool:
    """名前・任意名への部分一致（大文字小文字を区別しない）。"""
    q = (query or "").strip().lower()
    if not q:
        return True
    return q in raw_name.lower() or q in (custom_name or "").lower()


def check_edit(raw_name: str, passthrough: bool, unit_text: str, mult_text: str, off_text: str):
    """編集ダイアログの OK の検査。通れば (単位 または None, 倍率, オフセット)。通らなければ ValueError（メッセージは利用者向け）。"""
    m_val, o_val = cmapmod.validate_scaling_factors(raw_name, mult_text.strip(), off_text.strip())
    if (m_val != 1.0 or o_val != 0.0) and passthrough:
        raise ValueError(
            "When specifying linear transformation (Multiplier/Offset), please specify the converted unit explicitly.\n"
            "(Cannot be combined with raw unit passthrough. Enter empty string to explicitly omit unit.)")
    return (None if passthrough else unit_text.strip()), m_val, o_val


def apply_edit(map_data: dict, raw_name: str, unit, custom_name: str, multiplier: float, offset: float) -> list[str]:
    """1 行の編集を表（メモリ）へ入れる。戻り値は、変換時に名前・単位が黙って変わる場合の警告（空 = 問題なし）。"""
    warnings = cmapmod.validate_map_entry(custom_name or None, unit or None)
    cmapmod.update_entry(map_data, raw_name, unit, custom_name or None, multiplier=multiplier, offset=offset)
    return warnings


class ChannelEditDialog(tk.Toplevel):
    """1 行（MBD の名前は固定・単位/任意名/Multiplier/Offset を編集可）のモーダルダイアログ。"""

    def __init__(self, parent: tk.Misc, raw_name: str, unit, custom_name: str, multiplier=1.0, offset=0.0) -> None:
        super().__init__(parent)
        self.raw_name = raw_name
        self.title(f"Edit: {raw_name}")
        self.resizable(False, False)
        self.result: tuple | None = None

        tk.Label(self, text="MBD Name (read-only):").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        tk.Label(self, text=raw_name).grid(row=0, column=1, sticky="w", padx=8, pady=(8, 2))

        tk.Label(self, text="Unit:").grid(row=1, column=0, sticky="w", padx=8, pady=2)
        unit_frame = tk.Frame(self)
        unit_frame.grid(row=1, column=1, sticky="w", padx=8, pady=2)
        self.passthrough_var = tk.BooleanVar(value=(unit is None))
        self.unit_var = tk.StringVar(value="" if unit is None else unit)
        self.unit_entry = tk.Entry(unit_frame, textvariable=self.unit_var, width=16)
        self.unit_entry.pack(side="left")
        tk.Checkbutton(unit_frame, text="Passthrough MBD unit (do not overwrite)", variable=self.passthrough_var,
                       command=self._on_toggle_passthrough).pack(side="left", padx=4)
        if self.passthrough_var.get():
            self.unit_entry.configure(state="disabled")

        tk.Label(self, text="Custom Name (leave empty if none):").grid(row=2, column=0, sticky="w", padx=8, pady=2)
        self.custom_var = tk.StringVar(value=custom_name)
        tk.Entry(self, textvariable=self.custom_var, width=32).grid(row=2, column=1, padx=8, pady=2)

        tk.Label(self, text="Multiplier:").grid(row=3, column=0, sticky="w", padx=8, pady=2)
        self.multiplier_var = tk.StringVar(value=format_scaling(multiplier))
        tk.Entry(self, textvariable=self.multiplier_var, width=16).grid(row=3, column=1, sticky="w", padx=8, pady=2)
        tk.Label(self, text="Offset:").grid(row=4, column=0, sticky="w", padx=8, pady=2)
        self.offset_var = tk.StringVar(value=format_scaling(offset))
        tk.Entry(self, textvariable=self.offset_var, width=16).grid(row=4, column=1, sticky="w", padx=8, pady=2)
        tk.Label(self, text=SCALING_HINT, fg="#555555").grid(row=5, column=0, columnspan=2, sticky="w", padx=8, pady=2)

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=8)
        tk.Button(btn_frame, text="OK", command=self._on_ok, width=10).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Cancel", command=self.destroy, width=10).pack(side="left", padx=4)
        self.transient(parent)
        self.grab_set()

    def _on_toggle_passthrough(self) -> None:
        self.unit_entry.configure(state="disabled" if self.passthrough_var.get() else "normal")

    def _on_ok(self) -> None:
        try:
            unit, m_val, o_val = check_edit(self.raw_name, bool(self.passthrough_var.get()), self.unit_var.get(),
                                            self.multiplier_var.get(), self.offset_var.get())
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        self.result = (unit, self.custom_var.get().strip(), m_val, o_val)
        self.destroy()


class MbdGui:
    """メインウィンドウ。「Convert」「Channel Map」「Other」の 3 タブ構成。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(version.version_string())
        self._apply_window_icon()
        self.selected_files: list[Path] = []
        self.channel_map_data = map_rules.load_map()
        self.deleted_rows: set[str] = set()  # この窓で削除した行（保存のとき、ディスクの行を戻さない）

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self.convert_tab = tk.Frame(notebook)
        self.map_tab = tk.Frame(notebook)
        self.other_tab = tk.Frame(notebook)
        notebook.add(self.convert_tab, text="Convert")
        notebook.add(self.map_tab, text="Channel Map")
        notebook.add(self.other_tab, text="Other")
        self._build_convert_tab()
        self._build_map_tab()
        self._build_other_tab()

    def _apply_window_icon(self) -> bool:
        """タイトルバー・タスクバーにアプリアイコンを適用する（`iconbitmap(default=...)` で、以後作る全トップレベルの既定にする。
        位置引数だけではタスクバーに Tk 既定の羽が残る）。適用できたら True。アイコンが読めなくても起動は続ける（False）。"""
        icon_path = resolve_icon_path()
        if not icon_path.is_file():
            return False
        try:
            self.root.iconbitmap(default=str(icon_path))
        except tk.TclError:
            return False
        return True

    # ------------------------------------------------------------ 変換タブ
    def _build_convert_tab(self) -> None:
        frame = self.convert_tab
        file_frame = tk.LabelFrame(frame, text="MBD Files to Convert")
        file_frame.pack(fill="x", padx=4, pady=4)
        self.file_listbox = tk.Listbox(file_frame, height=5, selectmode="extended")
        self.file_listbox.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        btns = tk.Frame(file_frame)
        btns.pack(side="left", padx=4)
        tk.Button(btns, text="Browse Files...", command=self._on_browse, width=16).pack(pady=2)
        tk.Button(btns, text="Remove Selected", command=self._on_remove_selected, width=16).pack(pady=2)
        tk.Button(btns, text="Clear List", command=self._on_clear_list, width=16).pack(pady=2)

        out_frame = tk.LabelFrame(frame, text="Output Directory")
        out_frame.pack(fill="x", padx=4, pady=4)
        self.output_dir_var = tk.StringVar(value=self._current_output_dir_text())
        tk.Entry(out_frame, textvariable=self.output_dir_var, width=60, state="readonly").pack(
            side="left", fill="x", expand=True, padx=4, pady=4)
        tk.Button(out_frame, text="Change...", command=self._on_change_output_dir, width=10).pack(side="left", padx=4)

        date_frame = tk.LabelFrame(frame, text="Recording Date (HED)")
        date_frame.pack(fill="x", padx=4, pady=4)
        tk.Label(date_frame, text="Date (YYYY-MM-DD). Empty = from the file name (e.g. 26.11.8...), else the file modification time:").pack(
            side="left", padx=4, pady=4)
        self.date_var = tk.StringVar(value="")
        self.date_entry = tk.Entry(date_frame, textvariable=self.date_var, width=12)
        self.date_entry.pack(side="left", padx=4)

        # イベントフォルダの候補（2D の WinRace で今選んでいるもの）。候補が無くても行は残し、Reload で読み直せる
        cand_frame = tk.Frame(frame)
        cand_frame.pack(fill="x", padx=4)
        self.candidate_var = tk.StringVar()
        self._candidate: Path | None = None
        tk.Label(cand_frame, textvariable=self.candidate_var).pack(side="left")
        self.use_candidate_button = tk.Button(cand_frame, text="Use This", command=self._on_use_candidate)
        self.use_candidate_button.pack(side="left", padx=4)
        self.reload_candidate_button = tk.Button(cand_frame, text="Reload", command=self._on_reload_candidate)
        self.reload_candidate_button.pack(side="left", padx=4)
        self._refresh_candidate()

        btn_frame = tk.Frame(frame)
        btn_frame.pack(pady=6)
        tk.Button(btn_frame, text="Convert", command=self._on_convert, bg="#2e7d32", fg="white", width=16).pack(side="left", padx=4)
        self.convert_unconverted_button = tk.Button(btn_frame, text="Convert Unconverted", command=self._on_convert_unconverted,
                                                    bg="#1976d2", fg="white", width=20)
        self.convert_unconverted_button.pack(side="left", padx=4)
        # 実行後・取りやめ後・例外のときも必ずオフに戻す（_on_convert_unconverted の finally）
        self.convert_all_var = tk.BooleanVar(value=False)
        self.convert_all_check = tk.Checkbutton(btn_frame, text="Convert all .MBD files", variable=self.convert_all_var)
        self.convert_all_check.pack(side="left", padx=4)

        log_frame = tk.LabelFrame(frame, text="Log")
        log_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.log_text = tk.Text(log_frame, height=12, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

    def _current_output_dir_text(self) -> str:
        d = cfgmod.get_output_dir(cfgmod.load_or_init_config())
        return str(d) if d else "(Not set)"

    def _on_browse(self) -> None:
        cfg = cfgmod.load_or_init_config()
        paths = filedialog.askopenfilenames(
            title="Select .MBD Files", filetypes=[("MBDA2 log", "*.MBD"), ("All Files", "*.*")],
            initialdir=dialog_start_dir(cfgmod.get_last_mbd_dir, cfg))  # 前に .MBD を選んだフォルダから
        if paths:
            try:
                cfgmod.set_last_mbd_dir(Path(paths[0]).parent)
            except Exception as exc:  # noqa: BLE001
                self._log(f"[WARN] Failed to save last browsed directory: {exc}")
        for p in paths:
            path = Path(p)
            if path not in self.selected_files:
                self.selected_files.append(path)
                self.file_listbox.insert("end", str(path))

    def _on_remove_selected(self) -> None:
        for idx in reversed(self.file_listbox.curselection()):
            self.file_listbox.delete(idx)
            del self.selected_files[idx]

    def _on_clear_list(self) -> None:
        """変換リストを全件クリアする。ディスク上のファイルは一切触らない。"""
        self.selected_files.clear()
        self.file_listbox.delete(0, "end")

    def _on_change_output_dir(self) -> None:
        cfg = cfgmod.load_or_init_config()
        d = filedialog.askdirectory(title="Select Output Directory",
                                    initialdir=dialog_start_dir(cfgmod.get_output_dir, cfg))  # いまの出力先から
        if d:
            self._set_output_dir(Path(d))

    def _set_output_dir(self, d: Path) -> None:
        cfgmod.set_output_dir(d)
        self.output_dir_var.set(str(d))

    # --- 2D のツリーが動いているときの今のイベントフォルダ（RACE.INI。LD2MES の Use This を写した RCZ2MES の形）
    def _refresh_candidate(self) -> str:
        """race_env.detect_output_dir() を呼び直し、候補の表示と Use This の行き先・押せるかを更新する。
        見つからない・想定外の例外のときも落ちず、Not detected と出して Use This を押せなくする。戻り値は表示の理由（ログ用）。
        Output Directory の欄は変えない（Use This か Change... だけが変える）。"""
        try:
            candidate, confidence, reason = renv.detect_output_dir()
        except Exception as exc:  # noqa: BLE001 -- 読み直しの失敗で GUI を落とさない
            candidate, confidence, reason = None, "", f"{exc!r}"
        if candidate is not None:
            self._candidate = Path(candidate)
            self.candidate_var.set(f"Detected candidate (confidence={confidence}): {candidate}")
            self.use_candidate_button.configure(state="normal")
        else:
            self._candidate = None
            self.candidate_var.set(f"Detected candidate: Not detected ({reason})")
            self.use_candidate_button.configure(state="disabled")
        return str(candidate) if candidate is not None else f"not detected ({reason})"

    def _on_reload_candidate(self) -> None:
        self._log(f"[INFO] Event folder candidate: {self._refresh_candidate()}")

    def _on_use_candidate(self) -> None:
        if self._candidate is not None:  # 作ったときの値ではなく、最後に読み直した値を使う
            self._set_output_dir(self._candidate)

    def _read_date_field(self):
        """日付の欄を読む。(日付 または None（自動）, 読めたか)。YYYY-MM-DD でなければ案内を出して読めなかったことにする。"""
        try:
            return dates.parse_date_text(self.date_var.get()), True
        except ValueError:
            messagebox.showwarning(APP_TITLE, "The recording date must be YYYY-MM-DD (for example 2026-11-08), or empty for automatic.")
            return None, False

    def _log(self, msg: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()

    def _on_convert(self) -> None:
        if not self.selected_files:
            messagebox.showwarning(APP_TITLE, "Please select .MBD files to convert.")
            return
        out_dir = cfgmod.get_output_dir(cfgmod.load_or_init_config())
        if out_dir is None:
            messagebox.showwarning(APP_TITLE, "Output directory is not set. Please set it via 'Change...'.")
            return
        date_value, date_ok = self._read_date_field()
        if not date_ok:
            return
        paths = list(self.selected_files)
        # 出力先に同名の MES があれば、一覧を出して上書きの確認（黙って上書きしない）
        existing = [p for p in paths if ac.target_mes_dir(p, out_dir).exists()]
        overwrite_all = False
        if existing:
            shown = [f"  - {ac.target_mes_dir(p, out_dir).name}" for p in existing[:10]]
            if len(existing) > 10:
                shown.append(f"  ... and {len(existing) - 10} more")
            overwrite_all = bool(messagebox.askyesno(
                f"{APP_TITLE} - Overwrite?",
                f"These MES folders already exist in:\n{out_dir}\n\n" + "\n".join(shown)
                + "\n\nOverwrite them?\n(Yes: overwrite. No: skip these files and convert the others.)"))
        try:
            outcome = ac.convert_many(paths, out_dir, log=self._log, channel_map_data=self.channel_map_data,
                                      confirm_overwrite=lambda _p, _d: overwrite_all, date=date_value, date_label=dates.SOURCE_FIELD)
        except Exception as exc:  # noqa: BLE001 -- windowed の exe ではログが唯一の手がかり
            self._log(f"[ERROR] Conversion failed: {exc}")
            self._log(traceback.format_exc())
            messagebox.showerror(APP_TITLE, f"An error occurred during conversion:\n{exc}")
            return
        for res in outcome.results:
            for line in _summary(res):
                self._log(line)
        self._reload_map_tree()
        if outcome.map_save_failed:
            self._log("[WARN] Failed to save some channel map entries. Please re-save using the 'Save' button in the 'Channel Map' tab.")
        messagebox.showinfo(APP_TITLE, ac.outcome_text(outcome, len(paths)))

    def _replace_list(self, paths: list[Path]) -> None:
        self.selected_files.clear()
        self.file_listbox.delete(0, "end")
        for p in paths:
            self.selected_files.append(p)
            self.file_listbox.insert("end", str(p))

    def _on_convert_unconverted(self) -> None:
        """前に選んだ .MBD のフォルダの、未変換の物を一度に変換する（走査 -> 確認の画面 -> 変換。LD2MES の Convert Unconverted と同じ流れ）。"""
        convert_all = bool(self.convert_all_var.get())
        try:
            cfg = cfgmod.load_or_init_config()
            out_dir = cfgmod.get_output_dir(cfg)
            if out_dir is None:
                messagebox.showwarning(APP_TITLE, "Output directory is not set. Please set it via 'Change...'.")
                return
            source_dir = cfgmod.get_last_mbd_dir(cfg)
            if source_dir is None:
                messagebox.showinfo(APP_TITLE, "Source directory is not set or does not exist.\n"
                                    "Please select .MBD file(s) via 'Browse Files...' first.")
                return

            date_value, date_ok = self._read_date_field()
            if not date_ok:
                return
            checkpoint = cfgmod.get_batch_checkpoint(source_dir)
            # 初回（このフォルダの起点が無く、「全部変換」オフ）は、起点だけ記録して変換しない（LD2MES の Convert Unconverted と同じ。
            # 以後は、この時刻より後に届いた・変わった .MBD だけが対象になる。既存の物も変換するなら「全部変換」か Convert を使う）
            if not convert_all and checkpoint is None:
                cfgmod.set_batch_checkpoint(source_dir, time.time_ns(), [])
                self._log(f"[INFO] Baseline checkpoint recorded for {source_dir}. Nothing was converted this time; "
                          "only .MBD files added or modified after now will be converted by this button.")
                messagebox.showinfo(
                    f"{APP_TITLE} - Checkpoint Recorded",
                    "Baseline checkpoint recorded for this directory.\n\n"
                    "Only newer .MBD files added or modified after this will be converted on subsequent runs.\n"
                    "To convert all existing files, check 'Convert all .MBD files' or use the Convert button.")
                return
            # 走査の開始時刻を固定する（確認の画面で待つ間に届いた物は、次回「新しい」になる）
            started_ns = time.time_ns()
            scan = batch.scan_mbd_directory(source_dir, out_dir, convert_all=convert_all, checkpoint=checkpoint,
                                            scan_started_at_ns=started_ns)
            for line in batch.scan_report_lines(scan):
                self._log(line)

            if not scan.to_convert:  # 起点も台帳も書かない
                kept = batch.remaining_after(scan, batch.BatchReport(failed_items=[(i.path, i.reason) for i in scan.unreadable]))
                if kept:
                    self._replace_list(kept)
                messagebox.showinfo(APP_TITLE, batch.nothing_text(scan))
                return

            for line in batch.date_lines(scan, date_value, dates.SOURCE_FIELD):
                self._log(f"[INFO] recording date: {line}")
            if not messagebox.askyesno(f"{APP_TITLE} - Confirm Batch Conversion",
                                       batch.confirm_text(scan, date_value, dates.SOURCE_FIELD)):
                return  # 「No」は何も書かない

            self._log(f"[INFO] Starting batch conversion for {len(scan.to_convert)} file(s)...")

            def progress(idx: int, total: int, path: Path) -> None:
                self._log(f"[{idx + 1}/{total}] Converting: {path.name}...")
                self.root.update_idletasks()

            report = batch.convert_unconverted(scan, log=self._log, progress_cb=progress, channel_map_data=self.channel_map_data,
                                               date=date_value, date_label=dates.SOURCE_FIELD)
            self._reload_map_tree()
            if not report.map_saved:
                self._log("[WARN] Failed to save some channel map entries. Please re-save using the 'Save' button in the 'Channel Map' tab.")
            if report.failed_items:
                self._log("\n[ERROR] Conversion failures:")
                for p, reason in report.failed_items:
                    self._log(f"  - {p.name}: {reason}")
            self._replace_list(batch.remaining_after(scan, report))
            messagebox.showinfo(APP_TITLE, batch.summary_text(report))
        except Exception as exc:  # noqa: BLE001 -- windowed の exe ではログが唯一の手がかり
            print(f"[FATAL EXCEPTION IN GUI] {exc}", file=sys.stderr, flush=True)
            self._log(f"[ERROR] Batch conversion failed: {exc}")
            self._log(traceback.format_exc())
            messagebox.showerror(APP_TITLE, f"An error occurred during batch conversion:\n{exc}")
        finally:
            self.convert_all_var.set(False)

    # ------------------------------------------------------------ 対応表タブ
    def _build_map_tab(self) -> None:
        frame = self.map_tab
        filter_frame = tk.Frame(frame)
        filter_frame.pack(fill="x", padx=4, pady=(4, 2))
        tk.Label(filter_frame, text="Filter:").pack(side="left", padx=(0, 4))
        self.filter_var = tk.StringVar()
        tk.Entry(filter_frame, textvariable=self.filter_var, width=30).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.filter_var.trace_add("write", lambda *_: self._reload_map_tree())
        tk.Button(filter_frame, text="Clear", command=lambda: self.filter_var.set(""), width=8).pack(side="left")
        tk.Label(frame, text=SCALING_HINT, fg="#555555").pack(anchor="w", padx=6)

        columns = ("name", "raw_unit", "unit", "custom_name", "multiplier", "offset")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=18)
        for col, text, width in (("name", "MBD Name", 150), ("raw_unit", "MBD Unit", 80), ("unit", "Unit", 80),
                                 ("custom_name", "Custom Name", 150), ("multiplier", "Multiplier", 80), ("offset", "Offset", 80)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<Double-1>", lambda _e: self._on_edit_row())

        btns = tk.Frame(frame)
        btns.pack(fill="x", padx=4, pady=4)
        tk.Button(btns, text="Edit...", command=self._on_edit_row).pack(side="left", padx=2)
        tk.Button(btns, text="Reset Row to Default", command=self._on_reset_row).pack(side="left", padx=2)
        tk.Button(btns, text="Delete Row", command=self._on_delete_row).pack(side="left", padx=2)
        tk.Button(btns, text="Reset Entire Map", command=self._on_reset_all).pack(side="left", padx=2)
        tk.Button(btns, text="Save", command=self._on_save_map, bg="#2e7d32", fg="white").pack(side="right", padx=2)
        self._reload_map_tree()

    def _reload_map_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for row in sorted_channel_rows(self.channel_map_data):
            if row_matches_filter(self.filter_var.get(), row[0], row[3]):
                self.tree.insert("", "end", iid=row[0], values=row)

    def _refuse_if_protected(self, raw_name: str) -> bool:
        """保護する行（地図に必須の GPS の 3 本）なら案内だけ出して True。"""
        if map_rules.is_protected(raw_name):
            messagebox.showinfo(APP_TITLE, map_rules.FIXED_MESSAGE)
            return True
        return False

    def _selected_name(self) -> str | None:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_edit_row(self) -> None:
        raw_name = self._selected_name()
        if raw_name is None or self._refuse_if_protected(raw_name):
            return
        entry = self.channel_map_data.get("channels", {}).get(raw_name, {})
        entry = entry if isinstance(entry, dict) else {}
        dialog = ChannelEditDialog(self.root, raw_name, entry.get("unit"), entry.get("custom_name") or "",
                                   entry.get("multiplier", 1.0), entry.get("offset", 0.0))
        self.root.wait_window(dialog)
        if dialog.result is None:
            return
        unit, custom_name, mult_val, off_val = dialog.result
        warnings = cmapmod.validate_map_entry(custom_name or None, unit or None)
        if warnings and not messagebox.askyesno(APP_TITLE, "\n".join(warnings) + "\n\nDo you want to save anyway?"):
            return
        apply_edit(self.channel_map_data, raw_name, unit, custom_name, mult_val, off_val)
        self.deleted_rows.discard(raw_name)
        self._reload_map_tree()

    def _on_reset_row(self) -> None:
        raw_name = self._selected_name()
        if raw_name is None or self._refuse_if_protected(raw_name):
            return
        cmapmod.reset_entry(self.channel_map_data, raw_name, self._load_seed())
        self._reload_map_tree()

    def _on_delete_row(self) -> None:
        raw_name = self._selected_name()
        if raw_name is None or self._refuse_if_protected(raw_name):
            return
        seed_data = self._load_seed()
        if raw_name in seed_data.get("channels", {}):
            messagebox.showwarning(APP_TITLE, "Built-in default channels cannot be deleted.\nPlease use 'Reset Row to Default'.")
            return
        if not messagebox.askyesno(
                APP_TITLE,
                f"Delete channel {raw_name!r} from the channel map?\n"
                "If files containing this channel are converted next time, it will be added again as an unmapped channel.\n\n"
                "Do you want to delete?"):
            return
        if cmapmod.delete_entry(self.channel_map_data, raw_name, seed_data):
            self.deleted_rows.add(raw_name)
        self._reload_map_tree()

    def _on_reset_all(self) -> None:
        if not messagebox.askyesno(APP_TITLE, "Reset entire channel map to defaults. Are you sure?"):
            return
        self.channel_map_data = cmapmod.reset_all(self._load_seed(), current_data=self.channel_map_data)
        self._reload_map_tree()

    def _load_seed(self) -> dict:
        seed_path = cmapmod.seed_path()
        if seed_path.exists():
            return json.loads(seed_path.read_text(encoding="utf-8"))
        return {"schema": 1, "channels": {}}

    def _on_save_map(self) -> None:
        map_rules.save_map_preserving_others(self.channel_map_data, self.deleted_rows)
        self.deleted_rows.clear()
        self.channel_map_data = map_rules.load_map()  # ディスクの最新（他プロセスが足した行を含む）を表示へ戻す
        self._reload_map_tree()
        messagebox.showinfo(APP_TITLE, "Channel map saved.")

    # ------------------------------------------------------------ その他タブ
    def _build_other_tab(self) -> None:
        frame = self.other_tab
        info = get_version_info()
        tk.Label(frame, text="Version Information", font=("", 11, "bold")).pack(anchor="w", padx=8, pady=(8, 2))
        tk.Label(frame, text=f"Version: {info['version']}", justify="left").pack(anchor="w", padx=8, pady=2)
        if info["kind"] == "exe":
            text = (f"exe: {info['path']}\nSize: {info['size_bytes']:,} bytes\nsha256: {info['sha256']}\nModified: {info['mtime']}")
        else:
            text = "Running development version (unbuilt)."
        tk.Label(frame, text=text, justify="left").pack(anchor="w", padx=8, pady=2)
        tk.Label(frame, text=f"Settings folder: {cfgmod.config_path().parent}", justify="left").pack(anchor="w", padx=8, pady=2)


def _summary(res) -> list[str]:
    from . import convert as cv

    return cv.summary_lines(res)


def get_version_info() -> dict:
    """「その他」画面のバージョン情報（exe 現物の sha256/サイズ/更新日時と一致させる）。"""
    import hashlib
    from datetime import datetime

    if getattr(sys, "frozen", False):
        target = Path(sys.executable)
        data = target.read_bytes()
        return {"kind": "exe", "version": version.version_string(), "path": str(target), "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "mtime": datetime.fromtimestamp(target.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")}
    return {"kind": "dev", "version": version.version_string(), "path": str(Path(__file__).resolve()),
            "size_bytes": None, "sha256": None, "mtime": None}


def run() -> int:
    # アプリ ID は Tk の窓を作る前に設定する（後だとタスクバーが python.exe のアイコンにまとめることがある）
    set_app_user_model_id()
    root = tk.Tk()
    MbdGui(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
