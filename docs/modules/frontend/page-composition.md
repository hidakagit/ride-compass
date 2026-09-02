# ページ全体構成・状態管理（frontend）

## 責務

`app/page.tsx`がアプリのコンポジションルート兼状態ハブ。地図（`MapView`）・ルート設定/
結果パネル（`RouteSettingsPanel`・`RouteForm`・`RouteAxisProfile`）・地図
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
| 地図オーバーレイ制御 | `MapOverlayControls`（地図上チップ）・`MapLayersPanel`（サイドバー）・`TravelBearingControl`（走行方位ダイヤルの地図上アイコン） |
| ルート設定 | `RouteForm`（モード切替/距離/生成ボタン）・`RouteSettingsPanel`（0次除外・軸選択・重み・地図色分けトグル） |
| ルート結果 | `RouteAxisProfile`（候補ごとのタブの中身、軸別難易度）。候補ごとのタブ自体は独立コンポーネントを持たずpage.tsxが直接組み立てる |
| 研究モード | `ComparisonPanel`（実験スロット比較表） |
| レイアウト | `BottomSheet`（モバイル下部シート） |

## page.tsxの状態管理

| 分類 | state | 永続化 |
|---|---|---|
| ルート結果 | `routes`・`selectedRouteId`・`selectedRouteSegment`・`comparisonTabActive`・`hasUnseenResults`・`loading`・`generationProgress`・`errorMessage`・`generatedConditions`・`generatedRoutePreference` | なし |
| 目的地モード | `waypoints`・`destination`・`destinationArmed`・`routeMode`・`distanceInput` | なし |
| 生成条件（研究） | `weightOverrideEnabled`・`scoringWeights`・`routePreference`・`hardFilters` | localStorage（研究モード2件は`/admin`と共有キー） |
| 実験スロット | `experimentSlots` | なし |
| 地図ビューポート | `mapViewport` | なし |
| レイヤー表示 | `layerVisibility`・`routeStyleModeId`・`hiddenLegendKeysByMode` | localStorage |
| パネル開閉 | `generateOpen`・`sidebarCollapsed`・`mobileSheet`・`mobileSheetHeightVh` | 一部localStorage |
| 地図状態 | `regionZoomTooWide`・`layerDataStatus`・`refreshToken`・`debugConsoleOpen` | なし |
| 動的パラメータ | `travelBearingDeg` | なし |

## 動的材料（風・勾配）の状態別表現契約

`page.tsx`は風・勾配それぞれについて「環境グループ（面塗り、探索用）」と「評価軸グループ
（線、視界内の全道路へ一律色分け）」の2表現を同時に配線する。両者は`[時刻, 向き]`のうち
「時刻」の扱いが異なる（風のみ時刻依存）が、「向き」は単一の共有state
`travelBearingDeg`を風・勾配の両方が使う（走行方位という1つの概念を表す単一state）:

```
travelBearingDeg（page.tsxの単一useState、TravelBearingControlで操作）
  │
  ├─→ 風:   [時刻]dynamicLayerTargetTime（useDynamicWeatherLayers由来）
  │           │                              │
  │           ├─→ 環境（面）: showWindPenaltyFill = showWindVector && !hasDetail
  │           │     useDynamicWeatherLayers内でwindPenaltyPayload計算
  │           └─→ 評価軸（線）: showWindAxis = layerVisibility.windAxis && !hasDetail
  │                 useDynamicWayValues("wind", showWindAxis, mapViewport,
  │                                     travelBearingDeg, dynamicLayerTargetTime)
  │
  └─→ 勾配: （時刻非依存）
              │                              │
              ├─→ 環境（面）: showGradientFill = layerVisibility.gradientFill && !hasDetail
              │     gradientGridCellsFromTileResponses(gradientAxisData.byTile)
              └─→ 評価軸（線）: showGradientAxis = layerVisibility.gradientAxis && !hasDetail
                    useDynamicWayValues("gradient", showGradientAxis || showGradientFill,
                                        mapViewport, travelBearingDeg, undefined)
```

いずれも**ルート確定後（`hasDetail`）は環境・評価軸どちらの一律表現も終了**し、「生成した
ルートの色分け」（`routeStyleModes.ts`由来のモード選択）へ委ねる契約になっている。設定UIは
`TravelBearingControl`（地図右上、MapLibreのズーム+/−・回転コントロールの直下に置く
アイコンボタン）1箇所へ集約されており、風・勾配いずれかの環境/評価軸表示が1つでもONの
間だけ表示される（`showWindVector || showGradientFill || showWindAxis || showGradientAxis`、
かつ`!hasDetail`）。中身は`RouteSettingsPanel`と同じ`WindBearingSlider`ダイヤルを
Radix Popoverで開く。

**暗黙の前提**: `windAxisPenalties`・`gradientAxisValues`・`gradientFillGeojson`（way_id/
タイル単位の実データ本体）は`MapView.tsx`の`MapViewProps`上で軸ごとに個別に型付けされた
propとして渡されている（汎用的な「軸id→値」の1つのpropにまとまっていない）。一方、
表示しきい値（軸スタジオの`display_thresholds_override`）は
`dedicatedWayValueBoundaries: ReadonlyMap<string, readonly number[]>`という1つの汎用propに
まとまっている。`page.tsx`が`axisCatalog.axes`から`dedicatedWayValueLayer===true`の軸を
横断的に抽出して構築するため、`dedicated_way_value_layer`軸が増えてもこのprop自体の
変更は不要。

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
- `travelBearingDeg`/`dynamicLayerTargetTime` → 環境/評価軸の風・勾配表現が共有する入力
  （上記「動的材料の状態別表現契約」参照）。

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
`onHeightCommit`（永続化）を呼ぶ2段階のコールバック構成を持つ。任意の`headerAction`
propでヘッダ右側・閉じるボタンの手前へ要素を差し込める（「ルート結果」シートの
情報アイコン＋「ルートをクリア」、下記`renderRouteOutcomeSectionBody`参照）。

