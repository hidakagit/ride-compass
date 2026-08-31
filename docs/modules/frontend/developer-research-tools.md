# 開発者/研究者機能（frontend）

## 責務

一般ユーザー向け画面には出ない、デバッグ・研究用の補助機能（ログ表示・システム状況・
研究モードのトグル・評価重みの実験的上書き）。大半は独立URL`/admin`
（`app/admin/page.tsx`）にある。

**対象ファイル**

| ファイル | 責務 | マウント先 |
|---|---|---|
| `components/DebugPanel/DebugPanel.tsx` | デバッグログ表示のON/OFFトグル | `/admin`「開発者」タブ |
| `components/DebugConsole/DebugConsole.tsx` | 地図イベント・外部API呼び出しの詳細ログを時系列表示するフローティングパネル | `page.tsx`（`/`）のヘッダー直下 |
| `components/SystemStatusPanel/SystemStatusPanel.tsx` | backend `/api/debug/stats`の集計・フロントバージョンを表示するフローティングパネル | `/admin`「開発者」タブ |
| `components/BackendStatus.tsx` | バックエンドの死活確認の簡易表示 | `/admin`「開発者」タブ |
| `components/BackendLogsPanel/BackendLogsPanel.tsx` | backend `GET /api/admin/debug/logs`の直近ログをレベル（DEBUG〜CRITICAL）・部分一致で絞り込んで表示するパネル。取得は「取得」ボタン押下時のみ（ポーリングなし） | `/admin`「開発者」タブ |
| `components/ResearchPanel/ResearchPanel.tsx` | 研究モードのトグル | `/admin`「研究」タブ |
| `components/FloatingPanel/FloatingPanel.tsx` | `DebugConsole`/`SystemStatusPanel`が共有するドラッグ可能な浮動パネルの共通シェル（`react-rnd`ベース） | 両パネルの実装基盤 |
| `hooks/useDebugLog.ts`・`lib/debugLog.ts` | デバッグモードON/OFF状態・ログエントリのシングルストア（`useSyncExternalStore`） | |
| `hooks/useResearchMode.ts`・`lib/researchMode.ts` | 研究モードON/OFF状態の同型シングルストア | |
| `services/debugStatsApi.ts`・`services/versionApi.ts` | `SystemStatusPanel`が使うAPIクライアント | |
| `services/debugAdminApi.ts` | `BackendLogsPanel`が使うAPIクライアント（`app/admin/api/debug/logs/`経由、生成型を経由しない手書き型） | |
| `services/healthApi.ts` | `BackendStatus.tsx`が使う`GET /api/health`クライアント | |
| `app/api/version/route.ts` | `versionApi.ts`が読むフロントエンドのビルドバージョンを返すNext.js route handler | |

## `/admin`とpage.tsx（`/`）の境界

```
app/admin/page.tsx（独立URL、Basic認証保護下）
  ├─ タブ「軸スタジオ」: AxisStudio（本モジュール対象外）
  ├─ タブ「研究」　　　: ResearchPanel + （researchEnabled時のみ）WeightPanel
  └─ タブ「開発者」　　: DebugPanel + BackendStatus + SystemStatusPanel + BackendLogsPanel

app/page.tsx（メインページ、地図を持つ）
  └─ header直下: DebugConsole（debugEnabled時のみボタン表示）
```

`DebugConsole`（デバッグログの表示自体）だけが`/`に残る——地図インスタンスに紐づく
情報のため、地図を持たない`/admin`へ移すと記録先（`lib/debugLog.ts`のシングルトン）が
タブ間で共有されず実質機能しない。デバッグモードのON/OFF自体は`/admin`の`DebugPanel`で
切り替え、localStorage経由で`/`側へ共有される。

## デバッグモードとログ表示・パネル開閉の3段階

1. **デバッグモードのON/OFF**（`useDebugEnabled`/`setDebugEnabled`、localStorage
   `ridecompass:debug-enabled`）: ログの**記録自体**の有効/無効。`/admin`の
   `DebugPanel`で切り替える。
2. **記録**（`debugLog(category, message, detail, level)`、`lib/debugLog.ts`）:
   デバッグモードON中、`services/`配下のfetchラッパー・`MapView.tsx`のmapイベント
   ハンドラから直接呼ばれるフレームワーク非依存のシングルトン（最大300件、
   `console.debug`/`warn`/`error`にも同時出力）。
3. **パネルの開閉**（`page.tsx`の`debugConsoleOpen`）: `DebugConsole`自体の表示/非表示。
   デバッグモードONでも常時パネルを占有させない、記録の有効/無効とは独立したstate。

## 研究モード（`ResearchPanel.tsx`）

ONにすると`/admin`「研究」タブ内に評価重みの上書きパネル（`WeightPanel`）が現れ、以降
`page.tsx`側の`handleGenerate`が生成した結果が実験スロット（`page.tsx`の
`experimentSlots`、最大3件）へ記録されて比較表（`ComparisonPanel`、`page.tsx`のルート
結果セクション内）・地図の重ね描き（`MapView`の`experimentSlots` prop）に使えるように
なる。`WeightPanel`が編集する`route_preference`は`/admin`側の`useStoredJsonState`と
`page.tsx`側の同じキーのstateがlocalStorage経由で共有される（同一タブでのリアルタイム
同期ではなく、次回開いたとき/再読み込み時に反映される）。

デバッグモード（ログ表示専任）とは独立した別のトグル。

## 暗黙の前提

- `useAxisCatalog()`（`GET /api/axis-catalog`）は呼び出しごとに独立してフェッチせず、
  モジュールレベル変数`inFlightCatalogFetch`で同時に飛んでいる未解決フェッチだけを
  共有する（`page.tsx`と`RouteSettingsPanel.tsx`が同時にマウントされる際、同じ
  リクエストが2重に飛ぶのを防ぐ）。解決後の結果は永続キャッシュしない——後続の別マウント
  （例: `/admin`と`/`を別タブで開く）では改めて最新を取得する。
- `SystemStatusPanel`・`DebugConsole`はポーリングをせず、開いたとき（`open`が`true`に
  なった瞬間）と明示的な「更新」ボタン押下時にのみ`fetchAll`/エントリ取得を行う
  （プロセス内カウンタ・モジュール評価時刻のスナップショットという性質のため）。
