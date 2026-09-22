/** 凡例の行を、地図を描いているのと同じ宣言から作る。
 *
 * **色と分類の正本はグループ（`groups/*.ts`）にしかない**——凡例が別に色を持つと、
 * 地図とチップの色が静かに食い違う。ここはその宣言を凡例の形へ移すだけで、値を持たない。
 */
import type { LegendEntry } from "@/components/Map/legendFilter";
import { PRIMARY_ATTRIBUTE_LABELS } from "@/components/Map/primaryAttributes";

import { POINT_LAYERS, pointAxisKey, type PointAxis, type PointLayerDecl } from "./groups/points";
import { ROAD_TRACKS } from "./groups/roadLines";

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
const UNKNOWN_ENTRY: LegendEntry = { key: "unknown", label: "不明・他", color: "#94a3b8", isFallback: true };

export function roadLegendAxes(): readonly SceneLegendAxis[] {
  return ROAD_TRACKS.map((track) => ({
    layerId: track.attrId,
    axisId: track.attrId,
    // 見出しはチップ名で足りる（軸が1本しかない）。名前の正本は源泉。
    label: "",
    entries: [
      ...track.categories.map((category) => ({ key: category.key, label: category.label, color: category.color })),
      UNKNOWN_ENTRY,
    ],
  }));
}

function pointAxisLegend(layer: PointLayerDecl, axis: PointAxis): SceneLegendAxis {
  return {
    layerId: layer.role,
    axisId: pointAxisKey(layer, axis),
    label: axis.label ?? "",
    entries: axis.categories.map((category) => ({
      key: category.key,
      label: category.label,
      color: category.color,
    })),
  };
}

export function pointLegendAxes(): readonly SceneLegendAxis[] {
  return POINT_LAYERS.flatMap((layer) => layer.axes.map((axis) => pointAxisLegend(layer, axis)));
}
