# 開発者/研究者機能（frontend）

## 責務

`/admin`（`app/admin/page.tsx`、Basic認証保護下）にある開発者向け補助機能（ログ表示・
システム状況・評価重みの実験的上書き）と、一般公開ページ`page.tsx`（`/`、認証なし）の
ヘッダーメニューから直接操作できる機能（デバッグログ表示・研究モードON/OFF）。

**対象ファイル**

| ファイル | 責務 | マウント先 |
|---|---|---|
| `components/HeaderMenu/HeaderMenu.tsx` | 研究モードON/OFF・デバッグログ表示を1個のメニューアイコンへ集約したRadix Popover | `page.tsx`（`/`）のヘッダー |
| `components/DebugPanel/DebugPanel.tsx` | デバッグログ表示のON/OFFトグル | `/admin`「開発者」タブ |
| `components/DebugConsole/DebugConsole.tsx` | 地図イベント・外部API呼び出しの詳細ログを時系列表示するフローティングパネル | `page.tsx`（`/`）、`HeaderMenu`から開閉 |
| `components/SystemStatusPanel/SystemStatusPanel.tsx` | backend `/api/debug/stats`の集計・フロントバージョンを表示するフローティングパネル | `/admin`「開発者」タブ |
| `components/BackendStatus.tsx` | バックエンドの死活確認の簡易表示 | `/admin`「開発者」タブ |
| `components/BackendLogsPanel/BackendLogsPanel.tsx` | backend `GET /api/admin/debug/logs`の直近ログをレベル（DEBUG〜CRITICAL）・部分一致で絞り込んで表示するパネル。取得は「取得」ボタン押下時のみ（ポーリングなし） | `/admin`「開発者」タブ |
| `components/ResearchPanel/ResearchPanel.tsx` | 研究モードの現在値（ON/OFF）の読み取り専用表示 | `/admin`「研究」タブ |
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
  ├─ タブ「研究」　　　: ResearchPanel（読み取り専用表示）
  └─ タブ「開発者」　　: DebugPanel + BackendStatus + SystemStatusPanel + BackendLogsPanel

app/page.tsx（メインページ、地図を持つ、認証なし）
  └─ header: HeaderMenu（研究モードON/OFFのトグル本体・デバッグログ表示ボタン）
       └─ DebugConsole（debugEnabled時のみHeaderMenuに項目表示、開閉はheader直下で管理）
```

研究モードON/OFFの操作は`HeaderMenu`（`/`、認証なし）が正であり、`/admin`の
`ResearchPanel`は現在値の読み取り専用表示のみを持つ（`researchMode.ts`のフラグ自体は
`/`・`/admin`のどちらからも`useResearchEnabled()`で参照できる共有state）。

`DebugConsole`（デバッグログの表示自体）は`/`に残る——地図インスタンスに紐づく情報の
ため、地図を持たない`/admin`へ移すと記録先（`lib/debugLog.ts`のシングルトン）がタブ間で
共有されず実質機能しない。デバッグモードのON/OFF自体は`/admin`の`DebugPanel`で切り替え、
localStorage経由で`/`側へ共有される（`HeaderMenu`はデバッグログ**表示**ボタンのみを持ち、
デバッグモード自体のON/OFFは持たない）。

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

## 研究モード（`HeaderMenu.tsx`でON/OFF、`useResearchEnabled()`で参照）

ONにすると`page.tsx`側の`handleGenerate`が生成した結果が実験スロット（`page.tsx`の
`experimentSlots`、最大3件）へ記録され、比較タブ（`ComparisonPanel`、「ルート選択」と
並ぶ2つ目のタブ）・地図の重ね描き（`MapView`の`experimentSlots` prop）に使えるように
なる——いずれも一般公開ページの機能として認証なしで直接利用できる（気軽に試せる比較
機能という位置づけ）。評価軸の重み（`route_preference`）自体は一般向けルート設定画面
（`RouteSettingsPanel`）が常時編集する状態で、研究モードON/OFFとは独立している。

トグル本体は`page.tsx`の`HeaderMenu`にあり、`/admin`の`ResearchPanel`は同じフラグ
（`researchMode.ts`）の現在値を読むだけの表示専用コンポーネント。デバッグモード
（ログ表示専任）とは独立した別のトグル。

## 暗黙の前提

- `useAxisCatalog()`（`GET /api/axis-catalog`）は解決済みのカタログをモジュールレベルの
  単一ストアとして持ち、全呼び出し元が`useSyncExternalStore`で同じオブジェクト参照を
  購読する。同時に飛んでいる未解決フェッチは`inFlightCatalogFetch`で重複排除する
  （`page.tsx`と`RouteSettingsPanel.tsx`が同時にマウントされる際、同じリクエストが
  2重に飛ぶのを防ぐ）。解決後の結果は永続キャッシュしない——後続の別マウント
  （例: `/admin`と`/`を別タブで開く）では改めて最新を取得する。
- `SystemStatusPanel`・`DebugConsole`はポーリングをせず、開いたとき（`open`が`true`に
  なった瞬間）と明示的な「更新」ボタン押下時にのみ`fetchAll`/エントリ取得を行う
  （プロセス内カウンタ・モジュール評価時刻のスナップショットという性質のため）。
