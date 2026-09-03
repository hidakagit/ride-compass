# 地図: 軸・ルート色分け（frontend）

## 責務

評価軸（軸スタジオ管理）のdifficulty値を、(1) ルート確定前は視界内の全道路（評価軸
グループの線）・環境グループの面、(2) ルート確定後は選択中ルートの線、それぞれ地図上で
色分け表示する。専用のway_id→値配信レイヤー（[動的材料・way_id値配信（backend）](../backend/dynamic-way-values.md)）
を持つ軸（現状: 風・勾配）が対象。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `Map/routeStyleModes.ts` | ルート確定後の色分けモード一覧・色式 |
| `Map/windAxisLayer.ts`・`gradientAxisLayer.ts` | ルート確定前の評価軸グループ線の色式 |
| `Map/windPenalty.ts`・`gradientGridFill.ts` | ルート確定前の環境グループ面（gridFill）の値計算・色式 |
| `Map/dynamicWayValues.ts` | タイル座標計算・複数タイル応答の統合（材料非依存の共通部分） |
| `Map/axisLayers.ts` | `rampColorForBand`/`COLOR_UNKNOWN`（共有色ヘルパー、windAxisLayer/gradientAxisLayerが使う）。ramp軸自体の全面的な生成ロジックは主に[地図: 静的レイヤー・道路表示](static-map-layers.md)の管轄 |
| `Map/mapColorLegend.ts` | 地図上の色分け凡例（`MapColorLegendBand`型・`buildRangeLegendBands`・`rangeStepLabel`）の共通ロジック。windAxisLayer/gradientAxisLayerの`*Legend`関数が使う |
| `components/MapColorLegend/MapColorLegend.tsx` | 上記の凡例データを地図上部中央に表示するUI部品（`page.tsx`が組み立てる、配置の理由は下記参照） |
| `Map/mapLayers.ts` | `isDedicatedWayValueLayerId`・`isAxisStudioLayer`（レイヤーID判定） |
| `Map/MapView.tsx`（windAxis/gradientAxis/gradientFill/DETAIL_LAYER_ID関連箇所のみ） | MapLibreへの実際の配線——ensure/apply関数群・setFeatureState反映・effect分割 |
| `hooks/useDynamicWayValues.ts` | フェッチ・状態管理（viewportデバウンス＋タイル単位取得） |
| `services/axisAdminApi.ts`・`regionApi.ts`（`fetchDynamicWayValues`のみ） | backend APIラッパー |

**`MapView.tsx`は路面タイル・動的気象（降水/風の矢印/雷/竜巻）・POI等のロジックも持つ
ファイルで、それらは[地図: 静的レイヤー・道路表示](static-map-layers.md)・
[地図: 動的気象レイヤー](dynamic-weather-layers.md)の管轄。本ドキュメントはwindAxis/
gradientAxis/gradientFill/ルート確定後の色分け（DETAIL_LAYER_ID）に関わる箇所のみを扱う。**

## ルート確定前後で異なる値source（3つの表示、共通しきい値）

```
                          [評価軸グループ（線）]                [環境グループ（面）]
ルート未確定  ── setFeatureState経由の値 ──┐   ┌── gridFill（風=風グリッド式計算 / 勾配=タイル平均） 
              （useDynamicWayValues）      │   │
                                            ▼   ▼
                                  同じ配色・しきい値を共有
                                            ▲
ルート確定後  ── RouteSegmentDetailの ──────┘   （環境グループは非表示、評価軸グループが
              axis_difficulties /              「生成したルートの色分け」モードへ役割を譲る）
              gradient_percent直読み
```

## 軸id→振る舞いの判定（データ駆動、axis_idのハードコード比較を使わない）

| 判定 | 使う軸データ属性 | 関数 |
|---|---|---|
| 専用way_id配信レイヤーを持つか | `AxisDefinition.dedicated_way_value_layer` | `mapLayers.ts: isDedicatedWayValueLayerId` |
| 符号付き値を直接読むべきか（勾配のような向きを持つ軸） | `shape.kind==="breakpoint_linear" && shape.preprocess==="abs" && shape.terms.length===1` | `routeStyleModes.ts: isSignedAbsShape` |

