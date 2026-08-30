# ページ全体構成・状態管理（frontend）

## 責務

`app/page.tsx`がアプリのコンポジションルート兼状態ハブ。地図（`MapView`）・ルート設定/
結果パネル（`RouteSettingsPanel`・`RouteForm`・`RouteList`等）・地図オーバーレイ制御
（`MapOverlayControls`・`MapLayersPanel`）を1つのReactツリーへ束ね、状態を集約する。

**規模**: `page.tsx` 1,827行。`useState`/`useStoredState`/`useStoredJsonState`の宣言数
（機械カウント）45件。

## 主な構成要素（import元）

| 種別 | コンポーネント |
|---|---|
| 地図本体 | `Map/MapView` |
| 地図オーバーレイ制御 | `MapOverlayControls`（地図上チップ）・`MapLayersPanel`（サイドバー） |
| ルート設定 | `RouteForm`（距離/生成ボタン）・`RouteSettingsPanel`（軸重み・除外道路） |
| ルート結果 | `RouteList`（候補一覧）・`RouteAxisProfile`（軸別内訳） |
| 研究モード | `WeightPanel`の定数（`DEFAULT_ROUTE_PREFERENCE`等）・`ComparisonPanel` |
| レイアウト | `BottomSheet`（モバイル下部シート） |

## 状態の永続化（`hooks/useStoredState.ts`）

`useStoredState(key, defaultValue, {serialize, deserialize, autoSave, reloadKey})`が
localStorageへの保存・復元を1箇所に集約する（以前は`page.tsx`にlocalStorage読み書きの
手書きペアが散在していた）。

- 復元は`useState`の初期化子ではなく、マウント後の`layout effect`で行う
  （SSR時のHTMLとハイドレーション結果のずれ・ちらつき防止のため）。
- 保存は「setter呼び出しのたびに即書き込む」方式（エフェクトでの自動保存ではない）。
  開発時StrictModeの再マウントで「復元前の初期値の保存」が復元読み出しへ割り込み、
  保存済み設定を既定値で上書きする実害が過去にあったため。
- `reloadKey`: 復元処理を再実行させたい追加の依存値（例: 軸カタログの実行時フェッチが
  完了した後、静的フォールバック集合から実行時集合へ2段階で再復元する`layerVisibility`）。
- 読み書きの失敗（プライベートブラウジング等）はデフォルト値へのフォールバックとして
  握りつぶす。

## page.tsxが橋渡しする主なデータフロー

- `routePreference`（[ルート設定・結果パネル](route-settings-and-results.md)の
  `RouteSettingsPanel`/`WeightPanel`が編集）→ ルート生成リクエスト。
- `layerVisibility`（`MapOverlayControls`/`MapLayersPanel`/`RouteSettingsPanel`の
  「色分け」トグルが共有）→ `MapView`の表示制御。
- `routeStyleModeId`（[地図: 軸・ルート色分け](map-axis-coloring.md)の
  `routeStyleModesFromCatalogAxes`が生成する選択肢）→ `MapView`のルート線色分け。
- `RAMP_AXES`（[地図: 軸・ルート色分け](map-axis-coloring.md)・
  [静的レイヤー・道路表示](static-map-layers.md)双方が参照する軸カタログ由来のramp軸
  一覧）→ `buildMapLayers`/`buildStaticFilterAxes`経由でレイヤー構成を組み立てる。
