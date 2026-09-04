# 地図: 静的レイヤー・道路表示（frontend）

## 責務

タイル焼き込み済みの静的道路属性（路面・道路種別・指定路線・トンネル・一方通行・停止
要因POI・補給休憩POI・事故）と二次(ramp)軸の汎用色分けレイヤーを地図上に表示し、チップ
（`MapOverlayControls`）・サイドバー（`MapLayersPanel`）から表示/絞り込みを操作する。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `Map/staticAttributeLayers.ts` | 指定路線・トンネル・一方通行・停止要因POI・補給休憩POI・事故の色分け定義、絞り込み軸カタログ`buildStaticFilterAxes` |
| `Map/roadFilterAxes.ts` | 路面レイヤー（路面の種類=`surface`・道路の種類=`highway`）の絞り込み軸・配色・太さ・線種 |
| `Map/legendFilter.ts` | カテゴリ絞り込みの汎用機構（凡例フィルタ式の組み立て・AND束ね・要約文生成） |
| `Map/primaryAttributes.ts` | 一次属性⇄二次軸の双方向導出（軸増減時の観測データ連動表示に使用） |
| `Map/mapLayers.ts` | レイヤーカタログ本体（`MapLayerDescriptor[]`）・地図上チップの最上位3グループ（道路/環境/スポット）判定・軸スタジオ由来レイヤーの除外判定 |
| `Map/MapView.tsx`（静的レイヤーのsource/layer初期化・並列トラック分離・下敷き表現箇所のみ） | 表示層本体 |
| `Map/routeArrowIcon.ts`・`icons.tsx` | ルート矢印・アイコン集（下記「本モジュールとの関係」参照） |
| `Map/axisInspectorPopup.ts` | 区間インスペクタ（backend `POST /api/region/axis-inspector`、[静的道路属性・タイル配信](../backend/static-road-attributes.md)参照）のポップアップHTML組み立て |
| `types/traffic.ts` | 停止要因POI・補給休憩POIの`kind`列挙型定義 |
| `services/regionApi.ts`（`roadSurfaceTileUrl`/`poiTileUrl`/`accidentTileUrl`とタイル世代定数） | ベクタタイルのURLテンプレート（`fetchDynamicWayValues`は[地図: 軸・ルート色分け](map-axis-coloring.md)の管轄） |
| `lib/tileBaseUrl.ts` | タイル配信元オリジンの決定（既定はフロント自身のオリジン＝rewrites経由、`NEXT_PUBLIC_TILE_BASE_URL`設定時はbackend直接） |
| `components/MapOverlayControls/` | 地図上チップ（フローティングUI） |
| `components/MapLayersPanel/`（`WidthSwatch.tsx`含む） | サイドバー版のレイヤー切替パネル |
| `Map/LayerChip.tsx` | ON/OFFトグルの共通部品（`MapLayersPanel`・`RouteSettingsPanel`・`page.tsx`のルート色分けセクションで共用） |
| `Map/InfoPopover.tsx` | 見出し脇の(i)アイコン→ポップオーバーという外枠の共通部品。中身はchildrenで呼び出し側が渡す（`MapLayersPanel`・`RouteSettingsPanel`・`RouteAxisProfile`で共用） |
| `Map/LegendCheckboxList.tsx` | 凡例のチェックボックス一覧（チェックボックス+スウォッチ/`WidthSwatch`+ラベル）の共通部品。リスト/行の見た目（class名）は呼び出し側が指定する（`MapLayersPanel`・`RouteAxisProfile`で共用） |

## タイルの配信元（`lib/tileBaseUrl.ts`）

ベクタタイルはMapLibreがWeb Worker内でfetchするため、URLは常に絶対URLでなければならない
（相対パスはWorkerのベースURLで解決できない）。`tileBaseUrl()`が返すオリジンは、
`NEXT_PUBLIC_TILE_BASE_URL`が設定されていればその値（backendへ直接取りに行く。フロントの
ホスティング経由の往復を省く）、未設定ならフロント自身のオリジン（`next.config.ts`の
rewritesでbackendへプロキシ）。`window`をSSR時に参照しないよう、モジュール定数ではなく
呼び出し時に評価する関数になっている。

