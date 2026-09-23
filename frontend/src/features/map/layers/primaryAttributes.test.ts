// @vitest-environment node
import { describe, expect, it } from "vitest";

import { mapDisplay } from "@/types/generated/mapDisplay";
import { primaryAttributes } from "@/types/generated/primaryAttributes";

import { PRIMARY_ATTRIBUTE_LABELS, primaryAttributeIdsToLayerIds } from "./primaryAttributes";

describe("一次属性", () => {
  it("どの一次属性も正式名を引ける", () => {
    expect(primaryAttributes).not.toHaveLength(0);
    for (const attr of primaryAttributes) expect(PRIMARY_ATTRIBUTE_LABELS[attr.attr_id]).toBe(attr.label);
  });

  it("地図のレイヤーを持つ属性だけを、重ねずに並べる（レイヤー名は属性idそのもの）", () => {
    const [layerId] = mapDisplay.layerIds;
    const withoutLayer = primaryAttributes.find(
      (attr) => !(mapDisplay.layerIds as readonly string[]).includes(attr.attr_id),
    );
    expect(withoutLayer).toBeDefined();
    expect(primaryAttributeIdsToLayerIds([layerId, withoutLayer!.attr_id, layerId])).toEqual([layerId]);
  });
});
