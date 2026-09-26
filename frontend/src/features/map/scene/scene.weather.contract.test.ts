// @vitest-environment node
/** 動的気象（降水・風・災害）を地図へ伝えたとき、**最後にどうなっているか**。
 *
 * 1つのチップが複数の名前付きソースを持ち、ソースごとに描き方（ラスタ／格子の面／格子のマーク／
 * ベクタ）が宣言されている。中身は時刻の変化で何度も入れ替わる。
 *
 * どのレイヤーが何を描いているかは、idの綴りではなく、**何も伝えなかったときより増えて見えている
 * レイヤー**と、そのソースへ流し込まれたタイルで見る。
 */
import { describe, expect, it } from "vitest";

import { createRecordingMap } from "@/testing/mapTrace/recordingMap";
import { applyScene, sceneInputsFrom } from "@/features/map/scene/applyToMap";
import { sceneState } from "@/features/map/scene/__fixtures__/sceneState";
import { buildMapScene } from "@/features/map/scene/buildScene";
import type { DynamicWeatherGroupState } from "@/features/map/layers/dynamicWeather";

type Handle = ReturnType<typeof createRecordingMap>["handle"];
type Chip = "precipitationNowcast" | "windVector" | "disaster";

const EMPTY_GEOJSON: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function raster(tileUrlTemplate: string) {
  return { visible: true, payload: { kind: "rasterTile" as const, tileUrlTemplate } };
}

function apply(map: unknown, id: Chip, state: DynamicWeatherGroupState) {
  const inputs = sceneInputsFrom(sceneState({ tileVersionsReady: false, look: { dynamicWeather: { [id]: state } } }));
  applyScene(map as never, buildMapScene(inputs));
}

function visibleLayerIds(handle: Handle): string[] {
  return handle.layerOrder().filter((layerId) => handle.layer(layerId)?.visibility === "visible");
}

/** 動的気象を何も伝えなかったときに見えているレイヤー。 */
const BASELINE = (() => {
  const { map, handle } = createRecordingMap();
  apply(map, "precipitationNowcast", {});
  return new Set(visibleLayerIds(handle));
})();

/** 何も伝えなかったときより増えて見えているレイヤー。 */
function shownByWeather(handle: Handle) {
  return visibleLayerIds(handle)
    .filter((layerId) => !BASELINE.has(layerId))
    .map((layerId) => handle.layer(layerId)!);
}

/** ソースが今持っているタイル（作ったときの宣言か、その後に流し込んだもの）。 */
function tilesOf(handle: Handle, sourceId: string): readonly string[] | undefined {
  const poured = handle.sourceContent(sourceId)?.tiles;
  if (poured !== undefined) return poured;
  const added = [...handle.trace].reverse().find((entry) => entry.call === "addSource" && entry.args[0] === sourceId);
  return (added?.args[1] as { tiles?: readonly string[] } | undefined)?.tiles;
}

describe("動的気象を地図へ伝えた結果", () => {
  it("中身が来ていて表示ONなら、その描き方のレイヤーが見えている", () => {
    const { map, handle } = createRecordingMap();

    apply(map, "precipitationNowcast", { main: raster("https://example.test/{z}/{x}/{y}.png") });

    const shown = shownByWeather(handle);
    expect(shown.map((layer) => layer.type)).toEqual(["raster"]);
    expect(tilesOf(handle, shown[0].source!)?.[0]).toContain("example.test/{z}/{x}/{y}.png");
  });

  it("表示ONでも、中身が来ていなければ見えない", () => {
    const { map, handle } = createRecordingMap();

    apply(map, "precipitationNowcast", { main: { visible: true, payload: undefined } });

    expect(shownByWeather(handle)).toEqual([]);
  });

  // 1つのソースが複数の描き方を宣言していても、見えるのは**いま来ている中身の描き方**だけ。
  it("中身の種類に合う描き方だけが見える", () => {
    const { map, handle } = createRecordingMap();

    apply(map, "precipitationNowcast", { main: raster("https://example.test/{z}/{x}/{y}.png") });
    expect(shownByWeather(handle).map((layer) => layer.type)).toEqual(["raster"]);

    apply(map, "precipitationNowcast", {
      main: { visible: true, payload: { kind: "gridFill", geojson: EMPTY_GEOJSON } },
    });
    expect(shownByWeather(handle).map((layer) => layer.type)).toEqual(["fill"]);
  });

  it("同じチップの中でも、ソースごとに出し分けられる", () => {
    const { map, handle } = createRecordingMap();

    apply(map, "disaster", {
      heavyRain: raster("https://example.test/rain/{z}/{x}/{y}.png"),
      landslide: { visible: false, payload: { kind: "rasterTile", tileUrlTemplate: "https://example.test/ls.png" } },
    });

    const shown = shownByWeather(handle);
    expect(shown).toHaveLength(1);
    expect(tilesOf(handle, shown[0].source!)?.[0]).toContain("/rain/");
  });

  // 時刻を動かすと同じ状態が何度も届く。中身が同じなら手を触れない——作り直しても
  // 流し込み直しても、取得済みのタイルを捨てて取り直すことになる。
  it("同じ中身を何度伝えても、ソースへ手を触れない", () => {
    const { map, handle } = createRecordingMap();
    const state = { main: raster("https://example.test/{z}/{x}/{y}.png") };

    apply(map, "precipitationNowcast", state);
    const sourceId = shownByWeather(handle)[0].source;
    apply(map, "precipitationNowcast", state);
    apply(map, "precipitationNowcast", state);

    const touched = handle.trace.filter(
      (entry) => ["addSource", "removeSource", "setTiles"].includes(entry.call) && entry.args[0] === sourceId,
    );
    expect(touched.map((entry) => entry.call)).toEqual(["addSource"]);
  });

  it("中身が変われば流し込み直す", () => {
    const { map, handle } = createRecordingMap();

    apply(map, "precipitationNowcast", { main: raster("https://example.test/a/{z}/{x}/{y}.png") });
    const sourceId = shownByWeather(handle)[0].source!;
    apply(map, "precipitationNowcast", { main: raster("https://example.test/b/{z}/{x}/{y}.png") });

    expect(handle.sourceContent(sourceId)?.tiles?.[0]).toContain("/b/");
  });
});
