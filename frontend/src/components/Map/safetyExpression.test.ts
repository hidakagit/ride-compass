// @vitest-environment node
import { describe, expect, it } from "vitest";
import testCases from "@/types/generated/safety-test-cases.json";
import {
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_SAFETY_RECIPE,
  buildSafetyExpression,
  evaluateSafetyLevel,
  type MotorVehicleDensityRecipe,
  type RoadSuitabilityRecipe,
  type SafetyRecipe,
} from "./safetyExpression";

// backend/app/domain/safety.py: safety_level()を実際に実行して得た(材料タグ, レシピ,
// 道路適正レシピ, 自動車密度レシピ, 期待値)の組（export_openapi.py: _safety_test_cases参照）。
// carStressExpression.test.tsと同じ理由（Python⇔JS間の実ドリフト検知、期待値はPythonの
// 実行結果を都度書き出す）。
describe("evaluateSafetyLevel（Python実装との相互検証フィクスチャ）", () => {
  it.each(
    testCases as {
      properties: Record<string, unknown>;
      recipe: SafetyRecipe | null;
      road_suitability_recipe: RoadSuitabilityRecipe | null;
      motor_vehicle_density_recipe: MotorVehicleDensityRecipe | null;
      expected_level: number | null;
    }[],
  )(
    "$properties -> $expected_level",
    ({ properties, recipe, road_suitability_recipe, motor_vehicle_density_recipe, expected_level }) => {
      expect(
        evaluateSafetyLevel(
          properties,
          recipe ?? undefined,
          road_suitability_recipe ?? undefined,
          motor_vehicle_density_recipe ?? undefined,
        ),
      ).toBe(expected_level);
    },
  );
});

describe("evaluateSafetyLevel（レシピ上書き）", () => {
  it("道路適正レシピのbase_by_highwayを変えると基準値が変わる", () => {
    const roadSuitabilityRecipe: RoadSuitabilityRecipe = {
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      base_by_highway: { ...DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway, secondary: 2 },
    };
    expect(evaluateSafetyLevel({ highway: "secondary" }, undefined, roadSuitabilityRecipe)).toBe(2);
    // 既定レシピでは3のまま（上書きの副作用が他レシピへ漏れていないことの確認）
    expect(evaluateSafetyLevel({ highway: "secondary" })).toBe(3);
  });

  it("道路適正レシピの補正量を変えるとcycleway補正の効き方が変わる", () => {
    const roadSuitabilityRecipe: RoadSuitabilityRecipe = {
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      cycleway_lane_adjustment: -3,
    };
    expect(
      evaluateSafetyLevel({ highway: "primary", cycleway_class: "lane" }, undefined, roadSuitabilityRecipe),
    ).toBe(1);
  });

  it("自動車密度レシピの閾値を変えるとmaxspeed補正の発火点が変わる", () => {
    const motorVehicleDensityRecipe: MotorVehicleDensityRecipe = {
      ...DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
      maxspeed_high_threshold: 40,
    };
    expect(
      evaluateSafetyLevel(
        { highway: "tertiary", maxspeed_kmh: 40 },
        undefined,
        undefined,
        motorVehicleDensityRecipe,
      ),
    ).toBe(4);
    // 既定レシピ(閾値60)では40は補正なし
    expect(evaluateSafetyLevel({ highway: "tertiary", maxspeed_kmh: 40 })).toBe(3);
  });

  it("軸固有レシピのlit/tunnel補正が効く", () => {
    expect(evaluateSafetyLevel({ highway: "secondary", lit: true })).toBe(2);
    expect(evaluateSafetyLevel({ highway: "secondary", tunnel: true })).toBe(4);
  });
});

describe("buildSafetyExpression", () => {
  it("既定レシピのhighwayキー数ぶんのmatch分岐を生成する", () => {
    const expr = buildSafetyExpression(DEFAULT_SAFETY_RECIPE);
    expect(Array.isArray(expr)).toBe(true);
    expect(expr[0]).toBe("case");
  });
});