公開軸は無条件でルート結果色分けの選択肢になる（`routeStyleModes.ts:
routeStyleModesFromCatalogAxes`が公開軸すべてをマップする）。実際にユーザーが使っている
軸だけへの絞り込みは`filterRouteStyleModesByPreference`（route_preferenceの重み>0）が担う。

`isSignedAbsShape`が真の場合、値は`axis_difficulties[axis_id]`（0-100正規化済み）
ではなく`shape.terms[0].material`（生材料、例: `gradient_percent`）を直接読む——
向き（登り/下り）は絶対値化されたdifficultyでは表現できないため。

## routeStyleModes.ts（ルート確定後）

- `buildRangeSteppedMode`: 境界値配列（軸スタジオの`display_thresholds_override`、
  未設定時は経路ごとの既定値）の**長さがそのまま段階数を決める**汎用関数。ラベルは
  境界値の実際の数字から機械的に生成する。
- `interpolateColors(colorLow, colorHigh, count)`: 2色の間をHSL色空間でcount色に均等
  補間する（固定の色配列を持たないため、しきい値の個数が変わっても色が自動追従する）。
- `DIFFICULTY_MODE`（総合難易度）だけがフロントの固定モード——特定のaxis_idに紐づかず
  全軸の重み付き合成コストそのものを表示するため、軸スタジオと同期する対象にならない。
- `filterRouteStyleModesByPreference`: `routePreference`で重み0にした軸のモードを
  選択肢から除外する（`page.tsx`側で使用）。
- `DEFAULT_ROUTE_STYLE_MODE_ID`は`ROUTE_STYLE_MODES[0].id`から導出する。
- **地図上の重ね順**（`MapView.tsx: drawDetailSegments`・`keepRouteArrowsAboveDetailSegments`）:
  選択中候補の区間色分け線（`DETAIL_LAYER_ID`、幅6px・不透明）とその当たり判定線
  （`DETAIL_HIT_LAYER_ID`、幅24px・透明）は、同じ候補の進行方向矢印
  （`ROUTE_ARROW_HALO_LAYER_ID`→`ROUTE_ARROW_LAYER_ID`、`routeArrowIcon.ts`）より常に下に置く。
  矢印層はページ表示直後に、色分け線は最初の生成後に作られるため、作成順に任せず
  「色分け線→当たり判定線→矢印ハロー→矢印」の順を両方の作成時に明示する。矢印2層は
  衝突判定を無効（`icon-allow-overlap`/`icon-ignore-placement: true`）にしてある——
  MapLibreは上のレイヤーから順にシンボルを配置するため、衝突判定を有効にすると主層の矢印と
  同位置・大きめのハロー層が全て落ち、色分け線が紺系のモードでは同色の矢印が線に沈む。

## windAxisLayer.ts / gradientAxisLayer.ts（ルート確定前の評価軸グループ線）

- `windAxisLayer.ts`: `WIND_AXIS_FEATURE_STATE_KEY = "windPenalty"`。
  `WIND_AXIS_THRESHOLDS = [-6, -2, 2, 6]`は未設定時のフォールバック既定値。
- `gradientAxisLayer.ts`: `GRADIENT_AXIS_FEATURE_STATE_KEY = "gradientValue"`。
  境界値は`routeStyleModes.ts: GRADIENT_BOUNDARIES`を未設定時のフォールバックとして持つ。
- wind/gradientいずれも、軸スタジオの`display_thresholds_override`は
  `page.tsx: dedicatedWayValueBoundaries`（`axisCatalog.axes`から
  `dedicated_way_value_layer===true`の軸を横断的に抽出した`ReadonlyMap<axisId,
  readonly number[]>`、`MapViewProps.dedicatedWayValueBoundaries`経由）から取得する
  汎用機構1つにまとまっている。未設定の軸idは上記のビルド時既定値へフォールバックする。
