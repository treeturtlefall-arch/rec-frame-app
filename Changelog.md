# Changelog

このプロジェクトの notable な変更を記録する。形式は Keep a Changelog の簡易版。
日付は JST。詳細仕様は `SPEC.md` が正本。

## [Unreleased]

## [0.2.0] - 2026-09-18

### Added

- 日本語／英語の即時切替
  - ヘッダーの言語欄で切替え、`ui_language` として自動記憶。旧設定は日本語で安全に読込（schema v8）
  - 画面、ネイティブダイアログ、バッチ進捗・結果、CLI help／出力を日英対応。CLIは `--lang ja|en`
  - 組込フォント・エフェクト・太さは内部キーと翻訳表示名を分離。カスタムフォント名、日時文、ファイル名、描画結果は変更しない
  - 切替時に画像・入力値・選択タブ・スクロール位置を保持。英語や高倍率で幅が足りないチェック欄は1列へ自動調整
  - `rec_i18n.py` と `tests/test_i18n.py` を追加。翻訳カタログ、旧設定互換、日英ピクセル一致、バッチエラー、CLIを検証

### Changed

- 採用済みProposal Bを本番GUIへ移植
  - 左設定・右プレビュー、淡い背景・暗いプレビュー・緑の主操作に刷新。初期最大1160×700、最小目安960×600
  - 簡易時は「表示・日時」タブを隠し、詳細時に再表示して自動選択。詳細値は保持
  - 開く・保存・一括処理を固定し、設定タブ内だけスクロール。内容が収まればバーを隠し、Tab移動先を自動表示
  - 画像未読込時の保存無効化、`Ctrl+O` / `Ctrl+S`、自動日時中の手入力無効化、保存直前の300ms未確定入力反映を追加
  - 「サンプルで試す」はPillow生成の中立ベース画像を使用し、Git管理外写真や配布リソースに依存しない
  - 本番の設定自動記憶、カスタムフォントの管理先コピー／削除、描画・保存・バッチ・CLIは維持

### Verification

- `tests/test_production_ui.py` と `tests/test_i18n.py` で本番UI状態遷移、永続化、日英切替、ダイアログ文言、描画不変を確認。全220件成功
- 一時APPDATA/XDGで日英再起動復元、GUI／バッチ3エフェクト一致、PNG/JPEG/WebP、日英CLI `--help`／バッチを統合確認
- Windows実画面（1920×1080、100%）を日英・詳細・960×600・最大化で撮影。1160×780の表示は縦472×630／横814×611
- ネイティブ保存／フォルダ選択ダイアログとOS表示倍率125/150%はユーザー実機確認で良好。英語のTk倍率125/150%も日時欄・スクロールを追加確認。exe再ビルドは未実施

### Fixed

- フォント「追加...」ダイアログの初期フォルダをユーザー側 (`%LOCALAPPDATA%/Microsoft/Windows/Fonts`) 優先に変更。`C:/Windows/Fonts` は仮想シェルフォルダのため開くダイアログで空に見えることがある（権限ではなく表示上の問題）。通常フォルダのユーザー側のフォントがそのまま見える

### Added

- ユースケース文書（`docs/USECASES.md` 新設＋README誘導）
  - 動画・配信系（サムネ／実況スクショ）・創作・ネタ系（TRPG証拠品／心霊・ハロウィン）・お出かけ・SNS系（旅行ログ／フォトブース／エモ投稿／ペット見守り）の3系統・8用途。用途別のおすすめ設定つき早見表あり

