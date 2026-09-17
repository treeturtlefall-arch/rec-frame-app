"""どんな画像サイズでも対応できる透過素材貼り付けソフト (REC枠)

参考画像: 四隅の黒いL字枠 + 左上電池マーク + 右上赤丸REC

使い方:
    python rec_frame_app.py
    1. [画像を開く] で任意サイズの画像を選択
    2. プレビュー確認
    3. [保存] で枠+REC合成画像を保存

仕組み:
    - 透過PNGを拡大縮小して貼るのではなく、画像サイズに合わせて
      ベクター的にオーバーレイを生成するため、どんな解像度でも劣化なし。
    - 画像生成の実体は `rec_overlay.py`、設定は `rec_config.py`。
      このモジュールは GUI 薄層 + エントリーポイント。
"""
import os
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

from rec_config import (
    CUSTOM_FONT_EXTENSIONS,
    DEFAULT_EFFECT,
    DEFAULT_FONT,
    DEFAULT_THICKNESS,
    EFFECT_CHOICES,
    FONT_CHOICES,
    SUPPORTED_EXTENSIONS,
    THICKNESS_CHOICES,
    OverlayConfig,
    compose_timecode_text,
    get_font_browse_start_dir,
    get_user_fonts_dir,
    is_simple_equivalent,
    load_user_config,
    parse_timecode_text,
    sanitize_custom_font_name,
    save_user_config,
    validate_custom_font_file,
)
from rec_overlay import (
    _load_font,  # 後方互換のための再エクスポート
    composite_with_config,
    composite_with_overlay,
    create_rec_overlay,  # 後方互換のための再エクスポート
    format_photo_timecode,
    load_base_image,
    resolve_photo_config,
    save_composited_image,
)
from rec_i18n import (
    LANGUAGE_NAMES,
    builtin_font_label,
    effect_label,
    normalize_language,
    thickness_label,
    tr,
)

__all__ = [
    "FONT_CHOICES",
    "DEFAULT_FONT",
    "OverlayConfig",
    "create_rec_overlay",
    "composite_with_overlay",
    "App",
]


def default_timecode_text(now: datetime | None = None) -> str:
    """手入力欄の初期値。1行12時間制 `YYYY/MM/DD PM HH:MM` (SPEC §3.5)。"""
    return format_photo_timecode(now or datetime.now())


BG, INK, MUTED, ACCENT = "#f3f1ed", "#242d32", "#687476", "#236b60"
PREVIEW_BG = "#20282b"


