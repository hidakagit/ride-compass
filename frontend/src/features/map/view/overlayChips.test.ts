// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  buildDefaultLayerVisibility,
  buildMapLayers,
  TILE_VERSIONS_MISSING_NOTICE,
  TILE_ZOOM_TOO_WIDE_NOTICE,
} from "@/features/map/layers/mapLayers";
import { disasterSourceLegendAxis, roadLegendAxes } from "@/features/map/scene/legends";

import { catalogOf, dedicatedEntry, rampEntry } from "@/lib/mapDisplay/__fixtures__/catalogAxes";
import { deserializeLayerVisibility, overlayChips } from "./overlayChips";

const catalog = catalogOf([rampEntry("ramp_a", [1]), dedicatedEntry("dedicated_b", [1])]);
const LAYERS = buildMapLayers(catalog.rampAxes, catalog.dedicatedAxes);

type Options = Parameters<typeof overlayChips>[0];
function chips(options: Partial<Options> = {}) {
  return overlayChips({
    layers: LAYERS,
    visibility: buildDefaultLayerVisibility(),
    hidden: {},
    screenLegends: {},
    dataStatus: {},
    zoomTooWideLayerIds: [],
    versionMissingLayerIds: [],
    catalogSettled: true,
    hasSelectedRoute: true,
    ...options,
  });
}
const chipOf = (list: ReturnType<typeof chips>, id: string) => list.find((chip) => chip.id === id)!;

describe("overlayChips（地図上チップの状態）", () => {
  it("軸スタジオ由来のレイヤーはチップにしない", () => {
    const ids = chips().map((chip) => chip.id);
    expect(ids).not.toContain("axis:ramp_a");
    expect(ids).not.toContain("dedicated_bAxis");
    expect(ids).toContain("highway");
  });

  it("表示状態をそのまま映し、略名が無ければ正式名で出す", () => {
    const list = chips({ visibility: { ...buildDefaultLayerVisibility(), surface: true } });
    const surface = LAYERS.find((layer) => layer.id === "surface")!;
    const disaster = LAYERS.find((layer) => layer.id === "disaster")!;
    expect(chipOf(list, "surface")).toMatchObject({
      on: true,
      chipLabel: surface.chipLabel,
      title: surface.description,
    });
    const withoutChipLabel = LAYERS.find((layer) => layer.chipLabel === undefined && layer.id !== "route")!;
    expect(chipOf(list, withoutChipLabel.id).chipLabel).toBe(withoutChipLabel.label);
    expect(chipOf(list, disaster.id).chipLabel).toBe(disaster.chipLabel);
  });

  it("ルートにひもづくレイヤーは、候補を選ぶまで押せない", () => {
    expect(chipOf(chips({ hasSelectedRoute: false }), "route").disabled).toBe(true);
    expect(chipOf(chips({ hasSelectedRoute: false }), "highway").disabled).toBe(false);
    expect(chipOf(chips(), "route").disabled).toBe(false);
  });

  it("タイル世代が無いときは、カタログを取り終えていれば失敗・取得中なら読み込み中として出す", () => {
    const settled = chipOf(chips({ versionMissingLayerIds: ["highway"], zoomTooWideLayerIds: ["highway"] }), "highway");
    expect(settled).toMatchObject({ notice: TILE_VERSIONS_MISSING_NOTICE, dataStatus: "error" });

    const waiting = chipOf(
      chips({ versionMissingLayerIds: ["highway"], zoomTooWideLayerIds: ["highway"], catalogSettled: false }),
      "highway",
    );
    expect(waiting).toMatchObject({ notice: TILE_ZOOM_TOO_WIDE_NOTICE, dataStatus: "loading" });
  });

  it("世代があれば、ズーム不足の案内と、地図が報告した取得状態を出す", () => {
    const list = chips({ zoomTooWideLayerIds: ["surface"], dataStatus: { surface: "empty" } });
    expect(chipOf(list, "surface")).toMatchObject({ notice: TILE_ZOOM_TOO_WIDE_NOTICE, dataStatus: "empty" });
    expect(chipOf(list, "highway")).toMatchObject({ notice: null, dataStatus: undefined });
  });

  it("▶パネルの凡例は、絞り込める凡例（隠した行つき）・表示専用の凡例・画面から渡した凡例の順", () => {
    const [road] = roadLegendAxes();
    const [first, second] = road.entries;
    const screenLegend = { label: "画面から", legend: [] };
    const list = chips({
      hidden: { [road.axisId]: [second.key, "gone"] },
      screenLegends: { [road.layerId]: [screenLegend] },
    });
    const details = chipOf(list, road.layerId).legendDetails ?? [];
    expect(details[0]).toMatchObject({ axisId: road.axisId, hiddenKeys: [second.key] });
    expect(details[0].legend[0].key).toBe(first.key);
    expect(details.at(-1)).toEqual({ ...screenLegend, hiddenKeys: [] });

    const precipitation = chipOf(list, "precipitationNowcast").legendDetails ?? [];
    expect(precipitation.length).toBeGreaterThan(0);
    expect(precipitation.every((detail) => detail.axisId === undefined && detail.hiddenKeys.length === 0)).toBe(true);
  });

  it("災害のチップは、要素を選ぶ凡例を先頭に持つ", () => {
    const disaster = disasterSourceLegendAxis();
    const [first] =
      chipOf(chips({ hidden: { [disaster.axisId]: [disaster.entries[0].key] } }), "disaster").legendDetails ?? [];
    expect(first).toMatchObject({ axisId: disaster.axisId, hiddenKeys: [disaster.entries[0].key] });
  });
});

describe("deserializeLayerVisibility（表示状態の保存値）", () => {
  it("いまのカタログにある鍵の真偽値だけを読み、無い鍵は既定のまま", () => {
    const defaults = buildDefaultLayerVisibility();
    const restored = deserializeLayerVisibility(
      JSON.stringify({ surface: true, disaster: false, gone: true, highway: "yes" }),
    );
    expect(restored).toEqual({ ...defaults, surface: true, disaster: false });
  });

  it("読めない形なら既定", () => {
    expect(deserializeLayerVisibility("null")).toEqual(buildDefaultLayerVisibility());
    expect(deserializeLayerVisibility("[]")).toEqual(buildDefaultLayerVisibility());
  });
});
