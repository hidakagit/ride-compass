# 地図: 軸・ルート色分け（frontend）

## 責務

評価軸（軸スタジオ管理）のdifficulty値を、(1) ルート確定前は視界内の全道路（評価軸
グループの線、風・勾配とも）・環境グループの面（勾配のみ。風は矢印のみで面塗りを持たない、
[地図: 動的気象レイヤー](dynamic-weather-layers.md)参照）、(2) ルート確定後は選択中
ルートの線、それぞれ地図上で色分け表示する。専用のway_id→値配信レイヤー
（[動的材料・way_id値配信（backend）](../backend/dynamic-way-values.md)）を持つ軸
（現状: 風・勾配）が対象。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `Map/routeStyleModes.ts` | ルート確定後の色分けモード一覧・色式 |
| `Map/dedicatedWayValueLayer.ts` | ルート確定前の評価軸グループ線（専用way値レイヤー、風・勾配共通）の色式・凡例・feature-stateキー。軸カタログの表示宣言（`DedicatedWayValueDisplay`）だけから組み立て、軸ごとのファイル・定数を持たない |
| `Map/valueScale.ts` | 地図表示値の種類（`MapValueKind`: 難易度／符号付き材料）ごとの既定しきい値・配色、HSL補間、段階分け色式。ルート前後の色分けが共有する葉モジュール |
| `Map/gradientGridFill.ts` | ルート確定前の環境グループ面（勾配のgridFill）の値計算・色式（風は面塗りを持たないため対象外） |
| `Map/dynamicWayValues.ts` | タイル座標計算・複数タイル応答の統合（材料非依存の共通部分） |
| `Map/axisLayers.ts` | `rampColorForBand`/`COLOR_UNKNOWN`（ramp軸の共有色ヘルパー）。ramp軸自体の全面的な生成ロジックは主に[地図: 静的レイヤー・道路表示](static-map-layers.md)の管轄 |
| `Map/mapColorLegend.ts` | 地図上の色分け凡例（`MapColorLegendBand`型・`buildRangeLegendBands`・`rangeStepLabel`）の共通ロジック。`dedicatedWayValueLegend`が使う |
| `components/LensControl/LensControl.tsx` | レンズ（地図を何で塗るか）の唯一の入口。地図上部中央のピルが現在のレンズと凡例を示し、タップで単一選択の一覧（なし／総合難易度／評価に使用中の軸／未使用の軸）と「ルート後も周囲の道路を薄く塗る」トグルを開く（`page.tsx`が選択肢・凡例を組み立てる） |
| `Map/mapLayers.ts` | `isDedicatedWayValueLayerId`・`isAxisStudioLayer`（レイヤーID判定） |
| `Map/MapView.tsx`（windAxis/gradientAxis/gradientFill/DETAIL_LAYER_ID関連箇所のみ） | MapLibreへの実際の配線——ensure/apply関数群・setFeatureState反映・effect分割 |
| `hooks/useDynamicWayValues.ts` | フェッチ・状態管理（viewportデバウンス＋タイル単位取得） |
| `services/axisAdminApi.ts`・`regionApi.ts`（`fetchDynamicWayValues`のみ） | backend APIラッパー |

**`MapView.tsx`は路面タイル・動的気象（降水/風の矢印/雷/竜巻）・POI等のロジックも持つ
ファイルで、それらは[地図: 静的レイヤー・道路表示](static-map-layers.md)・
[地図: 動的気象レイヤー](dynamic-weather-layers.md)の管轄。本ドキュメントはwindAxis/
gradientAxis/gradientFill/ルート確定後の色分け（DETAIL_LAYER_ID）に関わる箇所のみを扱う。**

## ルート確定前後で同じスケール（3つの表示、1つの表示宣言）