class ScrollPage(ttk.Frame):
    """設定タブ内だけをスクロールし、キーボードフォーカスを自動表示する。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self, bg=BG, highlightthickness=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.bar = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview)
        self.bar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.content = ttk.Frame(self.canvas, padding=10)
        self.item = self.canvas.create_window(
            0, 0, anchor="nw", window=self.content)
        self.content.bind("<Configure>", self._size)
        self.canvas.bind("<Configure>", self._size)

    def _size(self, _event=None):
        width = self.canvas.winfo_width()
        height = self.content.winfo_reqheight()
        self.canvas.itemconfigure(self.item, width=width)
        self.canvas.configure(scrollregion=(0, 0, width, height))
        if height <= self.canvas.winfo_height():
            self.bar.grid_remove()
            self.canvas.yview_moveto(0)
        else:
            self.bar.grid()

    def bind_controls(self):
        def visit(widget):
            # bind_all は使わず、コンボとSpinboxのホイール動作も奪わない。
            if not isinstance(widget, (ttk.Combobox, tk.Spinbox)):
                widget.bind("<MouseWheel>", self._wheel, add="+")
                widget.bind("<Button-4>", self._wheel, add="+")
                widget.bind("<Button-5>", self._wheel, add="+")
            widget.bind("<FocusIn>", self._reveal, add="+")
            for child in widget.winfo_children():
                visit(child)

        visit(self.content)
        self.canvas.bind("<MouseWheel>", self._wheel)

    def _wheel(self, event):
        if self.content.winfo_reqheight() > self.canvas.winfo_height():
            up = getattr(event, "num", None) == 4 or event.delta > 0
            self.canvas.yview_scroll((-2 if up else 2), "units")
        return "break"

    def _reveal(self, event):
        widget = event.widget
        # 祖先にも届くFocusInでは動かさず、実際のフォーカス先だけを表示する。
        if widget is not widget.focus_get():
            return
        top = widget.winfo_rooty() - self.canvas.winfo_rooty()
        bottom = top + widget.winfo_height()
        visible = self.canvas.winfo_height()
        offset = top - 6 if top < 0 else bottom - visible + 6 if bottom > visible else 0
        if offset:
            current = self.canvas.canvasy(0)
            self.canvas.yview_moveto(
                (current + offset) / max(1, self.content.winfo_height()))


def work_area(root: tk.Tk) -> tuple[int, int, int, int]:
    """Windowsではタスクバーを除く作業領域、他OSでは画面全体を返す。"""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(
                    48, 0, ctypes.byref(rect), 0):
                return (rect.left, rect.top,
                        rect.right - rect.left, rect.bottom - rect.top)
        except (AttributeError, OSError):
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class App(tk.Tk):
    def __init__(self, language_override: str | None = None):
        super().__init__()
        self.title("REC FRAME")
        left, top, width, height = work_area(self)
        window_w, window_h = min(1160, width - 24), min(700, height - 64)
        window_w, window_h = max(1, window_w), max(1, window_h)
        self.geometry(
            f"{window_w}x{window_h}+{left + 12}+{top + 12}")
        self.minsize(min(960, window_w), min(600, window_h))
        self.configure(bg=BG)
        self.src_image = None
        self.result_image = None
        self.src_path = None
        self.photo = None  # GC防止用
        self._resize_job = None
        self._timecode_edit_job = None

        # 設定の自動記憶(UI追加なし)。欠落・破損時は既定値。mode自体は保存対象外。
        self._loading_settings = True
        loaded = load_user_config()
        self.custom_fonts: dict[str, str] = dict(loaded.custom_fonts)
        self._configure_styles()
        self._initialize_variables(loaded, language_override)
        self._localized_widgets: list[tuple[tk.Widget, str]] = []
        self._detail_checks: list = []
        self._timecode_sel_widgets: list = []
        self._build_redesigned_layout()
        self.timecode_text_var.trace_add("write", self._on_timecode_edit)
        self.bind("<Configure>", self._on_window_resize)
        self.bind("<Control-o>", lambda _event: self.open_image())
        self.bind("<Control-s>", lambda _event: self.save_image())
        # 起動時復元をUI状態に反映。以降の変更は _save_settings で自動保存。
        self._loading_settings = False
        self._on_mode_change()

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Yu Gothic UI", 10),
                        background=BG, foreground=INK)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Yu Gothic UI", 15, "bold"))
        style.configure("Section.TLabel", font=("Yu Gothic UI", 11, "bold"))
        style.configure("TButton", padding=(12, 6), relief="flat",
                        background="#e4e7e2")
        style.map("TButton", background=[("active", "#d6ded8")],
                  bordercolor=[("focus", ACCENT)])
        style.configure("Accent.TButton", background=ACCENT, foreground="white")
        style.map(
            "Accent.TButton",
            background=[("disabled", "#d9dfdb"), ("active", "#1b564c")],
            foreground=[("disabled", "#56635b")],
            bordercolor=[("focus", "#122f2a")])
        style.configure("TRadiobutton", padding=(5, 6))
        style.configure("TCheckbutton", padding=(3, 2))
        style.configure("TNotebook", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(12, 7))
        style.map(
            "TNotebook.Tab",
            padding=[("selected", (12, 7)), ("!selected", (12, 7))],
            expand=[("selected", (0, 0, 0, 0)),
                    ("!selected", (0, 0, 0, 0))],
            background=[("selected", "white")],
            foreground=[("selected", ACCENT)])
        style.configure("TCombobox", padding=5)
        style.map("TEntry", foreground=[("disabled", MUTED)])
        style.map("TCombobox", foreground=[("disabled", MUTED)])

    def _initialize_variables(
        self, loaded: OverlayConfig, language_override: str | None = None
    ):
        initial_font = (loaded.font_key if loaded.font_key in self._font_choice_values()
                        else DEFAULT_FONT)
        values = {
            "color": loaded.color,
            "font": initial_font,
            "thickness": loaded.thickness,
            "effect": loaded.effect,
            "mode": "simple" if is_simple_equivalent(loaded) else "detail",
            "timecode_text": loaded.timecode_text or default_timecode_text(),
            "language": normalize_language(language_override or loaded.ui_language),
        }
        for name, value in values.items():
            setattr(self, f"{name}_var", tk.StringVar(self, value))
        for name in ("show_frame", "show_battery", "show_rec",
                     "show_cross", "show_timecode"):
            setattr(self, f"{name}_var",
                    tk.BooleanVar(self, getattr(loaded, name)))
        self.use_exif_var = tk.BooleanVar(self, loaded.timecode_from_exif)
        self._effect_label_to_key = dict(EFFECT_CHOICES)
        self._thickness_label_to_key = dict(THICKNESS_CHOICES)
        self._thickness_key_to_label = {
            key: label for label, key in THICKNESS_CHOICES.items()}
        self.language_display_var = tk.StringVar(
            self, LANGUAGE_NAMES[self.language_var.get()])
        self.font_display_var = tk.StringVar(self)
        self.effect_display_var = tk.StringVar(self)

    def _language(self) -> str:
        return normalize_language(self.language_var.get())

    def _tr(self, key: str, **values) -> str:
        return tr(self._language(), key, **values)

    def _remember_text(self, widget, key: str):
        self._localized_widgets.append((widget, key))
        widget.configure(text=self._tr(key))
        return widget

    def _label(self, parent, key, style="TLabel", **kwargs):
        widget = ttk.Label(parent, style=style, **kwargs)
        self._remember_text(widget, key)
        widget.pack(anchor="w", pady=(0, 5))
        return widget

    def _section(self, parent, key):
        ttk.Separator(parent).pack(fill="x", pady=(7, 5))
        self._label(parent, key, "Section.TLabel")

    def _choices(self, parent, variable, values, command=None):
        row = ttk.Frame(parent)
        row.pack(fill="x")
        for key, value in values:
            widget = ttk.Radiobutton(
                row, variable=variable, value=value,
                command=command or self._refresh)
            self._remember_text(widget, key)
            widget.pack(side="left", padx=(0, 10))

    def _button(self, parent, key, **kwargs):
        widget = ttk.Button(parent, **kwargs)
        self._remember_text(widget, key)
        return widget

    def _build_redesigned_layout(self):
        header = ttk.Frame(self, padding=(16, 8))
        header.pack(fill="x")
        brand = ttk.Frame(header)
        brand.pack(side="left")
        self._label(brand, "REC FRAME", "Title.TLabel")
        self.save_button = self._button(
            header, "action.save", style="Accent.TButton",
            command=self.save_image, state="disabled")
        self.save_button.pack(side="right", padx=(10, 0))
        self._button(header, "action.open", command=self.open_image).pack(
            side="right")
        self.language_box = ttk.Combobox(
            header, textvariable=self.language_display_var,
            values=list(LANGUAGE_NAMES.values()), state="readonly", width=9)
        self.language_box.pack(side="right", padx=(0, 10))
        self.language_box.bind(
            "<<ComboboxSelected>>", self._on_language_selected)
        self.language_label = self._label(header, "language.label")
        self.language_label.pack_forget()
        self.language_label.pack(side="right", padx=(0, 5), pady=0)
        ttk.Separator(self).pack(fill="x")

        body = ttk.Frame(self, padding=(12, 10, 12, 6))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        text_width = tkfont.Font(
            family="Yu Gothic UI", size=10).measure(
                "現在のモード・設定を全画像に適用")
        sidebar_width = max(294, text_width + 48)
        sidebar = ttk.Frame(body, width=sidebar_width)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(1, weight=1)

        mode = ttk.Frame(sidebar)
        mode.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._label(mode, "settings.title", "Section.TLabel")
        self._choices(mode, self.mode_var,
                      [("mode.simple", "simple"), ("mode.detail", "detail")],
                      self._on_mode_change)
        self.mode_hint = self._label(
            mode, "", "Muted.TLabel", wraplength=sidebar_width - 8)

        self.tabs = ttk.Notebook(sidebar)
        self.tabs.grid(row=1, column=0, sticky="nsew")
        self.style_page = ScrollPage(self.tabs)
        self.detail_page = ScrollPage(self.tabs)
        self.tabs.add(self.style_page, text=self._tr("tab.style"))
        self.tabs.add(self.detail_page, text=self._tr("tab.detail"))
        self.tabs.enable_traversal()
        self.tabs.bind("<<NotebookTabChanged>>", self._tab_labels)

        page = self.style_page.content
        self._label(page, "style.color", "Section.TLabel")
        self._choices(page, self.color_var,
                      [("color.black", "black"), ("color.white", "white")])
        self._label(page, "style.color_hint", "Muted.TLabel", wraplength=250)
        self._section(page, "style.thickness")
        self._choices(page, self.thickness_var,
                      [(f"thickness.{key}", key)
                       for key in ("small", "medium", "large")])
        self._label(page, "style.thickness_hint", "Muted.TLabel", wraplength=250)
        self._section(page, "style.font")
        self.font_box = ttk.Combobox(
            page, textvariable=self.font_display_var,
            state="readonly", width=24)
        self.font_box.pack(fill="x", pady=(0, 8))
        self.font_box.bind("<<ComboboxSelected>>", lambda _event: self._refresh())
        font_row = ttk.Frame(page)
        font_row.pack(fill="x")
        self._button(font_row, "action.font_add",
                     command=self._on_add_custom_font).pack(side="left")
        self._button(font_row, "action.font_remove",
                     command=self._on_remove_custom_font).pack(
                         side="left", padx=6)
        self._section(page, "style.effect")
        self.effect_box = ttk.Combobox(
            page, textvariable=self.effect_display_var,
            state="readonly")
        self.effect_box.pack(fill="x")
        self.effect_box.bind("<<ComboboxSelected>>", self._on_effect_selected)

        self._build_redesigned_details()
        self.style_page.bind_controls()
        self.detail_page.bind_controls()

        batch = ttk.Frame(sidebar, padding=(0, 8, 0, 0))
        batch.grid(row=2, column=0, sticky="ew")
        self._button(batch, "action.batch", command=self.batch_images).pack(
            fill="x")
        self._label(batch, "batch.hint", "Muted.TLabel", wraplength=280)

        preview = ttk.Frame(body)
        preview.grid(row=0, column=1, sticky="nsew")
        self._label(preview, "preview.title", "Section.TLabel")
        self.stage = tk.Frame(preview, bg=PREVIEW_BG)
        self.stage.pack(fill="both", expand=True, pady=(2, 6))
        self.stage.pack_propagate(False)
        self.canvas_label = tk.Label(self.stage, bg=PREVIEW_BG, bd=0)
        self.canvas_label.pack(fill="both", expand=True, padx=6, pady=6)
        self.empty = tk.Frame(self.stage, bg=PREVIEW_BG)
        self.empty.place(relx=.5, rely=.5, anchor="center")
        empty_lines = [
            ("[  REC  ]", 26, "#d5dedb"),
            ("preview.empty_title", 13, "#f4f3ef"),
            ("preview.empty_steps", 10, "#9daead"),
        ]
        for key, size, color in empty_lines:
            widget = tk.Label(self.empty, font=("Yu Gothic UI", size),
                              bg=PREVIEW_BG, fg=color)
            self._remember_text(widget, key)
            widget.pack(pady=10)
        self._button(
            self.empty, "action.open", style="Accent.TButton",
            command=self.open_image).pack(pady=(14, 8))
        self._button(self.empty, "action.sample", command=self.open_sample).pack(
            pady=(0, 10))
        self.info = self._label(
            preview, "preview.empty_info",
            "Muted.TLabel")
        self.info.configure(wraplength=500)
        preview.bind(
            "<Configure>",
            lambda event: self.info.configure(wraplength=max(100, event.width - 8)))

    def _build_redesigned_details(self):
        page = self.detail_page.content
        self._label(page, "detail.elements", "Section.TLabel")
        row = ttk.Frame(page)
        row.pack(fill="x")
        self.element_row = row
        self._element_checks = []
        elements = [("element.frame", "show_frame"),
                    ("element.battery", "show_battery"),
                    ("element.rec", "show_rec"),
                    ("element.cross", "show_cross")]
        for index, (key, name) in enumerate(elements):
            widget = ttk.Checkbutton(
                row, variable=getattr(self, f"{name}_var"),
                command=self._refresh)
            self._remember_text(widget, key)
            widget.grid(row=index // 2, column=index % 2, sticky="w")
            self._detail_checks.append(widget)
            self._element_checks.append(widget)
        row.bind("<Configure>", self._layout_element_checks, add="+")

        self._section(page, "detail.time")
        self.timecode_check = ttk.Checkbutton(
            page, variable=self.show_timecode_var,
            command=self._refresh)
        self._remember_text(self.timecode_check, "time.show")
        self.timecode_check.pack(anchor="w")
        self.exif_check = ttk.Checkbutton(
            page, variable=self.use_exif_var,
            command=self._on_exif_toggle)
        self._remember_text(self.exif_check, "time.use_photo")
        self.exif_check.pack(anchor="w")
        self._detail_checks += [self.timecode_check, self.exif_check]
        self._label(
            page, "time.photo_hint",
            "Muted.TLabel", wraplength=250)
        self.time_hint = ttk.Label(page, style="Muted.TLabel")
        self.time_hint.configure(wraplength=250)
        self.time_hint.pack(anchor="w", pady=(0, 5))
        self.timecode_entry = ttk.Entry(
            page, textvariable=self.timecode_text_var)
        self.timecode_entry.pack(fill="x", pady=(8, 12))

        self._label(page, "time.select", "Section.TLabel")
        date_row = ttk.Frame(page)
        date_row.pack(fill="x", pady=(0, 8))
        self.tc_year_spin = tk.Spinbox(
            date_row, from_=1, to=9999, width=5,
            command=self._on_timecode_select)
        self.tc_year_spin.pack(side="left")
        self.tc_year_spin.bind("<FocusOut>", self._on_timecode_select)
        self.tc_year_spin.bind("<Return>", self._on_timecode_select)
        self._timecode_sel_widgets.append(self.tc_year_spin)
        year_label = ttk.Label(date_row)
        self._remember_text(year_label, "time.year")
        year_label.pack(side="left")

        def choice(parent, values, suffix_key):
            box = ttk.Combobox(
                parent, values=values, width=3, state="readonly")
            box.pack(side="left")
            box.bind("<<ComboboxSelected>>", self._on_timecode_select)
            suffix = ttk.Label(parent)
            self._remember_text(suffix, suffix_key)
            suffix.pack(side="left")
            self._timecode_sel_widgets.append(box)
            return box

        self.tc_month_box = choice(
            date_row, [f"{i:02}" for i in range(1, 13)], "time.month")
        self.tc_day_box = choice(
            date_row, [f"{i:02}" for i in range(1, 32)], "time.day")
        time_row = ttk.Frame(page)
        time_row.pack(fill="x")
        self.tc_ampm_box = choice(time_row, ["AM", "PM"], " ")
        self.tc_hour_box = choice(
            time_row, [f"{i:02}" for i in range(1, 13)], "time.hour")
        self.tc_min_box = choice(
            time_row, [f"{i:02}" for i in range(60)], "time.minute")
        self._sync_timecode_selector(self.timecode_text_var.get())
        self._refresh_font_choices()
        self._refresh_effect_choices()

    def _layout_element_checks(self, _event=None):
        """翻訳・DPIで2列が収まらない場合は1列へ切り替える。"""
        if not getattr(self, "_element_checks", None):
            return
        available = max(1, self.element_row.winfo_width())
        col0 = max(widget.winfo_reqwidth() for widget in self._element_checks[::2])
        col1 = max(widget.winfo_reqwidth() for widget in self._element_checks[1::2])
        two_columns = col0 + col1 + 22 <= available
        for index, widget in enumerate(self._element_checks):
            widget.grid_configure(
                row=(index // 2 if two_columns else index),
                column=(index % 2 if two_columns else 0),
                padx=((0, 22) if two_columns and index % 2 == 0 else 0))

    def _build_toolbar(self):
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=8)
        tk.Button(btn_frame, text="画像を開く", width=14,
                  command=self.open_image).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_frame, text="保存", width=14,
                  command=self.save_image).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_frame, text="一括処理...", width=14,
                  command=self.batch_images).pack(side=tk.LEFT, padx=6)

    def _font_choice_values(self) -> list[str]:
        values = list(FONT_CHOICES)
        for name in self.custom_fonts:
            if name not in FONT_CHOICES and name not in values:
                values.append(name)
        return values

    def _font_display_pairs(self) -> list[tuple[str, str]]:
        """Comboboxの表示名と保存済みfont_keyの対応。"""
        pairs: list[tuple[str, str]] = []
        used: set[str] = set()
        for key in FONT_CHOICES:
            display = builtin_font_label(key, self._language())
            pairs.append((display, key))
            used.add(display)
        for key in self.custom_fonts:
            display = key
            if display in used:
                marker = self._tr("font.custom_marker")
                display = f"{key} [{marker}]"
                index = 2
                while display in used:
                    display = f"{key} [{marker} {index}]"
                    index += 1
            pairs.append((display, key))
            used.add(display)
        return pairs

    def _on_font_selected(self, _event=None):
        key = self._font_display_to_key.get(self.font_display_var.get())
        if key is not None:
            self.font_var.set(key)
            self._refresh()

    def _refresh_effect_choices(self) -> None:
        if not hasattr(self, "effect_box"):
            return
        pairs = [(effect_label(key, self._language()), key)
                 for key in ("off", "oled", "2000s")]
        self._effect_display_to_key = dict(pairs)
        self._effect_key_to_display = {key: display for display, key in pairs}
        self.effect_box.configure(values=[display for display, _key in pairs])
        key = self.effect_var.get()
        if key not in self._effect_key_to_display:
            key = self._effect_label_to_key.get(key, DEFAULT_EFFECT)
            self.effect_var.set(key)
        self.effect_display_var.set(self._effect_key_to_display[key])

    def _on_effect_selected(self, _event=None):
        key = self._effect_display_to_key.get(self.effect_display_var.get())
        if key is not None:
            self.effect_var.set(key)
            self._refresh()

    def _on_language_selected(self, _event=None):
        by_name = {name: key for key, name in LANGUAGE_NAMES.items()}
        language = by_name.get(self.language_display_var.get())
        if language is None or language == self._language():
            return
        self.language_var.set(language)
        self._apply_language()
        self._save_settings()

    def _apply_language(self) -> None:
        """現在の状態を壊さず、表示文字だけを選択言語へ切り替える。"""
        self.language_display_var.set(LANGUAGE_NAMES[self._language()])
        for widget, key in self._localized_widgets:
            try:
                widget.configure(text=self._tr(key))
            except tk.TclError:
                pass
        self._refresh_font_choices()
        self._refresh_effect_choices()
        self._tab_labels()
        self.mode_hint.configure(
            text=self._tr("mode.detail_hint" if self.mode_var.get() == "detail"
                          else "mode.simple_hint"))
        self.time_hint.configure(
            text=self._tr("time.auto_hint" if self.use_exif_var.get()
                          else "time.manual_hint"))
        if self.result_image is not None and self.photo is not None:
            self._update_preview_info(self.result_image)
        else:
            self.info.configure(text=self._tr("preview.empty_info"))
        self.update_idletasks()
        self._layout_element_checks()
        self.style_page._size()
        self.detail_page._size()

    def _build_color_font_bar(self, loaded: OverlayConfig):
        color_frame = tk.Frame(self)
        color_frame.pack(pady=2)
        tk.Label(color_frame, text="枠の色:").pack(side=tk.LEFT)
        self.color_var = tk.StringVar(value=loaded.color)
        tk.Radiobutton(color_frame, text="黒", value="black",
                       variable=self.color_var,
                       command=self._refresh).pack(side=tk.LEFT, padx=4)
        tk.Radiobutton(color_frame, text="白", value="white",
                       variable=self.color_var,
                       command=self._refresh).pack(side=tk.LEFT, padx=4)
        tk.Label(color_frame, text="  RECフォント:").pack(side=tk.LEFT)
        initial_font = (loaded.font_key if loaded.font_key in self._font_choice_values()
                        else DEFAULT_FONT)
        self.font_var = tk.StringVar(value=initial_font)
        self.font_box = ttk.Combobox(color_frame, textvariable=self.font_var,
                                     values=self._font_choice_values(),
                                     width=26, state="readonly")
        self.font_box.pack(side=tk.LEFT)
        self.font_box.bind("<<ComboboxSelected>>", lambda _: self._refresh())
        tk.Button(color_frame, text="追加...",
                  command=self._on_add_custom_font).pack(side=tk.LEFT, padx=4)
        tk.Button(color_frame, text="削除",
                  command=self._on_remove_custom_font).pack(side=tk.LEFT)

    def _refresh_font_choices(self) -> None:
        if hasattr(self, "font_display_var"):
            pairs = self._font_display_pairs()
            self._font_display_to_key = dict(pairs)
            self._font_key_to_display = {key: display for display, key in pairs}
            values = [display for display, _key in pairs]
            self.font_box.config(values=values)
            key = self.font_var.get()
            if key not in self._font_key_to_display:
                key = DEFAULT_FONT
                self.font_var.set(key)
            self.font_display_var.set(self._font_key_to_display[key])
            self.font_box.unbind("<<ComboboxSelected>>")
            self.font_box.bind("<<ComboboxSelected>>", self._on_font_selected)
            return
        values = self._font_choice_values()
        self.font_box.config(values=values)
        if self.font_var.get() not in values:
            self.font_var.set(DEFAULT_FONT)

    def _on_add_custom_font(self):
        """所持フォント (.ttf/.otf/.ttc) を fonts/ へ複写して登録する。"""
        import shutil
        from pathlib import Path

        from PIL import ImageFont

        exts = " ".join(f"*{e}" for e in sorted(CUSTOM_FONT_EXTENSIONS))
        start = get_font_browse_start_dir()
        path = filedialog.askopenfilename(
            parent=self,
            title=self._tr("dialog.font.title"),
            initialdir=str(start) if start is not None else None,
            filetypes=[(self._tr("dialog.filetype.font"), exts),
                       (self._tr("dialog.filetype.all"), "*.*")])
        if not path:
            return
        err = validate_custom_font_file(path, self._language())
        if err is not None:
            messagebox.showerror(
                self._tr("dialog.error.title"),
                self._tr("font.add_invalid", error=err), parent=self)
            return
        try:
            ImageFont.truetype(path, 20)
        except Exception as e:
            messagebox.showerror(
                self._tr("dialog.error.title"),
                self._tr("font.unreadable", error=e), parent=self)
            return
        src = Path(path)
        display = sanitize_custom_font_name(src.stem, self.custom_fonts)
        try:
            fonts_dir = get_user_fonts_dir()
            fonts_dir.mkdir(parents=True, exist_ok=True)
            dest = fonts_dir / src.name
            if dest.exists():
                stem, suffix = dest.stem, dest.suffix
                i = 1
                while dest.exists():
                    dest = fonts_dir / f"{stem}_{i:02d}{suffix}"
                    i += 1
            shutil.copy2(src, dest)
        except OSError as e:
            messagebox.showerror(
                self._tr("dialog.error.title"),
                self._tr("font.copy_failed", error=e), parent=self)
            return
        self.custom_fonts[display] = str(dest)
        self.font_var.set(display)
        self._refresh_font_choices()
        self._refresh()

    def _on_remove_custom_font(self):
        """選択中のカスタムフォントを登録解除する (組込は対象外)。"""
        from pathlib import Path

        cur = self.font_var.get()
        if cur in FONT_CHOICES:
            messagebox.showinfo(
                self._tr("dialog.info.title"), self._tr("font.builtin_remove"),
                parent=self)
            return
        if cur not in self.custom_fonts:
            messagebox.showinfo(
                self._tr("dialog.info.title"), self._tr("font.no_custom"),
                parent=self)
            return
        if not messagebox.askyesno(
                self._tr("font.remove.title"),
                self._tr("font.remove.message", name=cur), parent=self):
            return
        old_path = Path(self.custom_fonts.pop(cur))
        try:
            if old_path.parent == get_user_fonts_dir() and old_path.is_file():
                old_path.unlink()
        except OSError:
            pass
        self.font_var.set(DEFAULT_FONT)
        self._refresh_font_choices()
        self._refresh()

    def _build_thickness_bar(self, loaded: OverlayConfig):
        thick_frame = tk.Frame(self)
        thick_frame.pack(pady=2)
        tk.Label(thick_frame, text="枠の太さ:").pack(side=tk.LEFT)
        self.thickness_var = tk.StringVar(value=loaded.thickness)
        self._thickness_label_to_key = dict(THICKNESS_CHOICES)
        self._thickness_key_to_label = {v: k for k, v in THICKNESS_CHOICES.items()}
        for label in THICKNESS_CHOICES.keys():
            tk.Radiobutton(thick_frame, text=label,
                           value=THICKNESS_CHOICES[label],
                           variable=self.thickness_var,
                           command=self._refresh).pack(side=tk.LEFT, padx=4)

    def _build_effect_bar(self, loaded: OverlayConfig):
        # UI劣化エフェクト (SPEC §3.6)。枠太さと同様に両モード共通で常時有効。
        effect_frame = tk.Frame(self)
        effect_frame.pack(pady=2)
        tk.Label(effect_frame, text="エフェクト:").pack(side=tk.LEFT)
        self._effect_label_to_key = dict(EFFECT_CHOICES)
        default_effect_label = next(
            (k for k, v in EFFECT_CHOICES.items() if v == loaded.effect),
            next(
                (k for k, v in EFFECT_CHOICES.items() if v == DEFAULT_EFFECT),
                next(iter(EFFECT_CHOICES))))
        self.effect_var = tk.StringVar(value=default_effect_label)
        tk.OptionMenu(effect_frame, self.effect_var, *EFFECT_CHOICES.keys(),
                      command=lambda _: self._refresh()).pack(side=tk.LEFT)

    def _build_mode_bar(self, loaded: OverlayConfig):
        mode_frame = tk.Frame(self)
        mode_frame.pack(pady=2)
        tk.Label(mode_frame, text="モード:").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(
            value="simple" if is_simple_equivalent(loaded) else "detail")
        tk.Radiobutton(mode_frame, text="簡易", value="simple",
                       variable=self.mode_var,
                       command=self._on_mode_change).pack(side=tk.LEFT, padx=4)
        tk.Radiobutton(mode_frame, text="詳細", value="detail",
                       variable=self.mode_var,
                       command=self._on_mode_change).pack(side=tk.LEFT, padx=4)

    def _build_detail_checks(self, loaded: OverlayConfig):
        # 詳細チェックは常時表示し、簡易モードでは無効化 (disabled)。枠太さラジオは両モード共通で常時有効 (SPEC §10.2)。
        # 中央十字・日時は詳細限定・既定OFF。簡易モードでは非表示扱い。
        self.show_frame_var = tk.BooleanVar(value=loaded.show_frame)
        self.show_battery_var = tk.BooleanVar(value=loaded.show_battery)
        self.show_rec_var = tk.BooleanVar(value=loaded.show_rec)
        self.show_cross_var = tk.BooleanVar(value=loaded.show_cross)
        self.detail_frame = tk.Frame(self)
        self.detail_frame.pack(pady=2)
        self._detail_checks = []
        for text, var in (("枠フレーム", self.show_frame_var),
                          ("電池残量マーク", self.show_battery_var),
                          ("REC", self.show_rec_var),
                          ("中央十字", self.show_cross_var)):
            cb = tk.Checkbutton(self.detail_frame, text=text,
                                variable=var, state=tk.DISABLED,
                                command=self._refresh)
            cb.pack(side=tk.LEFT, padx=4)
            self._detail_checks.append(cb)

    def _build_timecode_bar(self, loaded: OverlayConfig):
        # 日時表示 (SPEC §3.5): 詳細限定のON/OFF＋手入力欄＋撮影日時モード。簡易モードでは無効化。
        self.show_timecode_var = tk.BooleanVar(value=loaded.show_timecode)
        self.use_exif_var = tk.BooleanVar(value=loaded.timecode_from_exif)
        self.timecode_text_var = tk.StringVar(
            value=loaded.timecode_text or default_timecode_text())
        self.timecode_frame = tk.Frame(self)
        self.timecode_frame.pack(pady=2)
        self.timecode_check = tk.Checkbutton(
            self.timecode_frame, text="日時表示",
            variable=self.show_timecode_var, state=tk.DISABLED,
            command=self._refresh)
        self.timecode_check.pack(side=tk.LEFT, padx=4)
        self.timecode_entry = tk.Entry(
            self.timecode_frame, textvariable=self.timecode_text_var,
            width=22, state=tk.DISABLED)
        self.timecode_entry.pack(side=tk.LEFT, padx=4)
        self.exif_check = tk.Checkbutton(
            self.timecode_frame, text="撮影日時を使う",
            variable=self.use_exif_var, state=tk.DISABLED,
            command=self._on_exif_toggle)
        self.exif_check.pack(side=tk.LEFT, padx=4)
        self._detail_checks.append(self.timecode_check)
        self._detail_checks.append(self.exif_check)
        self.timecode_text_var.trace_add("write", self._on_timecode_edit)

    def _on_exif_toggle(self):
        """撮影日時モードON時は日時表示もONにして即時反映する (片方向アシスト)。"""
        if self.use_exif_var.get() and not self.show_timecode_var.get():
            self.show_timecode_var.set(True)
        self._refresh()

    def _build_timecode_selector(self, loaded: OverlayConfig):
        # 日時選択式入力 (SPEC §10.3): Spinbox群→同一 timecode_text に合成(片方向)。
        # 検証は緩和し暦チェックなし。手入力欄も残し、直接編集も可(セレクタ操作で上書き)。
        now = datetime.now()
        self.timecode_sel_frame = tk.Frame(self)
        self.timecode_sel_frame.pack(pady=1)
        tk.Label(self.timecode_sel_frame, text="選択入力:").pack(side=tk.LEFT)
        self._timecode_sel_widgets: list = []

        def _spin(from_, to, width, value, wrap=True, fmt=None):
            sb = tk.Spinbox(self.timecode_sel_frame, from_=from_, to=to,
                            width=width, wrap=wrap, state=tk.DISABLED,
                            command=self._on_timecode_select,
                            **({"format": fmt} if fmt else {}))
            sb.delete(0, tk.END)
            sb.insert(0, str(value))
            sb.bind("<FocusOut>", self._on_timecode_select)
            sb.bind("<Return>", self._on_timecode_select)
            sb.pack(side=tk.LEFT, padx=1)
            self._timecode_sel_widgets.append(sb)
            return sb

        def _dropdown(label, values, value, width=4):
            tk.Label(self.timecode_sel_frame, text=label).pack(side=tk.LEFT)
            cb = ttk.Combobox(self.timecode_sel_frame, values=values,
                              width=width, state=tk.DISABLED)
            cb.set(value)
            cb.bind("<<ComboboxSelected>>", self._on_timecode_select)
            cb.pack(side=tk.LEFT, padx=1)
            self._timecode_sel_widgets.append(cb)
            return cb

        def _padded(from_, to):
            return [f"{i:02d}" for i in range(from_, to + 1)]

        tk.Label(self.timecode_sel_frame, text="年").pack(side=tk.LEFT)
        self.tc_year_spin = _spin(1, 9999, 5, now.year, wrap=False)
        self.tc_month_box = _dropdown("月", _padded(1, 12), f"{now.month:02d}")
        self.tc_day_box = _dropdown("日", _padded(1, 31), f"{now.day:02d}")
        self.tc_ampm_box = _dropdown("", ["AM", "PM"],
                                     "AM" if now.hour < 12 else "PM", width=4)
        h12 = now.hour % 12 or 12
        self.tc_hour_box = _dropdown("時", _padded(1, 12), f"{h12:02d}")
        self.tc_min_box = _dropdown("分", _padded(0, 59), f"{now.minute:02d}")
        self._sync_timecode_selector(loaded.timecode_text)

    def _build_preview_area(self):
        self.info = tk.Label(self, text="画像を開いてください (どんなサイズでもOK)",
                             fg="gray")
        self.info.pack()

        self.canvas_label = tk.Label(self, bg="#cccccc")
        self.canvas_label.pack(expand=True, fill=tk.BOTH, padx=10, pady=10)

    def _on_timecode_edit(self, *args):
        """日時手入力欄の変更時ハンドラ。300msデバウンスで再描画・保存を実行。"""
        if self._timecode_edit_job is not None:
            self.after_cancel(self._timecode_edit_job)
        self._timecode_edit_job = self.after(300, self._refresh)

    def _sync_timecode_selector(self, text: str) -> None:
        """保存済み日時文字列を選択式UIに反映。空・不正形式は現在値のまま。"""
        parsed = parse_timecode_text(text)
        if not parsed:
            return
        year, month, day, ampm, hour, minute = parsed
        year_state = self.tc_year_spin.cget("state")
        try:
            self.tc_year_spin.config(state=tk.NORMAL)
            self.tc_year_spin.delete(0, tk.END)
            self.tc_year_spin.insert(0, str(year))
            self.tc_month_box.set(f"{month:02d}")
            self.tc_day_box.set(f"{day:02d}")
            self.tc_ampm_box.set(ampm)
            self.tc_hour_box.set(f"{hour:02d}")
            self.tc_min_box.set(f"{minute:02d}")
        except (ValueError, tk.TclError):
            pass
        finally:
            self.tc_year_spin.config(state=year_state)

    def _full_config(self) -> OverlayConfig:
        """UI上の全ウィジェット値をそのまま反映した設定を返す (保存用)。"""
        raw_effect = self.effect_var.get()
        effect = (raw_effect if raw_effect in ("off", "oled", "2000s")
                  else self._effect_label_to_key[raw_effect])
        font_key = self.font_var.get()
        if font_key not in FONT_CHOICES and font_key not in self.custom_fonts:
            font_key = DEFAULT_FONT
        return OverlayConfig(
            color=self.color_var.get(),
            font_key=font_key,
            thickness=self.thickness_var.get(),
            show_frame=self.show_frame_var.get(),
            show_battery=self.show_battery_var.get(),
            show_rec=self.show_rec_var.get(),
            show_cross=self.show_cross_var.get(),
            show_timecode=self.show_timecode_var.get(),
            timecode_text=self.timecode_text_var.get(),
            effect=effect,
            custom_fonts=dict(self.custom_fonts),
            timecode_from_exif=self.use_exif_var.get(),
            ui_language=self._language(),
        )

    def _current_config(self) -> OverlayConfig:
        """描画用設定。簡易モードは show_* 全True・中央十字・日時OFF扱い (SPEC §10.2・§3.5)。"""
        cfg = self._full_config()
        if self.mode_var.get() == "simple":
            return OverlayConfig(
                color=cfg.color,
                font_key=cfg.font_key,
                thickness=cfg.thickness,
                effect=cfg.effect,
                custom_fonts=dict(self.custom_fonts),
                timecode_from_exif=cfg.timecode_from_exif,
                ui_language=cfg.ui_language,
            )
        return cfg

    def _save_settings(self) -> None:
        """現在のUI設定を自動保存。起動時復元中・保存失敗時は静かに何もしない。

        簡易モード中も詳細チェック状態は保持して保存する (描画用の
        `_current_config` とは異なり show_* を強制上書きしない)。
        """
        if getattr(self, "_loading_settings", False):
            return
        try:
            save_user_config(self._full_config())
        except Exception:
            pass

    def _on_mode_change(self):
        detail = self.mode_var.get() == "detail"
        if not detail:
            self.tabs.select(self.style_page)
        self.tabs.tab(self.detail_page, state="normal" if detail else "hidden")
        if detail:
            self.tabs.select(self.detail_page)
        self.mode_hint.config(
            text=self._tr("mode.detail_hint" if detail else "mode.simple_hint"))
        state = tk.NORMAL if detail else tk.DISABLED
        for cb in self._detail_checks:
            cb.config(state=state)
        self._save_settings()
        self._refresh()

    def _tab_labels(self, _event=None):
        for page, key in ((self.style_page, "tab.style"),
                          (self.detail_page, "tab.detail")):
            prefix = "● " if self.tabs.select() == str(page) else "   "
            self.tabs.tab(page, text=prefix + self._tr(key))

    def _on_timecode_select(self, *args):
        """セレクタ値を timecode_text に合成する。不正入力中は無視。"""
        if self.mode_var.get() != "detail" or self.use_exif_var.get():
            return
        try:
            text = compose_timecode_text(
                self.tc_year_spin.get(),
                self.tc_month_box.get(), self.tc_day_box.get(),
                self.tc_ampm_box.get(),
                self.tc_hour_box.get(), self.tc_min_box.get())
        except (ValueError, tk.TclError):
            return
        self.timecode_text_var.set(text)

    def open_image(self):
        ext_patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        path = filedialog.askopenfilename(
            parent=self, title=self._tr("dialog.open.title"),
            filetypes=[(self._tr("dialog.filetype.image"), ext_patterns),
                       (self._tr("dialog.filetype.all"), "*.*")])
        if not path:
            return
        try:
            img = load_base_image(path)
        except Exception as e:
            messagebox.showerror(
                self._tr("dialog.error.title"),
                self._tr("dialog.open.failed", error=e), parent=self)
            return
        self.src_image = img
        self.src_path = path
        self.result_image = self._render()
        self._show_preview(self.result_image)

    def open_sample(self):
        """配布ファイルに依存しない中立的なデモ用ベース画像を生成する。"""
        width, height = 1600, 1000
        img = Image.new("RGB", (width, height), "#cad8d2")
        draw = ImageDraw.Draw(img)
        # 写真代替として、空・遠景・机を抽象化した落ち着いたベースを作る。
        draw.rectangle((0, 0, width, 560), fill="#b9ced0")
        draw.ellipse((980, 100, 1190, 310), fill="#f5e2a8")
        draw.polygon([(0, 560), (360, 300), (760, 560)], fill="#789b91")
        draw.polygon([(420, 560), (980, 250), (1420, 560)], fill="#55796f")
        draw.rectangle((0, 560, width, height), fill="#b58f70")
        draw.rectangle((250, 665, 1350, 825), fill="#e4d6bf")
        draw.rounded_rectangle(
            (610, 600, 990, 900), radius=28, fill="#53636a")
        draw.ellipse((720, 675, 880, 835), fill="#97b9b0")
        self.src_image = img
        self.src_path = "rec-frame-sample.png"
        self._refresh()

    def _render(self):
        cfg = self._current_config()
        if cfg.timecode_from_exif and self.src_image is not None:
            # 写真毎の日時 (EXIF→mtime→固定文) を描画と入力欄へ反映する。
            # 値が変わった時だけ set する (traceの300ms再描画ループを防ぐ)。
            cfg = resolve_photo_config(cfg, self.src_image, self.src_path)
            text = cfg.timecode_text
            if text != self.timecode_text_var.get():
                self.timecode_text_var.set(text)
                self._sync_timecode_selector(text)
        return composite_with_config(self.src_image, cfg)

    def _refresh(self):
        manual = self.mode_var.get() == "detail" and not self.use_exif_var.get()
        self.timecode_entry.config(state="normal" if manual else "disabled")
        for widget in self._timecode_sel_widgets:
            if isinstance(widget, ttk.Combobox):
                widget.config(state="readonly" if manual else "disabled")
            else:
                widget.config(state="normal" if manual else "disabled")
        self.time_hint.config(
            text=self._tr("time.auto_hint" if self.use_exif_var.get()
                          else "time.manual_hint"))
        self._save_settings()
        if self.src_image is None:
            return
        self.result_image = self._render()
        self._show_preview(self.result_image)

    def _on_window_resize(self, event):
        # ウィンドウリサイズにプレビューを追従 (デバウンス)。
        # 追従しないと古いサイズのまま欠け・余白ズレに見える。
        if event.widget is not self or self.src_image is None:
            return
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(150, self._delayed_preview)

    def _delayed_preview(self):
        self._resize_job = None
        if self.src_image is not None and self.result_image is not None:
            self._show_preview(self.result_image)

    def _show_preview(self, img: Image.Image):
        # ラベルの実表示域に収まるよう縮小プレビュー (thumbnailは比率維持)
        self.empty.place_forget()
        self.update_idletasks()
        lw, lh = self.canvas_label.winfo_width(), self.canvas_label.winfo_height()
        if lw < 50 or lh < 50:  # レイアウト確定前などのフォールバック
            lw, lh = self.winfo_width() - 40, self.winfo_height() - 120
        pw = max(1, lw - 4)
        ph = max(1, lh - 4)
        preview = img.copy()
        preview.thumbnail((pw, ph))
        self.photo = ImageTk.PhotoImage(preview)
        self.canvas_label.config(image=self.photo)
        self.save_button.config(state="normal")
        self._update_preview_info(img)

    def _update_preview_info(self, img: Image.Image) -> None:
        view_w = self.photo.width() if self.photo is not None else 0
        view_h = self.photo.height() if self.photo is not None else 0
        self.info.config(text=self._tr(
            "preview.info", name=Path(self.src_path).name,
            save_w=img.width, save_h=img.height,
            view_w=view_w, view_h=view_h))

    def save_image(self):
        # 300msデバウンス中の日時編集も、保存直前に必ず確定する。
        if self.src_image is not None:
            self._refresh()
        if self.result_image is None:
            messagebox.showinfo(
                self._tr("dialog.info.title"),
                self._tr("dialog.save.no_image"), parent=self)
            return
        base, ext = os.path.splitext(os.path.basename(self.src_path))
        init = f"{base}_rec{ext or '.png'}"
        path = filedialog.asksaveasfilename(
            parent=self, title=self._tr("dialog.save.title"), initialfile=init,
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg"),
                       ("WebP", "*.webp"),
                       (self._tr("dialog.filetype.all"), "*.*")])
        if not path:
            return
        try:
            save_composited_image(self.result_image, path)
            messagebox.showinfo(
                self._tr("dialog.save.done_title"),
                self._tr("dialog.save.done", path=path), parent=self)
        except Exception as e:
            messagebox.showerror(
                self._tr("dialog.error.title"),
                self._tr("dialog.save.failed", error=e), parent=self)

    def batch_images(self):
        """フォルダ一括処理。現在の画面設定をそのまま使う(設定ファイル選択なし)。"""
        from pathlib import Path

        from rec_batch import process_folder

        src_dir = filedialog.askdirectory(
            parent=self, title=self._tr("dialog.batch.input"))
        if not src_dir:
            return
        dst_dir = filedialog.askdirectory(
            parent=self, title=self._tr("dialog.batch.output"))
        if not dst_dir:
            return
        config = self._current_config()
        if not messagebox.askyesno(
                self._tr("dialog.batch.confirm_title"),
                self._tr("dialog.batch.confirm", input=src_dir, output=dst_dir),
                parent=self):
            return
        self._save_settings()
        prog = tk.Toplevel(self)
        prog.title(self._tr("dialog.batch.progress_title"))
        prog.geometry("380x110")
        prog.transient(self)
        prog.grab_set()
        label = tk.Label(prog, text=self._tr("batch.preparing"))
        label.pack(pady=8)
        bar = ttk.Progressbar(prog, length=320, mode="determinate")
        bar.pack(pady=4)

        def _progress(idx, total, name):
            bar["maximum"] = max(1, total)
            bar["value"] = idx
            label.config(text=(self._tr(
                "batch.progress", index=idx, total=total, name=name)
                if name else self._tr("batch.progress_done", total=total)))
            prog.update_idletasks()

        try:
            result = process_folder(
                Path(src_dir), Path(dst_dir), config, progress=_progress,
                language=self._language())
        finally:
            prog.grab_release()
            prog.destroy()
        lines = [self._tr("batch.success", count=result.success),
                 self._tr("batch.failed", count=result.failed),
                 self._tr("batch.skipped", count=result.skipped)]
        if result.errors:
            lines.append("")
            lines += result.errors[:10]
            if len(result.errors) > 10:
                lines.append(self._tr(
                    "batch.more", count=len(result.errors) - 10))
        messagebox.showinfo(
            self._tr("dialog.batch.result_title"), "\n".join(lines), parent=self)


def run_batch_cli(
    input_dir: str,
    output_dir: str,
    config_path: str | None = None,
    language: str | None = None,
) -> int:
    """CLI `--batch` の実体。GUIを開かずフォルダ一括処理する。"""
    import json
    from pathlib import Path

    from rec_batch import process_folder

    if config_path:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            config = OverlayConfig.from_dict(data if isinstance(data, dict) else {})
        except (OSError, ValueError) as e:
            lang = normalize_language(language)
            print(tr(lang, "cli.config_read_error", error=e))
            return 2
    else:
        config = load_user_config()
    lang = normalize_language(language or config.ui_language)
    result = process_folder(Path(input_dir), Path(output_dir), config,
                            progress=lambda i, total, name: print(
                                tr(lang, "batch.progress", index=i, total=total, name=name)
                                if name else tr(lang, "batch.progress_done", total=total)),
                            language=lang)
    print(tr(lang, "cli.result", success=result.success,
             failed=result.failed, skipped=result.skipped))
    for err in result.errors:
        print(tr(lang, "cli.error", error=err))
    if result.failed > 0 or (result.success == 0 and result.errors):
        return 1
    return 0


def _preferred_cli_language(argv: list[str]) -> str:
    """argparse生成前にhelp表示言語を決める。"""
    import json

    if "--lang" in argv:
        try:
            return normalize_language(argv[argv.index("--lang") + 1])
        except IndexError:
            pass
    if "--config" in argv:
        try:
            path = argv[argv.index("--config") + 1]
            with open(path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict):
                return OverlayConfig.from_dict(data).ui_language
        except (IndexError, OSError, ValueError, TypeError):
            pass
    return load_user_config().ui_language


if __name__ == "__main__":
    import argparse
    import sys
    # 西欧ロケールの console (cp1252 等) でも --help/--batch の日本語出力で
    # 落ちないよう標準入出力を UTF-8 に寄せる。GUI 動作には無影響。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    _cli_language = _preferred_cli_language(sys.argv[1:])
    _parser = argparse.ArgumentParser(
        description=tr(_cli_language, "cli.description"), add_help=False)
    _parser.add_argument(
        "-h", "--help", action="help", help=tr(_cli_language, "cli.help"))
    _parser.add_argument(
        "--batch", nargs=2,
        metavar=(tr(_cli_language, "cli.input_metavar"),
                 tr(_cli_language, "cli.output_metavar")),
        help=tr(_cli_language, "cli.batch_help"))
    _parser.add_argument(
        "--config", default=None, help=tr(_cli_language, "cli.config_help"))
    _parser.add_argument(
        "--lang", choices=("ja", "en"), default=None,
        help=tr(_cli_language, "cli.lang_help"))
    _args = _parser.parse_args()
    if _args.batch:
        raise SystemExit(run_batch_cli(
            _args.batch[0], _args.batch[1], _args.config, _args.lang))
    App(language_override=_args.lang).mainloop()
