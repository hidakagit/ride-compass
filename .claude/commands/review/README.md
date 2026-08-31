# RideCompass レビュー基盤

AIによる継続的なコード・設計レビューの基盤。単発のレビュープロンプトではなく、
大規模な機能追加・リファクタリング・設計変更のたびに**同じ品質基準**でレビューを実施し、
結果を蓄積してレビュー基準そのものを継続的に改善するための仕組み。

目的の詳細と判断原則は [principles.md](principles.md)、
プロジェクト固有の前提は [context.md](context.md) を参照。

## ディレクトリ構成

```
.claude/commands/review/
├── README.md        # 本ファイル（運用ガイド）
├── principles.md    # 共通レビュー原則・標準フォーマット・共通実行手順
├── context.md       # プロジェクト固有コンテキスト（構造・設計思想・Keep List・履歴の所在）
├── overall.md       # 全体最適レビュー
├── complexity.md    # 複雑度平衡性レビュー
├── consistency.md   # 設計・実装・テスト整合性レビュー
├── ui.md            # UI/UXユーザーレビュー（Playwright実機確認つき）
├── metrics.md       # 定量メトリクス計測（規模・churn・テスト規模・静的検査・依存関係）
├── all.md           # 統合レビュー（4種＋metrics＋相互確認＋統合判断）
├── improve.md       # レビュー基準の自己改善（提案のみ、自動書き換え禁止）
├── _history.md      # 各.mdファイルの運用ルールの経緯・根拠（正式版は手順のみ、経緯はここへ）
└── history/         # レビュー結果の蓄積（YYYY-MM-DD_<type>.md）
```

## 各レビューの役割

| コマンド | 問い | 主な使いどころ |
|---|---|---|
| `/review:overall` | システム全体として設計思想が一貫しているか。局所最適の連鎖がないか | 大規模改修後 |
| `/review:complexity` | 複雑さが適切な場所に配置されているか。変更コストが悪化していないか | 大規模改修後・定期 |
| `/review:consistency` | 設計・実装・テストが一致しているか | 毎回の実装後 |
| `/review:ui` | 初見ユーザーが目的と操作を理解できるか（実機確認） | UI変更後 |
| `/review:metrics` | 規模・churn・テスト規模・静的検査・依存関係の**数値を機械的に計測**（判断はしない） | 毎回のall実行時・単独実行可 |
| `/review:all` | overall/complexity/consistency/ui 4種の統合＋metrics計測＋矛盾・トレードオフの統合判断 | 大規模改修後・定期 |
| `/review:improve` | レビュー基準自体の改善提案 | 数回レビューが蓄積したら |

**観点の分担（重複指摘の防止）**:
- 重複・残骸・新旧混在の**存在検出**と局所最適の連鎖 → overall
- 複雑さの**配置の適否**・変更コスト定量評価 → complexity
- 性能: スケール成立性・スケールしないクエリ類型の検出 → overall、
  最適化の複雑度対価の判断 → complexity
- **規模・依存関係等の数値そのもの**（Findingsではなく実測値）→ metrics。
  「その数値が過大か」の判断はoverall・complexityへ委ねる（metrics自身は判定しない）
- **セキュリティは本基盤の対象外**。Claude Code 組み込みの `/security-review` を使う
  （観点を複製しない）

## 実行方法

Claude Code で `/review:overall` のように実行する。引数で対象範囲を絞れる
（例: `/review:consistency backend/app/services/`）。無指定なら
「前回同種レビュー以降の変更」を中心に見る。

## 推奨ワークフロー

**通常開発:**
```
実装 → テスト → /review:consistency → /review:complexity
```

**大規模改修後:**
```
実装 → テスト → /review:overall → /review:complexity
     → /review:consistency → /review:ui → /review:all
```
（/review:all は4観点を内包するため、時間が限られる場合は個別4種を省略して
/review:all 単独でもよい。個別に実施済みなら all は該当Phaseを結果ファイルの
読み込み＋差分確認に置き換え、Phase 6以降の相互確認を中心に行う。
コンテキスト逼迫時はPhase単位の分割実行・中間保存も可 — 詳細は all.md）

