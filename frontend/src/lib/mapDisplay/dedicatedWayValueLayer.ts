// 専用way_id→値配信レイヤー（backend `GET /api/region/dynamic-way-values/{axis_id}/...`、
// `dedicated_way_value_layer=true`の軸）の表示宣言。軸ごとのファイル・定数は持たず、
// 軸スタジオが配信する表示宣言（種類・単位・しきい値・段階ラベル）だけから組み立てる。
// 地図の線は`features/map/scene/groups/axisLines.ts`、凡例は`features/map/view/lens.ts`が作る。

import type { MapValueKind } from "./valueScale";

/** 軸カタログ（GET /api/axis-catalog）から軸ごとに組み立てる表示宣言。しきい値は
 * map_value_thresholds（地図が塗る値のスケールへ揃えた境界）、段階ラベルは
 * display_band_labels_override（未設定ならそれぞれ種類の既定値・数値レンジのみ）。 */
export interface DedicatedWayValueDisplay {
  kind: MapValueKind;
  unit: string;
  boundaries?: readonly number[] | null;
  bandLabels?: readonly string[] | null;
}
