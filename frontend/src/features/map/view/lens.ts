/** レンズ（地図を何で塗るか）の1つの値から、地図と`LensControl`へ渡すものを導く。
 *
 * 全道路の塗り（ramp軸・専用配信軸）もルート線の色分けも同じ`lens`から導き、軸の種類ごとの
 * 分岐は持たない——軸を公開すれば、ここへ何も足さずに選択肢と塗り分けへ現れる。
 */
import type { DedicatedWayValueAxis, RampAxis } from "@/lib/mapDisplay/axisLayers";
import {
  NO_DATA_LEGEND_BAND,
  UNDETERMINED_LEGEND_BAND,
  type MapColorLegendBand,
} from "@/lib/mapDisplay/mapColorLegend";
import { dedicatedAxisBands, rampAxisBands } from "@/lib/mapDisplay/valueScale";
import { buildAxisRampUnknownExpression, buildAxisRampValueExpression } from "@/features/map/scene/groups/axisLines";
import type { LegendEntry } from "@/lib/mapDisplay/legendFilter";
import {
  LENS_DIFFICULTY_ID,
  LENS_NEUTRAL_COLOR,
  type LensId,
  type RouteStyleMode,
} from "@/lib/mapDisplay/routeStyleModes";
import type { LensOption } from "@/features/map/LensControl/LensControl";
import type { CatalogAxis } from "@/lib/catalogAxis";
import { cardinalLabel } from "@/lib/cardinalLabel";

/** 全道路を塗っている軸。ルート確定後は、周囲も塗り続ける設定の間だけ塗る。 */
export function paintedAxisId(lens: LensId, hasDetail: boolean, keepAfterRoute: boolean): LensId | null {
  return !hasDetail || keepAfterRoute ? lens : null;
}

/** 周りの道の色が拠る走る条件の文（例:「北へ走る・時速20km・19:30出発」）。塗っている軸が使う条件だけを、軸カタログの
 * 宣言から並べる。塗っている軸が条件を使わなければnull——画面に出ていない条件で、同じ道の色が変わって見えないように出す。 */
export function lensConditionsLabel(
  paintedAxis: LensId | null,
  dedicatedAxes: readonly DedicatedWayValueAxis[],
  ride: { bearingDeg: number; speedKmh: number },
  departureLabel: string,
): string | null {
  const axis = dedicatedAxes.find((candidate) => candidate.axisId === paintedAxis);
  if (axis === undefined) return null;
  const parts = [
    axis.needsBearing ? `${cardinalLabel(ride.bearingDeg)}へ走る` : null,
    axis.needsSpeed ? `時速${ride.speedKmh}km` : null,
    axis.needsTime ? `${departureLabel}出発` : null,
  ].filter((part) => part !== null);
  return parts.length > 0 ? parts.join("・") : null;
}

/** レンズの凡例。地図がいま塗っているものの凡例だけを出す——塗っていない間に出すと、
 * 地図のどこにも無い色見本の表になる。ルート確定後はルート線のモードの凡例。 */
export function lensLegend(
  lens: LensId,
  hasDetail: boolean,
  catalog: {
    routeStyleModes: readonly RouteStyleMode[];
    rampAxes: readonly RampAxis[];
    dedicatedAxes: readonly DedicatedWayValueAxis[];
  },
): readonly LegendEntry[] {
  if (hasDetail) return catalog.routeStyleModes.find((mode) => mode.id === lens)?.legend ?? [];
  const ramp = catalog.rampAxes.find((axis) => axis.axisId === lens);
  if (ramp) return buildAxisRampLegend(ramp);
  const dedicated = catalog.dedicatedAxes.find((axis) => axis.axisId === lens);
  if (dedicated) return dedicatedWayValueLegend(dedicated);
  return [];
}

