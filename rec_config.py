"""オーバーレイ設定の定義。SPEC.md §3・§10.2 が正本。

GUI・バッチ・CLI で共有するための薄い設定層。
SPEC §10.1〜10.2 のバッチ用 JSON と互換の dict 変換を持つ。
旧 `{color, font_key}` は thickness=medium・show_*=True・show_cross=False・show_timecode=False として読込。
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from rec_i18n import DEFAULT_LANGUAGE, LanguageKey, normalize_language, tr

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})

OverlayColor = Literal["black", "white"]
ThicknessKey = Literal["small", "medium", "large"]
EffectKey = Literal["off", "oled", "2000s"]

# カラープリセット定義 (表示名/内部キー: (R, G, B, A))
COLOR_PRESETS: dict[str, tuple[int, int, int, int]] = {
    "black": (0, 0, 0, 255),
    "white": (255, 255, 255, 255),
    "green": (0, 255, 80, 255),     # #00FF50 暗視スコープ・ナイトビジョン
    "cyan": (0, 220, 255, 255),     # #00DCFF 近未来SF・サイバーHUD
    "red": (255, 30, 30, 255),      # #FF1E1E 警報・エマージェンシー
    "yellow": (255, 225, 0, 255),   # #FFE100 ハザード・注意喚起・ミリタリー測距
}

_HEX_COLOR_RE = re.compile(r"^#?([0-9a-fA-F]{3,8})$")


def parse_color_to_rgba(val: Any) -> tuple[int, int, int, int] | None:
    """色指定 (プリセット名 / HEXコード / RGBタプル) を RGBA タプル (0..255) に変換する。"""
    if not val:
        return None
    if isinstance(val, (tuple, list)) and len(val) in (3, 4):
        try:
            r, g, b = [max(0, min(255, int(round(c)))) for c in val[:3]]
            a = max(0, min(255, int(round(val[3])))) if len(val) == 4 else 255
            return (r, g, b, a)
        except (ValueError, TypeError):
            return None
    if not isinstance(val, str):
        return None

    cleaned = val.strip().lower()
    # 1. プリセット名完全一致
    if cleaned in COLOR_PRESETS:
        return COLOR_PRESETS[cleaned]

    # 2. プレフィックス一致 (例: "green (暗視グリーン)" -> "green")
    first_token = cleaned.split()[0].rstrip(",;:")
    if first_token in COLOR_PRESETS:
        return COLOR_PRESETS[first_token]

    # 3. HEXコード (#RGB, #RGBA, #RRGGBB, #RRGGBBAA)
    m = _HEX_COLOR_RE.match(cleaned)
    if m:
        hex_str = m.group(1)
        try:
            if len(hex_str) == 3:  # #RGB
                r = int(hex_str[0] * 2, 16)
                g = int(hex_str[1] * 2, 16)
                b = int(hex_str[2] * 2, 16)
                return (r, g, b, 255)
            elif len(hex_str) == 4:  # #RGBA
                r = int(hex_str[0] * 2, 16)
                g = int(hex_str[1] * 2, 16)
                b = int(hex_str[2] * 2, 16)
                a = int(hex_str[3] * 2, 16)
                return (r, g, b, a)
            elif len(hex_str) == 6:  # #RRGGBB
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
                return (r, g, b, 255)
            elif len(hex_str) == 8:  # #RRGGBBAA
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
                a = int(hex_str[6:8], 16)
                return (r, g, b, a)
        except ValueError:
            pass

    return None


# 枠太さの表示名と内部キーの対応 (GUIラジオ用)
THICKNESS_CHOICES: dict[str, ThicknessKey] = {
    "小": "small",
    "中": "medium",
    "大": "large",
}
DEFAULT_THICKNESS: ThicknessKey = "medium"

# REC文字に使えるOS標準フォント候補 (表示名: ファイル名, 既存10種維持)
FONT_CHOICES: dict[str, str] = {
    "Arial(標準)": "arial.ttf",
    "Arial Narrow Bold(細長)": "ARIALNB.TTF",
    "Arial Black(極太)": "ariblk.ttf",
    "Impact(凝縮テロップ風)": "impact.ttf",
    "Bahnschrift(工業的)": "bahnschrift.ttf",
    "Consolas(等幅)": "consola.ttf",
    "Roboto Condensed": "RobotoCondensed-Regular.ttf",
    "Montserrat Medium": "Montserrat-Medium.otf",
    "Bebas Neue(縦長)": "BebasNeue-Regular.otf",
    "OCRB(計測機器風)": "OCRB.TTF",
}
DEFAULT_FONT = "Arial Narrow Bold(細長)"

# 同梱オープンソースフォント候補 (表示名: ファイル名)
BUNDLED_FONT_CHOICES: dict[str, str] = {
    "Roboto Condensed Bold(細長)": "RobotoCondensed-Bold.ttf",
    "Bebas Neue(縦長大文字)": "BebasNeue-Regular.ttf",
    "DSEG7 Classic(7セグLED)": "DSEG7Classic-Bold.ttf",
    "Share Tech Mono(等幅)": "ShareTechMono-Regular.ttf",
    "VT323(レトロドット)": "VT323-Regular.ttf",
    "Zen Kaku Gothic(日本語)": "ZenKakuGothicNew-Bold.ttf",
}

ALL_BUILTIN_FONTS: dict[str, str] = {**FONT_CHOICES, **BUNDLED_FONT_CHOICES}

# ファインダーUI劣化エフェクトの選択肢 (表示名: 内部キー、SPEC §3.6)
EFFECT_CHOICES: dict[str, EffectKey] = {
    "OFF(クリーン)": "off",
    "OLED(微発光)": "oled",
    "2000sデジカメ": "2000s",
}
DEFAULT_EFFECT: EffectKey = "off"
DEFAULT_RETRO_EFFECT: int = 0

CLASSIC_DOT_STYLE: str = "classic"
DEFAULT_DOT_STYLE: str = "classic"

CONFIG_SCHEMA_VERSION = 8

CUSTOM_FONT_EXTENSIONS: frozenset[str] = frozenset({".ttf", ".otf", ".ttc"})
DOT_ASSET_EXTENSIONS: frozenset[str] = frozenset({".png", ".webp", ".jpg", ".jpeg"})

APP_CONFIG_DIRNAME = "rec-frame-app"
APP_CONFIG_FILENAME = "config.json"


def get_resource_base_dir() -> Path:
    """リソース基底パス。PyInstaller onefile実行時は _MEIPASS、通常時はリポジトリ直下。"""
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def get_bundled_fonts_dir() -> Path:
    """同梱オープンソースフォントの配置フォルダ。"""
    return get_resource_base_dir() / "fonts"


def get_dot_assets_dir() -> Path:
    """同梱ドットマーク素材フォルダ。"""
    return get_resource_base_dir() / "assets" / "dots"


def discover_dot_assets() -> dict[str, str]:
    """利用可能なマーク素材 `{キー: ファイルパス}` を収集する。"""
    assets: dict[str, str] = {}
    d = get_dot_assets_dir()
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in (".png", ".webp"):
                assets[p.stem] = str(p)
    return assets


def get_all_dot_styles() -> list[str]:
    """GUI選択肢用ドットスタイル一覧 (classic -> flat_* -> glow_* -> その他)。"""
    assets = discover_dot_assets()
    flats = [k for k in assets if k.startswith("flat_")]
    glows = [k for k in assets if k.startswith("glow_")]
    others = [k for k in assets if not k.startswith("flat_") and not k.startswith("glow_")]
    return [CLASSIC_DOT_STYLE] + flats + glows + others


def get_user_config_path() -> Path:
    """自動記憶用JSONの保存先。UI追加なしで毎回読み書きする。

    - Windows: %APPDATA%/rec-frame-app/config.json
    - その他: $XDG_CONFIG_HOME/rec-frame-app/config.json (既定 ~/.config)
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_CONFIG_DIRNAME / APP_CONFIG_FILENAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_CONFIG_DIRNAME / APP_CONFIG_FILENAME


