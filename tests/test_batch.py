"""バッチ最小限 (SPEC §10.1) のテスト。GUIを開かず純粋ロジックのみ。"""
import json

from PIL import Image

from rec_batch import process_folder, resolve_output_path
from rec_config import OverlayConfig
from rec_overlay import composite_with_config, load_base_image


def _make_image(path, size=(640, 360), color=(10, 20, 30)):
    Image.new("RGB", size, color).save(path)


def test_output_naming_and_collision(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    src = tmp_path / "photo.jpg"
    src.touch()
    assert resolve_output_path(out, src).name == "photo_rec.jpg"
    (out / "photo_rec.jpg").touch()
    assert resolve_output_path(out, src).name == "photo_rec_01.jpg"
    (out / "photo_rec_01.jpg").touch()
    assert resolve_output_path(out, src).name == "photo_rec_02.jpg"


def test_process_folder_success_skip(tmp_path):
    src_dir = tmp_path / "in"
    dst_dir = tmp_path / "out"
    src_dir.mkdir()
    _make_image(src_dir / "a.png")
    _make_image(src_dir / "b.JPG")
    (src_dir / "note.txt").write_text("skip me", encoding="utf-8")
    cfg = OverlayConfig()
    result = process_folder(src_dir, dst_dir, cfg)
    assert result.success == 2
    assert result.skipped == 1
    assert result.failed == 0
    assert (dst_dir / "a_rec.png").exists()
    assert (dst_dir / "b_rec.JPG").exists()


def test_batch_matches_single_composite(tmp_path):
    src_dir = tmp_path / "in"
    dst_dir = tmp_path / "out"
    src_dir.mkdir()
    _make_image(src_dir / "a.png", size=(640, 360))
    cfg = OverlayConfig(color="white", thickness="small")
    result = process_folder(src_dir, dst_dir, cfg)
    assert result.success == 1
    expected = composite_with_config(load_base_image(src_dir / "a.png"), cfg)
    actual = load_base_image(dst_dir / "a_rec.png")
    assert expected.convert("RGB").tobytes() == actual.convert("RGB").tobytes()


def test_broken_image_counts_as_failed(tmp_path):
    src_dir = tmp_path / "in"
    dst_dir = tmp_path / "out"
    src_dir.mkdir()
    (src_dir / "bad.png").write_text("not an image", encoding="utf-8")
    result = process_folder(src_dir, dst_dir, OverlayConfig())
    assert result.success == 0
    assert result.failed == 1
    assert result.errors


def test_missing_input_dir_reports_error(tmp_path):
    result = process_folder(tmp_path / "nope", tmp_path / "out", OverlayConfig())
    assert result.success == 0
    assert result.errors


def test_cli_config_file(tmp_path):
    from rec_frame_app import run_batch_cli

    src_dir = tmp_path / "in"
    dst_dir = tmp_path / "out"
    src_dir.mkdir()
    _make_image(src_dir / "a.png")
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"color": "white"}), encoding="utf-8")
    code = run_batch_cli(str(src_dir), str(dst_dir), str(cfg_path))
    assert code == 0
    assert (dst_dir / "a_rec.png").exists()


def test_cli_bad_config_returns_2(tmp_path):
    from rec_frame_app import run_batch_cli

    code = run_batch_cli(str(tmp_path), str(tmp_path / "out"), str(tmp_path / "nope.json"))
    assert code == 2
