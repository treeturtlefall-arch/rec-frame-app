"""フォルダ一括処理の純粋ロジック層。GUI/CLIから共有する。

SPEC §10.1 の最小実装。GUIと完全一致させるため合成は
`composite_with_config` に委譲するのみで、独自の描画は持たない。

- 対象: 入力フォルダ直下のみ(非再帰)。拡張子 png/jpg/jpeg/webp/bmp(大小不問)。
- 命名: `{元名}_rec{拡張子}`。衝突時は `{元名}_rec_01{拡張子}` のように連番。
- 対象外はスキップし、成功/失敗/スキップをレポートする。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from rec_config import SUPPORTED_EXTENSIONS, OverlayConfig
from rec_i18n import DEFAULT_LANGUAGE, LanguageKey, normalize_language, tr
from rec_overlay import (
    composite_with_config,
    load_base_image,
    resolve_photo_config,
    save_composited_image,
)

SUPPORTED_EXTS = SUPPORTED_EXTENSIONS


def is_supported_image(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTS


def resolve_output_path(out_dir: Path, src: Path) -> Path:
    """出力先を決める。存在すれば `_rec_01` のように連番で別名保存する。"""
    stem, suffix = src.stem, src.suffix
    candidate = out_dir / f"{stem}_rec{suffix}"
    if not candidate.exists():
        return candidate
    i = 1
    while True:
        candidate = out_dir / f"{stem}_rec_{i:02d}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


@dataclass
class BatchError:
    code: str
    values: dict[str, str] = field(default_factory=dict)

    def format(self, language: LanguageKey = DEFAULT_LANGUAGE) -> str:
        return tr(language, f"batch.error.{self.code}", **self.values)


@dataclass
class BatchResult:
    success: int = 0
    failed: int = 0
    skipped: int = 0
    outputs: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    error_details: list[BatchError] = field(default_factory=list)

    def add_error(
        self, code: str, language: LanguageKey = DEFAULT_LANGUAGE, **values: object
    ) -> None:
        detail = BatchError(code, {key: str(value) for key, value in values.items()})
        self.error_details.append(detail)
        self.errors.append(detail.format(language))


def process_single_file(src: Path, dest: Path, config: OverlayConfig) -> Path:
    """1件処理。合成〜保存まで。GUI単発保存と同一経路。

    撮影日時モードON時はファイル毎に日時文を解決する
    (EXIF→mtime→固定文。SPEC §3.5)。
    """
    base = load_base_image(src)
    cfg = resolve_photo_config(config, base, src)
    out = composite_with_config(base, cfg)
    save_composited_image(out, dest)
    return dest


def process_folder(
    input_dir: Path | str,
    output_dir: Path | str,
    config: OverlayConfig,
    progress: Callable[[int, int, str], None] | None = None,
    language: LanguageKey | None = None,
) -> BatchResult:
    """フォルダ直下を一括処理する。例外は件数に畳み、raiseしない。"""
    src_dir = Path(input_dir)
    dst_dir = Path(output_dir)
    language = normalize_language(language or config.ui_language)
    result = BatchResult()
    if not src_dir.is_dir():
        result.add_error("input_missing", language, path=src_dir)
        return result
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        result.add_error("output_create", language, path=dst_dir, error=e)
        return result

    files = sorted(p for p in src_dir.iterdir() if p.is_file())
    total = len(files)
    for idx, src in enumerate(files):
        if progress is not None:
            try:
                progress(idx, total, src.name)
            except Exception:
                pass
        if not is_supported_image(src):
            result.skipped += 1
            continue
        try:
            dest = resolve_output_path(dst_dir, src)
            process_single_file(src, dest, config)
            result.success += 1
            result.outputs.append(dest)
        except Exception as e:  # 1件の失敗で全体を止めない
            result.failed += 1
            result.add_error("file", language, name=src.name, error=e)
    if progress is not None:
        try:
            progress(total, total, "")
        except Exception:
            pass
    return result
