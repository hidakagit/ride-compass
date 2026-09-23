// @vitest-environment node
import { describe, expect, it } from "vitest";

import { catalogOf, dedicatedEntry, rampEntry } from "@/features/map/view/__fixtures__/catalog";
import { pointLegendAxes } from "@/features/map/scene/legends";
import { mapDisplay } from "@/types/generated/mapDisplay";

import { LANDCOVER_CLASSES, LANDCOVER_PAINTED_CLASSES } from "./landcoverClasses";
import {
  buildDefaultLayerVisibility,
  buildMapLayers,
  deriveFetchLayerStatus,
  isAxisStudioLayer,
  mapOverlayGroupFor,
  tileVersionGatedLayerIds,
  tileZoomTooWideLayerIds,
  type MapLayerDescriptor,
} from "./mapLayers";

const catalog = catalogOf([
  rampEntry("ramp_a", [10, 20], { raw_value_unit: "%", chip_label: "勾配" }),
  dedicatedEntry("dedicated_b", [1, 2]),
]);
const withAxes = buildMapLayers(catalog.rampAxes, catalog.dedicatedAxes, [2021, 2019, 2020]);
const withoutAxes = buildMapLayers([], []);
const layer = (layers: readonly MapLayerDescriptor[], id: string) => layers.find((entry) => entry.id === id)!;

describe("buildMapLayers（レイヤーの一覧）", () => {
  it("源泉が地図に載せると宣言したものは、どれも1つずつ記述子を持つ", () => {
    expect(withoutAxes.map((entry) => entry.id).sort()).toEqual([...mapDisplay.layerIds].sort());
  });

  it("軸を渡すと、ramp軸と専用配信軸のレイヤーが軸ごとに別の名前で加わる（どちらも軸スタジオ由来）", () => {
    const added = withAxes.filter((entry) => !(mapDisplay.layerIds as readonly string[]).includes(entry.id));
    expect(added.map((entry) => entry.id)).toEqual(["axis:ramp_a", "dedicated_bAxis"]);
    expect(added.every(isAxisStudioLayer)).toBe(true);
    expect(new Set(withAxes.map((entry) => entry.id)).size).toBe(withAxes.length);
  });

  it("ramp軸のレイヤーは軸の名前・略名・単位と、軸が属する種別を使う", () => {
    expect(layer(withAxes, "axis:ramp_a")).toMatchObject({
      label: "ramp_a",
      chipLabel: "勾配",
      category: "roadCondition",
      description: expect.stringContaining("ramp_a[%]"),
    });
  });

  it("事故の説明は収録年を、連続していれば範囲で言う（年が届くまでは触れない）", () => {
    expect(layer(withAxes, "accident_point").description).toContain("[2019〜2021年]");
    expect(layer(buildMapLayers([], [], [2018, 2020]), "accident_point").description).toContain("[2018・2020年]");
    expect(layer(buildMapLayers([], [], [2020]), "accident_point").description).toContain("[2020年]");
    expect(layer(withoutAxes, "accident_point").description).not.toContain("[");
  });

  it("停止要因・補給休憩の説明は、凡例と同じ種別名を並べる（受け皿の種別は除く）", () => {
    const pointAxes = pointLegendAxes().filter((axis) => axis.layerId === "stop_poi" || axis.layerId === "supply_poi");
    expect(pointAxes).toHaveLength(2);
    for (const axis of pointAxes) {
      const description = layer(withoutAxes, axis.layerId).description;
      for (const entry of axis.entries) {
        if (entry.isFallback) expect(description).not.toContain(entry.label);
        else expect(description).toContain(entry.label);
      }
    }
  });

  it("土地被覆の凡例は、地図に塗るクラスだけを並べる", () => {
    expect(LANDCOVER_PAINTED_CLASSES.length).toBeLessThan(LANDCOVER_CLASSES.length);
    const [block] = layer(withoutAxes, "landcover").readOnlyLegend ?? [];
    expect(block.legend.map((entry) => entry.label)).toEqual(LANDCOVER_PAINTED_CLASSES.map((cls) => cls.label));
  });
});

describe("地図上チップのグループ", () => {
  it("種別が属するグループへ入れ、軸スタジオ由来・種別を持たないもの（ルート）はどこにも入れない", () => {
    for (const category of mapDisplay.layerCategories) {
      expect(mapOverlayGroupFor({ id: "highway", category: category.key })).toBe(category.group);
    }
    expect(mapOverlayGroupFor(layer(withAxes, "axis:ramp_a"))).toBeUndefined();
    expect(mapOverlayGroupFor(layer(withAxes, "dedicated_bAxis"))).toBeUndefined();
    expect(mapOverlayGroupFor(layer(withoutAxes, "route"))).toBeUndefined();
  });
});

describe("出せない理由の案内", () => {
  it("タイル世代が届くまで描けないのは、世代を持つ配信（路面・点・事故のタイル）を読むレイヤー（ramp軸を含む）", () => {
    const gated = tileVersionGatedLayerIds(catalog.rampAxes);
    expect(gated).toContain("axis:ramp_a");
    expect(gated).toContain("highway");
    expect(gated).toContain("accident_point");
    expect(gated).not.toContain("elevation");
    expect(gated).not.toContain("precipitationNowcast");
  });

  it("タイルの最小ズーム未満のレイヤーだけを、ズーム不足として出す", () => {
    const tileLayers = withoutAxes.filter((entry) => entry.tileMinZoom !== undefined);
    expect(tileLayers).not.toHaveLength(0);
    const lowest = Math.min(...tileLayers.map((entry) => entry.tileMinZoom!));
    expect(tileZoomTooWideLayerIds(lowest)).toEqual(
      tileLayers.filter((entry) => entry.tileMinZoom! > lowest).map((entry) => entry.id),
    );
    expect(tileZoomTooWideLayerIds(lowest - 0.1)).toEqual(tileLayers.map((entry) => entry.id));
    expect(tileZoomTooWideLayerIds(22)).toEqual([]);
  });
});

describe("buildDefaultLayerVisibility（表示の既定値）", () => {
  it("チップで切り替えられるレイヤーだけがキーを持ち、既定表示を宣言したものだけがON", () => {
    const visibility = buildDefaultLayerVisibility();
    expect(Object.keys(visibility).sort()).toEqual([...mapDisplay.layerIds].sort());
    for (const entry of withoutAxes) expect(visibility[entry.id]).toBe(entry.defaultOn === true);
  });
});

describe("deriveFetchLayerStatus（自前で取るレイヤーの取得状態）", () => {
  it("失敗 > 読み込み中 > 取り終えて値なし の順に1つ決め、まだ取りに行っていない間と値がある間は何も出さない", () => {
    expect(deriveFetchLayerStatus(true, "失敗", false, true)).toBe("error");
    expect(deriveFetchLayerStatus(true, null, false, false)).toBe("loading");
    expect(deriveFetchLayerStatus(false, null, false, true)).toBe("empty");
    expect(deriveFetchLayerStatus(false, null, false, false)).toBeUndefined();
    expect(deriveFetchLayerStatus(false, null, true, true)).toBeUndefined();
  });
});