- 撮影日時モード（SPEC §3.5）
  - `rec_config.py`: `OverlayConfig.timecode_from_exif: bool=False` 追加、`CONFIG_SCHEMA_VERSION` 6→7。`is_simple_equivalent` は本旗ONを非等価（詳細推定）扱い。旧JSONはOFF読込
  - `rec_overlay.py`: `EXIF_DATETIME_TAGS`（Original→Digitized→DateTime）＋`parse_exif_datetimestr` / `format_photo_timecode` / `photo_timecode_text(img, path, fallback)`（EXIF→mtime→固定文・例外なし）/ `resolve_timecode_text` を新設
  - `rec_batch.py`: `process_single_file` が撮影日時モード時にファイル毎の日時文で合成（01.jpg AM08:00 / 10.jpg AM08:24 のように追従）
  - `rec_frame_app.py`: 日時欄に「撮影日時を使う」チェックを追加（ONで日時表示も連動ON）。`_render` で写真毎に解決し入力欄・セレクタへ反映（値変化時のみsetで再描画ループ防止）
  - `tests/test_photo_timecode.py` (新規, 15件): 書式・優先順・mtime追従・固定文フォールバック・バッチ追従（EXIF/mtime）・単発一致。既存の `schema_version` 主張4件を7に更新。計200件通過

- カスタムフォント登録（SPEC §5）
  - `rec_config.py`: `OverlayConfig.custom_fonts: dict={表示名: 複写先絶対パス}` 追加、`CONFIG_SCHEMA_VERSION` 5→6。`get_user_fonts_dir` / `sanitize_custom_font_name` / `validate_custom_font_file` / `resolve_custom_font_path` / `get_all_font_names` / `with_custom_font` / `without_custom_font` を新設。旧JSON（custom_fontsなし）は空読込
  - `rec_overlay.py`: `_load_font` に `custom_path` 引数を追加（最優先試行・失敗時は組込フォールバック）。`create_rec_overlay` / `composite_with_overlay` に `custom_fonts` 引数を追加。`create_rec_overlay_with_config` は設定の custom_fonts を使用
  - `rec_frame_app.py`: フォント選択を OptionMenu→Combobox＋「追加...」/「削除」に変更。追加時は `ImageFont.truetype` 確認後に `fonts/` へ複写して登録、削除時は確認後に登録解除＋複写削除
  - `tests/test_custom_fonts.py` (新規, 17件): schema v6・旧JSON互換・roundtrip・表示名一意化・実体描画・欠落フォールバック・複写実体の描画。既存の `schema_version` 主張3件を6に更新。計183件通過

### Fixed

- リリース smoke 失敗2件の修正（`v0.1.0` タグ付け直し）
  - 西欧ロケールの console（cp1252）で `--help` / `--batch` の日本語出力が `UnicodeEncodeError` → CLI 起点で stdout/stderr を UTF-8 化（GUI 無影響）
  - 極小画像（短辺約93px以下、例 64x48）で電池残量バーの内幅が負になり `x1 must be greater than or equal to x0` → バーを省略（既存サイズの描画は不変）。回帰テスト12件追加、計166テスト通過

### Changed

- 撮影日時・設定読み込みのリファクタリング（2026-09-16、動作仕様・設定スキーマは変更なし）
  - `rec_overlay.resolve_photo_config()` に写真毎の描画用設定の生成を集約し、GUI・バッチから共有。元の設定は変更せず、日時の取得順序（EXIF→mtime→固定文）を維持
  - GUIの初期日時書式を既存の `format_photo_timecode()` に統一
  - `OverlayConfig.from_dict()` の欠落フィールドはdataclassの既定値・default_factoryに委譲。カスタムフォント操作の重複importも整理
  - `tests/test_render_consistency.py` に10件追加。GUI・バッチのピクセル一致（日時3種×エフェクト3種）、日時入力欄の再更新抑制、設定の既定辞書の独立性を確認。Windowsローカルで全210件通過（画面のない環境ではGUI関連9件をスキップ）
  - 作業時の変更前後比較でも360パターンの描画ピクセル一致を確認（2サイズ×2色×3エフェクト×3太さ×10フォント）。GUIの手動操作確認・exe再ビルドは未実施

