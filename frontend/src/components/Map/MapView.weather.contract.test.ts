// @vitest-environment node
/** 動的気象（降水・風・災害）を地図へ伝えたとき、**最後にどうなっているか**。
 *
 * 筋書きは[遷移表](../../../../docs/records/tasks/T1001.md)から取っている。1つのチップが
 * 複数の名前付きソースを持ち、ソースごとに描き方（ラスタ／格子の面／格子のマーク／
 * ベクタ）が宣言されている。中身は時刻の変化で何度も入れ替わる。
 */
import { describe, expect, it } from "vitest";

import { createRecordingMap } from "@/testing/mapTrace/recordingMap";
import { DYNAMIC_WEATHER_RENDERERS, applyDynamicWeatherState, dynamicWeatherIds } from "@/components/Map/MapView";
import type { DynamicWeatherGroupState } from "@/components/Map/dynamicWeather";

const EMPTY_GEOJSON: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function raster(tileUrlTemplate: string) {
  return { visible: true, payload: { kind: "rasterTile" as const, tileUrlTemplate } };
}

function apply(map: unknown, id: "precipitationNowcast" | "windVector" | "disaster", state: DynamicWeatherGroupState) {
  applyDynamicWeatherState(map as never, id, DYNAMIC_WEATHER_RENDERERS[id], state);
}

describe("動的気象を地図へ伝えた結果", () => {
  it("中身が来ていて表示ONなら、その描き方のレイヤーが見えている", () => {
    const { map, handle } = createRecordingMap();

    apply(map, "precipitationNowcast", { main: raster("https://example.test/{z}/{x}/{y}.png") });

    const { layerId } = dynamicWeatherIds("precipitationNowcast", "main", "raster");
    expect(handle.layer(layerId)?.visibility).toBe("visible");
  });

  it("表示ONでも、中身が来ていなければ見えない", () => {
    const { map, handle } = createRecordingMap();

    apply(map, "precipitationNowcast", { main: { visible: true, payload: undefined } });

    const { layerId } = dynamicWeatherIds("precipitationNowcast", "main", "raster");
    expect(handle.layer(layerId)?.visibility).toBe("none");
  });

  // 1つのソースが複数の描き方を宣言していても、見えるのは**いま来ている中身の描き方**だけ。
  it("中身の種類に合う描き方だけが見える", () => {
    const { map, handle } = createRecordingMap();
    const rasterLayer = dynamicWeatherIds("precipitationNowcast", "main", "raster").layerId;
    const fillLayer = dynamicWeatherIds("precipitationNowcast", "main", "fill").layerId;

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

    expect(handle.layer(dynamicWeatherIds("disaster", "heavyRain", "raster").layerId)?.visibility).toBe("visible");
    expect(handle.layer(dynamicWeatherIds("disaster", "landslide", "raster").layerId)?.visibility).toBe("none");
  });

  // 時刻を動かすと同じ状態が何度も届く。中身が同じなら流し込み直さない——流し込み直すと、
  // 取得済みのタイルを捨てて取り直すことになる。
  it("同じ中身を何度伝えても、流し込みは1回だけ", () => {
    const { map, handle } = createRecordingMap();
    const state = { main: raster("https://example.test/{z}/{x}/{y}.png") };

    apply(map, "precipitationNowcast", state);
    apply(map, "precipitationNowcast", state);
    apply(map, "precipitationNowcast", state);

    const { sourceId } = dynamicWeatherIds("precipitationNowcast", "main", "raster");
    expect(handle.trace.filter((entry) => entry.call === "setTiles" && entry.args[0] === sourceId)).toHaveLength(1);
  });

  it("中身が変われば流し込み直す", () => {
    const { map, handle } = createRecordingMap();
    const { sourceId } = dynamicWeatherIds("precipitationNowcast", "main", "raster");

    apply(map, "precipitationNowcast", { main: raster("https://example.test/a/{z}/{x}/{y}.png") });
    apply(map, "precipitationNowcast", { main: raster("https://example.test/b/{z}/{x}/{y}.png") });

    expect(handle.sourceContent(sourceId)?.tiles?.[0]).toContain("/b/");
  });
});
