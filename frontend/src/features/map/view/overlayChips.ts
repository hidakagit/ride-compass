/** 地図上チップ（`MapOverlayControls`）へ渡す1枚ずつの状態と、レイヤーのON/OFFから導く
 * 地図側の値を組み立てる。
 *
 * チップの母集団はレイヤーカタログ（`buildMapLayers`）そのもので、ここでレイヤーidを並べない。
 * 画面の状態からしか作れない凡例（ルート・災害の要素トグル）だけを、呼び出し側が
 * レイヤーid→凡例の形で渡す。
 */
import type { LegendEntry, LegendFilterSummaryAxis } from "@/components/Map/legendFilter";
import {
  buildDefaultLayerVisibility,
  isAxisStudioLayer,
  TILE_VERSIONS_MISSING_NOTICE,
  TILE_ZOOM_TOO_WIDE_NOTICE,
  UNUSED_LEGEND_FILTER,
  type LayerDataStatus,
  type LayerDataStatusByLayer,
  type MapLayerDescriptor,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import type { DisasterSourceKey } from "@/components/Map/dynamicWeather";
import { RISK_LEVEL_COLORS } from "@/components/Map/riskMap";
import { THUNDER_ACTIVITY_LEVELS, TORNADO_POTENTIAL_LEVELS } from "@/components/Map/thunderNowcast";
import { axisMapLayerId } from "@/components/Map/axisLayers";
import { primaryAttributeIdsToLayerIds } from "@/components/Map/primaryAttributes";
import type { SecondaryAxisSummary } from "@/components/Map/secondaryAxes";
import type { OverlayLayerChip } from "@/components/MapOverlayControls/MapOverlayControls";
import { pointLegendAxes, roadLegendAxes } from "@/features/map/scene/legends";
import palette from "@/types/generated/palette.json";

import { hiddenKeysOf, presentHiddenKeys, type HiddenLegendKeys } from "./legendFilters";

/** 画面の状態から組み立てる凡例1本。`axisId`を持てば絞り込める。 */
export interface ScreenLegendAxis {
  label: string;
  legend: readonly LegendEntry[];
  axisId?: string;
}

/** 災害チップの要素トグルの保存先id。チップidをそのまま使う。 */
export const DISASTER_LAYER_ID = "disaster" satisfies MapLayerId;

/** 災害の要素ごとの呼び名と、▶パネルの行に添える色見本。
 *
 * 鍵は源泉が配る災害のソース（`DisasterSourceKey`）で、源泉に要素が増えれば型検査が落ちる。
 * 呼び名は源泉が持たない（気象庁の製品名を画面の語で呼ぶのは画面の持ち物）。色見本は、
 * 地図がその要素を塗る段のうち「注意を促す最初の段」の色——平常時の色（透明・白）を見本に
 * すると、どの要素も同じに見える。 */
const DISASTER_SOURCE_ROWS: Record<DisasterSourceKey, { label: string; color: string }> = {
  landslide: { label: "土砂災害キキクル", color: RISK_LEVEL_COLORS[1].color },
  heavyRain: { label: "大雨キキクル", color: RISK_LEVEL_COLORS[1].color },
  inundation: { label: "浸水キキクル", color: RISK_LEVEL_COLORS[1].color },
  flood: { label: "洪水キキクル", color: RISK_LEVEL_COLORS[1].color },
  thunder: { label: "雷ナウキャスト", color: THUNDER_ACTIVITY_LEVELS[0].color },
  tornado: { label: "竜巻発生確度ナウキャスト", color: TORNADO_POTENTIAL_LEVELS[0].color },
  liden: { label: "雷放電位置（落雷地点）", color: palette.semantic.lightning },
};

/** 災害の危険度の読み方。配信元が色を焼き込んだ画像なので絞り込めない。 */
const DISASTER_LEVEL_LEGENDS: readonly ScreenLegendAxis[] = [
  { label: "キキクル（土砂災害・大雨・浸水・洪水）", legend: RISK_LEVEL_COLORS.slice(1) },
  { label: "雷ナウキャスト", legend: THUNDER_ACTIVITY_LEVELS },
  { label: "竜巻発生確度ナウキャスト", legend: TORNADO_POTENTIAL_LEVELS },
].map((axis) => ({ ...axis, legend: axis.legend.map((entry) => ({ ...entry, filter: UNUSED_LEGEND_FILTER })) }));

/** 災害チップの▶パネル。1本目が要素ごとの表示切替で、隠した要素は取りに行かない。 */
export function disasterLegendAxes(): readonly ScreenLegendAxis[] {
  return [
    {
      label: "表示する情報",
      axisId: DISASTER_LAYER_ID,
      legend: (Object.entries(DISASTER_SOURCE_ROWS) as [DisasterSourceKey, { label: string; color: string }][]).map(
        ([key, row]) => ({ key, label: row.label, color: row.color, filter: UNUSED_LEGEND_FILTER }),
      ),
    },
    ...DISASTER_LEVEL_LEGENDS,
  ];
}

/** 絞り込みの宣言（`scene/legends.ts`）と記述子の表示専用の凡例から、そのレイヤーの▶の中身。 */
function declaredLegendAxes(layer: MapLayerDescriptor): readonly ScreenLegendAxis[] {
  const filterable = [...roadLegendAxes(), ...pointLegendAxes()]
    .filter((axis) => axis.layerId === layer.id)
    .map((axis) => ({ label: axis.label, legend: axis.entries, axisId: axis.axisId }));
  const readOnly = (layer.readOnlyLegend ?? []).map((block) => ({ label: block.label, legend: block.legend }));
  return [...filterable, ...readOnly];
}

function toSummaryAxis(axis: ScreenLegendAxis, hidden: HiddenLegendKeys): LegendFilterSummaryAxis {
  return {
    label: axis.label,
    legend: axis.legend,
    hiddenKeys: axis.axisId === undefined ? [] : presentHiddenKeys(axis.legend, hiddenKeysOf(hidden, axis.axisId)),
    ...(axis.axisId === undefined ? {} : { axisId: axis.axisId }),
  };
}

/** そのレイヤーのチップへ出す案内。世代が無いとそもそも描けないため、ズームより先に言う。 */
function noticeFor(layerId: MapLayerId, versionMissing: ReadonlySet<MapLayerId>, zoomTooWide: ReadonlySet<MapLayerId>) {
  if (versionMissing.has(layerId)) return TILE_VERSIONS_MISSING_NOTICE;
  if (zoomTooWide.has(layerId)) return TILE_ZOOM_TOO_WIDE_NOTICE;
  return null;
}

/** 地図上チップの一覧。軸スタジオ由来のレイヤーは出さない——表示はレンズだけが決め、
 * `layerVisibility`にON/OFFの鍵が無い。 */
export function overlayChips(options: {
  layers: readonly MapLayerDescriptor[];
  visibility: MapLayerVisibility;
  dataStatus: LayerDataStatusByLayer;
  /** 世代が届くまで描けないレイヤーのうち、いま世代が無いもの。 */
  versionMissingLayerIds: readonly MapLayerId[];
  zoomTooWideLayerIds: readonly MapLayerId[];
  hidden: HiddenLegendKeys;
  /** 画面の状態からしか作れない凡例（レイヤーid→凡例）。 */
  screenLegends: Partial<Record<MapLayerId, readonly ScreenLegendAxis[]>>;
  /** 候補が1件以上あるか。無い間、ルートにひもづくレイヤーは押しても何も出ない。 */
  hasRoutes: boolean;
}): OverlayLayerChip[] {
  const versionMissing = new Set(options.versionMissingLayerIds);
  const zoomTooWide = new Set(options.zoomTooWideLayerIds);
  return options.layers
    .filter((layer) => !isAxisStudioLayer(layer))
    .map((layer) => ({
      id: layer.id,
      label: layer.label,
      icon: layer.icon,
      chipLabel: layer.chipLabel,
      on: options.visibility[layer.id] === true,
      disabled: layer.kind === "dynamic" && !options.hasRoutes,
      title: layer.description,
      notice: noticeFor(layer.id, versionMissing, zoomTooWide),
      legendDetails: [...declaredLegendAxes(layer), ...(options.screenLegends[layer.id] ?? [])].map((axis) =>
        toSummaryAxis(axis, options.hidden),
      ),
      category: layer.category,
      dataNature: layer.dataNature,
      axisStudioLayer: layer.axisStudioLayer,
      panelHint: layer.panelHint,
      dataStatus: options.dataStatus[layer.id],
    }));
}

/** 世代が届くまで描けないレイヤーの取得状態。カタログを取りに行っている間は読み込み中、
 * 取得を終えたのに世代が無ければ失敗。 */
export function versionMissingStatus(
  versionMissingLayerIds: readonly MapLayerId[],
  catalogSettled: boolean,
): LayerDataStatusByLayer {
  const status: LayerDataStatus = catalogSettled ? "error" : "loading";
  return Object.fromEntries(versionMissingLayerIds.map((id) => [id, status]));
}

/** 下敷きで描くramp軸のレイヤーid。材料（一次属性の表示レイヤー）が1つでもONのとき。 */
export function secondaryAxisCasingLayerIds(
  secondaryAxes: readonly SecondaryAxisSummary[],
  visibility: MapLayerVisibility,
): string[] {
  return secondaryAxes
    .filter((axis) => axis.layerId !== undefined)
    .filter((axis) => primaryAttributeIdsToLayerIds(axis.primaryAttributeIds).some((id) => visibility[id] === true))
    .map((axis) => axisMapLayerId(axis.axisId));
}

/** 「まとめて元に戻す」の対象があるか（既定と違うレイヤーが1つでもあるか）。 */
export function layerVisibilityChanged(visibility: MapLayerVisibility): boolean {
  const defaults = buildDefaultLayerVisibility();
  return (Object.keys(defaults) as MapLayerId[]).some((id) => (visibility[id] === true) !== defaults[id]);
}

/** いま描いている凡例のどこかで行を隠しているか。OFFのチップの凡例は描いていないので数えない。 */
export function hasVisibleLegendFilter(chips: readonly OverlayLayerChip[], lensHiddenKeys: readonly string[]): boolean {
  if (lensHiddenKeys.length > 0) return true;
  return chips.some(
    (chip) =>
      chip.on && (chip.legendDetails ?? []).some((axis) => axis.axisId !== undefined && axis.hiddenKeys.length > 0),
  );
}

export function serializeLayerVisibility(visibility: MapLayerVisibility): string {
  return JSON.stringify(visibility);
}

/** 保存値のうち、いまのレイヤーカタログにある鍵の真偽値だけを読む。無い鍵は既定のまま
 * ——レイヤーが増えた後の古い保存値から、新しいレイヤーの既定が消えないようにする。 */
export function deserializeLayerVisibility(raw: string): MapLayerVisibility | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const stored = parsed as Record<string, unknown>;
  const visibility = buildDefaultLayerVisibility();
  for (const id of Object.keys(visibility) as MapLayerId[]) {
    const value = stored[id];
    if (typeof value === "boolean") visibility[id] = value;
  }
  return visibility;
}