**暗黙の前提**: backend直接にすると、API呼び出し（`lib/apiBaseUrl.ts`）と同じオリジンに
タイル要求が載る。backend前段がHTTP/1.1のままだとブラウザのオリジン単位の同時接続数上限
（6本程度）をタイル要求が埋め、API呼び出しが詰まるため、HTTP/2以上（多重化）で応答できる
構成でのみ設定する（[docs/architecture.md](../../architecture.md)「同時接続数上限との競合」）。

## 表示層の実装（`MapView.tsx`）

このモジュールが扱う静的レイヤーの実際のMapLibre実装（`addSource`/`addLayer`/
`setPaintProperty`/`setFilter`呼び出し）はすべて`MapView.tsx`にある。
`staticAttributeLayers.ts`等は色分け式・凡例の**定義**のみを持つ純粋なデータ層で、
DOM/MapLibreを一切知らない。

```
buildStaticOverlayLayers(axisOverlayLayers) が描画順（＝重なり順、背面→前面）を決める:

  elevation（標高ラスタ）
    │
  axisOverlayLayers（二次ramp軸: car_stress・stop_density・accident等）
    │  ← 「材料が同時に表示されているときだけ」太く半透明な下敷きにする
    │    （applySecondaryAxisCasingStyles）
    ▼
  designation → tunnel → oneway
    │  ← ROAD_MATERIAL_TRACK_LAYER_IDS（road+designation+tunnel+onewayの4本）を
    │    line-offsetで並列トラックへ分離（applyRoadMaterialTrackOffsets）
    ▼
  windAxis → gradientAxis → gradientFill（評価軸/環境グループ、本モジュール対象外）
    ▼
  accidents → stopPoi → supplyPoi（点データ、別ソース）
```

`ROAD_TILE_LAYER_ID`（roadType/roadSurfaceの合成レイヤー）は`applyRoadLayerState`が
`showRoadSurface`/`showRoadType`の組み合わせに応じて色・太さ・線種・不透明度を都度
再計算する:

| 状態 | 色 | 太さ・線種 |
|---|---|---|
| 両方ON | 路面の種類の配色 | 道路の種類の太さ・線種 |
| 路面の種類のみON | 路面の種類の配色 | 中立（均一・実線） |
| 道路の種類のみON | 道路の種類の濃淡パレット | 道路の種類の太さ・線種 |
| 両方OFF | レイヤー自体を隠す | — |

## 並列トラック分離（`applyRoadMaterialTrackOffsets`）

同じ道路ジオメトリへ複数の独立レイヤー（合成道路/路面・指定路線・トンネル・一方通行）を
重ねて描画すると、後から描画されたレイヤーが前のレイヤーを覆い隠す。`line-offset`で
道路と平行な複数トラックへ横並びに分離することでこれを避ける——ON中のレイヤーだけを
対称に割り付ける（1件→0、2件→±1.5、3件→-3/0/+3）ため、どれかをOFFにすると残りが
自動で中央へ寄り直す。

トラック本数（`ROAD_MATERIAL_TRACK_LAYER_IDS.length`=4）・オフセット間隔
（`MATERIAL_TRACK_OFFSET_STEP`=2px）・1次レイヤーの太さ（`DEFAULT_ROAD_LINE_WIDTH`=3px）
から、二次軸の下敷き幅（`SECONDARY_AXIS_CASING_WIDTH`）が式として算出される。

## 二次軸の下敷き表現（`applySecondaryAxisCasingStyles`）

二次(ramp)軸は「その材料（対応する一次属性の表示レイヤー）が1つでも同時に表示されて
いるとき」だけ太く半透明な下敷きになる。材料が1つも表示されていなければ通常の太さ・
不透明度で表示する。「どの一次属性がどの二次軸の材料か」の解決は`page.tsx`が
`axisCatalog.secondaryAxes`（実行時カタログ）の`primaryAttributeIds`から行い、
`MapView.tsx`は渡された`secondaryAxisCasingLayerIds`（キー集合）をそのまま使うだけの
汎用描画係のまま保たれている。

## 最上位グルーピング（道路/環境/スポット）

`mapLayers.ts: mapOverlayGroupFor(layer)`がレイヤーIDを3グループへ分類する。
`isAxisStudioLayer`（`dedicated_way_value_layer`軸[windAxis/gradientAxis]・ramp軸
[`dataNature==="composite"`]）に該当するものは`undefined`（地図上チップ・サイドバーの
どちらにも一切出さない——ルート設定パネルへ移設済み、[ページ構成](page-composition.md)参照）。

