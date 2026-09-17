"""オーバーレイ設定の定義。SPEC.md §3・§10.2 が正本。

GUI・バッチ・CLI で共有するための薄い設定層。
SPEC §10.1〜10.2 のバッチ用 JSON `{color, font_key, thickness, show_*, show_cross, show_timecode, timecode_text, ui_language}` と互換の dict 変換を持つ。
旧 `{color, font_key}` は thickness=medium・show_*=True・show_cross=False・show_timecode=False として読込。
"""
from __future__ import annotations

import dataclasses
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from rec_i18n import DEFAULT_LANGUAGE, LanguageKey, normalize_language, tr

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})

OverlayColor = Literal["black", "white"]
ThicknessKey = Literal["small", "medium", "large"]
EffectKey = Literal["off", "oled", "2000s"]

# 枠太さの表示名と内部キーの対応 (GUIラジオ用)
THICKNESS_CHOICES: dict[str, ThicknessKey] = {
    "小": "small",
    "中": "medium",
    "大": "large",
}
DEFAULT_THICKNESS: ThicknessKey = "medium"

# REC文字に使えるフォント候補 (表示名: ファイル名)
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

# ファインダーUI劣化エフェクトの選択肢 (表示名: 内部キー、SPEC §3.6)
EFFECT_CHOICES: dict[str, EffectKey] = {
    "OFF(クリーン)": "off",
    "OLED(微発光)": "oled",
    "2000sデジカメ": "2000s",
}
DEFAULT_EFFECT: EffectKey = "off"

CONFIG_SCHEMA_VERSION = 8

# ユーザーが追加できるフォントの拡張子 (SPEC §5)。ttcは先頭フェイス(index=0)を使用。
CUSTOM_FONT_EXTENSIONS: frozenset[str] = frozenset({".ttf", ".otf", ".ttc"})

APP_CONFIG_DIRNAME = "rec-frame-app"
APP_CONFIG_FILENAME = "config.json"


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
    """カスタムフォントのコピー先。設定JSONと同じルート直下の `fonts/`。

    絶対パス保存だと元ファイルの移動・削除に弱いため、追加時にここへ
    コピーしてから `custom_fonts` に登録する (SPEC §5)。
    """
    return get_user_config_path().parent / "fonts"


def get_system_font_dirs() -> list[Path]:
    """OSのフォント格納先の候補。存在するものだけ返す (優先順)。

    - Windows: `%LOCALAPPDATA%/Microsoft/Windows/Fonts` (ユーザー) →
      `C:/Windows/Fonts` (システム)。システム側を後にしているのは、
      `C:/Windows/Fonts` が仮想シェルフォルダのため「開く」ダイアログで
      空に見えることがあり、通常フォルダのユーザー側の方が確実だから。
      読み取り権限の問題ではない (`is_dir` では見える)。
    - Linux/macOS: `/usr/share/fonts` → `~/.local/share/fonts` → `~/.fonts`
      → macOS用 `/System/Library/Fonts` → `/Library/Fonts` → `~/Library/Fonts`
    """
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
    """組込10種の表示名か。"""
    return font_key in FONT_CHOICES


def get_all_font_names(config: "OverlayConfig") -> list[str]:
    """GUI選択肢用。組込＋カスタムの表示名一覧 (組込順→登録順)。"""
    names = list(FONT_CHOICES)
    for name in config.custom_fonts:
        if name not in FONT_CHOICES:
            names.append(name)
    return names


def resolve_custom_font_path(
    font_key: str, custom_fonts: dict[str, str] | None
) -> Path | None:
    """カスタム名に対応する実ファイル。存在しない・組込名なら None。"""
    if not custom_fonts or font_key in FONT_CHOICES:
        return None
    raw = custom_fonts.get(font_key)
    if not raw:
        return None
    return Path(raw)


def sanitize_custom_font_name(proposed: str, custom_fonts: dict[str, str] | None) -> str:
    """表示名の衝突回避。組込・登録済みと重なったら `名 2` / `名 3` …を付ける。"""
    base = (proposed or "").strip() or "カスタムフォント"
    if base not in FONT_CHOICES and not (custom_fonts and base in custom_fonts):
        return base
    i = 2
    while True:
        candidate = f"{base} {i}"
        if candidate not in FONT_CHOICES and not (custom_fonts and candidate in custom_fonts):
            return candidate
        i += 1


def validate_custom_font_file(
    path: Path | str, language: LanguageKey = DEFAULT_LANGUAGE
) -> str | None:
    """追加前の軽量検査。問題なければ None、あれば理由文を返す。

    Pillowでの読込可否までは見ない (設定層にPillow依存を持ち込まない。
    描画層 `_load_font` が失敗時は組込フォールバックする)。
    """
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
    )


