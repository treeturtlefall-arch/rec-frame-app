"""本番UIの実ウィンドウを再現可能な条件で撮影する手動検証スクリプト。"""
from __future__ import annotations

import json
import platform
import sys
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rec_frame_app import App, work_area  # noqa: E402


OUTPUT = ROOT / "docs" / "ui-redesign" / "production" / "shots"


def settle(app: App) -> None:
    for _ in range(6):
        app.update()
        time.sleep(0.06)


def capture(app: App, name: str) -> None:
    settle(app)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    ImageGrab.grab(
        bbox=(x, y, x + app.winfo_width(), y + app.winfo_height())
    ).save(OUTPUT / name)


def set_image(app: App, size: tuple[int, int], name: str) -> None:
    app.src_image = Image.new("RGB", size, (174, 196, 188))
    app.src_path = name
    app._refresh()
    settle(app)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    app = App()
    app.attributes("-topmost", True)
    measurements = {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "tk": app.tk.call("info", "patchlevel"),
            "screen": [app.winfo_screenwidth(), app.winfo_screenheight()],
            "work_area": work_area(app),
            "dpi": app.winfo_fpixels("1i"),
        }
    }
    try:
        capture(app, "01_initial.png")
        app.open_sample()
        capture(app, "02_sample_loaded.png")

        app.mode_var.set("detail")
        app._on_mode_change()
        app.show_cross_var.set(True)
        app.show_timecode_var.set(True)
        app.use_exif_var.set(False)
        app.timecode_text_var.set("2026/09/18 PM 08:30")
        app._refresh()
        capture(app, "03_detail.png")

        app.geometry("960x600+30+30")
        app.mode_var.set("simple")
        app._on_mode_change()
        capture(app, "04_small.png")
        measurements["small_simple"] = {
            "window": [app.winfo_width(), app.winfo_height()],
            "content_height": app.style_page.content.winfo_reqheight(),
            "viewport_height": app.style_page.canvas.winfo_height(),
            "scrollbar_visible": bool(app.style_page.bar.winfo_ismapped()),
            "detail_tab_state": app.tabs.tab(app.detail_page, "state"),
        }

        app.geometry("1160x780+30+30")
        set_image(app, (1500, 2000), "portrait.png")
        measurements["portrait_1160x780"] = [
            app.photo.width(), app.photo.height()]
        set_image(app, (2000, 1500), "landscape.png")
        measurements["landscape_1160x780"] = [
            app.photo.width(), app.photo.height()]

        app.state("zoomed")
        app.mode_var.set("simple")
        app._on_mode_change()
        capture(app, "05_maximized_simple.png")
        measurements["maximized_simple"] = {
            "window": [app.winfo_width(), app.winfo_height()],
            "scrollbar_visible": bool(app.style_page.bar.winfo_ismapped()),
        }
        app.mode_var.set("detail")
        app._on_mode_change()
        capture(app, "06_maximized_detail.png")
        measurements["maximized_detail"] = {
            "window": [app.winfo_width(), app.winfo_height()],
            "scrollbar_visible": bool(app.detail_page.bar.winfo_ismapped()),
            "detail_tab_state": app.tabs.tab(app.detail_page, "state"),
        }

        app.state("normal")
        app.geometry("1160x700+30+30")
        app.language_display_var.set("English")
        app._on_language_selected()
        app.mode_var.set("simple")
        app._on_mode_change()
        capture(app, "07_english_simple.png")
        app.mode_var.set("detail")
        app._on_mode_change()
        capture(app, "08_english_detail.png")
        app.geometry("960x600+30+30")
        app.mode_var.set("simple")
        app._on_mode_change()
        capture(app, "09_english_small.png")
        measurements["english_small"] = {
            "window": [app.winfo_width(), app.winfo_height()],
            "scrollbar_visible": bool(app.style_page.bar.winfo_ismapped()),
            "detail_tab_state": app.tabs.tab(app.detail_page, "state"),
            "language": app.language_var.get(),
        }
    finally:
        for job in app.tk.call("after", "info"):
            try:
                app.after_cancel(job)
            except Exception:
                pass
        app.destroy()

    original_init = tk.Tk.__init__
    for percent in (125, 150):
        def scaled_init(root, *args, _percent=percent, **kwargs):
            original_init(root, *args, **kwargs)
            root.tk.call("tk", "scaling", 96 * (_percent / 100) / 72)

        with patch.object(tk.Tk, "__init__", scaled_init):
            scaled = App(language_override="en")
        try:
            scaled.attributes("-topmost", True)
            scaled.geometry("960x600+30+30")
            scaled.mode_var.set("detail")
            scaled._on_mode_change()
            capture(scaled, f"{10 if percent == 125 else 11}_english_scale_{percent}.png")
            right = (scaled.detail_page.canvas.winfo_rootx()
                     + scaled.detail_page.canvas.winfo_width())
            measurements[f"english_scale_{percent}"] = {
                "window": [scaled.winfo_width(), scaled.winfo_height()],
                "date_controls_fit": all(
                    widget.winfo_rootx() + widget.winfo_width() <= right
                    for widget in scaled._timecode_sel_widgets),
                "scrollbar_visible": bool(scaled.detail_page.bar.winfo_ismapped()),
            }
        finally:
            for job in scaled.tk.call("after", "info"):
                try:
                    scaled.after_cancel(job)
                except Exception:
                    pass
            scaled.destroy()

    (OUTPUT / "measurements.json").write_text(
        json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(measurements, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
