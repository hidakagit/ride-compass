// @vitest-environment node
/** グループを畳んだ結果が満たすこと。 */
import { sceneSourceId } from "./sceneBuilders";
import { describe, expect, it } from "vitest";

import { composeScene, declareGroup, type SceneLayerEntry } from "./mapSceneGroups";

type State = { readonly on: boolean };

const ROAD_SOURCE = { id: sceneSourceId("road"), spec: { type: "vector" as const, tiles: [] }, sourceLayer: "r" };

function line(role: string, tier: SceneLayerEntry["tier"], extra: Partial<SceneLayerEntry> = {}): SceneLayerEntry {
  return { role, tier, source: sceneSourceId("road"), type: "line", visible: true, ...extra };
}

const area = declareGroup<State>(() => ({
  sources: [{ id: sceneSourceId("relief"), spec: { type: "raster" }, tiles: ["https://example.test/{z}/{x}/{y}.png"] }],
  layers: [{ role: "relief", tier: "area", source: sceneSourceId("relief"), type: "raster", visible: true }],
}));

const roadLines = declareGroup<State>((state) => ({
  sources: [{ ...ROAD_SOURCE, featureStates: new Map([["surface", new Map([["w1", 1]])]]) }],
  layers: [line("surface", "observedLine", { visible: state.on })],
}));

const axes = declareGroup<State>(() => ({
  sources: [{ ...ROAD_SOURCE, featureStates: new Map([["windValue", new Map([["w1", 3]])]]) }],
  layers: [line("wind", "lensLine")],
}));

describe("composeScene", () => {
  it("重なりは段だけで決まり、グループを並べる順に依存しない", () => {
    const forward = composeScene([area, roadLines, axes], { on: true });
    const reversed = composeScene([axes, roadLines, area], { on: true });

    const ids = (scene: typeof forward) => scene.layers.map((layer) => layer.spec.id);
    expect(ids(forward)).toEqual(ids(reversed));
  });

  it("同じソースを2つのグループが名乗っても、ソースは1本になる", () => {
    const scene = composeScene([roadLines, axes], { on: true });

    expect(scene.sources.filter((source) => source.id === "road")).toHaveLength(1);
  });

  it("同じソースへ載せた feature-state は、両方とも残る", () => {
    const scene = composeScene([roadLines, axes], { on: true });

    const road = scene.sources.find((source) => source.id === "road");
    expect([...(road?.featureStates?.keys() ?? [])].sort()).toEqual(["surface", "windValue"]);
  });
});