## `renderRouteOutcomeSectionBody`（生成結果、デスクトップ「ルートを作る」ブロック後半・
モバイル「ルート結果」タブ共通）

`routes.length === 0`の間は何も描画しない（生成前は空）。1件以上生成された後は、
「ルート結果」見出し（`showHeading`引数、既定true。デスクトップはこの関数自身が
`<h2>`を描画し、モバイルはBottomSheet側の`title="ルート結果"`と重複するため
`showHeading=false`で呼ぶ——`renderRouteSettingsSectionBody`と同じ使い分け）に続けて、
Radix Tabs（`@radix-ui/react-tabs`）1段のフラットなタブ列を描画する。タブの並び順は
`routes`配列の並び順（backendが`overall_difficulty`昇順で返す、`route_generator.py`
参照）をそのまま使い、フロント側での並べ替えは行わない。タブは
**候補ごと**（`routes`の件数ぶん、方向・距離のみを表示。総合難易度の点数はタブの中身
（`RouteAxisProfile`のスコア行）に既に出ているためタブ内では繰り返さない）＋「比較」
（`ComparisonPanel`、`researchEnabled`の間だけ末尾に追加。実験スロット2件未満の
自己ガードは`ComparisonPanel`自身が持つため、非アクティブ中も状態更新を止めないよう
`forceMount`でマウントし続け、`[data-state="inactive"]`のCSSで非表示にする）で構成
される（「ルート選択」のような候補一覧をまとめる中間タブは無い。候補一覧タブ・比較タブの
2段構成を経て現在の1段フラット構成に落ち着いた）。候補数（8方位＋経由地/目的地ルート）が
画面幅を超える場合はタブ列自身が横スクロールする。`routes`・`selectedRouteId`・
`comparisonTabActive`・`generatedConditions`・`generatedRoutePreference`に加え
`experimentSlots`（比較タブ・地図重ね描き用の履歴）も同時に空にする（`handleRoutesClear`）。

総合難易度の説明（`ROUTE_RESULT_HINT`）と「ルートをクリア」
（`handleRoutesClear`）は`renderRouteResultHeaderActions()`という1つのヘルパーへまとめ、
「ルート結果」セクション見出し1箇所（候補タブ・`RouteAxisProfile`側には置かない）から
呼ぶ。デスクトップは`renderRouteOutcomeSectionBody`自身の見出し行内（`<h2>`ルート結果と
`justify-content: space-between`で並べる）、モバイルはBottomSheetの`headerAction`
propとして同じヘルパーを渡す（`routes.length > 0`の間のみ）。情報アイコン
（`FieldLabel`）は`hideLabel`propでラベル文言をsr-only化し、アイコン単体の見た目にする。

外側タブの選択値は`selectedRouteId`（候補タブ選択時）と`comparisonTabActive`
（比較タブ選択時）を組み合わせて求める。`selectedRouteId`自体は比較タブを見ている間も
「最後に見ていた候補」を保持し続け、地図の色分け対象・`selectedCandidate`等の使われ方は
タブ構成に関わらず変わらない（比較タブから候補タブへ戻ると、見ていた候補がそのまま
選択された状態に戻る）。

候補タブの中身（`Tabs.Content`）は`RouteAxisProfile`単体。`RouteAxisProfile`は
「地図の色分け」チップ列（総合難易度＋`route_preference`の重み>0の軸のみ、
`RouteSettingsPanel`の凡例チップと同じ見た目の1行）・総合難易度の表示・軸別内訳
（`domain/difficulty.py:
composite_difficulty`と同じ考え方で軸の重みを反映した寄与度をバー長に、生の
`axis_difficulties`値をバー色に使う。この一覧は選択操作を持たない読み取り専用）・
凡例の表示/非表示設定（`stackBarLegendTrigger`パターン）をまとめて持つ。地図の色分け
チップ選択は地図側の色分けモード（`routeStyleModeId`）を切り替え、選択中モードが
まだOFFなら「ルート」チップ（`layerVisibility.route`）も自動でONにする。

`ComparisonPanel`へ渡す`axes`は、表示中のいずれかの実験スロットで生成時点の重み
（`ExperimentSlot.conditions.route_preference`）が>0だった軸に絞り込む（現在のライブな
`routePreference`ではない）。

## `MapView`（`Map/MapView.tsx`）との境界

`page.tsx`は`MapView`へ多数のprops（表示フラグ・色分けデータ・コールバック）を渡す。
`MapView`自身はレイヤー固有の判断ロジックを持たず、渡された値をそのままMapLibreの
source/layer操作へ変換する「汎用描画係」という位置づけを保っている
（[静的レイヤー・道路表示](static-map-layers.md)・[動的気象レイヤー](dynamic-weather-layers.md)参照）。
地図初期化用の`useEffect`は空配列依存でマウント時に1度だけ実行され、最新props値は
`redrawPropsRef`（refへ都度同期）経由で読む——`useEffect`の依存配列に載せると再マウント
のたびにMapLibreインスタンスが作り直されてしまうため。
