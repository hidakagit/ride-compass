// 専用way_id→値配信レイヤー（backend `GET /api/region/dynamic-way-values/{axis_id}/...`、
// `dedicated_way_value_layer=true`の軸）のMapLibre側純粋ロジック。ルート確定前に視界内の
// 全道路を、その軸の地図表示値（backendが軸定義から決める`map_value_kind`のスケール:
// 難易度0〜100、または符号付き材料生値）で線色分けする。他のramp軸（axisLayers.ts）と違い
// 値がタイルへ焼き込まれておらず、setFeatureStateで別経路から取得した値を後から地物へ
// 差し込む。軸ごとのファイル・定数は持たず、軸スタジオが配信するDedicatedWayValueDisplay
// （種類・単位・しきい値・段階ラベル）だけから色式と凡例を組み立てる。
//
// 実際のfetch（services/regionApi.ts: fetchDynamicWayValues）・状態管理
// （hooks/useDedicatedWayValues.ts）・DOM/MapLibre操作（MapView.tsx: map.setFeatureState）は
// 別ファイルが持ち、このファイルはMapLibreインスタンスを一切知らない純粋関数のみを持つ。

import {
  bandLabelsForBandCount,
  buildRangeLegendBands,
  LEGEND_NO_DATA_KEY,
  type MapColorLegendBand,
} from "./mapColorLegend";
import { FALLBACK_LINE_OPACITY, KNOWN_LINE_OPACITY } from "./roadFilterAxes";
import {
  bandColorsFor,
  buildSteppedColorExpression,
  COLOR_NO_DATA,
  valueScaleFor,
  type MapValueKind,
} from "./valueScale";

/** 軸カタログ（GET /api/axis-catalog）から軸ごとに組み立てる表示宣言。しきい値は
 * map_value_thresholds（地図が塗る値のスケールへ揃えた境界）、段階ラベルは
 * display_band_labels_override（未設定ならそれぞれ種類の既定値・数値レンジのみ）。 */
export interface DedicatedWayValueDisplay {
  kind: MapValueKind;
  unit: string;
  boundaries?: readonly number[] | null;
  bandLabels?: readonly string[] | null;
}

/** 軸カタログの取得前など表示宣言が無い場合の既定（難易度スケール、単位なし）。 */
export const DEFAULT_DEDICATED_WAY_VALUE_DISPLAY: DedicatedWayValueDisplay = { kind: "difficulty", unit: "" };

/** setFeatureStateで差し込む状態キー。同じ路面タイルソースの地物へ複数の軸が値を持つため
 * 軸idごとに異なるキーにする。 */
export function dedicatedWayValueFeatureStateKey(axisId: string): string {
  return `${axisId}Value`;
}

/** 値取得式（feature-state or geojsonプロパティ）を色へ変換するMapLibre expression。値の
 * 取得元だけを引数に取る形にしてあり、feature-state以外から値を読む呼び出し側を足せる。
 * `loading`はまだ値を受け取っていない対象の色をCOLOR_LOADING（フェッチ進行中）と
 * COLOR_NO_DATA（取得済みだが値が無い）のどちらにするか（valueScale.ts参照）。
 * `hiddenBandKeys`は凡例で非表示にした段階のキー（同上）。 */
export function buildDedicatedWayValueColorExpression(
  valueExpression: unknown[],
  display: DedicatedWayValueDisplay = DEFAULT_DEDICATED_WAY_VALUE_DISPLAY,
  loading = false,
  hiddenBandKeys: readonly string[] = [],
): unknown[] {
  return buildSteppedColorExpression({
    valueExpression,
    kind: display.kind,
    boundaries: display.boundaries,
    loading,
    hiddenBandKeys,
  });
}

/** feature-state値を色へ変換するMapLibre expression。["feature-state", key]は該当キーが
 * 未設定のfeatureに対しnullを返す（MapLibreの仕様）。 */
export function dedicatedWayValueColorExpression(
  axisId: string,
  display?: DedicatedWayValueDisplay,
  loading = false,
  hiddenBandKeys: readonly string[] = [],
): unknown[] {
  return buildDedicatedWayValueColorExpression(
    ["feature-state", dedicatedWayValueFeatureStateKey(axisId)],
    display,
    loading,
    hiddenBandKeys,
  );
}

/** 値の有無で線の濃さを決めるMapLibre expression。値を受け取れなかった道は
 * `FALLBACK_LINE_OPACITY`で薄くし、値を持つ道だけが浮かび上がるようにする——
 * 地図全体の「薄い＝対象外、濃い＝分類あり」という読み方（roadFilterAxes.ts）を
 * このレイヤーにも揃える。**薄くするのであって消さない**
 * （docs/design-principles.md「消さずに薄くする」）。
 *
 * 値が無い道には、標高が計算されていない道と、勾配のように向きを指定する軸で
 * **その向きに対して直角に近く、値を示せない道**（domain/gradient.py: shows_gradient）。
 * 方位を1つ指定すると後者が街区の半分近くを占めうるため、濃いまま塗ると値のある道が
 * そこへ埋もれる。どちらも利用者にとっては「いま見ている条件の対象外」なので同じ薄さで
 * 足りる（分けるなら配信側が種類を持つ必要がある）。
 *
 * `loading`（まだ一度も値を受け取っていない）のあいだは薄くしない——取得中を示す
 * COLOR_LOADINGが見えなくなり、「取得中」と「対象外」の区別が付かなくなる。 */
export function buildDedicatedWayValueOpacityExpression(valueExpression: unknown[], loading = false): unknown[] {
  return [
    "case",
    ["==", valueExpression, null],
    loading ? KNOWN_LINE_OPACITY : FALLBACK_LINE_OPACITY,
    KNOWN_LINE_OPACITY,
  ];
}

/** feature-state値から線の濃さを決めるMapLibre expression（色式と同じ値の取得元を使う）。 */
export function dedicatedWayValueOpacityExpression(axisId: string, loading = false): unknown[] {
  return buildDedicatedWayValueOpacityExpression(["feature-state", dedicatedWayValueFeatureStateKey(axisId)], loading);
}

/** 地図上の色分け凡例。色式と同じ配色・しきい値から段階ラベル付きの凡例を組み立てる。
 * 段階ラベル（bandLabels）は要素数が段階数と一致する間だけ数値レンジの前に添える
 * （不一致な保存データへの防御）。末尾の「データなし」は値を受け取れなかった道路の受け皿で、
 * ルート確定後のルート線の凡例（`routeStyleModes.ts`）と段階の並び・キーを揃える。 */
export function dedicatedWayValueLegend(
  display: DedicatedWayValueDisplay = DEFAULT_DEDICATED_WAY_VALUE_DISPLAY,
): MapColorLegendBand[] {
  const boundaries = display.boundaries ?? valueScaleFor(display.kind).defaultBoundaries;
  const colors = bandColorsFor(display.kind, boundaries);
  const labels = bandLabelsForBandCount(display.bandLabels, boundaries.length + 1);
  return [
    ...buildRangeLegendBands(boundaries, colors, display.unit, labels),
    { key: LEGEND_NO_DATA_KEY, label: "データなし", color: COLOR_NO_DATA, isFallback: true },
  ];
}