_TIMECODE_RE = re.compile(
    r"^\s*(\d{1,4})/(\d{1,2})/(\d{1,2})\s+(AM|PM)\s+(\d{1,2}):(\d{1,2})\s*$"
)


def compose_timecode_text(year, month, day, ampm, hour, minute) -> str:
    """日時セレクタ値を `YYYY/MM/DD AM/PM HH:MM` に整形する (SPEC §10.3)。

    検証は緩和：暦妥当性チェックなし。1800年・2月30日のような値もそのまま通す。
    数値以外が渡された場合は ValueError (int変換失敗) を送出する。
    """
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
    font_key: str = DEFAULT_FONT
    thickness: ThicknessKey = DEFAULT_THICKNESS
    show_frame: bool = True
    show_battery: bool = True
    show_rec: bool = True
    show_cross: bool = False
    show_timecode: bool = False
    timecode_text: str = ""
    effect: EffectKey = "off"
    custom_fonts: dict[str, str] = field(default_factory=dict)
    # 撮影日時モード。Trueなら固定文の代わりに写真毎の日時
    # (EXIF DateTimeOriginal→Digitized→DateTime→ファイルmtime→固定文) を使う。
    timecode_from_exif: bool = False
    # GUI/CLIの表示言語。描画結果と簡易/詳細モード推定には影響しない。
    ui_language: LanguageKey = DEFAULT_LANGUAGE

    def __post_init__(self) -> None:
        if self.color not in ("black", "white"):
            raise ValueError(f"color must be 'black'|'white', got {self.color!r}")
        if not isinstance(self.custom_fonts, dict):
            raise ValueError(f"custom_fonts must be dict, got {self.custom_fonts!r}")
        for k, v in self.custom_fonts.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(f"custom_fonts keys must be non-empty str, got {k!r}")
            if k in FONT_CHOICES:
                raise ValueError(f"custom_fonts key collides with builtin: {k!r}")
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"custom_fonts values must be non-empty str, got {v!r}")
        if self.font_key not in FONT_CHOICES and self.font_key not in self.custom_fonts:
            raise ValueError(f"unknown font_key: {self.font_key!r}")
        if self.thickness not in ("small", "medium", "large"):
            raise ValueError(
                f"thickness must be 'small'|'medium'|'large', got {self.thickness!r}"
            )
        for key in ("show_frame", "show_battery", "show_rec", "show_cross",
                      "show_timecode", "timecode_from_exif"):
            if not isinstance(getattr(self, key), bool):
                raise ValueError(f"{key} must be bool, got {getattr(self, key)!r}")
        if not isinstance(self.timecode_text, str):
            raise ValueError(f"timecode_text must be str, got {self.timecode_text!r}")
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
                # custom_fontsは辞書以外・壊れた中身でも落とさず吸収する。
                # from_dict直呼びの不正は __post_init__ のValueErrorで通知する。
                if f.name == "custom_fonts":
                    if isinstance(value, dict):
                        cleaned = {
                            k: v for k, v in value.items()
                            if isinstance(k, str) and k.strip()
                            and isinstance(v, str) and v.strip()
                            and k not in FONT_CHOICES
                        }
                        kwargs[f.name] = cleaned
                    # 欠落・非辞書は既定{}に任せるため何もしない
                elif f.name == "ui_language":
                    kwargs[f.name] = normalize_language(value)
                else:
                    kwargs[f.name] = value
        # 欠落フィールドの既定値・default_factoryはdataclassの生成処理に任せる。
        return cls(**kwargs)

    def with_custom_font(self, display_name: str, file_path: Path | str) -> "OverlayConfig":
        """カスタムフォントを1件登録し、使用フォントも切替えた新設定を返す。"""
        name = sanitize_custom_font_name(display_name, self.custom_fonts)
        err = validate_custom_font_file(file_path)
        if err is not None:
            raise ValueError(err)
        if name in FONT_CHOICES:
            raise ValueError(f"collides with builtin: {name!r}")
        merged = dict(self.custom_fonts)
        merged[name] = str(Path(file_path))
        return dataclasses.replace(self, custom_fonts=merged, font_key=name)

    def without_custom_font(self, display_name: str) -> "OverlayConfig":
        """カスタム1件を解除する。使っていた場合は既定フォントに戻す。"""
        if display_name in FONT_CHOICES:
            raise ValueError(f"builtin font cannot be removed: {display_name!r}")
        if display_name not in self.custom_fonts:
            raise ValueError(f"unknown custom font: {display_name!r}")
        merged = {k: v for k, v in self.custom_fonts.items() if k != display_name}
        next_key = self.font_key if self.font_key != display_name else DEFAULT_FONT
        return dataclasses.replace(self, custom_fonts=merged, font_key=next_key)