- 両者とも`buildXxxColorExpression(valueExpression, boundaries?)`という「値の取得元
  （feature-state or geojsonプロパティ）だけが呼び出し側で異なる」共通ロジックを持ち、
  評価軸グループ（feature-state経由）と環境グループのgridFill（`["get",...]`経由）が
  同じ配色・しきい値を共有する契約をコード上でも1箇所に集約する。
- `windAxisLegend(boundaries?, labels?)`/`gradientAxisLegend(boundaries?, labels?)`は、
  同じ配色・しきい値から地図上の凡例（色→値の対応、`mapColorLegend.ts:
  MapColorLegendBand[]`）を組み立てる。任意の`labels`（段階ごとの体感ラベル、例:
  「強い向かい風」）を渡すと数値レンジの前に添える（`mapColorLegend.ts:
  buildRangeLegendBands`の`labels`引数、色は指定せず既存の`rampColorForBand`/
  `interpolateColors`自動生成のまま）。`labels`は`boundaries.length+1`（段階数）と
  要素数が一致する間だけ使い、不一致時は数値レンジのみへフォールバックする（不整合な
  保存データへの防御）。`labels`自体はこのファイルに固定値を持たず、軸スタジオの
  `display_band_labels_override`（`AxisDefinition`、`display_thresholds_override`と
  対になるフィールド、[軸スタジオ・評価軸定義（backend）](../backend/axis-studio.md)参照）
  が唯一のソース——`page.tsx`が`dedicatedWayValueBoundaries`と同じパターンで
  `axisCatalog.axes`から`dedicatedWayValueBandLabels`（軸id→ラベル配列のMap）を組み立てて
  渡す。通常のramp軸（`buildAxisRampLegend`）も同じ`display_band_labels_override`
  （`RampAxis.bandLabelsOverride`経由）を読み、同じ「段階数一致時のみ適用」規則で
  体感ラベルを表示できる。
  `page.tsx`が`showWindAxis || showWindPenaltyFill`/`showGradientAxis || showGradientFill`
  （評価軸の線・環境グループのgridFillのどちらか一方でもONの間）・ramp軸（`axisVisibility`、
  `axisLayers.ts: buildAxisRampLegend`）を横断して集め、`MapColorLegend`
  （`components/MapColorLegend/`）が地図上部中央に常時表示する（モバイルのBottomSheetが
  画面下側を覆っても隠れないための配置、コンポーネント側コメント参照）。ramp軸の凡例は
  絞り込みフィルタと共有する`LegendEntry`（`filter`必須）を返すが、windAxis/gradientAxisには
  絞り込み機構自体が無いため、意味の無い`filter`を捏造せずに済む`MapColorLegendBand`
  （`{label, color}`のみ）という軽量な専用型を使う。環境グループのgridFillも評価軸グループの
  線と同じ`windAxisLegend`/`gradientAxisLegend`をそのまま使う（同じ配色・しきい値を
  共有する契約のため、凡例データ自体は変わらず表示条件だけを広げている）。

## windPenalty.ts / gradientGridFill.ts（環境グループの面表示、計算方法が異なる）

| | 風（`windPenalty.ts`） | 勾配（`gradientGridFill.ts`） |
|---|---|---|
| 値の出所 | 独立した空間フィールド（気象グリッド、道路とは無関係に存在） | way単位のeffective_gradient（評価軸グループ向けに既にフェッチ済み） |
| 計算方法 | `windPenalty()`——backend `WindCalculator.wind_penalty`のJS移植（物理式） | フェッチ元のタイル境界を1セルとして平均集計（追加のAPI呼び出し無し） |
| セルの単位 | 格子点を中心とする正方形（`gridCellRing`） | タイル境界そのもの（`tileRing`） |

`windPenalty()`は`WindCalculator.wind_penalty`（backend）と同一計算をfrontendで実装した
もの。`windPenalty.test.ts`が既知入出力ペアでbackendとの一致を検証する。