def load_user_config(path: Path | str | None = None) -> "OverlayConfig":
    """保存済み設定を読む。欠落・破損・旧形式は既定値で吸収し例外を出さない。"""
    target = Path(path) if path is not None else get_user_config_path()
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        return OverlayConfig()
    if not isinstance(data, dict):
        return OverlayConfig()
    try:
        return OverlayConfig.from_dict(data)
    except (ValueError, TypeError):
        return OverlayConfig()


def save_user_config(config: "OverlayConfig", path: Path | str | None = None) -> Path | None:
    """設定を自動保存する。書けない環境では None を返し例外を出さない。"""
    target = Path(path) if path is not None else get_user_config_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)
        return target
    except OSError:
        return None


def get_user_fonts_dir() -> Path:
    """カスタムフォントのコピー先。設定JSONと同じルート直下の `fonts/`。"""
    return get_user_config_path().parent / "fonts"


def get_system_font_dirs() -> list[Path]:
    """OSのフォント格納先の候補。存在するものだけ返す (優先順)。"""
    candidates: list[Path] = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
        candidates.append(Path("C:/Windows/Fonts"))
        windir = os.environ.get("WINDIR")
        if windir:
            candidates.append(Path(windir) / "Fonts")
    else:
        candidates += [
            Path("/usr/share/fonts"),
            Path.home() / ".local" / "share" / "fonts",
            Path.home() / ".fonts",
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library" / "Fonts",
        ]
    seen: set[str] = set()
    result: list[Path] = []
    for p in candidates:
        key = os.path.normcase(str(p))
        if key in seen:
            continue
        seen.add(key)
        try:
            if p.is_dir():
                result.append(p)
        except OSError:
            continue
    return result


