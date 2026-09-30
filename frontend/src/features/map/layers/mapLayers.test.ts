// @vitest-environment node
import { describe, expect, it } from "vitest";

import { mapCatalogOf } from "@/testing/mapAxisCatalog";
import { catalogEntry, dedicatedEntry, rampEntry } from "@/testing/catalogAxes";
import { pointLegendAxes } from "@/features/map/scene/legends";
import { mapDisplay } from "@/types/generated/mapDisplay";

import regionTileConfig from "@/types/generated/region-tile-config.json";
import weatherScales from "@/types/generated/weather-scales.json";

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

const catalog = mapCatalogOf([
  rampEntry("ramp_a", [10, 20], { raw_value_unit: "%", chip_label: "勾配" }),
  dedicatedEntry("dedicated_b", [1, 2]),
]);
const withAxes = buildMapLayers({ ...catalog, accidentYears: [2021, 2019, 2020] });
const withoutAxes = buildMapLayers(mapCatalogOf([]));
const withYears = (accidentYears: number[]) => buildMapLayers({ ...mapCatalogOf([]), accidentYears });
const layer = (layers: readonly MapLayerDescriptor[], id: string) => layers.find((entry) => entry.id === id)!;
const staticLayerIds: readonly string[] = mapDisplay.layers.map((entry) => entry.id);

describe("buildMapLayers（レイヤーの一覧）", () => {
  it("源泉が地図に載せると宣言したものは、どれも1つずつ記述子を持つ", () => {
    expect(withoutAxes.map((entry) => entry.id).sort()).toEqual([...staticLayerIds].sort());
  });

  it("軸を渡すと、ramp軸と専用配信軸のレイヤーが軸ごとに別の名前で加わる（どちらも軸スタジオ由来）", () => {
    const added = withAxes.filter((entry) => !staticLayerIds.includes(entry.id));
    expect(added.map((entry) => [entry.id, isAxisStudioLayer(entry)])).toEqual([
      ["axis:ramp_a", true],
      ["dedicated_bAxis", true],
    ]);
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
    expect(layer(withYears([2018, 2020]), "accident_point").description).toContain("[2018・2020年]");
    expect(layer(withYears([2020]), "accident_point").description).toContain("[2020年]");
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

  it("説明は、そのレイヤーの元データを材料に持つ公開中の評価を名前で挙げ、無ければ評価に触れない", () => {
    const axes = buildMapLayers(
      mapCatalogOf([
        catalogEntry({ axis_id: "night", label: "暗さ", primary_attribute_ids: ["lit", "tunnel"] }),
        catalogEntry({ axis_id: "stops", label: "止まりやすさ", primary_attribute_ids: ["stop_poi"] }),
        catalogEntry({ axis_id: "wind", label: "向かい風", weather_layer_groups: ["windVector"] }),
      ]),
    );
    expect(layer(axes, "tunnel").panelHint).toContain("評価「暗さ」");
    expect(layer(axes, "stop_poi").panelHint).toContain("評価「止まりやすさ」");
    expect(layer(axes, "windVector").panelHint).toContain("評価「向かい風」");
    for (const id of ["tunnel", "stop_poi", "windVector"]) {
      expect(layer(withoutAxes, id).panelHint).not.toContain("評価");
    }
  });

  it("ルートの説明は、レンズで選べる色分け（公開中の評価と総合難易度）を並べる", () => {
    const axes = buildMapLayers(
      mapCatalogOf([catalogEntry({ axis_id: "a", label: "坂" }), catalogEntry({ axis_id: "b", label: "風" })]),
    );
    expect(layer(axes, "route").description).toContain("[坂・風・総合難易度]");
    expect(layer(withoutAxes, "route").description).toContain("[総合難易度]");
  });

  it("土地被覆の凡例は、地図に塗るクラスだけを並べる", () => {
    const [block] = layer(withoutAxes, "landcover").readOnlyLegend ?? [];
    expect(block.legend.map((entry) => entry.label)).toEqual(LANDCOVER_PAINTED_CLASSES.map((cls) => cls.label));
  });

  it("土地被覆の説明は、塗らない分類と、評価が土地被覆を数える帯の幅を源泉から出す", () => {
    const landcover = layer(withoutAxes, "landcover");
    const unpainted = LANDCOVER_CLASSES.filter((entry) => !entry.painted);
    expect(unpainted.length).toBeGreaterThan(0);
    for (const cls of unpainted) {
      expect(landcover.description).toContain(cls.label);
      expect(landcover.panelHint).toContain(`${cls.label}は塗りません`);
    }
    expect(landcover.panelHint).toContain(`周囲${regionTileConfig.landcover.ring_outer_m}m`);
  });

  it("災害の説明は、源泉が災害のチップに宣言した要素の名前を全部挙げる", () => {
    const disaster = layer(withoutAxes, "disaster");
    const elements = mapDisplay.weatherElements.filter((element) => element.group === "disaster");
    expect(elements.length).toBeGreaterThan(0);
    for (const element of elements) {
      expect(disaster.description).toContain(element.label);
      expect(disaster.panelHint).toContain(element.label);
    }
  });

  it("災害の凡例は、要素が塗る段ごとに1つ並び、見出しにその段で塗る要素の名前が入る", () => {
    const blocks = layer(withoutAxes, "disaster").readOnlyLegend ?? [];
    const scaled = mapDisplay.weatherElements.filter((element) => element.group === "disaster" && element.levelScale);
    expect(scaled.length).toBeGreaterThan(0);
    expect(blocks).toHaveLength(new Set(scaled.map((element) => element.levelScale)).size);
    for (const element of scaled) {
      const keys = weatherScales[element.levelScale!].map((level) => level.key);
      const block = blocks.find((candidate) => candidate.legend.map((entry) => entry.key).join() === keys.join());
      expect(block?.label).toContain(element.label);
    }
  });
});

describe("地図上チップのグループ", () => {
  it("種別を持たないもの（ルート）はどのグループにも入れない", () => {
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
  it("チップで切り替えられるレイヤーだけがキーを持つ（軸スタジオ由来は持たない）", () => {
    expect(Object.keys(buildDefaultLayerVisibility()).sort()).toEqual([...staticLayerIds].sort());
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