```
                          [評価軸グループ（線）]                [環境グループ（面、勾配のみ）]
ルート未確定  ── setFeatureState経由の値 ──┐   ┌── gridFill（勾配=タイル平均。風は対象外）
              （useDynamicWayValues、      │   │
               backendが軸定義で評価した   │   │
               地図表示値）                 ▼   ▼
                                  同じ表示宣言（種類・単位・しきい値・段階ラベル）
                                            ▲
ルート確定後  ── RouteSegmentDetailの ──────┘   （環境グループは非表示、評価軸グループが
              axis_difficulties /              「地図の色分け」モードへ役割を譲る）
              符号付き材料の直読み
```

軸ごとに地図が塗る値の種類はbackendが軸定義から決める（`GET /api/axis-catalog`の
`map_value_kind`/`map_value_unit`、[動的材料・way_id値配信（backend）](../backend/dynamic-way-values.md)
参照）。`difficulty`の軸はルート前（専用way値レイヤー）もルート後（ルート線）も
軸スタジオのbreakpointsで評価済みの0〜100を塗り、`signed_material`の軸（勾配）は
どちらも符号付き材料生値を塗る。`display_thresholds_override`は軸ごとに1つのスケールで
解釈される（ルート前後でスケールが食い違う軸は無い）。

## 軸id→振る舞いの判定（データ駆動、axis_idのハードコード比較を使わない）

| 判定 | 使う軸データ属性 | 関数・場所 |
|---|---|---|
| 専用way_id配信レイヤーを持つか | `AxisDefinition.dedicated_way_value_layer` | `mapLayers.ts: isDedicatedWayValueLayerId` |
| 符号付き材料を直接読むか／難易度を読むか | `AxisCatalogEntry.map_value_kind`（backend `domain/dynamic_way_values.py: map_value_kind`が`shape`から導出） | `routeStyleModes.ts: routeColorableModeFromAxis`・`dedicatedWayValueLayer.ts`（`DedicatedWayValueDisplay.kind`） |
| 凡例の単位 | `AxisCatalogEntry.map_value_unit`（材料カタログの`unit`） | 同上 |

公開軸は無条件でレンズの選択肢になる（`routeStyleModes.ts: routeStyleModesFromCatalogAxes`が
公開軸すべて＋`difficulty`（総合難易度）＋`none`（塗らない）をマップする）。重み0の軸も
選べ、`LensControl`が「未使用」バッジで示す。ルート前に塗る手段（ramp・専用配信）を
持たない軸は「ルート後のみ」バッジ付きで選べるが、ルート前は何も塗らない。

**レンズ状態は1つ**（`page.tsx: lens`、`"none" | "difficulty" | axis_id`。localStorage
キーは`ridecompass:route-style-mode`）。ルート前は全道路（ramp軸は`axisVisibility`、
専用配信は`showWindAxis`/`showGradientAxis`）、ルート後はルート線（`MapView`の
`routeStyleModeId`）をこの1つの値から導出する。ルート後も全道路の塗りを残すかは
`lensKeepAfterRoute`（既定ON）。レンズが軸を指していれば生成リクエストへ`lens_axis_id`を
載せ、重み0でもbackendが区間表示のため風の時変化合成を行う。

`map_value_kind==="signed_material"`の場合、値は`axis_difficulties[axis_id]`ではなく
`shape.terms[0].material`（生材料、例: `gradient_percent`）を直接読む——向き（登り/下り）は
絶対値化されたdifficultyでは表現できないため。

## valueScale.ts（ルート前後で共有する葉モジュール）

- `valueScaleFor(kind)`: 種類ごとの既定しきい値（`DEFAULT_DIFFICULTY_BOUNDARIES=[33,66]`・
  `SIGNED_MATERIAL_BOUNDARIES=[-2,2,6,10]`）と配色（難易度は`COLOR_EASY→COLOR_HARD`、
  符号付き材料は`COLOR_SIGNED_LOW→COLOR_HARD`）。
- `interpolateColors(colorLow, colorHigh, count)`: 2色の間をHSL色空間でcount色に均等
  補間する（固定の色配列を持たないため、しきい値の個数が変わっても色が自動追従する）。
- `buildSteppedColorExpression(valueExpression, kind, boundaries?, numericExpression?)`:
  null→`COLOR_NO_DATA`、それ以外は`["step", ...]`の色式。