def get_font_browse_start_dir() -> Path | None:
    """「追加...」ダイアログの初期フォルダ。無ければNone (→ダイアログ既定)。"""
    dirs = get_system_font_dirs()
    return dirs[0] if dirs else None


def is_builtin_font(font_key: str) -> bool:
    """組込(OS標準または同梱OSS)の表示名か。"""
    return font_key in ALL_BUILTIN_FONTS


def get_all_font_names(config: "OverlayConfig") -> list[str]:
    """GUI選択肢用。OS標準＋同梱OSS＋カスタムの表示名一覧。"""
    names = list(FONT_CHOICES)
    for name in BUNDLED_FONT_CHOICES:
        if name not in names:
            names.append(name)
    for name in config.custom_fonts:
        if name not in names:
            names.append(name)
    return names


def resolve_custom_font_path(
    font_key: str, custom_fonts: dict[str, str] | None
) -> Path | None:
    """カスタム名に対応する実ファイル。存在しない・組込名なら None。"""
    if not custom_fonts or font_key in ALL_BUILTIN_FONTS:
        return None
    raw = custom_fonts.get(font_key)
    if not raw:
        return None
    return Path(raw)


def sanitize_custom_font_name(proposed: str, custom_fonts: dict[str, str] | None) -> str:
    """表示名の衝突回避。組込・登録済みと重なったら `名 2` / `名 3` …を付ける。"""
    base = (proposed or "").strip() or "カスタムフォント"
    if base not in ALL_BUILTIN_FONTS and not (custom_fonts and base in custom_fonts):
        return base
    i = 2
    while True:
        candidate = f"{base} {i}"
        if candidate not in ALL_BUILTIN_FONTS and not (custom_fonts and candidate in custom_fonts):
            return candidate
        i += 1


def validate_custom_font_file(
    path: Path | str, language: LanguageKey = DEFAULT_LANGUAGE
) -> str | None:
    """追加前の軽量検査。問題なければ None、あれば理由文を返す。"""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return tr(language, "font.validation.missing")
    if p.suffix.lower() not in CUSTOM_FONT_EXTENSIONS:
        return tr(
            language, "font.validation.extension",
            extensions=sorted(CUSTOM_FONT_EXTENSIONS))
    return None


