"""撮影日時モード (SPEC §3.5) の自動化。

- 解決順: EXIF(DateTimeOriginal→Digitized→DateTime)→ファイルmtime→固定文
- バッチではファイル毎に追従する (01.pngと10.pngで日時が変わる)
"""
import dataclasses
import json
import os
from datetime import datetime

import pytest
from PIL import Image

from rec_batch import process_folder, process_single_file
from rec_config import (
    CONFIG_SCHEMA_VERSION,
    OverlayConfig,
    is_simple_equivalent,
    load_user_config,
    save_user_config,
)
from rec_overlay import (
    EXIF_DATETIME_TAGS,
    format_photo_timecode,
    load_base_image,
    parse_exif_datetimestr,
    photo_timecode_text,
    resolve_timecode_text,
)


def _save_jpeg_with_exif(path, exif_dict, size=(640, 360)):
    ex = Image.Exif()
    for tag, value in exif_dict.items():
        ex[tag] = value
    Image.new("RGB", size, (10, 20, 30)).save(path, exif=ex)


def test_schema_version_is_8():
    assert CONFIG_SCHEMA_VERSION == 8
    assert OverlayConfig().to_dict()["schema_version"] == 8


def test_exif_flag_defaults_off_and_old_json_compat(tmp_path):
    assert OverlayConfig().timecode_from_exif is False
    target = tmp_path / "config.json"
    target.write_text(json.dumps({"color": "white"}), encoding="utf-8")
    assert load_user_config(target).timecode_from_exif is False


def test_exif_flag_roundtrip_and_validation(tmp_path):
    target = tmp_path / "config.json"
    cfg = OverlayConfig(show_timecode=True, timecode_from_exif=True,
                        timecode_text="2026/09/14 PM 08:30")
    assert save_user_config(cfg, target) == target
    assert load_user_config(target) == cfg
    with pytest.raises(ValueError):
        OverlayConfig(timecode_from_exif="yes")


def test_exif_flag_breaks_simple_equivalence():
    assert is_simple_equivalent(OverlayConfig())
    assert not is_simple_equivalent(OverlayConfig(timecode_from_exif=True))


def test_parse_exif_datetimestr():
    assert parse_exif_datetimestr("2026:01:02 08:00:00") == datetime(2026, 1, 2, 8, 0, 0)
    assert parse_exif_datetimestr("2015:12:16 23:19:27") == datetime(2015, 12, 16, 23, 19, 27)
    assert parse_exif_datetimestr("") is None
    assert parse_exif_datetimestr(None) is None
    assert parse_exif_datetimestr("2026/01/02 08:00") is None
    assert parse_exif_datetimestr(b"2026:01:02 08:00:00") == datetime(2026, 1, 2, 8, 0, 0)


def test_format_photo_timecode_am_pm():
    assert format_photo_timecode(datetime(2026, 1, 2, 8, 0)) == "2026/01/02 AM 08:00"
    assert format_photo_timecode(datetime(2026, 1, 2, 0, 5)) == "2026/01/02 AM 12:05"
    assert format_photo_timecode(datetime(2026, 1, 2, 12, 30)) == "2026/01/02 PM 12:30"
    assert format_photo_timecode(datetime(2015, 12, 16, 23, 19)) == "2015/12/16 PM 11:19"


def test_exif_tag_priority_order():
    assert EXIF_DATETIME_TAGS == (36867, 36868, 306)


def test_exif_original_beats_datetime(tmp_path):
    p = tmp_path / "a.jpg"
    _save_jpeg_with_exif(p, {36867: "2026:01:02 08:00:00", 306: "2020:05:05 05:05:05"})
    img = load_base_image(p)
    assert photo_timecode_text(img, p, "FIXED") == "2026/01/02 AM 08:00"


def test_exif_datetime_fallback_like_real_photo(tmp_path):
    """DateTimeOriginalなし・DateTimeあり (test_picture_1.jpgと同型)。"""
    p = tmp_path / "b.jpg"
    _save_jpeg_with_exif(p, {306: "2015:12:16 23:19:27"})
    img = load_base_image(p)
    assert photo_timecode_text(img, p, "FIXED") == "2015/12/16 PM 11:19"