- コード構造のリファクタリングと保守性・性能向上
  - `rec_frame_app.py`: 170行超あった `__init__` を 9 つのプライベートビルダー（`_build_*`）に分割。
  - `rec_frame_app.py`: `_full_config()` を新設し、`_current_config()` と `_save_settings()` の `OverlayConfig` 組み立て重複を解消。
  - `rec_frame_app.py`: 日時手入力欄（`timecode_text_var`）に 300ms デバウンスを導入し、タイピング中のフルサイズ再描画と保存の多発を抑制。
  - `rec_frame_app.py`: `_sync_timecode_selector` 内のインライン `import re` を撤廃し `rec_config.parse_timecode_text` を使用。
  - `rec_config.py`: `SUPPORTED_EXTENSIONS` を集約定義し、`rec_frame_app.py` / `rec_batch.py` から参照。
  - `rec_config.py`: `compose_timecode_text` の逆操作となる `parse_timecode_text` を新設。
  - `rec_config.py`: `OverlayConfig.from_dict` を `dataclasses.fields` によるデフォルト値自動取得に変更し、二重管理を解消。
  - `rec_overlay.py`: 定数を SPEC セクション別（§3.1〜§3.6）にブロックコメントでグルーピング。`OverlayColor`, `ThicknessKey`, `EffectKey` 等の型アノテーションを適用。`save_composited_image` の JPEG 判定を整理。
  - `rec_batch.py`: `SUPPORTED_EXTENSIONS` 参照および `process_folder` のコールバック引数に型ヒントを付与。
  - `tests/`: `tests/conftest.py` を新設して共通定数・`count_color` ヘルパーを集約。`test_config_persistence.py` に `parse_timecode_text` の単体テストを追加。全154テスト通過。

### Added

- PyInstaller配布の決定・実装（SPEC §9）
  - `rec-frame-app.spec` (新規): onefile・`console=True` 維持（GUI/CLI `--batch` 兼用）・フォント非同梱。`windowed=True` 化は禁止
  - `.github/workflows/release-exe.yml` (新規): `v*` タグでWindowsビルド→Releaseに `rec-frame-app.exe` 添付。手動実行可。smokeはexeの `--help`＋`--batch` 実走＋出力存在確認
  - `.gitignore`: `build/`・`dist/`・`smoke_in/`・`smoke_out/` を追加（spec自体はコミット）
  - `tests/test_dist.py` (新規, 3件): specの存在・コンパイル・onefile/console維持、ワークフローの存在・ビルド内容。計151件通過
  - 実機検証: ローカルビルド成功（約17.6MB）、exe出力と.py出力のバイト一致を確認
  - SPEC §4・§8・§9、READMEに配布手順を記載。配布形態は「正本.py＋Releasesで単体exe」に決定（pip/zipappは副手段）

### Added

- 設定の自動記憶（UI追加なし）
  - `rec_config.py`: `get_user_config_path/load_user_config/save_user_config/is_simple_equivalent` 追加。保存先は Windows `%APPDATA%/rec-frame-app/config.json`、他OSは XDG。欠落・破損・旧JSONは既定値吸収
  - `rec_frame_app.py`: 起動時復元＋変更時自動保存（`_save_settings`）。簡易モード中も詳細チェック状態を保持して保存。`mode` 自体は保存対象外で `show_*` から推定、日時セレクタも復元
  - `tests/test_config_persistence.py` (新規, 8件): roundtrip・欠落・破損・非dict・不正値・旧JSON互換・`is_simple_equivalent`
  - SPEC §7・§8・§10.1 を更新。マージンスライダー／オーバーレイ単体書き出しは凍結と明記

- バッチモード最小実装 (SPEC §10.1)
  - `rec_batch.py` (新規): `process_folder/process_single_file/resolve_output_path`。直下のみ・非再帰、png/jpg/jpeg/webp/bmp、命名 `{元名}_rec{拡張子}`・衝突時 `_rec_01` 連番、対象外スキップ＋件数レポート。合成は `composite_with_config` 委譲
  - `rec_frame_app.py`: 「一括処理...」ボタン追加（現在の設定を使用、設定ファイル選択なし）。CLI `--batch 入力 出力 [--config]` 追加（省略時は自動記憶）。進捗ダイアログ＋結果レポート
  - `tests/test_batch.py` (新規, 7件): 命名・衝突・スキップ・単発一致・失敗計数・CLI config・不正config