/** レンズの選択肢（公開軸、カタログの並び順）。「なし」「総合難易度」は`LensControl`が足す。
 *
 * 「未使用」は`weights`（生成後は生成に使われた重み、生成前は今の設定の重み）が0の軸——重みタブが
 * 薄く出す軸と同じで、重みを変えずに生成すれば前後で並びが変わらない。 */
export function lensOptions(
  axes: readonly CatalogAxis[],
  paintableAxisIds: ReadonlySet<string>,
  weights: Readonly<Record<string, number>>,
  axisColors: Readonly<Record<string, string>>,
): LensOption[] {
  return axes.map((axis) => ({
    id: axis.axisId,
    label: axis.label,
    color: axisColors[axis.axisId] ?? LENS_NEUTRAL_COLOR,
    unused: (weights[axis.axisId] ?? 0) <= 0,
    routeOnly: !paintableAxisIds.has(axis.axisId),
  }));
}

/** ramp軸の凡例。分類で塗るレイヤーと同じLegendEntry型で返し、凡例のチェックボックス・
 * 地図チップの▶展開凡例をそのまま共有する。段の鍵・範囲の文字・体感ラベル・色は
 * 地図の線と同じ`rampAxisBands`が決める——段の鍵はルート確定前後で共通で、
 * **軸idを混ぜない**（非表示にした段の保存先は前後で同じ軸idの下なので、別の綴りにすると
 * 隠した段がルート生成で黙って戻る）。
 * filterはbuildAxisRampValueExpression（地図の色分けが使うのと同じ線形結合）への
 * 範囲比較で、実際に塗られる色と凡例が食い違わないようにする。
 * hasUnknownFallbackな軸は末尾に「データなし」の行を足し、他の段階のfilterには
 * 「値が無いのではない」条件を足して二重分類を防ぐ。 */
function buildAxisRampLegend(axis: RampAxis): LegendEntry[] {
  const valueExpression = buildAxisRampValueExpression(axis);
  const unknownExpression = buildAxisRampUnknownExpression(axis);
  const { thresholds } = axis;
  const bands = rampAxisBands(axis).map(({ key, label, color }, index) => {
    const filterParts: unknown[] = ["all"];
    if (unknownExpression !== null) filterParts.push(["!", unknownExpression]);
    if (index > 0) filterParts.push([">=", valueExpression, thresholds[index - 1]]);
    if (index < thresholds.length) filterParts.push(["<", valueExpression, thresholds[index]]);
    return { key, label, color, filter: filterParts };
  });
  if (unknownExpression === null) return bands;
  return [...bands, { ...NO_DATA_LEGEND_BAND, filter: ["all", unknownExpression] }];
}

/** 地図上の色分け凡例。地図の線と同じ配色・しきい値から段階ラベル付きの凡例を組み立てる。
 * 段階ラベル（bandLabels）は要素数が段階数と一致する間だけ数値レンジの前に添える
 * （不一致な保存データへの防御）。末尾の「データなし」は値を受け取れなかった道路の受け皿で、
 * ルート確定後のルート線の凡例（`routeStyleModes.ts`）と段階の並び・キーを揃える。
 * 「向きで決まらない」は、配信がその道を返しうる軸だけに足す（ルートの線は実際に走る向きで決まるので持たない）。 */
function dedicatedWayValueLegend(axis: DedicatedWayValueAxis): MapColorLegendBand[] {
  const bands = dedicatedAxisBands(axis.display).map(({ key, label, color }) => ({ key, label, color }));
  return [...bands, ...(axis.undeterminedByBearing ? [UNDETERMINED_LEGEND_BAND] : []), NO_DATA_LEGEND_BAND];
}

// 既定のレンズは総合難易度（軸の公開状態に依存せず常に存在するモード）。
export const DEFAULT_ROUTE_STYLE_MODE_ID: LensId = LENS_DIFFICULTY_ID;

export function isRouteStyleModeId(
  modes: readonly RouteStyleMode[],
  value: string | null | undefined,
): value is LensId {
  return modes.some((mode) => mode.id === value);
}
