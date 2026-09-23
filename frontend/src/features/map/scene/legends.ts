/** 凡例の行を、地図を描いているのと同じ宣言から作る。
 *
 * **色と分類の正本はグループ（`groups/*.ts`）にしかない**——凡例が別に色を持つと、
 * 地図とチップの色が静かに食い違う。ここはその宣言を凡例の形へ移すだけで、値を持たない。
 */
import { COLOR_UNKNOWN } from "@/components/Map/axisLayers";
import type { LegendEntry } from "@/components/Map/legendFilter";
import { LEGEND_NO_DATA_KEY } from "@/components/Map/mapColorLegend";

import palette from "@/types/generated/palette.json";

import { POINT_LAYERS, pointAxisKey, pointCategoryRadiusPx, type PointAxis } from "./groups/points";
import { ROAD_TRACKS, roadTrackAxis } from "./groups/roadLines";

/** 凡例1本ぶん。1つのチップが複数の軸を持つことがある（事故は当事者と重大度）。 */
export type SceneLegendAxis = {
  /** 地図チップのid（＝レイヤーの役割）。 */
  readonly layerId: string;
  /** 隠した行を覚えておく鍵。 */
  readonly axisId: string;
  /** 軸が1本だけなら見出しは空でよい（チップ名で足りる）。 */
  readonly label: string;
  readonly entries: readonly LegendEntry[];
};

/** 分類に当てはまらないものの受け皿。**地図も同じ扱い**（消さずに薄く出す）。 */
const UNKNOWN_ENTRY: LegendEntry = {
  key: LEGEND_NO_DATA_KEY,
  label: "不明・他",
  color: COLOR_UNKNOWN,
  isFallback: true,
};

export function roadLegendAxes(): readonly SceneLegendAxis[] {
  return ROAD_TRACKS.map((track) => ({
    layerId: track.attr_id,
    axisId: track.attr_id,
    // 見出しはチップ名で足りる（軸が1本しかない）。名前の正本は源泉。
    label: "",
    entries: [
      ...roadTrackAxis(track).categories.map((category) => ({
        key: category.key,
        label: category.label,
        color: category.color,
      })),
      UNKNOWN_ENTRY,
    ],
  }));
}

/** 点の凡例。**色見本を出すのは、地図の色式が読む先頭の軸だけ**——2本目以降（重大度）は
 * 地図では大きさだけで表れるので、見本も色を持たない灰で、地図と同じ大きさにする。 */
function pointAxisLegend(layer: (typeof POINT_LAYERS)[number], axis: PointAxis, index: number): SceneLegendAxis {
  return {
    layerId: layer.attr_id,
    axisId: pointAxisKey(layer, axis),
    label: axis.label ?? "",
    entries: axis.categories.map((category) =>
      index === 0 && "color" in category
        ? { key: category.key, label: category.label, color: category.color }
        : {
            key: category.key,
            label: category.label,
            color: palette.semantic.legend_size_only,
            diameterPx: 2 * pointCategoryRadiusPx(layer, axis, category),
          },
    ),
  };
}

export function pointLegendAxes(): readonly SceneLegendAxis[] {
  return POINT_LAYERS.flatMap((layer) =>
    layer.display_axes.map((axis: PointAxis, index: number) => pointAxisLegend(layer, axis, index)),
  );
}
