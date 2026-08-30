# 開発者/研究者機能（frontend）

## 責務

一般ユーザー向け画面には出ない、デバッグ・研究用の補助機能（ログ表示・システム状況・
評価重みの実験的上書き）。

**対象ファイル**

| ファイル | 責務 | トグル |
|---|---|---|
| `components/DebugPanel/DebugPanel.tsx` | デバッグログ表示のON/OFFトグル（サイドバーの小さなチェックボックス） | `useDebugLog`/`debugLog.ts: setDebugEnabled` |
| `components/DebugConsole/DebugConsole.tsx` | 地図イベント・外部API呼び出しの詳細ログを時系列表示するフローティングパネル | `open`/`onClose`（デバッグモードON/OFFとは別のパネル開閉） |
| `components/SystemStatusPanel/SystemStatusPanel.tsx` | backend `/api/debug/stats`の集計・フロントバージョンを表示するフローティングパネル | 同上 |
| `components/ResearchPanel/ResearchPanel.tsx` | 研究モードのトグル | `useResearchMode`/`researchMode.ts: setResearchEnabled` |

## デバッグ機能とシステム状況の分離

`DebugPanel`（トグル）→`DebugConsole`（ログ表示）と`SystemStatusPanel`（集計値表示）は
別パネルに分離されている——「ログ本文」と「backendの集計・commit等のシステム状況」は
情報源・更新頻度が異なる別種の情報のため、1つのパネルに詰め込むと見づらいという理由で
分割された。

- デバッグモードON＝ログの**記録自体**は常時有効。`DebugConsole`の表示（`open`）は
  別途トグルで制御する（常時表示は画面の占有面積が大きいという理由）。
- `SystemStatusPanel`は[横断基盤（backend）](../backend/cross-cutting-infrastructure.md)の
  `debug_log.py`が集計した値（呼び出し回数・エラー数・キャッシュヒット率等）を
  `services/debugStatsApi.ts`経由で取得する。

## 研究モード（`ResearchPanel.tsx`）

ONにすると評価重みの上書きパネル（`WeightPanel`、[ルート設定・結果パネル](route-settings-and-results.md)）
が生成条件セクションへ現れ、以降の生成結果が実験スロットへ記録されて比較表
（`ComparisonPanel`）・地図の重ね描きに使えるようになる。

デバッグモード（ログ表示専任）とは独立した別のトグル（2役分割）。
