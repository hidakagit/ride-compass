/** 地図上チップ（`MapOverlayControls`）へ渡す1枚ずつの状態と、レイヤーのON/OFFの保存形式。
 *
 * チップも▶パネルの中身も宣言から作る——チップはレイヤーカタログ（`buildMapLayers`）、絞り込める
 * 凡例は`scene/legends.ts`、表示専用の凡例は記述子の`readOnlyLegend`。画面の状態からしか
 * 作れない凡例（ルート線の段）だけを呼び出し側が渡す。
 */
import type { LegendEntry, LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
import {
  buildDefaultLayerVisibility,
  isAxisStudioLayer,
  TILE_VERSIONS_MISSING_NOTICE,
  TILE_ZOOM_TOO_WIDE_NOTICE,
  type LayerDataStatusByLayer,
  type MapLayerDescriptor,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import type { OverlayLayerChip } from "@/components/MapOverlayControls/MapOverlayControls";
import { disasterSourceLegendAxis, pointLegendAxes, roadLegendAxes } from "@/features/map/scene/legends";

import { hiddenKeysOf } from "./legendFilters";
import type { HiddenLegendKeys } from "./mapLook";

/** 凡例1本。`axisId`を持てば絞り込める（保存先の鍵）。 */
export interface ChipLegend {
  label: string;
  legend: readonly LegendEntry[];
  axisId?: string;
}

function chipLegends(layer: MapLayerDescriptor, screenLegends: readonly ChipLegend[]): ChipLegend[] {
  return [
    ...[...roadLegendAxes(), ...pointLegendAxes(), disasterSourceLegendAxis()]
      .filter((axis) => axis.layerId === layer.id)
      .map((axis) => ({ label: axis.label, legend: axis.entries, axisId: axis.axisId })),
    ...(layer.readOnlyLegend ?? []),
    ...screenLegends,
  ];
}

/** 地図上チップの一覧。軸スタジオ由来のレイヤーは出さない——表示はレンズだけが決める。 */
export function overlayChips(options: {
  layers: readonly MapLayerDescriptor[];
  visibility: MapLayerVisibility;
  hidden: HiddenLegendKeys;
  screenLegends: Partial<Record<MapLayerId, readonly ChipLegend[]>>;
  dataStatus: LayerDataStatusByLayer;
  zoomTooWideLayerIds: readonly MapLayerId[];
  /** タイル世代が届くまで描けず、いま世代が無いレイヤー。 */
  versionMissingLayerIds: readonly MapLayerId[];
  /** 軸カタログの取得を終えたか。終えたのに世代が無いなら、待っても直らない。 */
  catalogSettled: boolean;
  /** 候補を選んでいるか。選ぶまで、ルートにひもづくレイヤーは押しても何も出ない。 */
  hasSelectedRoute: boolean;
}): OverlayLayerChip[] {
  const { hidden, catalogSettled } = options;
  return options.layers
    .filter((layer) => !isAxisStudioLayer(layer))
    .map((layer) => {
      const versionMissing = options.versionMissingLayerIds.includes(layer.id);
      return {
        id: layer.id,
        label: layer.label,
        icon: layer.icon,
        chipLabel: layer.chipLabel ?? layer.label,
        on: options.visibility[layer.id] === true,
        disabled: layer.kind === "dynamic" && !options.hasSelectedRoute,
        title: layer.description,
        notice:
          versionMissing && catalogSettled
            ? TILE_VERSIONS_MISSING_NOTICE
            : options.zoomTooWideLayerIds.includes(layer.id)
              ? TILE_ZOOM_TOO_WIDE_NOTICE
              : null,
        legendDetails: chipLegends(layer, options.screenLegends[layer.id] ?? []).map(
          (axis): LegendFilterSummaryAxis => ({
            ...axis,
            hiddenKeys: axis.axisId === undefined ? [] : hiddenKeysOf(hidden, axis.axisId),
          }),
        ),
        category: layer.category,
        dataNature: layer.dataNature,
        axisStudioLayer: layer.axisStudioLayer,
        panelHint: layer.panelHint,
        // 世代が無いとソースを作らないため、MapLibreのイベントは何も言わない。
        dataStatus: versionMissing ? (catalogSettled ? "error" : "loading") : options.dataStatus[layer.id],
      };
    });
}

/** 保存値のうち、いまのレイヤーカタログにある鍵の真偽値だけを読む。無い鍵は既定のまま
 * ——レイヤーが増えた後の古い保存値から、新しいレイヤーの既定が消えないようにする。 */
export function deserializeLayerVisibility(raw: string): MapLayerVisibility {
  const stored: unknown = JSON.parse(raw);
  const visibility = buildDefaultLayerVisibility();
  if (stored === null || typeof stored !== "object") return visibility;
  for (const id of Object.keys(visibility) as MapLayerId[]) {
    const value = (stored as Record<string, unknown>)[id];
    if (typeof value === "boolean") visibility[id] = value;
  }
  return visibility;
}
