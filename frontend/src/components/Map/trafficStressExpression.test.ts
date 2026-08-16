import { describe, expect, it } from "vitest";
import testCases from "@/types/generated/traffic-stress-test-cases.json";
import {
  DEFAULT_TRAFFIC_STRESS_RECIPE,
  buildTrafficStressExpression,
  evaluateTrafficStressLevel,
  type TrafficStressRecipe,
} from "./trafficStressExpression";

// backend/app/domain/traffic.py: traffic_stress_level()を実際に実行して得た
// (材料タグ, レシピ, 期待値)の組（export_openapi.py: _traffic_stress_test_cases参照）。
// 期待値をこちらでベタ書きすると、Python側のロジックが変わってもJSのミラー実装が古いまま
// 気づけない（旧test_road_graph_repository.pyのSQL⇔Python整合性テストで実際に起きていた
// 問題の再発）。フィクスチャはPythonの実行結果を都度書き出すため、traffic_stress_breakdown
// が変わればJSONも追従し、buildTrafficStressExpressionが追従していなければこのテストが
// 落ちる（Python⇔JS間の実ドリフト検知）。
describe("evaluateTrafficStressLevel（Python実装との相互検証フィクスチャ）", () => {
  it.each(testCases as { properties: Record<string, unknown>; recipe: TrafficStressRecipe | null; expected_level: number | null }[])(
    "$properties -> $expected_level",
    ({ properties, recipe, expected_level }) => {
      expect(evaluateTrafficStressLevel(properties, recipe ?? undefined)).toBe(expected_level);
    },
  );
});

describe("evaluateTrafficStressLevel（レシピ上書き）", () => {
  it("base_by_highwayを変えると基準値が変わる", () => {
    const recipe: TrafficStressRecipe = {
      ...DEFAULT_TRAFFIC_STRESS_RECIPE,
      base_by_highway: { ...DEFAULT_TRAFFIC_STRESS_RECIPE.base_by_highway, secondary: 2 },
    };
    expect(evaluateTrafficStressLevel({ highway: "secondary" }, recipe)).toBe(2);
    // 既定レシピでは3のまま（上書きの副作用が他レシピへ漏れていないことの確認）
    expect(evaluateTrafficStressLevel({ highway: "secondary" }, DEFAULT_TRAFFIC_STRESS_RECIPE)).toBe(3);
  });

  it("補正量を変えるとcycleway補正の効き方が変わる", () => {
    const recipe: TrafficStressRecipe = { ...DEFAULT_TRAFFIC_STRESS_RECIPE, cycleway_lane_adjustment: -3 };
    expect(evaluateTrafficStressLevel({ highway: "primary", cycleway_class: "lane" }, recipe)).toBe(1);
  });

  it("閾値を変えるとmaxspeed補正の発火点が変わる", () => {
    const recipe: TrafficStressRecipe = { ...DEFAULT_TRAFFIC_STRESS_RECIPE, maxspeed_high_threshold: 40 };
    expect(evaluateTrafficStressLevel({ highway: "tertiary", maxspeed_kmh: 40 }, recipe)).toBe(4);
    // 既定レシピ(閾値60)では40は補正なし
    expect(evaluateTrafficStressLevel({ highway: "tertiary", maxspeed_kmh: 40 }, DEFAULT_TRAFFIC_STRESS_RECIPE)).toBe(3);
  });
});

describe("buildTrafficStressExpression", () => {
  it("既定レシピのhighwayキー数ぶんのmatch分岐を生成する", () => {
    const expr = buildTrafficStressExpression(DEFAULT_TRAFFIC_STRESS_RECIPE);
    expect(Array.isArray(expr)).toBe(true);
    expect(expr[0]).toBe("case");
  });
});
