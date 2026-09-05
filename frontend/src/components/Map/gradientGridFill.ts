// 環境グループの勾配面表示。
//
// 勾配は本質的に道路（way）ごとの属性であり、道路と無関係な「勾配の面」という概念自体が
// 存在しない（降水延長予報のような独立した空間フィールドを持たない）。そのため本実装は、
// 評価軸グループ（線、dedicatedWayValueLayer.ts）向けに既にフェッチ済みのway単位の
// effective_gradient値（hooks/useDynamicWayValues.ts: byTile、追加のAPI呼び出し無し）を、
// フェッチ元のタイル境界そのものを1セルとして集計（平均）した面表示へ変換する——道路が
// 密なタイルほど「そのタイル周辺の道路網は平均してどれくらいの勾配か」を表す近似になる。

import type { TileXY } from "./dynamicWayValues";
import { tileBoundsLonLat } from "./dynamicWayValues";
import { buildDedicatedWayValueColorExpression, type DedicatedWayValueDisplay } from "./dedicatedWayValueLayer";
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
 * precipitationGridToCellFeatureCollectionと同じ「1点の欠損で全体を落とさない」方針）。 */
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
 * グループの線（dedicatedWayValueLayer.ts、feature-state経由）と同じ表示宣言・色ロジックを
 * 共有する——環境（面）・評価軸（線）は同じ[向き]入力を共有するという契約に加え、色の
 * 意味も揃えることで両者を見比べやすくする。こちらはgeojson sourceのプロパティを
 * 直接["get",...]で読む。表示宣言が無い間は符号付き材料の既定スケールを使う。`loading`は
 * dedicatedWayValueColorExpressionと同じ意味——ただしこのレイヤーは値を
 * 持つタイルだけをfeatureとして含む（gradientGridCellsFromTileResponses参照）ため、
 * COLOR_LOADING/COLOR_NO_DATAの分岐が実際に描画へ現れることは無い。 */
export function gradientFillColorExpression(display?: DedicatedWayValueDisplay, loading = false): unknown[] {
  return buildDedicatedWayValueColorExpression(
    ["get", "gradientValue"],
    display ?? { kind: "signed_material", unit: "" },
    loading
  );
}
