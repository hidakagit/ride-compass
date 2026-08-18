// @vitest-environment node
import { describe, expect, it } from "vitest";
import testCases from "@/types/generated/traffic-stress-test-cases.json";
import {
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_TRAFFIC_STRESS_RECIPE,
  buildTrafficStressExpression,
  evaluateTrafficStressLevel,
  type MotorVehicleDensityRecipe,
  type RoadSuitabilityRecipe,
  type TrafficStressRecipe,
} from "./trafficStressExpression";

// backend/app/domain/traffic.py: traffic_stress_level()を実際に実行して得た
// (材料タグ, レシピ, 道路適正レシピ, 自動車密度レシピ, 期待値)の組
// （export_openapi.py: _traffic_stress_test_cases参照）。期待値をこちらでベタ書きすると、
// Python側のロジックが変わってもJSのミラー実装が古いまま気づけない（旧
// test_road_graph_repository.pyのSQL⇔Python整合性テストで実際に起きていた問題の再発）。
// フィクスチャはPythonの実行結果を都度書き出すため、traffic_stress_breakdownが変われば
// JSONも追従し、buildTrafficStressExpressionが追従していなければこのテストが落ちる
// （Python⇔JS間の実ドリフト検知）。
describe("evaluateTrafficStressLevel（Python実装との相互検証フィクスチャ）", () => {
  it.each(
    testCases as {
      properties: Record<string, unknown>;
      recipe: TrafficStressRecipe | null;
      road_suitability_recipe: RoadSuitabilityRecipe | null;
      motor_vehicle_density_recipe: MotorVehicleDensityRecipe | null;
      expected_level: number | null;
    }[],
  )(
    "$properties -> $expected_level",
    ({ properties, recipe, road_suitability_recipe, motor_vehicle_density_recipe, expected_level }) => {
      expect(
        evaluateTrafficStressLevel(
          properties,
          recipe ?? undefined,
          road_suitability_recipe ?? undefined,
          motor_vehicle_density_recipe ?? undefined,
        ),
      ).toBe(expected_level);
    },
  );
});

describe("evaluateTrafficStressLevel（レシピ上書き）", () => {
  it("道路適正レシピのbase_by_highwayを変えると基準値が変わる", () => {
    const roadSuitabilityRecipe: RoadSuitabilityRecipe = {
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      base_by_highway: { ...DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway, secondary: 2 },
    };
    expect(
      evaluateTrafficStressLevel({ highway: "secondary" }, undefined, roadSuitabilityRecipe),
    ).toBe(2);
    // 既定レシピでは3のまま（上書きの副作用が他レシピへ漏れていないことの確認）
    expect(evaluateTrafficStressLevel({ highway: "secondary" })).toBe(3);
  });

  it("道路適正レシピの補正量を変えるとcycleway補正の効き方が変わる", () => {
    const roadSuitabilityRecipe: RoadSuitabilityRecipe = {
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      cycleway_lane_adjustment: -3,
    };
    expect(
      evaluateTrafficStressLevel(
        { highway: "primary", cycleway_class: "lane" },
        undefined,
        roadSuitabilityRecipe,
      ),
    ).toBe(1);
  });

  it("自動車密度レシピの閾値を変えるとmaxspeed補正の発火点が変わる", () => {
    const motorVehicleDensityRecipe: MotorVehicleDensityRecipe = {
      ...DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
      maxspeed_high_threshold: 40,
    };
    expect(
      evaluateTrafficStressLevel(
        { highway: "tertiary", maxspeed_kmh: 40 },
        undefined,
        undefined,
        motorVehicleDensityRecipe,
      ),
    ).toBe(4);
    // 既定レシピ(閾値60)では40は補正なし
    expect(evaluateTrafficStressLevel({ highway: "tertiary", maxspeed_kmh: 40 })).toBe(3);
  });

  it("軸固有レシピのlanes_low補正量を変えると効き方が変わる", () => {
    const recipe: TrafficStressRecipe = { ...DEFAULT_TRAFFIC_STRESS_RECIPE, lanes_low_adjustment: -3 };
    expect(evaluateTrafficStressLevel({ highway: "primary", lanes_count: 1 }, recipe)).toBe(1); // 4-3
  });
});

describe("buildTrafficStressExpression", () => {
  it("既定レシピのhighwayキー数ぶんのmatch分岐を生成する", () => {
    const expr = buildTrafficStressExpression(DEFAULT_TRAFFIC_STRESS_RECIPE);
    expect(Array.isArray(expr)).toBe(true);
    expect(expr[0]).toBe("case");
  });
});