## routeStyleModes.ts（ルート確定後）

- `buildRangeSteppedMode`: 境界値配列（軸スタジオの`display_thresholds_override`、
  未設定時は経路ごとの既定値）の**長さがそのまま段階数を決める**汎用関数。ラベルは
  境界値の実際の数字から機械的に生成する。
- `DIFFICULTY_MODE`（総合難易度）だけがフロントの固定モード——特定のaxis_idに紐づかず
  全軸の重み付き合成コストそのものを表示するため、軸スタジオと同期する対象にならない。
- `NONE_MODE`（レンズなし）: ルート線を単色（候補線の非選択色）で描き、凡例を持たない。
- `DEFAULT_ROUTE_STYLE_MODE_ID`は`"difficulty"`（総合難易度）。
- **地図上の重ね順**（`MapView.tsx: drawDetailSegments`・`keepRouteArrowsAboveDetailSegments`）:
  選択中候補の区間色分け線（`DETAIL_LAYER_ID`、幅6px・不透明）とその当たり判定線
  （`DETAIL_HIT_LAYER_ID`、幅24px・透明）は、同じ候補の進行方向矢印
  （`ROUTE_ARROW_HALO_LAYER_ID`→`ROUTE_ARROW_LAYER_ID`、`routeArrowIcon.ts`）より常に下に置く。
  矢印層はページ表示直後に、色分け線は最初の生成後に作られるため、作成順に任せず
  「色分け線→当たり判定線→矢印ハロー→矢印」の順を両方の作成時に明示する。矢印2層は
  衝突判定を無効（`icon-allow-overlap`/`icon-ignore-placement: true`）にしてある——
  MapLibreは上のレイヤーから順にシンボルを配置するため、衝突判定を有効にすると主層の矢印と
  同位置・大きめのハロー層が全て落ち、色分け線が紺系のモードでは同色の矢印が線に沈む。

## dedicatedWayValueLayer.ts（ルート確定前の評価軸グループ線）

- `DedicatedWayValueDisplay`: `{kind, unit, boundaries?, bandLabels?}`。`page.tsx`が
  `axisCatalog.axes`から`dedicatedWayValueLayer===true`の軸を横断的に抽出し、
  `mapValueKind`/`mapValueUnit`/`displayThresholdsOverride`/`displayBandLabelsOverride`から
  組み立てて`MapViewProps.dedicatedWayValueDisplays`（axisId→宣言の汎用Map）として渡す。
  未設定の軸は`DEFAULT_DEDICATED_WAY_VALUE_DISPLAY`（難易度スケール・単位なし）。
- `dedicatedWayValueFeatureStateKey(axisId)`: setFeatureStateのキー（`${axisId}Value`）。
  同じ路面タイルソースの地物へ複数の軸が値を持つため軸idごとに異なる。
- `buildDedicatedWayValueColorExpression(valueExpression, display)`: 値の取得元
  （feature-state or geojsonプロパティ）だけが呼び出し側で異なる共通ロジック。評価軸
  グループ（`dedicatedWayValueColorExpression`、feature-state経由）と環境グループの
  gradientFill（`["get",...]`経由）が同じ配色・しきい値を共有する契約をコード上で1箇所に
  集約する。
- `dedicatedWayValueLegend(display)`: 同じ配色・しきい値から地図上の凡例
  （`mapColorLegend.ts: MapColorLegendBand[]`）を組み立てる。段階ラベル（軸スタジオの
  `display_band_labels_override`）は要素数が段階数と一致する間だけ数値レンジの前に添える
  （不整合な保存データへの防御）。単位は`display.unit`（難易度は空文字）。
  `page.tsx`が現在のレンズに応じて凡例を1つ組み立てる（`lensLegend`: ルート後はルート線
  モードの凡例、ルート前はramp軸なら`axisLayers.ts: buildAxisRampLegend`、専用配信軸なら
  この関数）。`LensControl`（`components/LensControl/`）が地図上部中央のピルとポップオーバーに
  表示する（モバイルのBottomSheetが画面下側を覆っても隠れないための配置）。ルート後だけ
  凡例の段階を非表示にできる（`hiddenLegendKeysByMode[lens]`）。専用way値レイヤーには
  絞り込み機構自体が無いため`MapColorLegendBand`（`{label, color}`のみ）という軽量な型を使う。