def is_simple_equivalent(config: "OverlayConfig") -> bool:
    """簡易モードの描画と等価か。mode自体は保存対象外のため起動時推定に使う。"""
    return (
        config.show_frame
        and config.show_battery
        and config.show_rec
        and not config.show_cross
        and not config.show_timecode
        and not config.timecode_from_exif
        and config.bg_box_opacity == 0.0
        and config.battery_bars == 4
        and config.rec_label == "REC"
        and config.show_red_dot
        and config.dot_style == CLASSIC_DOT_STYLE
        and not isinstance(config.thickness, int)
        and config.custom_color == ""
    )


_TIMECODE_RE = re.compile(
    r"^\s*(\d{1,4})/(\d{1,2})/(\d{1,2})\s+(AM|PM)\s+(\d{1,2}):(\d{1,2})\s*$"
)


def compose_timecode_text(year, month, day, ampm, hour, minute) -> str:
    """日時セレクタ値を `YYYY/MM/DD AM/PM HH:MM` に整形する (SPEC §10.3)。"""
    return (f"{int(year):04d}/{int(month):02d}/{int(day):02d} "
            f"{ampm} {int(hour):02d}:{int(minute):02d}")


def parse_timecode_text(text: str) -> tuple[int, int, int, str, int, int] | None:
    """日時文字列をパースする。不正形式は None を返す。compose_timecode_text の逆操作。"""
    m = _TIMECODE_RE.match(text or "")
    if not m:
        return None
    year, month, day, ampm, hour, minute = m.groups()
    try:
        return int(year), int(month), int(day), ampm, int(hour), int(minute)
    except ValueError:
        return None


