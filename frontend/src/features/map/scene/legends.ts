/** 凡例の行を、地図を描いているのと同じ宣言から作る。
 *
 * **色と分類の正本はグループ（`groups/*.ts`）にしかない**——凡例が別に色を持つと、
 * 地図とチップの色が静かに食い違う。ここはその宣言を凡例の形へ移すだけで、値を持たない。
 */
import { COLOR_UNKNOWN } from "@/features/map/scene/sceneBuilders";
import type { DisasterSourceKey } from "@/features/map/layers/dynamicWeather";
import type { LegendEntry } from "@/lib/mapDisplay/legendFilter";
import { LEGEND_NO_DATA_KEY } from "@/lib/mapDisplay/mapColorLegend";

import { mapDisplay } from "@/types/generated/mapDisplay";
import palette from "@/types/generated/palette.json";
import weatherScales from "@/types/generated/weather-scales.json";

import { POINT_LAYERS, pointAxisKey, pointCategoryRadiusPx, type PointAxis } from "@/features/map/scene/groups/points";
import {
  ROAD_OTHER_KEY,
  ROAD_TRACKS,
  roadCategoryWidthPx,
  roadTrackAxis,
  roadTrackHasMissing,
} from "@/features/map/scene/groups/roadLines";

/** 凡例1本ぶん。1つのチップが複数の軸を持つことがある（事故は当事者と重大度）。 */
type SceneLegendAxis = {
  /** 地図チップのid（＝レイヤーの役割）。 */
  readonly layerId: string;
  /** 隠した行を覚えておく鍵。 */
  readonly axisId: string;
  /** 軸が1本だけなら見出しは空でよい（チップ名で足りる）。 */
  readonly label: string;
  readonly entries: readonly LegendEntry[];
};

/** 分類に当てはまらない値の道。値はあるので実線で出す。タグの不在も確定した値として載る属性（トンネル等）では、
 * それが「該当しない」ことそのものなので呼び方を変える。 */
function otherEntry(hasMissing: boolean): LegendEntry {
  return { key: ROAD_OTHER_KEY, label: hasMissing ? "その他" : "該当なし", color: COLOR_UNKNOWN };
}

/** タグが無い道の受け皿。**地図も同じ扱い**（消さずに薄い破線で出す）。 */
const NO_DATA_ENTRY: LegendEntry = {
  key: LEGEND_NO_DATA_KEY,
  label: "不明",
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
        lineWidthPx: roadCategoryWidthPx(category),
      })),
      { ...otherEntry(roadTrackHasMissing(track)), lineWidthPx: mapDisplay.road.lineWidthPx },
      ...(roadTrackHasMissing(track) ? [{ ...NO_DATA_ENTRY, lineWidthPx: mapDisplay.road.lineWidthPx }] : []),
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

export const DISASTER_LAYER_ID = "disaster";

/** 災害の要素ごとの色見本。地図がその要素を塗る段のうち、注意を促す段の色（平常時の色を
 * 見本にすると、どの要素も同じに見える）。鍵は源泉が配る災害のソースで、要素が増えれば
 * 型検査が落ちる。 */
const DISASTER_SOURCE_SWATCH: Record<DisasterSourceKey, string> = {
  heavyRain: weatherScales.risk_levels[2].color,
  landslide: weatherScales.risk_levels[2].color,
  inundation: weatherScales.risk_levels[2].color,
  flood: weatherScales.risk_levels[2].color,
  thunder: weatherScales.thunder_activity[1].color,
  tornado: weatherScales.tornado_potential[0].color,
  liden: palette.semantic.lightning,
};

/** 災害チップの要素ごとの表示切替。隠した要素は取りに行かない（地図の絞り込みではなく取得を止める）。
 * 行の並びと名前は源泉の要素の宣言のまま。 */
export function disasterSourceLegendAxis(): SceneLegendAxis {
  const sources = mapDisplay.weatherElements.filter((element) => element.group === DISASTER_LAYER_ID);
  return {
    layerId: DISASTER_LAYER_ID,
    axisId: DISASTER_LAYER_ID,
    label: "表示する情報",
    entries: [...new Map(sources.map((element) => [element.source, element.label]))].map(([source, label]) => ({
      key: source,
      label,
      color: DISASTER_SOURCE_SWATCH[source as DisasterSourceKey],
    })),
  };
}
