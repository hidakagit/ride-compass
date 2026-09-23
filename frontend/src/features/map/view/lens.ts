/** レンズ（地図を何で塗るか）の1つの値から、地図と`LensControl`へ渡すものを導く。
 *
 * ルート確定前は全道路の塗り（ramp軸は`axisVisibility`、専用配信軸は
 * `dedicatedWayValueVisibility`）、確定後はルート線（`routeStyleModeId`）を、どれも同じ
 * `lens`から導く。軸の種類ごとの分岐は持たず、軸カタログの一覧を横断するだけにする——
 * 軸を公開すれば、ここへ何も足さずにレンズの選択肢と塗り分けへ現れる。
 */
import {
  axisMapLayerId,
  buildAxisRampLegend,
  dedicatedWayValueMapLayerId,
  type DedicatedWayValueAxis,
  type RampAxis,
} from "@/components/Map/axisLayers";
import { dedicatedWayValueLegend } from "@/components/Map/dedicatedWayValueLayer";
import type { LegendEntry } from "@/components/Map/legendFilter";
import { deriveFetchLayerStatus, LAYER_DATA_STATUS_LABELS, type LayerDataStatus } from "@/components/Map/mapLayers";
import {
  isRouteStyleModeId,
  LENS_NEUTRAL_COLOR,
  type LensId,
  type RouteStyleMode,
} from "@/components/Map/routeStyleModes";
import type { LensOption } from "@/components/LensControl/LensControl";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";

/** 1軸ぶんの専用配信の結果のうち、レンズの状態ドットが読むもの。 */
interface DedicatedFetchResult {
  values: ReadonlyMap<string, number>;
  loading: boolean;
  error: boolean;
  hasFetched: boolean;
}

const NO_LEGEND: readonly LegendEntry[] = [];

/** ルート確定後も全道路を塗り続けるか。確定前は常に塗る。 */
export function lensBackgroundShown(hasDetail: boolean, keepAfterRoute: boolean): boolean {
  return !hasDetail || keepAfterRoute;
}

/** ramp軸のレイヤーid → 表示するか。全ramp軸の鍵を持つ（選ばれていない軸はfalse）。 */
export function lensAxisVisibility(
  rampAxes: readonly RampAxis[],
  lens: LensId,
  backgroundShown: boolean,
): Record<string, boolean> {
  return Object.fromEntries(
    rampAxes.map((axis) => [axisMapLayerId(axis.axisId), backgroundShown && axis.axisId === lens]),
  );
}

/** 専用配信軸のレイヤーid → 表示するか。 */
export function lensDedicatedWayValueVisibility(
  dedicatedAxes: readonly DedicatedWayValueAxis[],
  lens: LensId,
  backgroundShown: boolean,
): Record<string, boolean> {
  return Object.fromEntries(
    dedicatedAxes.map((axis) => [dedicatedWayValueMapLayerId(axis.axisId), backgroundShown && axis.axisId === lens]),
  );
}

/** 値を取りに行く専用配信軸。塗らない軸は取りに行かない（表示中のものだけ叩く）。 */
export function lensFetchAxes(
  dedicatedAxes: readonly DedicatedWayValueAxis[],
  lens: LensId,
  backgroundShown: boolean,
): readonly DedicatedWayValueAxis[] {
  if (!backgroundShown) return [];
  return dedicatedAxes.filter((axis) => axis.axisId === lens);
}

/** レンズの凡例。**地図がいま塗っているものの凡例だけを出す**——塗っていない間に凡例を
 * 出すと、地図のどこにも無い色見本の表になる。
 *
 * ルート確定後はルート線のモードの凡例。確定前は、そのレンズで全道路を塗る手段の凡例
 * （専用配信とramp表示の両方を持つ軸は専用配信の側。専用配信の線はramp軸の線より前面の段に
 * 描かれるため、見えているのはそちら）。 */
export function lensLegend(options: {
  lens: LensId;
  hasDetail: boolean;
  routeStyleModes: readonly RouteStyleMode[];
  rampAxes: readonly RampAxis[];
  dedicatedAxes: readonly DedicatedWayValueAxis[];
}): readonly LegendEntry[] {
  const { lens, hasDetail, routeStyleModes, rampAxes, dedicatedAxes } = options;
  if (hasDetail) return routeStyleModes.find((mode) => mode.id === lens)?.legend ?? NO_LEGEND;
  const dedicated = dedicatedAxes.find((axis) => axis.axisId === lens);
  if (dedicated) return dedicatedWayValueLegend(dedicated.display);
  const ramp = rampAxes.find((axis) => axis.axisId === lens);
  if (ramp) return buildAxisRampLegend(ramp);
  return NO_LEGEND;
}

/** レンズの選択肢（公開軸、カタログの並び順）。「なし」「総合難易度」は`LensControl`が足す。
 *
 * 重みが0の軸も選べる（未使用として示す）。重みが無い軸は軸の既定重みで判断する——
 * 評価の設定がまだ軸カタログへ整合していない間も、生成時と同じ重みで見分けるため。 */
export function lensOptions(options: {
  axes: readonly PreferenceAxisDef[];
  rampAxes: readonly RampAxis[];
  dedicatedAxes: readonly DedicatedWayValueAxis[];
  axisWeights: Readonly<Record<string, number>>;
  defaultWeights: Readonly<Record<string, number>>;
  axisColors: Readonly<Record<string, string>>;
}): LensOption[] {
  const { axes, rampAxes, dedicatedAxes, axisWeights, defaultWeights, axisColors } = options;
  const paintable = new Set([...rampAxes.map((axis) => axis.axisId), ...dedicatedAxes.map((axis) => axis.axisId)]);
  return axes.map((axis) => ({
    id: axis.axisId,
    label: axis.label,
    color: axisColors[axis.axisId] ?? LENS_NEUTRAL_COLOR,
    description: axis.description || undefined,
    unused: (axisWeights[axis.axisId] ?? defaultWeights[axis.axisId] ?? 0) <= 0,
    routeOnly: !paintable.has(axis.axisId),
  }));
}

/** レンズのピルに添える取得状態。専用配信軸を取りに行っている間だけ持つ——他のレンズは
 * タイル（道路のチップ側が状態を出す）かルートの結果を塗るため、この失敗の形を持たない。 */
export function lensDataStatus(result: DedicatedFetchResult | undefined): LayerDataStatus | undefined {
  if (result === undefined) return undefined;
  return deriveFetchLayerStatus(
    result.loading,
    result.error ? LAYER_DATA_STATUS_LABELS.error : null,
    result.values.size > 0,
    result.hasFetched,
  );
}

/** 保存したレンズを、いま選べるモードの中にあるときだけ読む。 */
export function restoreLens(raw: string, routeStyleModes: readonly RouteStyleMode[]): LensId | null {
  return isRouteStyleModeId(routeStyleModes, raw) ? raw : null;
}

/** 専用配信の結果を、地図が受け取る軸id→値・軸id→取得中の2つへ写す。 */
export function dedicatedResultsForMap(results: ReadonlyMap<string, DedicatedFetchResult>): {
  dedicatedWayValues: ReadonlyMap<string, ReadonlyMap<string, number>>;
  dedicatedWayValueLoading: ReadonlyMap<string, boolean>;
} {
  const entries = [...results];
  return {
    dedicatedWayValues: new Map(entries.map(([axisId, result]) => [axisId, result.values])),
    dedicatedWayValueLoading: new Map(entries.map(([axisId, result]) => [axisId, result.loading])),
  };
}
