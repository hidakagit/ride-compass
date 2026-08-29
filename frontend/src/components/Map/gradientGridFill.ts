// 環境グループの勾配面表示（改善計画T423、docs/tasks/T400.md「2. 動的要素…は状態（ルートの
// 有無）に応じてパラメータの出所と塗る対象が変わる」節）。
//
// 風のgridFill（windPenalty.ts）は独立した空間フィールド（気象グリッド、道路とは無関係に
// 存在する）を持つため、格子点を中心とする正方形セルで面表示できた。勾配にはそのような
// 独立した空間フィールドが無い——勾配は本質的に道路（way）ごとの属性であり、道路と無関係な
// 「勾配の面」という概念自体が存在しない。そのため本実装は、評価軸グループ（線、
// gradientAxisLayer.ts）向けに既にフェッチ済みのway単位のeffective_gradient値
// （hooks/useDynamicWayValues.ts: byTile、追加のAPI呼び出し無し）を、フェッチ元のタイル
// 境界そのものを1セルとして集計（平均）した面表示へ変換する——道路が密なタイルほど「そのタイル
// 周辺の道路網は平均してどれくらいの勾配か」を表す近似になる。

import type { TileXY } from "./dynamicWayValues";
import { tileBoundsLonLat } from "./dynamicWayValues";
import { buildGradientColorExpression } from "./gradientAxisLayer";
import type { TileDynamicWayValues } from "@/hooks/useDynamicWayValues";

export interface GradientGridCellProperties {
  gradientValue: number;
}

function tileRing(tile: TileXY): number[][] {
  const bounds = tileBoundsLonLat(tile.z, tile.x, tile.y);
  return [
    [bounds.west, bounds.north],
    [bounds.east, bounds.north],
    [bounds.east, bounds.south],
    [bounds.west, bounds.south],
    [bounds.west, bounds.north],
  ];
}

function averageOf(values: Record<string, number>): number | null {
  const numbers = Object.values(values);
  if (numbers.length === 0) return null;
  return numbers.reduce((sum, v) => sum + v, 0) / numbers.length;
}

/** タイルごとのway単位effective_gradient応答（useDynamicWayValues: byTile）を、タイル境界を
 * 1セルとする正方形（実際は経緯度矩形）のFeatureCollectionへ変換する。1way以上の値を持つ
 * タイルだけをセルとして含む（値が1件も無いタイル[取込範囲外・カバレッジ内0件]はスキップし、
 * windPenaltyGridToCellFeatureCollectionと同じ「1点の欠損で全体を落とさない」方針）。 */
export function gradientGridCellsFromTileResponses(
  byTile: readonly TileDynamicWayValues[]
): GeoJSON.FeatureCollection<GeoJSON.Polygon, GradientGridCellProperties> {
  const features: GeoJSON.Feature<GeoJSON.Polygon, GradientGridCellProperties>[] = [];
  for (const { tile, values } of byTile) {
    const average = averageOf(values);
    if (average == null) continue;
    features.push({
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [tileRing(tile)] },
      properties: { gradientValue: average },
    });
  }
  return { type: "FeatureCollection", features };
}

/** gradientValue（["get","gradientValue"]）を色へ変換するMapLibre fill-color式。評価軸
 * グループ（gradientAxisLayer.ts: gradientAxisColorExpression、feature-state経由）と
 * 同じ配色・しきい値の組み立てロジック（buildGradientColorExpression）を共有する——環境
 * （面）・評価軸（線）は同じ[向き]入力を共有するという契約（T400.md「2.」節）に加え、色の
 * 意味も揃えることで両者を見比べやすくする。feature-state版と異なり、こちらはgeojson
 * sourceのプロパティを直接["get",...]で読む。 */
export function gradientFillColorExpression(): unknown[] {
  return buildGradientColorExpression(["get", "gradientValue"]);
}
