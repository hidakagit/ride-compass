/** 軸カタログの応答（`GET /api/axis-catalog`）のうち、地図だけが読むものを導く。機能をまたいで読む形は
 * `lib/axisCatalog.ts`が同じ応答から導き、取得は両者で1つを共有する（`useMapAxisCatalog.ts`）。 */
import {
  dedicatedWayValueAxesFromCatalogAxes,
  rampAxesFromCatalogAxes,
  type DedicatedWayValueAxis,
  type RampAxis,
} from "@/lib/mapDisplay/axisLayers";
import {
  ROUTE_STYLE_MODES_WITHOUT_AXES,
  routeStyleModesFromCatalogAxes,
  type RouteStyleMode,
} from "@/lib/mapDisplay/routeStyleModes";
import { completeTileVersions, type TileVersions } from "@/features/map/regionApi";
import { buildMapLayers, NO_AXES, type MapLayerDescriptor } from "@/features/map/layers/mapLayers";
import { catalogAxisFromEntry, type CatalogAxis } from "@/lib/catalogAxis";
import type { AxisCatalogResponse } from "@/types/route";

export interface MapAxisCatalog {
  /** 公開中の軸（共有の軸カタログと同じ導出）。地図の説明文が評価の名前を差し込み、レンズが選択肢を作る。 */
  axes: readonly CatalogAxis[];
  /** 地図のramp表示を持つ軸。 */
  rampAxes: readonly RampAxis[];
  /** 専用のフィーチャー→値配信レイヤーを持つ軸。レイヤー登録・カタログ・可視性・フェッチの
   * 全てがこの一覧から導出される。 */
  dedicatedAxes: readonly DedicatedWayValueAxis[];
  /** ルート地図の色分けモード一覧。公開軸を無条件で含む。取得できるまでは軸に依らない
   * モードだけ（`ROUTE_STYLE_MODES_WITHOUT_AXES`）。 */
  routeStyleModes: readonly RouteStyleMode[];
  /** 事故データの収録年（backendの取込の宣言そのもの）。地図の説明文が範囲を書くのに使う。
   * フェッチ完了まで・エラー時は空で、その間は説明文が年に触れない。 */
  accidentYears: readonly number[];
  /** タイルの世代。全系統が揃うまで`null`で、その間は地図がタイルのソースを作らない。 */
  tileVersions: TileVersions | null;
  /** 地図に載るものの一覧。上の軸と収録年から、応答1つにつき1回だけ組む。 */
  layers: readonly MapLayerDescriptor[];
}

// 取得できるまでは軸が1つも無く、タイルの世代も無い状態（ビルド時の写しで埋めない）。
export const EMPTY_MAP_AXIS_CATALOG: MapAxisCatalog = {
  ...NO_AXES,
  routeStyleModes: ROUTE_STYLE_MODES_WITHOUT_AXES,
  tileVersions: null,
  layers: buildMapLayers(NO_AXES),
};

export function mapAxisCatalogFromResponse(response: AxisCatalogResponse): MapAxisCatalog {
  const layerAxes = {
    axes: response.axes.map(catalogAxisFromEntry),
    rampAxes: rampAxesFromCatalogAxes(response.axes, response.tile_runtime_scales),
    dedicatedAxes: dedicatedWayValueAxesFromCatalogAxes(response.axes),
    accidentYears: response.accident_years,
  };
  return {
    ...layerAxes,
    routeStyleModes: routeStyleModesFromCatalogAxes(response.axes),
    tileVersions: completeTileVersions(response.tile_versions),
    layers: buildMapLayers(layerAxes),
  };
}
