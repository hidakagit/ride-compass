// @vitest-environment node
// 一次属性カタログ・双方向導出（改善計画T164）の純ロジック検証。DOM不要のためnode環境で
// 実行する（vitest.config.mtsのコメント参照）。

import { describe, expect, it } from "vitest";

import { PRIMARY_ATTRIBUTE_LABELS, primaryAttributeIdsToLayerIds } from "./primaryAttributes";

describe("primaryAttributes", () => {
  it("正式名はaxis-catalog.jsonのprimary_attributes[].labelをそのまま反映する", () => {
    expect(PRIMARY_ATTRIBUTE_LABELS.highway).toBe("道路の種類");
    expect(PRIMARY_ATTRIBUTE_LABELS.accident_point).toBe("事故地点");
    expect(PRIMARY_ATTRIBUTE_LABELS.elevation).toBe("標高");
  });

  // 改善計画T308: axisMaterials/attrConsumers（軸id→材料の逆引き、ビルド時静的
  // axis-catalog.json由来）は撤去した。GUI作成軸を含む解決はbackendのGET /api/axis-catalog
  // （primary_attribute_ids）へ移し、frontendはその結果（呼び出し側が既に持つattrId配列）を
  // primaryAttributeIdsToLayerIdsへ渡すだけの汎用関数として残す。

  it("primaryAttributeIdsToLayerIdsはレイヤーを持つ材料だけを重複無しで返す", () => {
    // レイヤーを持つのはhighway/tunnelのみ（lanes/maxspeed/cycleway/
    // motor_vehicle_accessはレイヤー無し）。
    const layerIds = primaryAttributeIdsToLayerIds([
      "highway",
      "lanes",
      "maxspeed",
      "cycleway",
      "tunnel",
      "motor_vehicle_access",
    ]);
    expect(new Set(layerIds)).toEqual(new Set(["highway", "tunnel"]));
    expect(layerIds.length).toBe(new Set(layerIds).size); // 重複が無い
  });

  it("primaryAttributeIdsToLayerIdsは一部の材料だけレイヤーを持つ場合その分だけを返す", () => {
    // night軸の材料はlit/tunnelの2件。tunnelはレイヤーを持つが、litは引き続きレイヤー無し
    expect(primaryAttributeIdsToLayerIds(["lit", "tunnel"])).toEqual(["tunnel"]);
  });

  it("primaryAttributeIdsToLayerIdsは未知のattrIdを無視する", () => {
    expect(primaryAttributeIdsToLayerIds(["no_such_attr"])).toEqual([]);
  });
});

describe("土地被覆の一次属性", () => {
  it("専用レイヤーを持つものとして対応表から引ける", () => {
    // 推定指標レイヤーをONにしたとき、観測データ側（土地被覆の面）も連動してONになる。
    // 「レイヤー無し」の一覧に残っていると、レイヤーが実在するのに連動しない。
    expect(primaryAttributeIdsToLayerIds(["landcover"])).toEqual(["landcover"]);
  });
});
