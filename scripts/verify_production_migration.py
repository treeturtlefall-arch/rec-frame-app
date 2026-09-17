"""隔離設定領域で本番UI移植の統合確認を行い、JSON結果を残す。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "ui-redesign" / "production" / "verification.json"


def destroy(app) -> None:
    app.update_idletasks()
    for job in app.tk.call("after", "info"):
        try:
            app.after_cancel(job)
        except Exception:
            pass
    app.destroy()


def main() -> None:
    results: list[str] = []
    with tempfile.TemporaryDirectory(prefix="rec-frame-production-") as temp:
        scratch = Path(temp)
        os.environ["APPDATA"] = str(scratch / "appdata")
        os.environ["XDG_CONFIG_HOME"] = str(scratch / "xdg")
        sys.path.insert(0, str(ROOT))

        import rec_frame_app
        from rec_batch import process_single_file
        from rec_config import OverlayConfig, get_user_config_path, save_user_config
        from rec_overlay import load_base_image, save_composited_image

        config_path = get_user_config_path()
        assert scratch in config_path.parents

        save_user_config(OverlayConfig())
        app = rec_frame_app.App()
        app.withdraw()
        try:
            assert app.mode_var.get() == "simple"
            assert app.tabs.tab(app.detail_page, "state") == "hidden"
            assert str(app.save_button["state"]) == "disabled"
        finally:
            destroy(app)
        results.append("Simple-equivalent config restarts in simple mode with detail tab hidden")

        detail = OverlayConfig(
            color="white", font_key="Consolas(等幅)", thickness="large",
            effect="oled", show_frame=False, show_battery=True,
            show_rec=True, show_cross=True, show_timecode=True,
            timecode_text="2024/02/03 AM 04:05", timecode_from_exif=True,
            ui_language="en")
        save_user_config(detail)
        app = rec_frame_app.App()
        app.withdraw()
        try:
            assert app.mode_var.get() == "detail"
            assert app.language_var.get() == "en"
            assert app.language_label.cget("text") == "Language"
            assert app.tabs.tab(app.detail_page, "state") == "normal"
            assert app.tabs.select() == str(app.detail_page)
            assert str(app.timecode_entry["state"]) == "disabled"
            assert app.tc_year_spin.get() == "2024"
            app.color_var.set("black")
            app._refresh()
        finally:
            destroy(app)
        app = rec_frame_app.App()
        app.withdraw()
        try:
            assert app.color_var.get() == "black"
            assert app.thickness_var.get() == "large"
            assert app.use_exif_var.get()
            assert app.language_var.get() == "en"
        finally:
            destroy(app)
        results.append("Detailed, automatic-date, and English UI settings persist across restart")

        src = scratch / "source.png"
        Image.new("RGB", (640, 360), (60, 90, 120)).save(src)
        stamp = datetime(2025, 6, 7, 12, 30).timestamp()
        os.utime(src, (stamp, stamp))
        for effect in ("off", "oled", "2000s"):
            cfg = OverlayConfig(
                color="white", effect=effect, show_cross=True,
                show_timecode=True, timecode_from_exif=True)
            save_user_config(cfg)
            app = rec_frame_app.App()
            app.withdraw()
            try:
                app.src_path = str(src)
                app.src_image = load_base_image(src)
                actual = app._render()
            finally:
                destroy(app)
            dest = scratch / f"batch-{effect}.png"
            process_single_file(src, dest, cfg)
            expected = load_base_image(dest)
            assert actual.size == expected.size
            assert actual.tobytes() == expected.convert("RGBA").tobytes()
        results.append("GUI and batch pixels match for fixed mtime across all three effects")

        app = rec_frame_app.App()
        app.withdraw()
        try:
            app.open_sample()
            assert app.src_image.size == app.result_image.size == (1600, 1000)
            assert app.src_path == "rec-frame-sample.png"
            assert str(app.save_button["state"]) == "normal"
            rendered = app.result_image
        finally:
            destroy(app)
        for suffix in (".png", ".jpg", ".webp"):
            target = scratch / f"saved{suffix}"
            save_composited_image(rendered, target)
            with Image.open(target) as saved:
                assert saved.size == rendered.size
                if suffix == ".jpg":
                    assert saved.mode == "RGB"
                elif suffix == ".png":
                    assert saved.mode == "RGBA"
                else:
                    assert saved.format == "WEBP"
        results.append("Generated sample and PNG/JPEG/WebP original-size save paths pass")

        help_run = subprocess.run(
            [sys.executable, "-B", str(ROOT / "rec_frame_app.py"), "--help"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        assert help_run.returncode == 0 and "--batch" in help_run.stdout

        input_dir, output_dir = scratch / "in", scratch / "out"
        input_dir.mkdir()
        output_dir.mkdir()
        Image.new("RGB", (96, 64), "#844").save(input_dir / "one.png")
        (input_dir / "skip.txt").write_text("skip", encoding="utf-8")
        for _ in range(2):
            batch_run = subprocess.run(
                [sys.executable, "-B", str(ROOT / "rec_frame_app.py"),
                 "--batch", str(input_dir), str(output_dir)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            assert batch_run.returncode == 0
            assert "成功: 1" in batch_run.stdout and "スキップ: 1" in batch_run.stdout
        assert (output_dir / "one_rec.png").exists()
        assert (output_dir / "one_rec_01.png").exists()

        explicit = scratch / "explicit.json"
        explicit.write_text(
            json.dumps(OverlayConfig(color="white").to_dict(), ensure_ascii=False),
            encoding="utf-8")
        explicit_out = scratch / "explicit-out"
        explicit_run = subprocess.run(
            [sys.executable, "-B", str(ROOT / "rec_frame_app.py"),
             "--batch", str(input_dir), str(explicit_out),
             "--config", str(explicit)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        assert explicit_run.returncode == 0 and (explicit_out / "one_rec.png").exists()
        english_out = scratch / "english-out"
        english_run = subprocess.run(
            [sys.executable, "-B", str(ROOT / "rec_frame_app.py"),
             "--batch", str(input_dir), str(english_out), "--lang", "en"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        assert english_run.returncode == 0
        assert "Succeeded: 1" in english_run.stdout
        results.append("Japanese/English CLI, remembered/explicit config batch, counts and collision numbering pass")

        assert scratch in config_path.parents
        results.append("All preference writes stayed inside the temporary APPDATA/XDG area")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps({"results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("\n".join(results))


if __name__ == "__main__":
    main()