def test_mtime_fallback_for_png_without_exif(tmp_path):
    p = tmp_path / "shot.png"
    Image.new("RGB", (320, 200), (1, 2, 3)).save(p)
    ts = datetime(2026, 9, 14, 8, 24).timestamp()
    os.utime(p, (ts, ts))
    img = load_base_image(p)
    assert photo_timecode_text(img, p, "FIXED") == "2026/09/14 AM 08:24"


def test_fixed_fallback_when_nothing_available():
    assert photo_timecode_text(None, None, "FIXED") == "FIXED"
    assert photo_timecode_text(None, "Z:/no/such/file.jpg", "FIXED") == "FIXED"


def test_resolve_respects_flag(tmp_path):
    p = tmp_path / "a.jpg"
    _save_jpeg_with_exif(p, {36867: "2026:01:02 08:00:00"})
    img = load_base_image(p)
    on = OverlayConfig(show_timecode=True, timecode_from_exif=True, timecode_text="FIXED")
    off = OverlayConfig(show_timecode=True, timecode_text="FIXED")
    assert resolve_timecode_text(on, img, p) == "2026/01/02 AM 08:00"
    assert resolve_timecode_text(off, img, p) == "FIXED"


def test_batch_follows_per_file_exif(tmp_path):
    """01.jpgが08:00・10.jpgが08:24なら出力の日時も追従する。"""
    src_dir = tmp_path / "in"
    dst_dir = tmp_path / "out"
    src_dir.mkdir()
    _save_jpeg_with_exif(src_dir / "01.jpg", {36867: "2026:09:14 08:00:00"})
    _save_jpeg_with_exif(src_dir / "10.jpg", {36867: "2026:09:14 08:24:00"})
    cfg = OverlayConfig(show_timecode=True, timecode_from_exif=True,
                        timecode_text="FIXED")
    result = process_folder(src_dir, dst_dir, cfg)
    assert result.success == 2
    out1 = load_base_image(dst_dir / "01_rec.jpg")
    out2 = load_base_image(dst_dir / "10_rec.jpg")
    # 日時文が異なる=追従している (同一設定の固定文バッチでは一致するはず)
    assert out1.convert("RGB").tobytes() != out2.convert("RGB").tobytes()
    # 固定文モードでは2出力が一致することの裏付け
    fixed = process_folder(src_dir, tmp_path / "out2",
                           OverlayConfig(show_timecode=True, timecode_text="FIXED"))
    assert fixed.success == 2
    f1 = load_base_image(tmp_path / "out2" / "01_rec.jpg")
    f2 = load_base_image(tmp_path / "out2" / "10_rec.jpg")
    assert f1.convert("RGB").tobytes() == f2.convert("RGB").tobytes()


def test_batch_png_follows_mtime(tmp_path):
    src_dir = tmp_path / "in"
    dst_dir = tmp_path / "out"
    src_dir.mkdir()
    for name, minute in (("01.png", 0), ("10.png", 24)):
        p = src_dir / name
        Image.new("RGB", (640, 360), (10, 20, 30)).save(p)
        ts = datetime(2026, 9, 14, 8, minute).timestamp()
        os.utime(p, (ts, ts))
    cfg = OverlayConfig(show_timecode=True, timecode_from_exif=True)
    result = process_folder(src_dir, dst_dir, cfg)
    assert result.success == 2
    o1 = load_base_image(dst_dir / "01_rec.png")
    o2 = load_base_image(dst_dir / "10_rec.png")
    assert o1.convert("RGB").tobytes() != o2.convert("RGB").tobytes()


def test_process_single_file_matches_resolved_composite(tmp_path):
    from rec_overlay import composite_with_config

    src = tmp_path / "a.jpg"
    _save_jpeg_with_exif(src, {36867: "2026:01:02 08:00:00"})
    dest = tmp_path / "a_rec.png"  # JPEG再保存は不可逆のため比較はPNGで
    cfg = OverlayConfig(show_timecode=True, timecode_from_exif=True, timecode_text="FIXED")
    process_single_file(src, dest, cfg)
    base = load_base_image(src)
    expected = composite_with_config(
        base, dataclasses.replace(cfg, timecode_text="2026/01/02 AM 08:00"))
    actual = load_base_image(dest)
    assert expected.convert("RGB").tobytes() == actual.convert("RGB").tobytes()