### Fixed

- 赤丸＋RECの垂直中央合わせをインク中央化（`anchor="lm"`→`"lt"`、SPEC §3.3）
  - `lm` は行ボックス中央（アセンダ〜ディセンダ）のため、Bebas Neue -6.0px／Consolas -5.5px（1920x1080、2048x3072では-11.5px）等のフォント依存の浮きがあった
  - `rec_overlay.py` `_draw_rec_indicator`: `textbbox(anchor="lt")` でタイト高さを測り `cy - text_h//2` に配置。`rec_dy`・右寄せ・赤丸常赤は不変。全フォント・全サイズで中心差±1px以内（整数丸めのみ）
  - `tests/test_overlay.py`: 回帰テスト20件追加（10フォント×640x360・1920x1080）。計133件通過

### Added

- UI劣化エフェクトを追加 (SPEC §3.6)
  - `rec_config.py`: `EffectKey` (`off/oled/2000s`)＋`EFFECT_CHOICES`（表示名 `OFF(クリーン)/OLED(微発光)/2000sデジカメ`）追加。`OverlayConfig.effect="off"`、`CONFIG_SCHEMA_VERSION` 4→5。欠落は `off` 読込（旧JSONはクリーン等価）
  - `rec_overlay.py`: `EFFECT_PRESETS`＋`apply_ui_effects()` 追加。順序固定（RGBシフト→ブルーム→低解像）。シフトは `Affine`＋`fillcolor=0`（`ImageChops.offset` の回り込み回避）。`create_rec_overlay` / `composite_with_overlay` に `effect` 引数追加（既定off）。CRT/VHS・走査線は画面全体への破壊処理となりコンセプトに合わないため不採用（実装・仕様とも撤去）
  - OLEDのブルームを少し強化（弱: 半径 `s*0.005`→`s*0.006`・発光層α160→190）
  - OLEDのブルーム弱を枠色で分岐（白は強化値を維持・黒は強化前 `s*0.005`・α160に抑制）。`apply_ui_effects()`・`_apply_bloom()` に `color` 引数を追加し `create_rec_overlay_with_config()` から受け渡し
  - `rec_frame_app.py`: 「エフェクト」ドロップダウン追加（枠太さ同様に両モード共通・常時有効）。変更でプレビュー即時更新（既存150msデバウンス再利用）
- `tests/test_effects.py` (新規, 22件): OFF無操作・未知プリセット却下・全プリセット同寸・wrapなし回帰・弱/強差分・ブルーム拡大・ブルーム弱の色分岐・全OFF＋エフェクト透明維持・schema v5 roundtrip・旧JSON互換。既存の `schema_version` 主張2件を5に更新。計113件通過

### Changed

- 既定フォントを `Arial Narrow Bold(細長)` に変更（`DEFAULT_FONT` の1行変更。GUI初期選択・旧JSON欠落時の読込も連動）

- 簡易/詳細モード切替＋要素ON/OFF (SPEC §10.2を実装)
  - `rec_config.py`: `OverlayConfig` に `show_frame/show_battery/show_rec: bool=True` 追加、`CONFIG_SCHEMA_VERSION` 1→2。`from_dict` は欠落キーを `True` 読込（旧JSONは全ON等価）
  - `rec_overlay.py`: `create_rec_overlay_with_config` で要素ごと描画スキップ。`create_rec_overlay` / `composite_with_overlay` に `show_*` 引数追加（既定Trueで後方互換）。全OFFは透明→合成＝ベース一致
  - `rec_frame_app.py`: 「簡易/詳細」ラジオ＋4チェックボックス（枠フレーム/電池残量マーク/REC/中央十字）。枠太さラジオは両モード共通表示。簡易は全True・十字OFF扱い、チェック状態は保持
    - 詳細チェックは常時表示し簡易モードでは無効化（グレーアウト）に変更
