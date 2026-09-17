# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 単体exe用 spec (Windows 向け・SPEC §9)。

方針:
- エントリは `rec_frame_app.py` のみ。`rec_overlay / rec_config / rec_batch` は
  通常 import のため自動で同梱される。Pillow / tkinter も hook で自動検出。
- フォントは OS のシステムフォントを使うため `datas` 同梱なし
  (リポジトリにフォント非同梱・README に明記)。
- `console=True` を維持すること。GUI と CLI `--batch` を1本の exe で
  兼ねるためで、`windowed=True` にすると `--batch` の出力が見えなくなる。
- onefile 構成 (`EXE` に binaries/datas を全部畳む)。

再現ビルド:
    .venv\\Scripts\\python -m pip install pyinstaller
    .venv\\Scripts\\pyinstaller rec-frame-app.spec --clean --noconfirm
"""

block_cipher = None


a = Analysis(
    ['rec_frame_app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='rec-frame-app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
