---
description: 定量メトリクス計測 — 規模・変更頻度・テスト規模・静的検査・依存関係を機械的に計測しトレンド記録する
argument-hint: [省略可、常にリポジトリ全体を対象]
---

# 定量メトリクス計測

他4種のレビュー（overall/complexity/consistency/ui）とは性質が異なる。**Findingsの
判定・優先度付けは行わない**——毎回同じ手順で数値を機械的に測り、`history/metrics.md`
（トレンド専用の追記型ファイル）へ記録するだけの計測ロール。「この数値をどう評価するか」
（過大か・妥当か）は、この計測結果をEvidenceとして`/review:overall`または
`/review:complexity`が判断する。数値の算出自体に主観を混ぜない。

[principles.md](principles.md)の「事実と推測を分ける」原則を特に厳格に適用する:
本レビューは常にEvidence（実測値）のみを出力し、Inference/Recommendationは書かない。

## 実行手順

1. `history/metrics.md`の各節から直近1件の日付・値を読み、差分計算のベースラインにする
   （初回計測時は「初回記録」とする）。
2. 以下5項目を毎回同じコマンドで計測する（インストールが要る項目は現状未導入のため
   DEFERとし、代替の軽量指標のみ計測する）。`python scripts/review_checks.py metrics --full`
   が1〜5をまとめて計測しMarkdownで出力する（`--full`無しなら規模とchurnのみ数秒で終わる。
   `--since`でchurnの起点日を上書きできる）。下記の個別コマンドは、スクリプトが何を
   測っているかの定義と、単独で再計測したいときの手順。
3. `history/YYYY-MM-DD_metrics.md`へ本文（実測値＋前回差分＋計測コマンド）を保存し、
   `history/metrics.md`の対応する各節表へ1行ずつ追記する。
4. **閾値を超えた項目は「要確認」として一覧化するのみ**（下記「発火条件」）。
   判定は行わず、`/review:overall`・`/review:complexity`への確認依頼として提示する
   （P0/P1起票と同様、改善提案の形では出さない——本レビュー自体は改善提案を持たない）。

## 計測項目

### 1. 規模（cloc）

```bash
npx --yes cloc . \
  --exclude-dir=node_modules,.venv,venv,.next,dist,build,.git,coverage,.pytest_cache,__pycache__,.turbo,htmlcov \
  --exclude-ext=json,lock,svg,png,jpg,jpeg,ico,pbf,mbtiles,parquet
```

- 「SUM」行（全体、docs/配下のMarkdown含む）と、Markdown行を除いた「実装コードのみ」
  （TypeScript+Python+CSS+SQL+YAML+JS+HTML+Shell等の合算）の両方を記録する
  （docsの厚みとコード本体の規模を混同しないため）。
- 参考として`backend/app`（テスト除く実装本体）・`backend/tests`・
  `frontend/src`（テストファイル除く）・`frontend/src`のテストファイルを分けて
  `cloc <path> --not-match-f='\.(test|spec)\.(ts|tsx)$'`等で再計測し、
  実装本体とテストの比率も記録する（テスト方針docs/testing.mdの手厚さの裏付けとして
  過大判定の材料になる）。

### 2. 変更頻度（churn）

前回計測日を起点に、統合レビューの対象期間と揃える:

```bash
git log --since="<前回metrics計測日>" --oneline | wc -l
git log --since="<前回metrics計測日>" --name-only --pretty=format: | sort -u | sed '/^$/d' | wc -l
git log --since="<前回metrics計測日>" --name-only --pretty=format: | sed '/^$/d' | sort | uniq -c | sort -rn | head -10
```

コミット数・変更ファイル数（ユニーク）・変更頻度上位10ファイルを記録する。

### 3. テスト規模

```bash
cd backend && "<venvのpython.exe、CLAUDE.md記載のworktree事情に注意>" -m pytest -q -m "not postgis" --collect-only 2>&1 | tail -5
cd frontend && npx vitest list 2>&1 | tail -5
```

**実行(pass/fail)ではなく収集件数のみ**を計測する（フルスイート実行はdocs/testing.mdの
方針により反復開発の最終検証時のみ・本レビューの責務外。健全性[pass/fail]は
`/review:consistency`・CI・通常のテスト運用が担う）。テストファイル数／実装ファイル数の
比率も上記cloc結果から算出して記録する。

### 4. 静的検査

```bash
cd frontend && npx tsc --noEmit 2>&1 | tail -20   # エラー件数
cd frontend && npm run lint 2>&1 | tail -30        # warning/error件数
```

backendは現状lintツール（ruff/flake8等）が未導入のため計測対象外——**DEFER
（トリガー: backendへlintツールが導入された時点で本節へ追加する）**。

### 5. 依存関係

```bash
cd frontend && npm audit --json
```

`metadata.vulnerabilities`の`critical`/`high`/`moderate`/`low`件数を記録する。
backendは`pip-audit`が未導入のため計測対象外——**DEFER（トリガー: backendへ
`pip-audit`が導入された時点で本節へ追加する）**。依存パッケージ数（`package.json`の
dependencies/devDependencies件数、`requirements*.txt`の行数）は参考値として記録してよい。

## 発火条件（要確認フラグ、判定はoverall/complexityへ委ねる）

以下いずれかに該当した項目は、`/review:overall`または`/review:complexity`実行時に
確認するよう明示的に申し送る（本レビュー内では判定しない）:

- 規模: 総実装行数（Markdown除く）が前回比+15%以上、またはbackend/frontendいずれかの
  実装本体:テスト比率が前回から大きく変化（片方が急減=カバレッジ低下、急増=テスト過多の
  可能性いずれも申し送り対象）
- churn: 変更頻度上位10ファイルに新顔が複数入った場合（複雑度regime変化の兆候）
- 静的検査: tscエラー・eslintエラー（warning除く）が0件から増加
- 依存関係: critical/highが1件以上

## 出力

`history/YYYY-MM-DD_metrics.md`（実測値＋計測コマンド＋前回差分＋「要確認」一覧）を保存し、
`history/metrics.md`の各節表へ1行ずつ追記する。**Findings形式（P0-P3）・KEEP/REMOVE等の
標準フォーマットは使わない**（principles.mdの標準フォーマットの対象外、本レビュー固有の
軽量フォーマットとする）。**コードは変更しない。**