**定期的なレビュー**（2026-08-30、実施間隔が空きすぎた反省を受け閾値を明文化）:

- **トリガー**: 次のいずれか早い方に達したら`/review:all`（最低限`/review:consistency`）を
  実施する。①前回いずれかの種別のレビュー実行（`history/`の最新ファイル日付）から**7日経過**、
  ②その間に**20件以上のタスクが完了**（`docs/improvement-plan.md`の`[x]`増分で判定）。
  ③**量に関係なく**、T400のような分割元タスク（複数のTxxxへ分割する規模Lのタスク）が
  完了した直後は必ず実施する（大きな設計変更の直後こそドリフトが起きやすいため）。
- 新しいセッションが作業に着手する際は、上記トリガーに該当していないか
  `history/`の最新ファイル日付・`docs/improvement-plan.md`の直近チェック数を見て確認する
  （CLAUDE.mdからこの節へのポインタあり）。
- **Claude Code標準の`/code-review`（`ultra`含む）は、ユーザーがターミナルで自分で起動する
  必要があるコマンドで、セッション側から自動実行できない**（Skill/Toolとして公開されて
  おらず起動手段が無いことを2026-08-30に確認済み）。トリガー該当時は`/review:all`の
  実施と合わせて`/code-review`の実施もユーザーへ提案する。
- **忘れられがちな`/code-review`の代替として、トリガー該当時（`/review:all`実施時・難度の
  高いタスク完了時）はセッション自身が`ReportFindings`ツールでコードレビュー観点の
  自己レビューを実施する**（2026-08-30、「毎回`/code-review`を打つのを忘れる」という
  指摘を受け導入）。ただし**本物の`/code-review ultra`[複数エージェント・クラウド実行]と
  同等の品質・カバレッジは無い**ため、結果は別のreview-type
  `codereview-self`（history/README.md参照、ユーザー起動の本物`codereview`とは型を分ける）
  として保存する。月1回程度の低頻度な節目では、自己レビューで代替せず本物の
  `/code-review ultra`の実施をユーザーへ明示的に提案すること。
- いずれの`/code-review`系（ユーザー起動の本物・セッションの自己レビュー）の指摘も、
  `.claude/commands/review/history/`の既存レビューと同じ蓄積・フィードバック経路に乗せる:
  P0/P1相当の指摘は他レビュー種別と同じくimprovement-plan.mdへT番号タスクとして起票する
  （起票はユーザー承認後、という既存原則を継続）。

**レビュー基準の改善:** `/review:improve`（提案→ユーザー承認→反映）

## レビュー履歴の管理

- 結果は `history/YYYY-MM-DD_<type>.md` へ保存（詳細は [history/README.md](history/README.md)）
- 本基盤構築以前（2026-08-15〜16）のレビューは docs/*-review-*.md にあり、
  再発チェックの参照元として引き続き使う
- P0/P1指摘は docs/improvement-plan.md へT番号タスクとして起票する。
  **起票はユーザー承認後**（レビューコマンドは起票案の提示まで）

## レビュー基準の改善方法

1. `/review:improve` を実行 → 変更提案（`history/YYYY-MM-DD_improve.md`）が出る
2. ユーザーが提案ごとに承認/棄却を判断
3. 承認された提案のみ、ユーザーの指示で review/*.md へ反映

## 注意事項

- **レビューコマンドはコードを変更しない**（history/への結果保存のみ）
- レビュー基準・context.md もレビュー実行中に書き換えない（improve経由）
- Keep List（context.md・complexity-review-2026-08-16.md）記載の設計を
  新しい根拠なしに再指摘しない
- UIの所見は実機（Playwright）で再検証してから確定する（誤所見の先例2件あり）
- この基盤自体を複雑化させない（スクリプト・JSON設定・自動生成を足さない。
  Markdown＋コマンドのみで維持する）
