/** レンズ（地図を何で塗るか）の1つの値から、地図と`LensControl`へ渡すものを導く。
 *
 * 全道路の塗り（ramp軸・専用配信軸）もルート線の色分けも同じ`lens`から導き、軸の種類ごとの
 * 分岐は持たない——軸を公開すれば、ここへ何も足さずに選択肢と塗り分けへ現れる。
 */
import { buildAxisRampLegend, type DedicatedWayValueAxis, type RampAxis } from "@/components/Map/axisLayers";
import { dedicatedWayValueLegend } from "@/components/Map/dedicatedWayValueLayer";
import type { LegendEntry } from "@/components/Map/legendFilter";
import { LENS_NEUTRAL_COLOR, type LensId, type RouteStyleMode } from "@/components/Map/routeStyleModes";
import type { LensOption } from "@/components/LensControl/LensControl";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";

/** 全道路を塗っている軸。ルート確定後は、周囲も塗り続ける設定の間だけ塗る。 */
export function paintedAxisId(lens: LensId, hasDetail: boolean, keepAfterRoute: boolean): LensId | null {
  return !hasDetail || keepAfterRoute ? lens : null;
}

/** 軸ごとのレイヤーid → 表示するか。塗っている軸のレイヤーだけがtrue。 */
export function axisLayerVisibility(
  axes: readonly { axisId: string }[],
  layerIdOf: (axisId: string) => string,
  painted: LensId | null,
): Record<string, boolean> {
  return Object.fromEntries(axes.map((axis) => [layerIdOf(axis.axisId), axis.axisId === painted]));
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
  if (dedicated) return dedicatedWayValueLegend(dedicated.display);
  return [];
}

/** レンズの選択肢（公開軸、カタログの並び順）。「なし」「総合難易度」は`LensControl`が足す。
 *
 * 「未使用」は生成に実際に使われた重み（`usedWeights`）が0の軸で、生成前（null）は付けない
 * ——使う軸は生成した時点で決まる。 */
export function lensOptions(
  axes: readonly PreferenceAxisDef[],
  paintableAxisIds: ReadonlySet<string>,
  usedWeights: Readonly<Record<string, number>> | null,
  axisColors: Readonly<Record<string, string>>,
): LensOption[] {
  return axes.map((axis) => ({
    id: axis.axisId,
    label: axis.label,
    color: axisColors[axis.axisId] ?? LENS_NEUTRAL_COLOR,
    description: axis.description,
    unused: usedWeights !== null && (usedWeights[axis.axisId] ?? 0) <= 0,
    routeOnly: !paintableAxisIds.has(axis.axisId),
  }));
}
