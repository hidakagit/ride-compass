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
import { secondaryAxesFromCatalogAxes, type SecondaryAxisSummary } from "@/features/map/secondaryAxes";
import type { AxisCatalogResponse } from "@/types/route";

export interface MapAxisCatalog {
  /** 地図のramp表示を持つ軸。 */
  rampAxes: readonly RampAxis[];
  /** 専用のフィーチャー→値配信レイヤーを持つ軸。レイヤー登録・カタログ・可視性・フェッチの
   * 全てがこの一覧から導出される。 */
  dedicatedAxes: readonly DedicatedWayValueAxis[];
  /** 二次軸(推定指標)一覧。地図チップの「推定指標」グループが読む。 */
  secondaryAxes: readonly SecondaryAxisSummary[];
  /** ルート地図の色分けモード一覧。公開軸を無条件で含む。取得できるまでは軸に依らない
   * モードだけ（`ROUTE_STYLE_MODES_WITHOUT_AXES`）。 */
  routeStyleModes: readonly RouteStyleMode[];
  /** 事故データの収録年（backendの取込の宣言そのもの）。地図の説明文が範囲を書くのに使う。
   * フェッチ完了まで・エラー時は空で、その間は説明文が年に触れない。 */
  accidentYears: readonly number[];
  /** タイルの世代。全系統が揃うまで`null`で、その間は地図がタイルのソースを作らない。 */
  tileVersions: TileVersions | null;
}

// 取得できるまでは軸が1つも無く、タイルの世代も無い状態（ビルド時の写しで埋めない）。
export const EMPTY_MAP_AXIS_CATALOG: MapAxisCatalog = {
  rampAxes: [],
  dedicatedAxes: [],
  secondaryAxes: [],
  routeStyleModes: ROUTE_STYLE_MODES_WITHOUT_AXES,
  accidentYears: [],
  tileVersions: null,
};

export function mapAxisCatalogFromResponse(response: AxisCatalogResponse): MapAxisCatalog {
  return {
    rampAxes: rampAxesFromCatalogAxes(response.axes, response.tile_runtime_scales),
    dedicatedAxes: dedicatedWayValueAxesFromCatalogAxes(response.axes),
    secondaryAxes: secondaryAxesFromCatalogAxes(response.axes),
    routeStyleModes: routeStyleModesFromCatalogAxes(response.axes),
    accidentYears: response.accident_years,
    tileVersions: completeTileVersions(response.tile_versions),
  };
}