`windPenaltyFillColorExpression(boundaries?)`は評価軸グループ（`windAxisColorExpression`）と
同じ`dedicatedWayValueBoundaries`（`.get("wind")`）を`MapView.tsx`側で受け取り、両者が
同じ配色・しきい値を共有する。`gradientGridFill.ts`側（`makeEnsureGradientFillLayer`）も
同じMapを経由する。

## useDynamicWayValues.ts（フェッチ・状態管理）

viewportをデバウンス（500ms）してから、表示中のタイル範囲ぶんをまとめて1回の
リクエストで取得する（パン・ズームのたびに個別way_idを都度問い合わせない）。
**`bearingDeg`（走行方位）もviewportと同じ500msでデバウンスする**——コンパススライダー
（`WindBearingSlider`）はドラッグ中`onChange`を連続発火するため、素の値を依存配列に
入れるとドラッグ1回で「可視タイル数×連続イベント数」ぶんのfetchが発生してしまうため。
`enabled=false`の間はfetchせず結果も空へ戻す。

戻り値は2種類:

- `values: ReadonlyMap<number, number>`（way_id→値、複数タイル統合済み）——評価軸
  グループの`setFeatureState`にそのまま使える。
- `byTile: TileDynamicWayValues[]`（タイルごとの生応答）——勾配の環境グループgridFill
  （タイル境界セル）が使う。風のgridFillは別経路（風グリッド由来の格子点）のため
  `byTile`は使わない。

`materialId`（"wind"/"gradient"）ごとに呼び出し側（`page.tsx`）が別々にこのフックを
インスタンス化する。連続する呼び出しの間に古いリクエストが後から解決しても新しい結果を
上書きしないよう、リクエストの世代（`seq`、複数タイルの`Promise.all`をまたぐカウンタ）で
最新のものだけを反映する。

## MapView.tsx側の配線

`windAxisLayer.ts`/`gradientAxisLayer.ts`が組み立てる色式（純粋なMapLibre expression）は、
それ自体では地図に何も描かない。実際の地図反映は`MapView.tsx`側の以下の機構が担う。

```
page.tsx
  ├─ useDynamicWayValues("wind", showWindAxis, viewport, travelBearingDeg, targetTime)
  │     → windAxisData.values (ReadonlyMap<wayId, value>)
  ├─ useDynamicWayValues("gradient", showGradientAxis||showGradientFill, viewport, travelBearingDeg, undefined)
  │     → gradientAxisData.values / gradientFillPayload(gradientGridCellsFromTileResponses経由)
  ├─ dedicatedWayValues = Map(["wind", windAxisData.values], ["gradient", gradientAxisData.values])
  ▼
<MapView dedicatedWayValues={...} gradientFillGeojson={...} .../>
  ├─ makeEnsureDedicatedWayValueLayer(layerId, colorExpression)
  │     → windAxis/gradientAxisレイヤーをroad_surfaceタイルの独立レイヤーとして初回のみ追加
  │       （ensureRoadSurfaceTileLayerが先にpromoteId付きsourceを用意している前提）
  ├─ DEDICATED_WAY_VALUE_FEATURE_STATE_KEYS（axisId→featureStateKeyの小さなlookup）を
  │   1つのeffectでループし、各軸へapplyAxisFeatureStateValues(map, featureStateKey, values)
  │     → map.setFeatureState({source, sourceLayer, id: wayId}, {[key]: value}) を全way分実行
  └─ clearRoadTileFeatureState(map)
        → showWindAxis・showGradientAxisが両方falseへ揃った瞬間、setFeatureStateした
          全道路ぶんの値を明示的にクリアする1つのeffectに統合されている
          （`map.removeFeatureState`はsource/sourceLayer単位で全キーを一括で消す
          MapLibre仕様のため、風・勾配のどちらか一方だけがOFFになった時点でクリアすると
          もう片方の色分けまで巻き添えで消える。両方falseになるまで待つガードで防ぐ。
          判定条件自体は`shouldClearDedicatedWayValueFeatureState`という
          純粋関数が持つ）
```

