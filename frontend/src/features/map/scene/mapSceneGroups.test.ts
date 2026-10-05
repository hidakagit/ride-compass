// @vitest-environment node
/** グループを畳んだ結果が満たすこと。 */
import { sceneSourceId } from "./sceneBuilders";
import { describe, expect, it } from "vitest";

import { composeScene, declareGroup } from "./mapSceneGroups";

const ROAD_SOURCE = { id: sceneSourceId("road"), spec: { type: "vector" as const, tiles: [] }, sourceLayer: "r" };

const roadLines = declareGroup(() => ({
  sources: [{ ...ROAD_SOURCE, featureStates: new Map([["surface", new Map([["w1", 1]])]]) }],
  layers: [],
}));

const axes = declareGroup(() => ({
  sources: [{ ...ROAD_SOURCE, featureStates: new Map([["windValue", new Map([["w1", 3]])]]) }],
  layers: [],
}));

describe("composeScene", () => {
  it("同じソースへ載せた feature-state は、両方とも残る", () => {
    const scene = composeScene([roadLines, axes], undefined);

    const road = scene.sources.find((source) => source.id === "road");
    expect([...(road?.featureStates?.keys() ?? [])].sort()).toEqual(["surface", "windValue"]);
  });
});
