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

### ひとり開発での使い方

1. Issueを作り、「何を直すか」「どこまで直せば完了か」を書く。コード整理には「リファクタリング / Refactoring」テンプレートを使えます。
2. `codex/` で始まる作業ブランチを作り、変更とテストを行う。
3. 公開対象の差分を確認し、変更をコミットして作業ブランチをpushする。ローカルの検証画像・作業メモ・秘密情報は含めません。
4. `main` 向けのDraft PRを作り、目的・変更点・テスト結果を書く。Issue番号が確定したら、本文に `Closes #番号` を入れて紐付けます。
5. PRの「Files changed」で差分、「Checks」でCI結果を確認する。準備ができたらレビュー可能な状態へ切り替え、マージする。

Issueは作業の目的を残す場所、PRはその変更を確認する場所です。Draft PRは確認中の変更として公開でき、Draftのままではマージできません。
詳細は [GitHubのIssueガイド](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues) と [PRガイド](https://docs.github.com/en/pull-requests/reference/pull-requests) を参照してください。
