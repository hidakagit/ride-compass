// 専用のフィーチャー→値配信レイヤー（backend `GET /api/region/dynamic-way-values/{axis_id}/...`、
// `dedicated_way_value_layer=true`の軸）の表示宣言。軸ごとのファイル・定数は持たず、
// 軸スタジオが配信する表示宣言（種類・単位・しきい値・段階ラベル）だけから組み立てる。
// 地図の線は`features/map/scene/groups/axisLines.ts`、凡例は`features/map/view/lens.ts`が作る。

import type { MapLegendScale, MapValueKind } from "./valueScale";

/** 軸カタログ（GET /api/axis-catalog）から軸ごとに組み立てる表示宣言。しきい値は
 * map_value_thresholds（地図が塗る値のスケールへ揃えた境界。宣言の無い軸の既定もbackendが解いて入れる）、
 * 凡例がそれを書く目盛りはmap_legend、段階ラベルはdisplay_band_labels_override（未設定なら数値レンジのみ）。 */
export interface DedicatedWayValueDisplay {
  kind: MapValueKind;
  boundaries: readonly number[];
  legend: MapLegendScale;
  bandLabels?: readonly string[] | null;
}