- `promoteId: { [ROAD_TILE_SOURCE_LAYER]: "osm_way_id" }`（`ensureRoadSurfaceTileLayer`）が
  MVTフィーチャーへ安定したidを持たせる前提条件——これが無いと`setFeatureState`が使えない。
- `windAxis`/`gradientAxis`のensure関数は`ROAD_TILE_LAYER_ID`（路面本体）と同じ
  `ROAD_TILE_SOURCE_ID`/`ROAD_TILE_SOURCE_LAYER`を共有する独立レイヤーとして追加される
  （`designation`/`tunnel`/`oneway`と同型の構成）。
- `dedicatedWayValues`はパン・ズームのたびに変わりうる値のため、「表示ON/OFF」を担う
  一括effect（`STATIC_OVERLAY_LAYERS`ループ）とは別の専用effectで反映する（無関係な
  再実行を避けるため）。
- **`map.setStyle()`（「変わらないデータを更新」ボタン経由の基礎地図キャッシュクリア）は
  カスタムレイヤーを全て消すため、`redrawAllLayers`が全レイヤーを再構築する。この際
  `dedicatedWayValues`の値自体は変わっていないため通常の依存effectは再実行されないが、
  `redrawAllLayers`が`applyAxisFeatureStateValues`を明示的に再呼び出しすることで、
  setStyle直後に評価軸レイヤーが無色のまま残る事故を防いでいる**（暗黙の前提:
  この明示的な再適用を忘れると、setStyle後は視覚的にレイヤー自体は存在するが完全に無色の
  ままになる）。

`dedicatedWayValues`は`MapViewProps`上、`ReadonlyMap<axisId, ReadonlyMap<wayId, value>>`
という1つの汎用propにまとまっている（`dedicatedWayValueBoundaries`と同じく、
design-principles.md構造仕様3「軸ごとにpropを新設しない」に沿う）。`useDynamicWayValues`
自体はmaterialIdごとに個別インスタンス化する設計（デバウンス・レース対策がaxis間で
独立している必要があるため）で、汎用propへまとまっているのはpage.tsxがMapViewへ渡す
直前の形状だけである。MapView.tsx内部の`DEDICATED_WAY_VALUE_FEATURE_STATE_KEYS`
（axisId→featureStateKeyの小さなRecord）が`windAxisLayer.ts`/`gradientAxisLayer.ts`
それぞれの`*_FEATURE_STATE_KEY`定数を束ねる。

`WIND_PENALTY_FILL_LAYER_ID`（環境グループの風penalty gridFill）は`DYNAMIC_WEATHER_
RENDERERS`側の管理下にあり`STATIC_OVERLAY_LAYERS`に含まれないため、そのままでは
`interactiveLayerIds`（クリック判定対象）に入らない。専用のポップアップ内容を持たないため、
`handleClick`冒頭で「ヒットしたら何もしない」早期returnガードを持つ。

## 動的気象レイヤーとの関係

`windAxisLayer.ts`/`gradientAxisLayer.ts`が扱う「評価軸グループ」（道路そのものを線で塗る）は、
`windVector`（矢印・面表示、環境グループの探索用表現）とは完全に独立した見せ方であり、
同じ`[時刻/向き]`入力を共有するだけで、レイヤー・ソース・フェッチ経路はすべて別individual。
[地図: 動的気象レイヤー](dynamic-weather-layers.md)が扱う`DYNAMIC_WEATHER_RENDERERS`汎用機構
（風の矢印・降水ナウキャスト等）とは異なり、windAxis/gradientAxisは`mapLayers.ts:
isAxisStudioLayer`により地図上チップ（`MapOverlayControls.tsx`）・サイドバー
（`MapLayersPanel.tsx`）のどちらにも一切現れない。表示ON/OFFの起動導線は
[ルート設定・結果パネル](route-settings-and-results.md)の`RouteSettingsPanel`が持つ。
