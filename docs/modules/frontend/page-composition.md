# ページ全体構成・状態管理（frontend）

## 責務

`app/page.tsx`がアプリのコンポジションルート兼状態ハブ。地図（`MapView`）・ルート設定/
結果パネル（`RouteSettingsPanel`・`RouteForm`・`RouteList`・`RouteAxisProfile`）・地図
オーバーレイ制御（`MapOverlayControls`・`MapLayersPanel`）・研究モードの比較表
（`ComparisonPanel`）を1つのReactツリーへ束ね、状態を集約する。Next.jsのApp Router
フレームワークファイル（レイアウト・エラーバウンダリ）と、特定の機能モジュールに
属さない横断的なlib/hooks/UI基盤もここで扱う。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| app | `page.tsx`・`layout.tsx`・`error.tsx`・`global-error.tsx` |
| services | `routeApi.ts`（ルート生成・プレビューAPI） |
| hooks | `useStoredState.ts`・`useIsMobile.ts`・`useElementHeightCssVar.ts`・`useLocation.ts`・`useDebouncedValue.ts`・`useIsomorphicLayoutEffect.ts` |
| lib | `apiBaseUrl.ts`・`apiError.ts`・`backendInternalUrl.ts`・`fetchJson.ts`・`cn.ts` |
| types | `route.ts`（`RouteCandidate`等の生成APIレスポンス型） |
| components/Map | `useLayerDataStatus.ts`（`layerDataStatus` stateの実装） |
| components/ui | `Button`・`Card`・`Checkbox`・`Dialog`・`Input`・`ErrorText`（汎用UI基盤、全モジュール共通） |

`apiBaseUrl.ts`/`backendInternalUrl.ts`はブラウザからのfetch先（`NEXT_PUBLIC_API_BASE_
URL`）とNext.js route handlerからのサーバー間fetch先を区別する（後者はコンテナ内部
ネットワークのURLになりうるため別変数）。`fetchJson.ts`/`apiError.ts`は全`services/*Api.ts`
クライアントが共有するfetchラッパーとエラー正規化。`useLocation.ts`はブラウザの
Geolocation APIを扱うhookで、起点座標の取得に使う。

## 主な構成要素（import元）

| 種別 | コンポーネント |
|---|---|
| 地図本体 | `Map/MapView`（全静的/動的レイヤーのMapLibre実装本体） |
| 地図オーバーレイ制御 | `MapOverlayControls`（地図上チップ）・`MapLayersPanel`（サイドバー） |
| ルート設定 | `RouteForm`（モード切替/距離/生成ボタン）・`RouteSettingsPanel`（0次除外・軸選択・重み・地図色分けトグル） |
| ルート結果 | `RouteList`（候補一覧）・`RouteAxisProfile`（選択ルート全体の軸別難易度） |
| 研究モード | `ComparisonPanel`（実験スロット比較表）。`WeightPanel`自体は`/admin`側 |
| レイアウト | `BottomSheet`（モバイル下部シート） |

## page.tsxの状態管理

| 分類 | state | 永続化 |
|---|---|---|
| ルート結果 | `routes`・`selectedRouteId`・`hasUnseenResults`・`loading`・`generationProgress`・`errorMessage`・`generatedConditions`・`generatedRoutePreference` | なし |
| 目的地モード | `waypoints`・`destination`・`destinationArmed`・`routeMode`・`distanceInput` | なし |
| 生成条件（研究） | `weightOverrideEnabled`・`scoringWeights`・`routePreference`・`hardFilters` | localStorage（研究モード2件は`/admin`と共有キー） |
| 実験スロット | `experimentSlots` | なし |
| 地図ビューポート | `mapViewport` | なし |
| レイヤー表示 | `layerVisibility`・`routeStyleModeId`・`hiddenLegendKeysByMode` | localStorage |
| パネル開閉 | `generateOpen`・`sidebarCollapsed`・`mobileSheet`・`mobileSheetHeightVh`・`routeProfileOpen` | 一部localStorage |
| 地図状態 | `regionZoomTooWide`・`layerDataStatus`・`refreshToken`・`debugConsoleOpen` | なし |
| 動的パラメータ | `windBearingDeg`・`gradientBearingDeg` | なし |

## 動的材料（風・勾配）の状態別表現契約

`page.tsx`は風・勾配それぞれについて「環境グループ（面塗り、探索用）」と「評価軸グループ
（線、視界内の全道路へ一律色分け）」の2表現を同時に配線する。両者は`[時刻, 向き]`のうち
共有する入力が異なる:

```
風:   [時刻]dynamicLayerTargetTime（useDynamicWeatherLayers由来）
      [向き]windBearingDeg（page.tsxのuseState、WindBearingSliderで操作）
        │                              │
        ├─→ 環境（面）: showWindPenaltyFill = showWindVector && !hasDetail
        │     useDynamicWeatherLayers内でwindPenaltyPayload計算
        └─→ 評価軸（線）: showWindAxis = layerVisibility.windAxis && !hasDetail
              useDynamicWayValues("wind", showWindAxis, mapViewport,
                                  windBearingDeg, dynamicLayerTargetTime)

勾配: [向き]gradientBearingDeg（page.tsxの別のuseState、時刻非依存）
        │                              │
        ├─→ 環境（面）: showGradientFill = layerVisibility.gradientFill && !hasDetail
        │     gradientGridCellsFromTileResponses(gradientAxisData.byTile)
        └─→ 評価軸（線）: showGradientAxis = layerVisibility.gradientAxis && !hasDetail
              useDynamicWayValues("gradient", showGradientAxis || showGradientFill,
                                  mapViewport, gradientBearingDeg, undefined)
```

