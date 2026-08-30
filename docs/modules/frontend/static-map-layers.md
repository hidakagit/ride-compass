# 地図: 静的レイヤー・道路表示（frontend）

## 責務

タイル焼き込み済みの静的道路属性（路面・道路種別・停止要因POI・事故）を地図上に表示し、
チップ（`MapOverlayControls`）・サイドバー（`MapLayersPanel`）から表示/絞り込みを操作する。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `Map/staticAttributeLayers.ts` | 車ストレス・停止要因POI・事故の色分け定義 |
| `Map/roadFilterAxes.ts` | 路面レイヤー（路面の種類・道路の種類）の絞り込み軸 |
| `Map/legendFilter.ts` | カテゴリ絞り込みの汎用機構（凡例フィルタ式の組み立て） |
| `Map/primaryAttributes.ts` | 一次属性⇄二次軸の双方向導出 |
| `Map/mapLayers.ts` | レイヤーIDのグルーピング（`mapOverlayGroupFor`）・アイコン等 |
| `Map/routeArrowIcon.ts`・`routeSegmentChartPopup.ts`・`icons.tsx` | ルート矢印・区間クリックポップアップ・アイコン集 |
| `components/MapOverlayControls/` | 地図上チップ（フローティングUI） |
| `components/MapLayersPanel/` | サイドバー版のレイヤー切替パネル |

## 最上位グルーピング（道路/環境/スポット）

`mapLayers.ts: mapOverlayGroupFor(layer)`がレイヤーIDを3グループへ分類する。
`isAxisStudioLayer`（[軸スタジオ・評価軸定義](../backend/axis-studio.md)由来の
`dedicated_way_value_layer`軸・ramp軸[`dataNature==="composite"`]）に該当するものは
undefined（地図上チップ・サイドバーのどちらにも一切出さない——専用パネルへ移設済み）。

## 路面レイヤーの絞り込み軸（`roadFilterAxes.ts`）

タイルには`surface_good`（3値正準分類）・`surface`（OSM生タグ正規化済み）・`highway`
（道路種別）が焼き込まれている。**「路面の種類」（surface）と「道路の種類」（highway）の
2軸だけを絞り込み軸として持つ**——「舗装/未舗装」は「路面の種類」と同じ`surface`タグを
2値に粗く束ねただけの非独立な軸だったため廃止した（両方同時に選ぶと常に矛盾するか冗長に
なり、AND絞り込みとして意味を持たないため）。

色分け（line-color）は「路面の種類」がONの間は常にその配色で固定する（道路の種類の色を
上書きする形、両方ONでも色の奪い合いは起きない）。ユーザーが色分け軸を選ぶUIは持たない。

## staticAttributeLayers.ts（車ストレス・停止要因POI・事故）

`roadFilterAxes.ts`の軸機構（複数の生タグ値を少数のグループへ束ねる）とは異なり、これらは
backendが既に1つの分類値（車ストレス=1-5の整数・kind=列挙文字列・
involves_bicycle/fatal=真偽値）へ変換済みのプロパティのため、生値→グループの対応表は
不要で単純なmatch/case式で足りる。

| レイヤー | ソース |
|---|---|
| 車ストレス | 「路面」レイヤーと同じソース（`ROAD_TILE_SOURCE_ID`）の独立レイヤー |
| 停止要因POI | `region-poi-tiles`（点データ、別ソース） |
| 事故 | `region-accident-tiles`（点データ、別ソース） |

交差点密度（次数3以上のroad_node）は地図上の独立可視化レイヤーとしては提供しない
（道路網を見れば概ね自明という判断。ルーティング材料としては引き続き使う）。

各レイヤーの絞り込みは`STATIC_FILTER_AXES`にカタログ化し、`legendFilter.ts`の汎用機構
（`buildLegendFilterExpression`/`buildCombinedLegendFilterExpression`）をそのまま流用する。
