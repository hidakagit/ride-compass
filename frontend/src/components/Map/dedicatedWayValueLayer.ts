// 専用way_id→値配信レイヤー（backend `GET /api/region/dynamic-way-values/{axis_id}/...`、
// `dedicated_way_value_layer=true`の軸）の表示宣言と凡例。軸ごとのファイル・定数は持たず、
// 軸スタジオが配信する表示宣言（種類・単位・しきい値・段階ラベル）だけから組み立てる。
// 地図の線そのものは`features/map/scene/groups/axisLines.ts`が引く。

import {
  bandLabelsForBandCount,
  buildRangeLegendBands,
  LEGEND_NO_DATA_KEY,
  type MapColorLegendBand,
} from "./mapColorLegend";
import { bandColorsFor, COLOR_NO_DATA, DEFAULT_DIFFICULTY_BOUNDARIES, type MapValueKind } from "./valueScale";

/** 軸カタログ（GET /api/axis-catalog）から軸ごとに組み立てる表示宣言。しきい値は
 * map_value_thresholds（地図が塗る値のスケールへ揃えた境界）、段階ラベルは
 * display_band_labels_override（未設定ならそれぞれ種類の既定値・数値レンジのみ）。 */
export interface DedicatedWayValueDisplay {
  kind: MapValueKind;
  unit: string;
  boundaries?: readonly number[] | null;
  bandLabels?: readonly string[] | null;
}

/** 地図上の色分け凡例。地図の線と同じ配色・しきい値から段階ラベル付きの凡例を組み立てる。
 * 段階ラベル（bandLabels）は要素数が段階数と一致する間だけ数値レンジの前に添える
 * （不一致な保存データへの防御）。末尾の「データなし」は値を受け取れなかった道路の受け皿で、
 * ルート確定後のルート線の凡例（`routeStyleModes.ts`）と段階の並び・キーを揃える。 */
export function dedicatedWayValueLegend(display: DedicatedWayValueDisplay): MapColorLegendBand[] {
  const boundaries = display.boundaries ?? DEFAULT_DIFFICULTY_BOUNDARIES;
  const colors = bandColorsFor(display.kind, boundaries);
  const labels = bandLabelsForBandCount(display.bandLabels, boundaries.length + 1);
  return [
    ...buildRangeLegendBands(boundaries, colors, display.unit, labels),
    { key: LEGEND_NO_DATA_KEY, label: "データなし", color: COLOR_NO_DATA, isFallback: true },
  ];
}