- 中央十字を詳細限定で追加 (SPEC §3.4・§10.2)
  - `rec_config.py`: `show_cross: bool=False` 追加、`CONFIG_SCHEMA_VERSION` 2→3。欠落は `False` 読込（旧JSONは十字なし等価）
  - `rec_overlay.py`: `_draw_center_cross` 追加（中心・片腕 `s*0.035`・線幅 `max(1, s*0.002)`・枠色連動・枠太さ独立）。`create_rec_overlay` / `composite_with_overlay` に `show_cross` 引数追加（既定False）
- `tests/test_overlay.py`: 9件追加（既定False・v3 roundtrip・旧JSON互換・中心ピクセル・枠色連動・枠太さ独立）。計77件通過
- 日時表示を詳細限定で追加 (SPEC §3.5)
  - `rec_config.py`: `show_timecode: bool=False`＋`timecode_text: str=""` 追加、`CONFIG_SCHEMA_VERSION` 3→4。欠落は `False`/空読込（旧JSONは日時なし等価）
  - `rec_overlay.py`: `_draw_timecode` 追加（右下・`anchor="rb"`・`max(10, s*0.04)`・RECフォント/枠色連動・空スキップ）。`create_rec_overlay` / `composite_with_overlay` に `show_timecode` / `timecode_text` 引数追加（既定False/空）
  - `rec_frame_app.py`: 「日時表示」チェック＋手入力欄（幅22・初期値は起動時 `YYYY/MM/DD AM/PM HH:MM`）を追加。詳細限定・簡易時無効化、入力でプレビュー即時更新
  - 日時選択式入力を追加 (SPEC §10.3)
    - `rec_config.py`: `compose_timecode_text()` 追加（ゼロ埋め整形のみ、暦チェックなし。1800年・2月30日も許容）
    - `rec_frame_app.py`: 年/月/日/時/分Spinbox＋AM/PMコンボの選択行を追加。操作で手入力欄に合成（片方向、手入力も併存）。簡易時無効化
    - 選択式の月/日/時/分をドロップダウン（Combobox readonly、AM/PMと同方式）に変更（年はSpinboxのまま）

### Changed

- B案リファクタ: 単一ファイルから3モジュール分割（振る舞い不変）
  - `rec_config.py` (新規): `FONT_CHOICES` / `DEFAULT_FONT` / `OverlayConfig(color, font_key)` + `to_dict` / `from_dict`（将来のバッチ用JSON互換）
  - `rec_overlay.py` (新規): 純粋画像層。幾何パラメータを定数集約（`MARGIN_RATIO` 等）し `_draw_corner_frames` / `_draw_battery` / `_draw_rec_indicator` に分割。`load_base_image`（EXIF正規化）/ `save_composited_image`（JPEG quality=95）を抽出。`_load_font` に `lru_cache`
  - `rec_frame_app.py`: GUI薄層のみに縮小。旧公開名（`create_rec_overlay` / `composite_with_overlay` / `FONT_CHOICES`）は再エクスポートし互換維持
- 描画結果の前後一致を6サイズ×2色のPNGハッシュで検証（完全一致）

### Added

- `tests/test_overlay.py` (新規, 32件): 同寸出力・四隅等距離（640x360で10px）・10フォント全描画・赤丸常赤・色切替分離・Config検証・JPEG保存変換
- 実行: `.venv\Scripts\python -m pytest -q`

## [0.1.0] - 2026-09-14

- 初版: 四隅枠＋電池＋REC、任意サイズ対応GUI（単一ファイル `rec_frame_app.py`）
- マージン縮小、枠色（黒/白）切替
- 赤丸・RECの中心合わせ（`anchor="lm"`）
- REC一式を約3px下げ、電池バー均等配置
- 四隅を上下左右等距離化、右・下端1px補正
- RECフォント10種切替
- EXIF正規化、プレビューのリサイズ追従（150msデバウンス）、保存/表示サイズ表示
