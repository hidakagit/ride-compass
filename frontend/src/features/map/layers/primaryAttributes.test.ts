// @vitest-environment node
import { describe, expect, it } from "vitest";

import { mapDisplay } from "@/types/generated/mapDisplay";
import { primaryAttributes } from "@/types/generated/primaryAttributes";

import { primaryAttributeIdsToLayerIds } from "./primaryAttributes";

describe("一次属性", () => {
  it("地図のレイヤーを持つ属性だけを、重ねずに並べる（レイヤー名は属性idそのもの）", () => {
    const layerIds: readonly string[] = mapDisplay.layers.map((layer) => layer.id);
    const [layerId] = layerIds;
    const withoutLayer = primaryAttributes.find((attr) => !layerIds.includes(attr.attr_id));
    expect(withoutLayer).toBeDefined();
    expect(primaryAttributeIdsToLayerIds([layerId, withoutLayer!.attr_id, layerId])).toEqual([layerId]);
  });
});
