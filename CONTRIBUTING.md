# Contributing

## セットアップ

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install pytest
```

Linux の場合 tkinter が別途必要です（CI 参照）: `sudo apt-get install -y python3-tk`

## テスト

```bat
.venv\Scripts\python -m pytest -q
```

## GUI の手動確認（GUI 変更時）

1. 画像を開く → プレビューが表示される
2. 枠色・フォント・枠太さ・エフェクト・モードを変更 → プレビュー即時更新
3. 保存 → `{元名}_rec{拡張子}` で保存できる
4. 一括処理 → 入力/出力フォルダ選択で件数レポートが出る

## 守ってほしいこと

描画まわりの仕様は `SPEC.md` が正本です。以下は変えないでください。

- オーバーレイは `s = min(w, h)` 基準のベクター生成（PNG 貼り付け・拡縮なし）
- ピクセル座標・右/下隅の `-1` 補正・赤丸＋REC の `cy` 中心線・`rec_dy` 下げ補正
- 枠太さ（小/中/大）は四隅枠のみ連動。電池線幅・REC 丸・中央十字線幅は独立値
- エフェクト適用順序（RGB シフト→ブルーム→低解像度化）と `effect` の枠色分岐
- `rec-frame-app.spec` の `console=True`（GUI と CLI `--batch` 兼用のため）

詳しくは `AGENTS.md` の「注意点（壊さないこと）」を参照してください。

## Issue / PR

- バグ報告・機能要望は Issue テンプレートに沿って記載してください
- PR はテンプレートのチェックリストを埋めてください。CI（Python 3.11/3.12 × Ubuntu/Windows）が通過することが条件です
- リリース（`v*` タグ打ち・exe 配布）はメンテナが行います
