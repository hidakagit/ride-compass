// @vitest-environment node
import { describe, expect, it } from "vitest";
// ファイル名traffic-stress-test-cases.jsonはT150未追従の意図的な据え置き
// （backend/scripts/export_openapi.py: TRAFFIC_STRESS_TEST_CASES_PATH参照、carStressExpression.ts
// 冒頭コメントも参照）。
import testCases from "@/types/generated/traffic-stress-test-cases.json";
import {
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  DEFAULT_ROAD_SUITABILITY_RECIPE,
  DEFAULT_CAR_STRESS_RECIPE,
  buildCarStressExpression,
  evaluateCarStressLevel,
  type MotorVehicleDensityRecipe,
  type RoadSuitabilityRecipe,
  type CarStressRecipe,
} from "./carStressExpression";

// backend/app/domain/traffic.py: car_stress_level()を実際に実行して得た
// (材料タグ, レシピ, 道路適正レシピ, 自動車密度レシピ, 期待値)の組
// （export_openapi.py: _car_stress_test_cases参照）。期待値をこちらでベタ書きすると、
// Python側のロジックが変わってもJSのミラー実装が古いまま気づけない（旧
// test_road_graph_repository.pyのSQL⇔Python整合性テストで実際に起きていた問題の再発）。
// フィクスチャはPythonの実行結果を都度書き出すため、car_stress_breakdownが変われば
// JSONも追従し、buildCarStressExpressionが追従していなければこのテストが落ちる
// （Python⇔JS間の実ドリフト検知）。
describe("evaluateCarStressLevel（Python実装との相互検証フィクスチャ）", () => {
  it.each(
    testCases as {
      properties: Record<string, unknown>;
      recipe: CarStressRecipe | null;
      road_suitability_recipe: RoadSuitabilityRecipe | null;
      motor_vehicle_density_recipe: MotorVehicleDensityRecipe | null;
      expected_level: number | null;
    }[],
  )(
    "$properties -> $expected_level",
    ({ properties, recipe, road_suitability_recipe, motor_vehicle_density_recipe, expected_level }) => {
      expect(
        evaluateCarStressLevel(
          properties,
          recipe ?? undefined,
          road_suitability_recipe ?? undefined,
          motor_vehicle_density_recipe ?? undefined,
        ),
      ).toBe(expected_level);
    },
  );
});

describe("evaluateCarStressLevel（レシピ上書き）", () => {
  it("道路適正レシピのbase_by_highwayを変えると基準値が変わる", () => {
    const roadSuitabilityRecipe: RoadSuitabilityRecipe = {
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      base_by_highway: { ...DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway, secondary: 2 },
    };
    expect(
      evaluateCarStressLevel({ highway: "secondary" }, undefined, roadSuitabilityRecipe),
    ).toBe(2);
    // 既定レシピでは3のまま（上書きの副作用が他レシピへ漏れていないことの確認）
    expect(evaluateCarStressLevel({ highway: "secondary" })).toBe(3);
  });

  it("道路適正レシピの補正量を変えるとcycleway補正の効き方が変わる", () => {
    const roadSuitabilityRecipe: RoadSuitabilityRecipe = {
      ...DEFAULT_ROAD_SUITABILITY_RECIPE,
      cycleway_lane_adjustment: -3,
    };
    expect(
      evaluateCarStressLevel(
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
      evaluateCarStressLevel(
        { highway: "tertiary", maxspeed_kmh: 40 },
        undefined,
        undefined,
        motorVehicleDensityRecipe,
      ),
    ).toBe(4);
    // 既定レシピ(閾値60)では40は補正なし
    expect(evaluateCarStressLevel({ highway: "tertiary", maxspeed_kmh: 40 })).toBe(3);
  });

  it("軸固有レシピのlanes_low補正量を変えると効き方が変わる", () => {
    const recipe: CarStressRecipe = { ...DEFAULT_CAR_STRESS_RECIPE, lanes_low_adjustment: -3 };
    expect(evaluateCarStressLevel({ highway: "primary", lanes_count: 1 }, recipe)).toBe(1); // 4-3
  });
});

describe("buildCarStressExpression", () => {
  it("既定レシピのhighwayキー数ぶんのmatch分岐を生成する", () => {
    const expr = buildCarStressExpression(DEFAULT_CAR_STRESS_RECIPE);
    expect(Array.isArray(expr)).toBe(true);
    expect(expr[0]).toBe("case");
  });
});