いずれも**ルート確定後（`hasDetail`）は環境・評価軸どちらの一律表現も終了**し、「生成した
ルートの色分け」（`routeStyleModes.ts`由来のモード選択）へ委ねる契約になっている。

**暗黙の前提**: `windAxisPenalties`・`gradientAxisValues`・`gradientFillGeojson`は
`MapView.tsx`の`MapViewProps`上で軸ごとに個別に型付けされたpropとして渡されている
（汎用的な「軸id→値」の1つのpropにまとまっていない）。

## 状態の永続化（`hooks/useStoredState.ts`）

`useStoredState(key, defaultValue, {serialize, deserialize, autoSave, reloadKey})`が
localStorageへの保存・復元を1箇所に集約する。

- 復元は`useState`の初期化子ではなく、マウント後の`layout effect`
  （`useIsomorphicLayoutEffect`）で行う（SSR時のHTMLとハイドレーション結果のずれ防止）。
- 保存は「setter呼び出しのたびに即書き込む」方式（`autoSave`省略時true）。
- `reloadKey`: 復元処理を再実行させたい追加の依存値。`deserialize`はrefへ退避しない
  （`reloadKey`が変わった際、その時点の最新の`deserialize`クロージャで再復元する）。例:
  `layerVisibility`は`axisCatalog.loaded`を`reloadKey`にし、マウント直後（静的フォール
  バック集合で復元）→フェッチ完了後（実行時集合で再復元）の2段階復元にしている。
- `useStoredJsonState`は`JSON.stringify`/`JSON.parse`を既定にした薄いラッパー
  （`/admin`とのstate共有に使う）。
- 読み書きの失敗（プライベートブラウジング等）はデフォルト値へのフォールバックとして
  握りつぶす。

## page.tsxが橋渡しする主なデータフロー

- `routePreference`（`RouteSettingsPanel`が編集）→ `syncRoutePreferenceKeys`による
  キー整合補正 → ルート生成リクエスト。整合補正は`RouteSettingsPanel`のマウント時
  （`useEffect`）と、`handleGenerate`内（送信直前、パネル未マウント経路の穴埋め）の
  2箇所で行う。
- `layerVisibility`（`MapOverlayControls`/`MapLayersPanel`/`RouteSettingsPanel`の
  「色分け」トグルが共有）→ `MapView`の表示制御。
- `routeStyleModeId`（`routeStyleModesFromCatalogAxes`が`axisCatalog.axes`から動的生成
  する選択肢、`filterRouteStyleModesByPreference`で重み0の軸を除外）→ `MapView`の
  ルート線色分け。
- `RAMP_AXES`/`axisCatalog.rampAxes` → `buildMapLayers`/`buildStaticFilterAxes`/
  `buildRoadSurfaceSharedLayerIds`経由でレイヤー構成を組み立てる。
- `axisCatalog.secondaryAxes`（`primaryAttributeIds`）→ `secondaryAxisCasingLayerIds`
  （二次軸の下敷き表現、[静的レイヤー・道路表示](static-map-layers.md)参照）。
- `windBearingDeg`/`gradientBearingDeg`/`dynamicLayerTargetTime` → 環境/評価軸の
  風・勾配表現が共有する入力（上記「動的材料の状態別表現契約」参照）。

## モバイル/デスクトップのレイアウト分岐

`useIsMobile()`（`MOBILE_BREAKPOINT_PX`=640px、`globals.css`の`@media`と一致を自動
テストで検証）で分岐する:

- デスクトップ: サイドバー（`aside.app-sidebar`）に「ルートを作る」（`Disclosure`
  折りたたみ、`generateOpen`で開閉状態を永続化）と「地図の見え方」の2ブロックを縦積み。
- モバイル: 天候ヘッダー直下に`RouteForm`（`compact`）を常設し、下部タブバー（ルート
  設定/ルート結果/地図の見え方）+`BottomSheet`（3枚が`mobileSheet`で排他表示、高さ
  `mobileSheetHeightVh`を共有）。

`BottomSheet`はposition:fixedのオーバーレイで暗幕を敷かない（表示中も地図をパン/ズーム
できる）。ドラッグ中は`onHeightChange`のみ（見た目の即時反映）、確定時に
`onHeightCommit`（永続化）を呼ぶ2段階のコールバック構成を持つ。

選択中ルートの全体プロファイル（`RouteAxisProfile`、`axisCatalog.axes`と
`axis_difficulties`から横棒グラフ生成）は、`mobileSheet`の3タブとは独立した
`routeProfileOpen`という別のBottomSheetで、デスクトップの「ルートを作る」ブロック内・
モバイルの「ルート結果」タブの両方から同じ`renderRouteOutcomeSectionBody`関数経由で開ける。

## `MapView`（`Map/MapView.tsx`）との境界

`page.tsx`は`MapView`へ多数のprops（表示フラグ・色分けデータ・コールバック）を渡す。
`MapView`自身はレイヤー固有の判断ロジックを持たず、渡された値をそのままMapLibreの
source/layer操作へ変換する「汎用描画係」という位置づけを保っている
（[静的レイヤー・道路表示](static-map-layers.md)・[動的気象レイヤー](dynamic-weather-layers.md)参照）。
地図初期化用の`useEffect`は空配列依存でマウント時に1度だけ実行され、最新props値は
`redrawPropsRef`（refへ都度同期）経由で読む——`useEffect`の依存配列に載せると再マウント
のたびにMapLibreインスタンスが作り直されてしまうため。