@dataclass(frozen=True)
class OverlayConfig:
    """オーバーレイ生成設定。将来の拡張用にスキーマバージョン付き。"""

    color: OverlayColor = "black"
    custom_color: str = ""
    font_key: str = DEFAULT_FONT
    thickness: ThicknessKey | int = DEFAULT_THICKNESS
    show_frame: bool = True
    show_battery: bool = True
    show_rec: bool = True
    show_cross: bool = False
    show_timecode: bool = False
    timecode_text: str = ""
    effect: EffectKey = "off"
    retro_effect: int = DEFAULT_RETRO_EFFECT
    custom_fonts: dict[str, str] = field(default_factory=dict)
    timecode_from_exif: bool = False
    ui_language: LanguageKey = DEFAULT_LANGUAGE

    # 詳細・カスタマイズ用フィールド (既定値は既存仕様と完全互換)
    rec_label: str = "REC"
    show_red_dot: bool = True
    red_dot_visible: bool = True
    dot_style: str = DEFAULT_DOT_STYLE
    battery_bars: int = 4
    margin_ratio: float | None = None
    arm_len_ratio: float | None = None
    bg_box_opacity: float = 0.0

    def __post_init__(self) -> None:
        if self.color not in ("black", "white"):
            raise ValueError(f"color must be 'black'|'white', got {self.color!r}")
        if not isinstance(self.custom_color, str):
            raise ValueError(f"custom_color must be str, got {self.custom_color!r}")
        if self.custom_color.strip():
            if parse_color_to_rgba(self.custom_color.strip()) is None:
                raise ValueError(f"invalid custom_color: {self.custom_color!r}")
        if not isinstance(self.custom_fonts, dict):
            raise ValueError(f"custom_fonts must be dict, got {self.custom_fonts!r}")
        for k, v in self.custom_fonts.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(f"custom_fonts keys must be non-empty str, got {k!r}")
            if k in ALL_BUILTIN_FONTS:
                raise ValueError(f"custom_fonts key collides with builtin: {k!r}")
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"custom_fonts values must be non-empty str, got {v!r}")

        if self.font_key not in ALL_BUILTIN_FONTS and self.font_key not in self.custom_fonts:
            raise ValueError(f"unknown font_key: {self.font_key!r}")

        if isinstance(self.thickness, int):
            if not (0 <= self.thickness <= 100):
                raise ValueError(f"thickness must be int 0..100, got {self.thickness!r}")
        elif self.thickness not in ("small", "medium", "large"):
            raise ValueError(
                f"thickness must be 'small'|'medium'|'large' or int 0..100, got {self.thickness!r}"
            )

        for key in ("show_frame", "show_battery", "show_rec", "show_cross",
                      "show_timecode", "timecode_from_exif", "show_red_dot",
                      "red_dot_visible"):
            if not isinstance(getattr(self, key), bool):
                raise ValueError(f"{key} must be bool, got {getattr(self, key)!r}")

        if not isinstance(self.timecode_text, str):
            raise ValueError(f"timecode_text must be str, got {self.timecode_text!r}")
        if not isinstance(self.rec_label, str):
            raise ValueError(f"rec_label must be str, got {self.rec_label!r}")
        if not isinstance(self.dot_style, str):
            raise ValueError(f"dot_style must be str, got {self.dot_style!r}")
        if not isinstance(self.battery_bars, int) or not (0 <= self.battery_bars <= 4):
            raise ValueError(f"battery_bars must be int 0..4, got {self.battery_bars!r}")
        if not isinstance(self.bg_box_opacity, (int, float)) or not (0.0 <= float(self.bg_box_opacity) <= 1.0):
            raise ValueError(f"bg_box_opacity must be float 0.0..1.0, got {self.bg_box_opacity!r}")
        if not isinstance(self.retro_effect, int) or not (0 <= self.retro_effect <= 6):
            raise ValueError(f"retro_effect must be int 0..6, got {self.retro_effect!r}")

        if self.effect not in ("off", "oled", "2000s"):
            raise ValueError(
                f"effect must be 'off'|'oled'|'2000s', got {self.effect!r}"
            )
        if self.ui_language not in ("ja", "en"):
            raise ValueError(
                f"ui_language must be 'ja'|'en', got {self.ui_language!r}"
            )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["schema_version"] = CONFIG_SCHEMA_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OverlayConfig":
        kwargs: dict = {}
        for f in dataclasses.fields(cls):
            if f.name in d:
                value = d[f.name]
                if f.name == "custom_fonts":
                    if isinstance(value, dict):
                        cleaned = {
                            k: v for k, v in value.items()
                            if isinstance(k, str) and k.strip()
                            and isinstance(v, str) and v.strip()
                            and k not in ALL_BUILTIN_FONTS
                        }
                        kwargs[f.name] = cleaned
                elif f.name == "ui_language":
                    kwargs[f.name] = normalize_language(value)
                elif f.name == "effect":
                    # ComfyUI等からの互換: normal -> off
                    val = str(value)
                    if val in ("normal", "clean"):
                        val = "off"
                    kwargs[f.name] = val
                else:
                    kwargs[f.name] = value

        if "retro_effect" not in kwargs:
            legacy_eff = kwargs.get("effect", "off")
            kwargs["retro_effect"] = 2 if legacy_eff == "2000s" else 0

        return cls(**kwargs)

    def with_custom_font(self, display_name: str, file_path: Path | str) -> "OverlayConfig":
        """カスタムフォントを1件登録し、使用フォントも切替えた新設定を返す。"""
        name = sanitize_custom_font_name(display_name, self.custom_fonts)
        err = validate_custom_font_file(file_path)
        if err is not None:
            raise ValueError(err)
        if name in ALL_BUILTIN_FONTS:
            raise ValueError(f"collides with builtin: {name!r}")
        merged = dict(self.custom_fonts)
        merged[name] = str(Path(file_path))
        return dataclasses.replace(self, custom_fonts=merged, font_key=name)

    def without_custom_font(self, display_name: str) -> "OverlayConfig":
        """カスタム1件を解除する。使っていた場合は既定フォントに戻す。"""
        if display_name in ALL_BUILTIN_FONTS:
            raise ValueError(f"builtin font cannot be removed: {display_name!r}")
        if display_name not in self.custom_fonts:
            raise ValueError(f"unknown custom font: {display_name!r}")
        merged = {k: v for k, v in self.custom_fonts.items() if k != display_name}
        next_key = self.font_key if self.font_key != display_name else DEFAULT_FONT
        return dataclasses.replace(self, custom_fonts=merged, font_key=next_key)
