# AGENTS.md

tkinter アプリ。任意画像にファインダー風オーバーレイ（四隅枠＋電池＋赤丸REC＋中央十字＋日時＋UI劣化エフェクト）を合成する。オーバーレイ寸法とロードマップの正本は `SPEC.md`（日本語）。

## 実行

```bat
.venv\Scripts\python rec_frame_app.py
.venv\Scripts\python rec_frame_app.py --batch 入力フォルダ 出力フォルダ [--config 設定.json] [--lang ja|en]
.venv\Scripts\python -m pytest -q
```

- Python >=3.11 + Pillow のみ（`requirements.txt` / `pyproject.toml`: `Pillow==12.1.0`、test は `pytest`）。tkinter は標準ライブラリ（CI の Ubuntu は `python3-tk` を apt 導入）。
- CI: `.github/workflows/ci.yml`（pytest、Python 3.11/3.12 × Ubuntu/Windows）。
- 配布 exe: `rec-frame-app.spec`（onefile）＋ `.github/workflows/release-exe.yml`（`v*` タグで Windows ビルド→Release に `rec-frame-app.exe` 添付、手動実行可、smoke は `--help`＋`--batch` 実走）。

## 構成

- `rec_frame_app.py` — GUI 薄層＋エントリーポイント（開く / プレビュー / 保存 / 一括処理... / CLI `--batch`）。画像生成の実体は持たない。
- `rec_overlay.py` — 純粋な画像生成層（GUI 非依存）。`create_rec_overlay_with_config()` / `composite_with_config()` が正本。`create_rec_overlay()` / `composite_with_overlay()` は後方互換の再エクスポート。`load_base_image()` / `save_composited_image()` / `apply_ui_effects()` を持つ。
- `rec_config.py` — `OverlayConfig`（描画設定＋`ui_language`、`schema_version=8`）＋設定I/O・日時・カスタムフォント helpers。`DEFAULT_FONT` は `Arial Narrow Bold(細長)`。
- `rec_i18n.py` — GUI・ダイアログ・バッチ・CLIで共有する日英翻訳層。内部設定キーと翻訳表示名を分離し、欠落キーは日本語へフォールバック。
- `rec_batch.py` — フォルダ一括処理の純粋ロジック。`process_folder()` / `process_single_file()` / `resolve_output_path()`。合成は `composite_with_config` 委譲で GUI と完全一致。
- `tests/` — pytest（等距離・同寸出力・全フォント描画・設定記憶・バッチ・カスタムフォント・撮影日時・GUI/バッチ描画一致・本番UI状態遷移・日英切替・`conftest.py` 共通ヘルパー。計220件）。`test_dist.py` は配布spec・ワークフローの静的検査（exeのビルド・バイト一致検証は行わない）。GUI関連はTk画面が使えない環境ではスキップする。
- `scripts/` — `capture_production_ui.py`（本番実画面撮影）/ `verify_production_migration.py`（隔離設定での移植統合検証）。成果は `docs/ui-redesign/production/` に保存。

## 設定・バッチ仕様

- 設定は自動記憶（`%APPDATA%/rec-frame-app/config.json`、他 OS は XDG。UI 追加なし）。枠色・フォント・枠太さ・エフェクト・要素 ON/OFF・日時文を復元。`mode` 自体は保存対象外で `show_*` から簡易/詳細を推定。欠落・破損・旧 JSON は既定値吸収。
- 表示言語は `ui_language=ja|en` として同じ設定へ保存。既存設定は日本語。切替で描画設定・画像・入力・タブ・スクロールを変えない。CLIは `--lang` が保存値より優先。
- バッチは入力フォルダ直下のみ（非再帰、png/jpg/jpeg/webp/bmp）。GUI「一括処理...」は現在の設定を使用（設定ファイル選択なし）。CLI `--config` 省略時は自動記憶。命名 `{元名}_rec{拡張子}`、衝突時は `_rec_01` 連番。対象外スキップ＋成功/失敗/スキップの件数レポート。

## 注意点（壊さないこと）

- 写真毎の日時設定は `rec_overlay.resolve_photo_config()` をGUI・バッチから共有する。元の設定は変更せず、EXIF→mtime→固定文の順で解決する。GUIの初期日時書式も `format_photo_timecode()` を使用。入力欄への反映は値変化時のみ行い、traceによる再描画ループを防ぐ。
- オーバーレイは `s = min(w, h)` 基準のベクター生成。PNG 素材の貼り付け・拡大縮小はしない。
- 右・下隅は `w - 1 - margin` / `h - 1 - margin`：PIL の `rectangle` は inclusive 描画のため、`-1` 補正で四隅の端距離をピクセル一致させる。
- 赤丸＋REC 文字はインク中央の中心線 `cy` を共有し `anchor="lt"` で描画（`cy - text_h//2` 配置。旧 `lm` は行ボックス中央のためフォント依存の浮きが出る）。`rec_dy = int(s*0.01)` の下げ補正を維持すること。
- 枠太さ（小/中/大）は四隅枠のみ連動。電池線幅・REC 丸・中央十字線幅は独立値のため連動させない。中央十字・日時・`show_*` 全 OFF は透明のまま（合成＝ベース一致）。
- エフェクトは UI オーバーレイ層にのみ適用し原本は変えない。適用順序は RGB シフト→ブルーム→低解像度化で固定。ブルーム弱は枠色で分岐（白: `radius=s*0.006`/α190、黒: `radius=s*0.005`/α160）。CRT/VHS は破壊処理のため不採用。
- 画像は `ImageOps.exif_transpose` 経由で開く。外すとスマホ写真の向き・縦横比が外部ビューアーとずれる。
- JPEG 保存は `convert("RGB")` して `quality=95`。PNG / WebP は RGBA のまま保存。
- プレビューは `thumbnail()` で `canvas_label` 域に収め、`<Configure>` を 150ms デバウンス。`self.photo` の参照保持がないと GC で画像が消える。日時手入力欄の再描画・保存は 300ms デバウンス。
- フォントは `C:/Windows/Fonts` 優先、DejaVu フォールバック、最終手段 `load_default()`。`color` 切替は枠・電池・REC 文字・十字・日時のみ対象。赤丸は常に赤。フォントはリポジトリ・exe ともに非同梱（README に明記）。
- `rec-frame-app.spec` は `console=True` を維持すること。GUI と CLI `--batch` を 1 本の exe で兼ねるため `windowed=True` 化は禁止。

## git運用（初心者ユーザーの安全策）

- commit・push・タグ付け・PR作成はユーザーの明示指示があるまで行わない。`git add` の前に必ず `git status --short` を確認する。
- 開発途中の中間生成物を深く考えず上げようとしていたら、実行前に警告して立ち止まること。特に以下は公開禁止（`.gitignore` 済みのはずだが毎回 `git ls-files` で混入確認）：
  - `ui_prototypes/`（試作・大量スクショ・`handoff/*.bundle` 等の履歴塊）
  - `docs/ui-redesign/`（検証メモ・測定JSON・撮影画像）
  - `build/ dist/ .venv/ test_picture_*`、`#*` の作業メモ、`*.env / *.pem / *.key`、LLM作業メモ類
- push前の確認：絶対パス（`C:\Users\...`）・私用メール・トークン類が `git grep` で出ないこと。作者情報は `treeturtlefall-arch@users.noreply.github.com` を使用し、私用メールを履歴に入れない。
