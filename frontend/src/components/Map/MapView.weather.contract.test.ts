// @vitest-environment node
/** 動的気象（降水・風・災害）を地図へ伝えたとき、**最後にどうなっているか**。
 *
 * 筋書きは[遷移表](../../../../docs/records/tasks/T1001.md)から取っている。1つのチップが
 * 複数の名前付きソースを持ち、ソースごとに描き方（ラスタ／格子の面／格子のマーク／
 * ベクタ）が宣言されている。中身は時刻の変化で何度も入れ替わる。
 */
import { describe, expect, it } from "vitest";

import { createRecordingMap } from "@/testing/mapTrace/recordingMap";
import { applyScene, sceneInputsFrom } from "@/features/map/scene/applyToMap";
import { buildMapScene } from "@/features/map/scene/buildScene";
import { weatherSourceId, type WeatherRenderKind } from "@/features/map/scene/groups/weather";
import { sceneLayerId } from "@/features/map/scene/sceneBuilders";
import type { DynamicWeatherGroupState } from "@/components/Map/dynamicWeather";

/** **綴りを組み立て直さない**——`sceneLayerId`と`weatherSourceId`からしか作らない。 */
function dynamicWeatherIds(group: string, source: string, kind: WeatherRenderKind) {
  const sourceId = weatherSourceId({ group, source, kind });
  return { sourceId, layerId: sceneLayerId(sourceId, kind) };
}

/** 何も出していない状態。気象だけを差し替える。 */
function baseState() {
  return {
    routes: [],
    selectedRouteId: null,
    routeLayerOn: false,
    routeStyleModes: [],
    routeStyleModeId: "none",
    hiddenRouteLegendKeys: [],
    spliceStretches: [],
    splicedRoute: null,
    staticLayerVisibility: {},
    dynamicWeather: {},
    dedicatedWayValueVisibility: {},
    axisVisibility: {},
    roadHiddenKeysByMode: {},
    staticLegendHiddenKeysByAxis: {},
    experimentSlots: [],
    dedicatedWayValues: new Map(),
    rampAxes: [],
    dedicatedAxes: [],
    secondaryAxisCasingLayerIds: [],
    tileVersionsReady: false,
    inspectedWayId: null,
  };
}

const EMPTY_GEOJSON: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function raster(tileUrlTemplate: string) {
  return { visible: true, payload: { kind: "rasterTile" as const, tileUrlTemplate } };
}

function apply(map: unknown, id: "precipitationNowcast" | "windVector" | "disaster", state: DynamicWeatherGroupState) {
  const inputs = sceneInputsFrom({ ...baseState(), dynamicWeather: { [id]: state } } as never);
  applyScene(map as never, buildMapScene(inputs));
}

describe("動的気象を地図へ伝えた結果", () => {
  it("中身が来ていて表示ONなら、その描き方のレイヤーが見えている", () => {
    const { map, handle } = createRecordingMap();

    apply(map, "precipitationNowcast", { main: raster("https://example.test/{z}/{x}/{y}.png") });

    const { layerId } = dynamicWeatherIds("precipitationNowcast", "main", "rasterTile");
    expect(handle.layer(layerId)?.visibility).toBe("visible");
  });

  it("表示ONでも、中身が来ていなければ見えない", () => {
    const { map, handle } = createRecordingMap();

    apply(map, "precipitationNowcast", { main: { visible: true, payload: undefined } });

    const { layerId } = dynamicWeatherIds("precipitationNowcast", "main", "rasterTile");
    expect(handle.layer(layerId)?.visibility).toBe("none");
  });

  // 1つのソースが複数の描き方を宣言していても、見えるのは**いま来ている中身の描き方**だけ。
  it("中身の種類に合う描き方だけが見える", () => {
    const { map, handle } = createRecordingMap();
    const rasterLayer = dynamicWeatherIds("precipitationNowcast", "main", "rasterTile").layerId;
    const fillLayer = dynamicWeatherIds("precipitationNowcast", "main", "gridFill").layerId;

    apply(map, "precipitationNowcast", { main: raster("https://example.test/{z}/{x}/{y}.png") });
    expect(handle.layer(rasterLayer)?.visibility).toBe("visible");
    expect(handle.layer(fillLayer)?.visibility).toBe("none");

    apply(map, "precipitationNowcast", {
      main: { visible: true, payload: { kind: "gridFill", geojson: EMPTY_GEOJSON } },
    });
    expect(handle.layer(rasterLayer)?.visibility).toBe("none");
    expect(handle.layer(fillLayer)?.visibility).toBe("visible");
  });

  it("同じチップの中でも、ソースごとに出し分けられる", () => {
    const { map, handle } = createRecordingMap();

    apply(map, "disaster", {
      heavyRain: raster("https://example.test/rain/{z}/{x}/{y}.png"),
      landslide: { visible: false, payload: { kind: "rasterTile", tileUrlTemplate: "https://example.test/ls.png" } },
    });

    expect(handle.layer(dynamicWeatherIds("disaster", "heavyRain", "rasterTile").layerId)?.visibility).toBe("visible");
    expect(handle.layer(dynamicWeatherIds("disaster", "landslide", "rasterTile").layerId)?.visibility).toBe("none");
  });

  // 時刻を動かすと同じ状態が何度も届く。中身が同じなら手を触れない——作り直しても
  // 流し込み直しても、取得済みのタイルを捨てて取り直すことになる。
  it("同じ中身を何度伝えても、ソースへ手を触れない", () => {
    const { map, handle } = createRecordingMap();
    const state = { main: raster("https://example.test/{z}/{x}/{y}.png") };

    apply(map, "precipitationNowcast", state);
    apply(map, "precipitationNowcast", state);
    apply(map, "precipitationNowcast", state);

    const { sourceId } = dynamicWeatherIds("precipitationNowcast", "main", "rasterTile");
    const touched = handle.trace.filter(
      (entry) => ["addSource", "removeSource", "setTiles"].includes(entry.call) && entry.args[0] === sourceId,
    );
    expect(touched.map((entry) => entry.call)).toEqual(["addSource"]);
  });

  it("中身が変われば流し込み直す", () => {
    const { map, handle } = createRecordingMap();
    const { sourceId } = dynamicWeatherIds("precipitationNowcast", "main", "rasterTile");

    apply(map, "precipitationNowcast", { main: raster("https://example.test/a/{z}/{x}/{y}.png") });
    apply(map, "precipitationNowcast", { main: raster("https://example.test/b/{z}/{x}/{y}.png") });

    expect(handle.sourceContent(sourceId)?.tiles?.[0]).toContain("/b/");
  });
});
