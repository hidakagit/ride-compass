/** 地図上チップ（`MapOverlayControls`）へ渡す1枚ずつの状態と、レイヤーのON/OFFの保存形式。
 *
 * チップも▶パネルの中身も宣言から作る——チップはレイヤーカタログ（`buildMapLayers`）、絞り込める
 * 凡例は`scene/legends.ts`、表示専用の凡例は記述子の`readOnlyLegend`。
 */
import type { LegendEntry } from "@/lib/mapDisplay/legendFilter";
import {
  buildDefaultLayerVisibility,
  isAxisStudioLayer,
  TILE_VERSIONS_MISSING_NOTICE,
  TILE_ZOOM_TOO_WIDE_NOTICE,
  type LayerDataStatusByLayer,
  type ChipLayerDescriptor,
  type MapLayerDescriptor,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/features/map/layers/mapLayers";
import type { LegendFilterSummaryAxis, OverlayLayerChip } from "@/features/map/MapOverlayControls/MapOverlayControls";
import { disasterSourceLegendAxis, pointLegendAxes, roadLegendAxes } from "@/features/map/scene/legends";

import { hiddenKeysOf, presentHiddenKeys } from "./legendFilters";
import type { HiddenLegendKeys } from "./mapLook";

/** 凡例1本。`axisId`を持てば絞り込める（保存先の鍵）。 */
interface ChipLegend {
  label: string;
  legend: readonly LegendEntry[];
  axisId?: string;
}

function chipLegends(layer: ChipLayerDescriptor): ChipLegend[] {
  return [
    ...[...roadLegendAxes(), ...pointLegendAxes(), disasterSourceLegendAxis()]
      .filter((axis) => axis.layerId === layer.id)
      .map((axis) => ({ label: axis.label, legend: axis.entries, axisId: axis.axisId })),
    ...(layer.readOnlyLegend ?? []),
  ];
}

/** 地図上チップの一覧。軸スタジオ由来のレイヤーと、選択中のルートにひもづくレイヤー（`kind`が`dynamic`）は出さない
 * ——どちらも出し入れは色分け（`LensControl`）が持つ。チップの束ね方（`mapLayers.ts: mapOverlayGroupFor`）は中分類しか
 * 見ないので、除くのはここの1か所で、束ねる前に除く。 */
export function overlayChips(options: {
  layers: readonly MapLayerDescriptor[];
  visibility: MapLayerVisibility;
  hidden: HiddenLegendKeys;
  dataStatus: LayerDataStatusByLayer;
  zoomTooWideLayerIds: readonly MapLayerId[];
  /** タイル世代が届くまで描けず、いま世代が無いレイヤー。 */
  versionMissingLayerIds: readonly MapLayerId[];
  /** 軸カタログの取得を終えたか。終えたのに世代が無いなら、待っても直らない。 */
  catalogSettled: boolean;
}): OverlayLayerChip[] {
  const { hidden, catalogSettled } = options;
  return options.layers
    .filter((layer): layer is ChipLayerDescriptor => !isAxisStudioLayer(layer))
    .filter((layer) => layer.kind !== "dynamic")
    .map((layer) => {
      const versionMissing = options.versionMissingLayerIds.includes(layer.id);
      return {
        id: layer.id,
        label: layer.label,
        icon: layer.icon,
        on: options.visibility[layer.id] === true,
        title: layer.description,
        notice:
          versionMissing && catalogSettled
            ? TILE_VERSIONS_MISSING_NOTICE
            : options.zoomTooWideLayerIds.includes(layer.id)
              ? TILE_ZOOM_TOO_WIDE_NOTICE
              : null,
        legendDetails: chipLegends(layer).map((axis): LegendFilterSummaryAxis => ({
          ...axis,
          hiddenKeys:
            axis.axisId === undefined ? [] : presentHiddenKeys(axis.legend, hiddenKeysOf(hidden, axis.axisId)),
        })),
        category: layer.category,
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