## gradientGridFill.ts（環境グループの面表示、勾配のみ）

風は矢印のみで面塗りを持たないため（[地図: 動的気象レイヤー](dynamic-weather-layers.md)
参照）、環境グループの面表示は勾配専用。値は道路のeffective_gradient（評価軸グループ向けに
既にフェッチ済みのway単位の値）を、フェッチ元のタイル境界を1セルとして平均集計する
（`gradientGridCellsFromTileResponses`、追加のAPI呼び出し無し）。セルの単位はタイル境界
そのもの（`tileRing`）。

`gradientFillColorExpression(display?)`は評価軸グループ（`dedicatedWayValueColorExpression`）と
同じ`dedicatedWayValueDisplays`（`.get("gradient")`）を`MapView.tsx`側
（`makeEnsureGradientFillLayer`）で受け取り、両者が同じ配色・しきい値を共有する。

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
  （タイル境界セル）が使う。風は環境グループのgridFillを持たないため`byTile`は使わない。

`materialId`（"wind"/"gradient"）ごとに呼び出し側（`page.tsx`）が別々にこのフックを
インスタンス化する。連続する呼び出しの間に古いリクエストが後から解決しても新しい結果を
上書きしないよう、リクエストの世代（`seq`、複数タイルの`Promise.all`をまたぐカウンタ）で
最新のものだけを反映する。

## MapView.tsx側の配線

`dedicatedWayValueLayer.ts`が組み立てる色式（純粋なMapLibre expression）は、
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
  ├─ makeEnsureDedicatedWayValueLayer(layerId, colorExpression)（色式はdedicatedWayValueDisplaysから）
  │     → windAxis/gradientAxisレイヤーをroad_surfaceタイルの独立レイヤーとして初回のみ追加
  │       （ensureRoadSurfaceTileLayerが先にpromoteId付きsourceを用意している前提）
  ├─ dedicatedWayValuesのエントリを1つのeffectでループし、各軸へ
  │   applyAxisFeatureStateValues(map, dedicatedWayValueFeatureStateKey(axisId), values)
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
という1つの汎用propにまとまっている（`dedicatedWayValueDisplays`と同じく、
design-principles.md構造仕様3「軸ごとにpropを新設しない」に沿う）。`useDynamicWayValues`
自体はmaterialIdごとに個別インスタンス化する設計（デバウンス・レース対策がaxis間で
独立している必要があるため）で、汎用propへまとまっているのはpage.tsxがMapViewへ渡す
直前の形状だけである。feature-stateキーは`dedicatedWayValueFeatureStateKey(axisId)`で
軸idから機械的に導出するため、軸ごとの対応表は持たない。

## 動的気象レイヤーとの関係

`dedicatedWayValueLayer.ts`が扱う「評価軸グループ」（道路そのものを線で塗る）は、
`windVector`（矢印表示、環境グループの探索用表現）とは完全に独立した見せ方であり、
同じ`[時刻/向き]`入力を共有するだけで、レイヤー・ソース・フェッチ経路はすべて別individual。
[地図: 動的気象レイヤー](dynamic-weather-layers.md)が扱う`DYNAMIC_WEATHER_RENDERERS`汎用機構
（風の矢印・降水ナウキャスト等）とは異なり、windAxis/gradientAxisは`mapLayers.ts:
isAxisStudioLayer`により地図上チップ（`MapOverlayControls.tsx`）・サイドバー
（`MapLayersPanel.tsx`）のどちらにも一切現れない。表示ON/OFFの起動導線は
[ルート設定・結果パネル](route-settings-and-results.md)の`RouteSettingsPanel`が持つ。
