import { describe, expect, it } from "vitest";
import testCases from "@/types/generated/safety-test-cases.json";
import {
  DEFAULT_SAFETY_RECIPE,
  buildSafetyExpression,
  evaluateSafetyLevel,
  type SafetyRecipe,
} from "./safetyExpression";

// backend/app/domain/safety.py: safety_level()を実際に実行して得た(材料タグ, レシピ, 期待値)の
// 組（export_openapi.py: _safety_test_cases参照）。trafficStressExpression.test.tsと同じ理由
// （Python⇔JS間の実ドリフト検知、期待値はPythonの実行結果を都度書き出す）。
describe("evaluateSafetyLevel（Python実装との相互検証フィクスチャ）", () => {
  it.each(testCases as { properties: Record<string, unknown>; recipe: SafetyRecipe | null; expected_level: number | null }[])(
    "$properties -> $expected_level",
    ({ properties, recipe, expected_level }) => {
      expect(evaluateSafetyLevel(properties, recipe ?? undefined)).toBe(expected_level);
    },
  );
});

describe("evaluateSafetyLevel（レシピ上書き）", () => {
  it("base_by_highwayを変えると基準値が変わる", () => {
    const recipe: SafetyRecipe = {
      ...DEFAULT_SAFETY_RECIPE,
      base_by_highway: { ...DEFAULT_SAFETY_RECIPE.base_by_highway, secondary: 2 },
    };
    expect(evaluateSafetyLevel({ highway: "secondary" }, recipe)).toBe(2);
    // 既定レシピでは3のまま（上書きの副作用が他レシピへ漏れていないことの確認）
    expect(evaluateSafetyLevel({ highway: "secondary" }, DEFAULT_SAFETY_RECIPE)).toBe(3);
  });

  it("補正量を変えるとcycleway補正の効き方が変わる", () => {
    const recipe: SafetyRecipe = { ...DEFAULT_SAFETY_RECIPE, cycleway_lane_adjustment: -3 };
    expect(evaluateSafetyLevel({ highway: "primary", cycleway_class: "lane" }, recipe)).toBe(1);
  });

  it("閾値を変えるとmaxspeed補正の発火点が変わる", () => {
    const recipe: SafetyRecipe = { ...DEFAULT_SAFETY_RECIPE, maxspeed_high_threshold: 40 };
    expect(evaluateSafetyLevel({ highway: "tertiary", maxspeed_kmh: 40 }, recipe)).toBe(4);
    // 既定レシピ(閾値60)では40は補正なし
    expect(evaluateSafetyLevel({ highway: "tertiary", maxspeed_kmh: 40 }, DEFAULT_SAFETY_RECIPE)).toBe(3);
  });

  it("shoulder/lit/tunnelの補正が効く", () => {
    expect(evaluateSafetyLevel({ highway: "secondary", shoulder: true }, DEFAULT_SAFETY_RECIPE)).toBe(2);
    expect(evaluateSafetyLevel({ highway: "secondary", lit: true }, DEFAULT_SAFETY_RECIPE)).toBe(2);
    expect(evaluateSafetyLevel({ highway: "secondary", tunnel: true }, DEFAULT_SAFETY_RECIPE)).toBe(4);
  });
});

describe("buildSafetyExpression", () => {
  it("既定レシピのhighwayキー数ぶんのmatch分岐を生成する", () => {
    const expr = buildSafetyExpression(DEFAULT_SAFETY_RECIPE);
    expect(Array.isArray(expr)).toBe(true);
    expect(expr[0]).toBe("case");
  });
});