**暗黙の前提**: `mapOverlayGroupFor`は`isAxisStudioLayer`を最初にチェックしてから
`category`値を見る。`category`だけでは判別できない（例: `car_stress`の
`category="trafficSafety"`は`accidents`等と同じ値のため、`isAxisStudioLayer`のガードが
無いと誤って「スポット」グループへ紛れ込む）。

## 路面レイヤーの絞り込み軸（`roadFilterAxes.ts`）

タイルには`surface_good`（3値正準分類、絞り込み軸としては未使用）・`surface`（OSM生タグ
正規化済み）・`highway`（道路種別）が焼き込まれている。**「路面の種類」（surface）と
「道路の種類」（highway）の2軸だけを絞り込み軸として持つ。**

色分け（line-color）は「路面の種類」がONの間は常にその配色で固定する（道路の種類の色を
上書きする形、両方ONでも色の奪い合いは起きない）。ユーザーが色分け軸を選ぶUIは持たない。

## staticAttributeLayers.ts（指定路線・トンネル・一方通行・停止要因POI・補給休憩POI・事故）

`roadFilterAxes.ts`の軸機構（複数の生タグ値を少数のグループへ束ねる）とは異なり、これらは
backendが既に1つの分類値（`kind`=列挙文字列・`tunnel`/`oneway`/`involves_bicycle`/
`fatal`=真偽値・`designation`=3値）へ変換済みのプロパティのため、生値→グループの
対応表は不要で単純な`match`/`case`式で足りる。

| レイヤー | ソース | 独立/共有 |
|---|---|---|
| 指定路線・トンネル・一方通行 | `ROAD_TILE_SOURCE_ID`（路面と同じ） | 独立レイヤー（並列トラック対象） |
| 停止要因POI・補給休憩POI | `region-poi-tiles`（点データ） | 同一source-layer`stop_poi`を`kind`値集合で分ける（`baseFilter`必須） |
| 事故 | `region-accident-tiles`（点データ、別ソース） | 独立 |

色の使い分け（一次/二次の意味の統一）:
- 「事実の種類」を区別するだけのカテゴリ（停止要因POI種別・補給POI種別）は中立色。
- 「二次軸の材料そのもの」として寄与するカテゴリ（指定路線・事故の当事者区分）は二次軸と
  同じ緑→赤の評価配色（`AXIS_RAMP_COLORS`）を使い、「1次のこの色は2次のこの色と同じ
  方向を指す」と直接読めるようにする。

各レイヤーの絞り込みは`buildStaticFilterAxes(rampAxes)`にカタログ化し、`legendFilter.ts`の
汎用機構（`buildLegendFilterExpression`/`buildCombinedLegendFilterExpression`）をそのまま
流用する。ramp軸ぶんの絞り込み軸は`rampAxes`（実行時フェッチ、軸スタジオの公開軸を含む）
から関数的に組み立てる——ビルド時静的リストの手書き列挙ではない。

## 交差点密度は地図上の独立可視化レイヤーとして提供しない

次数3以上の`road_node`はバックエンドのPOIタイルに焼き込まれているが、専用レイヤーを
持たない（ルーティング材料の`intersection_weight`としては引き続き使う）。

## 本モジュールとの関係が薄いファイル

- `routeArrowIcon.ts`（周回ルートの順回り/逆回り矢印、選択中ルートにのみ描画）は
  「選択中ルート」に紐づく動的データを扱う。対象ファイル表に含まれているが、責務としては
  [ページ構成](page-composition.md)・[地図: 軸・ルート色分け](map-axis-coloring.md)に近い。
  区間クリック時の詳細表示（地点・到達予想時刻・軸別内訳）はボトムシート側
  （[ルート設定・結果パネル](route-settings-and-results.md)のRouteAxisProfile）が持ち、
  地図上（`MapView.tsx: handleRouteSegmentClick`）は軽量なマーカーを立てるのみで
  テキストポップアップを持たない。
- `icons.tsx`はこのモジュール（`MapOverlayControls`のアイコン辞書）専用ではなく、
  [動的気象レイヤー](dynamic-weather-layers.md)の`WeatherPanel`/`TodayOutlook`からも
  使われる、地図関連UI全体で共有するアイコン集である。
