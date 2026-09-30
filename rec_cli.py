"""GUIに依存しないCLIの引数解析・一括処理。"""
import argparse
import json
import sys
from pathlib import Path

from rec_batch import process_folder
from rec_config import OverlayConfig, load_user_config
from rec_i18n import normalize_language, tr


def run_batch_cli(
    input_dir: str,
    output_dir: str,
    config_path: str | None = None,
    language: str | None = None,
) -> int:
    """CLI `--batch` の実体。GUIを開かずフォルダ一括処理する。"""
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


def parse_cli_args(argv: list[str] | None = None) -> argparse.Namespace:
    """起動引数を解析する。明示的なargvでGUIなしに検証できる。"""
    arguments = sys.argv[1:] if argv is None else argv
    language = _preferred_cli_language(arguments)
    parser = argparse.ArgumentParser(
        description=tr(language, "cli.description"), add_help=False)
    parser.add_argument(
        "-h", "--help", action="help", help=tr(language, "cli.help"))
    parser.add_argument(
        "--batch", nargs=2,
        metavar=(tr(language, "cli.input_metavar"),
                 tr(language, "cli.output_metavar")),
        help=tr(language, "cli.batch_help"))
    parser.add_argument(
        "--config", default=None, help=tr(language, "cli.config_help"))
    parser.add_argument(
        "--lang", choices=("ja", "en"), default=None,
        help=tr(language, "cli.lang_help"))
    return parser.parse_args(arguments)


def configure_console() -> None:
    """西欧ロケールのconsoleでも日本語help・バッチ出力を可能にする。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
