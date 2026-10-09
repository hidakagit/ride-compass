// @vitest-environment node
import { describe, expect, it } from "vitest";

import { mapCatalogOf } from "@/testing/mapAxisCatalog";
import { catalogEntry, dedicatedEntry, rampEntry } from "@/testing/catalogAxes";
import { mapDisplay } from "@/types/generated/mapDisplay";

import weatherScales from "@/types/generated/weather-scales.json";

import { LANDCOVER_PAINTED_CLASSES } from "./landcoverClasses";
import {
  buildMapLayers,
  deriveFetchLayerStatus,
  isAxisStudioLayer,
  LAYER_DATA_STATUS_LABELS,
  layerDataStatusNotice,
  mapOverlayGroupFor,
  tileVersionGatedLayerIds,
  tileZoomTooWideLayerIds,
  type ChipLayerDescriptor,
  type MapLayerDescriptor,
} from "./mapLayers";

const catalog = mapCatalogOf([rampEntry("ramp_a", [10, 20]), dedicatedEntry("dedicated_b", [1, 2])]);
const withAxes = buildMapLayers({ ...catalog, accidentYears: [2021, 2019, 2020] });
const withoutAxes = buildMapLayers(mapCatalogOf([]));
const withYears = (accidentYears: number[]) => buildMapLayers({ ...mapCatalogOf([]), accidentYears });
const layer = (layers: readonly MapLayerDescriptor[], id: string) =>
  layers.find((entry): entry is ChipLayerDescriptor => entry.id === id && !isAxisStudioLayer(entry))!;
const staticLayerIds: readonly string[] = mapDisplay.layers.map((entry) => entry.id);

describe("buildMapLayers（レイヤーの一覧）", () => {
  it("軸を渡すと、ramp軸と専用配信軸のレイヤーが軸ごとに別の名前で加わる（どちらも軸スタジオ由来）", () => {
    const added = withAxes.filter((entry) => !staticLayerIds.includes(entry.id));
    expect(added.map((entry) => [entry.id, isAxisStudioLayer(entry)])).toEqual([
      ["axis:ramp_a", true],
      ["dedicated_bAxis", true],
    ]);
  });

  it("事故の説明は収録年を、連続していれば範囲で言う（年が届くまでは触れない）", () => {
    expect(layer(withAxes, "accident_point").description).toContain("[2019〜2021年]");
    expect(layer(withYears([2018, 2020]), "accident_point").description).toContain("[2018・2020年]");
    expect(layer(withYears([2020]), "accident_point").description).toContain("[2020年]");
    expect(layer(withoutAxes, "accident_point").description).not.toContain("[");
  });

  it("説明は、そのレイヤーの元データを材料に持つ公開中の評価軸を名前で挙げ、無ければ評価軸に触れない", () => {
    const axes = buildMapLayers(
      mapCatalogOf([
        catalogEntry({ axis_id: "night", label: "暗さ", primary_attribute_ids: ["lit", "tunnel"] }),
        catalogEntry({ axis_id: "stops", label: "止まりやすさ", primary_attribute_ids: ["stop_poi"] }),
        catalogEntry({ axis_id: "wind", label: "向かい風", weather_layer_groups: ["windVector"] }),
      ]),
    );
    expect(layer(axes, "tunnel").panelHint).toContain("評価軸「暗さ」");
    expect(layer(axes, "stop_poi").panelHint).toContain("評価軸「止まりやすさ」");
    expect(layer(axes, "windVector").panelHint).toContain("評価軸「向かい風」");
    for (const id of ["tunnel", "stop_poi", "windVector"]) {
      expect(layer(withoutAxes, id).panelHint).not.toContain("評価");
    }
  });

  it("ルートの説明は、レンズで選べる色分け（公開中の評価と総合難易度）を並べる", () => {
    const axes = buildMapLayers(
      mapCatalogOf([catalogEntry({ axis_id: "a", label: "坂" }), catalogEntry({ axis_id: "b", label: "風" })]),
    );
    expect(layer(axes, "route").description).toContain("[坂・風・総合難易度]");
  });

  it("土地被覆の凡例は、地図に塗るクラスだけを並べる", () => {
    const [block] = layer(withoutAxes, "landcover").readOnlyLegend ?? [];
    expect(block.legend.map((entry) => entry.label)).toEqual(LANDCOVER_PAINTED_CLASSES.map((cls) => cls.label));
  });

  it("土地被覆の凡例の行は、どれも（i）から開く説明を持つ", () => {
    const [block] = layer(withoutAxes, "landcover").readOnlyLegend ?? [];
    for (const entry of block.legend) expect(entry.description?.trim()).toBeTruthy();
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
  it("タイル世代が届くまで描けないのは、世代を持つ配信を読むレイヤー（ramp軸を含む）", () => {
    const gated = tileVersionGatedLayerIds(catalog.rampAxes);
    expect(gated).toContain("axis:ramp_a");
    expect(gated).not.toContain("elevation");
  });

  it("タイルの最小ズーム未満のレイヤーだけを、ズーム不足として出す", () => {
    const tileLayers = withoutAxes.filter((entry) => entry.tileMinZoom !== undefined);
    expect(tileLayers).not.toHaveLength(0);
    const lowest = Math.min(...tileLayers.map((entry) => entry.tileMinZoom!));
    expect(tileZoomTooWideLayerIds(lowest)).toEqual(
      tileLayers.filter((entry) => entry.tileMinZoom! > lowest).map((entry) => entry.id),
    );
    expect(tileZoomTooWideLayerIds(lowest - 0.1)).toEqual(tileLayers.map((entry) => entry.id));
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

describe("layerDataStatusNotice（取得状態を開いた先で読ませる文）", () => {
  it.each([
    [undefined, null],
    ["loading", null],
    ["error", LAYER_DATA_STATUS_LABELS.error],
  ] as const)("状態が%sなら%sを出す（読み込み中は絞り込みのたびに揺れるので出さない）", (status, notice) => {
    expect(layerDataStatusNotice(status)).toBe(notice);
  });
});
