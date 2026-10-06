# 開発者機能（frontend）

## 責務

`/admin`（`app/admin/page.tsx`、Basic認証保護下）にある開発者向け補助機能（ログ表示・
システム状況）と、一般公開ページ`page.tsx`（`/`、認証なし）のヘッダーメニューから直接操作
できる機能（デバッグログ表示）。

**対象ファイル**

| ファイル | 責務 | マウント先 |
|---|---|---|
| `app/admin/page.tsx` | `/admin`のタブ構成を束ねるコンポジションルート（開いたときは軸スタジオのタブ） | 独立URL |
| `components/HeaderMenu/HeaderMenu.tsx` | 使い方の説明の入口（「使い方を見る」。[ページ全体構成](page-composition.md)「使い方の説明」）・デバッグログ表示を1個のメニューアイコンへ集約したRadix Popover | `page.tsx`（`/`）のヘッダー |
| `features/admin/DebugPanel/DebugPanel.tsx` | デバッグログ表示のON/OFFトグル | `/admin`「開発者」タブ |
| `components/DebugConsole/DebugConsole.tsx` | 地図イベント・外部API呼び出しの詳細ログを時系列表示するフローティングパネル。**表示中の行をそのままの形でコピーできる**（絞り込みを無視して全件にすると、絞って見つけた数行を渡したいときに関係ない行まで混ざる） | `page.tsx`（`/`）、`HeaderMenu`から開閉 |
| `features/admin/SystemStatusPanel/SystemStatusPanel.tsx` | backend `/api/debug/stats`の集計・フロントバージョン・予報（MSM）の同期鮮度を表示するフローティングパネル | `/admin`「開発者」タブ |
| `features/admin/BackendStatus/BackendStatus.tsx` | バックエンドの死活確認の簡易表示 | `/admin`「開発者」タブ |
| `features/admin/BackendLogsPanel/BackendLogsPanel.tsx` | backend `GET /api/admin/debug/logs`の直近ログをレベル（DEBUG〜CRITICAL）・部分一致で絞り込んで表示するパネル。取得は「取得」ボタン押下時のみ（ポーリングなし） | `/admin`「開発者」タブ |
| `components/FloatingPanel/FloatingPanel.tsx` | `DebugConsole`/`SystemStatusPanel`が共有するドラッグ可能な浮動パネルの共通シェル（`react-rnd`ベース） | 両パネルの実装基盤 |
| `hooks/useCopyToClipboard.ts` | クリップボードへの書き込みと結果表示（コピー済み・失敗）。Clipboard APIは[SecureContext]のため、httpのIPアクセス等では`navigator.clipboard`自体がundefinedになる——`.catch()`はPromiseの拒否しか捕まえず、プロパティアクセスの同期TypeErrorをtryで受けないとボタンが無反応のままになる。失敗は握り潰さず文言を返す | `DebugConsole`・`BackendLogsPanel` |
| `hooks/useDebugLog.ts`・`lib/debugLog.ts` | デバッグモードON/OFF状態・ログエントリのシングルストア（`useSyncExternalStore`） | |
| `app/api/version/route.ts` | フロントエンドのビルドバージョンを返すNext.js route handler（`SystemStatusPanel`が読む） | |

## `/admin`とpage.tsx（`/`）の境界

```
app/admin/page.tsx（独立URL、Basic認証保護下）
  ├─ タブ「軸スタジオ」: AxisStudio（本モジュール対象外）
  ├─ タブ「材料」　　　: MaterialCoveragePanel（材料ごとの欠損割合、本モジュール対象外）
  ├─ タブ「較正値」　　: TuningPanel（走ってみて決める値の編集、本モジュール対象外）
  ├─ タブ「データ保守」: DerivedDataFreshnessPanel（派生データの鮮度台帳）+ DbStatusPanel
  │                     （本番DBの状態）+ TileCachePanel（タイルファイルキャッシュの全消去、
  │                     いずれも本モジュール対象外）
  └─ タブ「開発者」　　: DebugPanel + BackendStatus + SystemStatusPanel + BackendLogsPanel

app/page.tsx（メインページ、地図を持つ、認証なし）
  └─ header: HeaderMenu（使い方を見る・デバッグログ表示ボタン）
       └─ DebugConsole（debugEnabled時のみHeaderMenuに項目表示、開閉はheader直下で管理）
```

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
3. **パネルの開閉**（`app/page.tsx: debugConsoleOpen`）: `DebugConsole`自体の表示/非表示。
   デバッグモードONでも常時パネルを占有させない、記録の有効/無効とは独立したstate。

## 暗黙の前提

- `useAxisCatalog()`（`GET /api/axis-catalog`）の共有・取り直しの規則は
  [ルート設定・結果パネル](route-settings-and-results.md)「暗黙の前提」が持つ。`/admin`と`/`を別タブで
  開くと、タブごとに別のキャッシュで取る。
- `SystemStatusPanel`・`DebugConsole`はポーリングをせず、開いたとき（`open`が`true`に
  なった瞬間）と明示的な「更新」ボタン押下時にのみ`fetchAll`/エントリ取得を行う
  （プロセス内カウンタ・モジュール評価時刻のスナップショットという性質のため）。
