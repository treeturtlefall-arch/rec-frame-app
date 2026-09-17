"""PyInstaller 配布 (spec + Actions) の回帰テスト。exe 自体のビルドはしない。"""
import py_compile
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = REPO / "rec-frame-app.spec"
WORKFLOW = REPO / ".github" / "workflows" / "release-exe.yml"


def test_spec_exists_and_compiles():
    assert SPEC.exists(), "rec-frame-app.spec がありません"
    py_compile.compile(str(SPEC), doraise=True)


def test_spec_is_onefile_console():
    text = SPEC.read_text(encoding="utf-8")
    # エントリは rec_frame_app.py のみ・単体exe名・console 維持が壊れていないこと
    assert "rec_frame_app.py" in text
    assert "name='rec-frame-app'" in text
    assert "console=True" in text
    # GUI+CLI 兼用のため windowed=True への置き換えは禁止
    # (コメント・docstring 内の言及は許容し、実コードの EXE 引数のみ検査)
    assert re.search(r"(?m)^\s*windowed\s*=\s*True", text) is None


def test_release_workflow_exists_and_builds_spec():
    assert WORKFLOW.exists(), ".github/workflows/release-exe.yml がありません"
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "rec-frame-app.spec" in text
    assert "pyinstaller" in text.lower()
    assert "upload-artifact" in text
    assert "windows-latest" in text
