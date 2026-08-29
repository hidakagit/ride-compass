# RideCompass タスク運用基盤

`docs/improvement-plan.md`のタスク運用（次に何をやるかの選定、完了後の振り返り）を
支援するコマンド群。[review基盤](../review/README.md)と対になる位置づけ
（review=コードの品質を見る、task=何に取り組むかを見る）。

## ディレクトリ構成

```
.claude/commands/task/
├── README.md   # 本ファイル（運用ガイド）
├── next.md     # 次に着手すべきタスクの優先度順提案
├── retro.md    # タスク完了後の振り返り（教訓の抽出→提案）
└── history/    # retro.mdの結果の蓄積（YYYY-MM-DD_retro.md）
```

## 各コマンドの役割

| コマンド | 問い | 主な使いどころ |
|---|---|---|
| `/task:next` | 今すぐ着手できるタスクはどれか、優先度順に並べると | 何をやるか迷ったとき |
| `/task:retro` | 今回の作業から、今後に活かすべき教訓はあるか | タスク完了直後、特に規模M以上や手戻りがあった作業の後 |

両コマンドとも**自動でファイルを書き換えない**。`/task:next`はユーザーに選ばせるだけ、
`/task:retro`は提案のみ行い承認後に反映する（[review/improve.md](../review/improve.md)と
同じ型）。

## 注意事項

- `/task:retro`の提案先（CLAUDE.md本体／docs/`<topic>`.md／各`_history.md`／
  `docs/decisions/`／メモリ）は、CLAUDE.md冒頭の「ドキュメント階層」表を判定基準とする。
  同じ教訓を複数箇所へ重複提案しない。
- この基盤自体を複雑化させない（review基盤と同じ方針。スクリプト・JSON設定・自動生成を
  足さず、Markdown＋既存ツールのみで維持する）。
