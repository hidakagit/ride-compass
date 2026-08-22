// @vitest-environment node
// 一次属性カタログ・双方向導出（改善計画T164）の純ロジック検証。DOM不要のためnode環境で
// 実行する（vitest.config.mtsのコメント参照）。

import { describe, expect, it } from "vitest";

import {
  PRIMARY_ATTRIBUTES,
  PRIMARY_ATTRIBUTE_CHIP_LABELS,
  PRIMARY_ATTRIBUTE_LABELS,
  PRIMARY_ATTRIBUTE_LAYER_IDS,
  PRIMARY_ATTRIBUTES_WITHOUT_LAYER,
  attrConsumers,
  axisMaterialLayerIds,
  axisMaterials,
} from "./primaryAttributes";

describe("primaryAttributes", () => {
  it("カタログの全一次属性が略名カタログ（4文字以下）に存在する", () => {
    for (const attr of PRIMARY_ATTRIBUTES) {
      const chipLabel = PRIMARY_ATTRIBUTE_CHIP_LABELS[attr.attrId];
      expect(chipLabel, `${attr.attrId}の略名が無い`).toBeTruthy();
      expect(chipLabel.length).toBeLessThanOrEqual(4);
    }
  });

  it("略名は一意である", () => {
    const labels = Object.values(PRIMARY_ATTRIBUTE_CHIP_LABELS);
    expect(new Set(labels).size).toBe(labels.length);
  });

  // ドリフト検知: 全一次属性が「表示レイヤーを持つ」か「意図的にレイヤー無しと明示」の
  // どちらかであること。両方に無い（対応表への追加漏れ）を防ぐ。
  it("カタログの全一次属性が表示レイヤーを持つか、レイヤー無しと明示されている", () => {
    for (const attr of PRIMARY_ATTRIBUTES) {
      const hasLayer = PRIMARY_ATTRIBUTE_LAYER_IDS[attr.attrId] !== undefined;
      const isExplicitlyExcluded = PRIMARY_ATTRIBUTES_WITHOUT_LAYER.has(attr.attrId);
      expect(hasLayer || isExplicitlyExcluded, `${attr.attrId}がどちらの対応表にも無い`).toBe(true);
      // 両方に同時に該当するのは矛盾（レイヤーがあるのに「無し」とも明示している）
      expect(hasLayer && isExplicitlyExcluded).toBe(false);
    }
  });

  it("正式名はaxis-catalog.jsonのprimary_attributes[].labelをそのまま反映する", () => {
    expect(PRIMARY_ATTRIBUTE_LABELS.highway).toBe("道路の種類");
    expect(PRIMARY_ATTRIBUTE_LABELS.accident_point).toBe("事故地点");
    expect(PRIMARY_ATTRIBUTE_LABELS.elevation).toBe("標高");
  });

  it("axisMaterialsは軸の材料一次属性をそのまま返す（car_stressはT163でmotor_vehicle_accessを含む）", () => {
    expect(axisMaterials("car_stress")).toEqual([
      "highway",
      "lanes",
      "maxspeed",
      "cycleway",
      "designation",
      "motor_vehicle_access",
    ]);
    expect(axisMaterials("accident")).toEqual(["accident_point"]);
    expect(axisMaterials("stop_density")).toEqual(["stop_poi", "intersection"]);
  });

  it("axisMaterialsは未知の軸idに対して空配列を返す", () => {
    expect(axisMaterials("no_such_axis")).toEqual([]);
  });

  it("attrConsumersは1次属性を参照する2次軸を返す（排他制約により通常0〜1件）", () => {
    expect(attrConsumers("motor_vehicle_access")).toEqual(["car_stress"]);
    expect(attrConsumers("stop_poi")).toEqual(["stop_density"]);
    expect(attrConsumers("accident_point")).toEqual(["accident"]);
    // supply_poiはどの軸からも参照されない一次属性（registry_defaults.py参照）
    expect(attrConsumers("supply_poi")).toEqual([]);
  });

  it("axisMaterialLayerIdsはレイヤーを持つ材料だけを重複無しで返す", () => {
    // car_stressの材料6件のうちレイヤーを持つのはcycleway/designation/highway
    // （lanes/maxspeed/motor_vehicle_accessはレイヤー無し）
    const layerIds = axisMaterialLayerIds("car_stress");
    expect(new Set(layerIds)).toEqual(new Set(["roadType", "bicycleInfra", "designation"]));
    expect(layerIds.length).toBe(new Set(layerIds).size); // 重複が無い
  });

  it("axisMaterialLayerIdsは一部の材料だけレイヤーを持つ軸に対してその分だけを返す", () => {
    // night軸の材料はlit/tunnelの2件。tunnelはレイヤーを持つが、litは引き続きレイヤー無し
    expect(axisMaterialLayerIds("night")).toEqual(["tunnel"]);
  });
});
