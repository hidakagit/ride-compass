// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く
// （docs/testing.mdパターン3、windAxisLayer.test.tsと同型）。
import { describe, expect, it } from "vitest";
import {
  gradientAxisColorExpression,
  GRADIENT_AXIS_FEATURE_STATE_KEY,
  buildGradientColorExpression,
  gradientAxisLegend,
} from "./gradientAxisLayer";
import { GRADIENT_BOUNDARIES } from "./routeStyleModes";

describe("gradientAxisLayer（改善計画T423）", () => {
  describe("gradientAxisColorExpression", () => {
    it("feature-state未設定（null）の場合はCOLOR_NO_DATA（不明の灰色）へ分岐するcase式を返す", () => {
      const expression = gradientAxisColorExpression();
      expect(expression[0]).toBe("case");
      expect(expression[1]).toEqual(["==", ["feature-state", GRADIENT_AXIS_FEATURE_STATE_KEY], null]);
      expect(expression[2]).toBe("#9ca3af"); // routeStyleModes.ts: COLOR_NO_DATAと同じ値
    });

    it("段階数はGRADIENT_BOUNDARIES.length+1（stepの[しきい値,色]ペア数と一致）", () => {
      const expression = gradientAxisColorExpression();
      const stepExpression = expression[3] as unknown[];
      expect(stepExpression[0]).toBe("step");
      expect(stepExpression).toHaveLength(3 + GRADIENT_BOUNDARIES.length * 2);
    });
  });

  describe("buildGradientColorExpression（評価軸・環境グループで共有する色ロジック）", () => {
    it('["get","gradientValue"]のような任意の値取得式を受け取れる', () => {
      const expression = buildGradientColorExpression(["get", "gradientValue"]);
      expect(expression[1]).toEqual(["==", ["get", "gradientValue"], null]);
    });

    it("改善計画T440: boundariesを省略時はGRADIENT_BOUNDARIES、明示時は軸スタジオ由来のしきい値の個数に段階数が追従する", () => {
      const defaultExpr = buildGradientColorExpression(["get", "gradientValue"]);
      const stepDefault = defaultExpr[3] as unknown[];
      expect(stepDefault).toHaveLength(3 + GRADIENT_BOUNDARIES.length * 2);

      const customExpr = buildGradientColorExpression(["get", "gradientValue"], [0, 5]);
      const stepCustom = customExpr[3] as unknown[];
      expect(stepCustom).toHaveLength(3 + 2 * 2);
    });
  });

  // ユーザー要望（2026-08-31、「地図上の色付の凡例が欲しい」）: 地図の色分けが実際に塗る
  // 段階（buildGradientColorExpressionと同じ配色・しきい値）と、凡例に出す段階のラベル・色が
  // 一致することを検証する。
  describe("gradientAxisLegend", () => {
    it("段階数はboundaries.length+1で、境界値からラベルを機械的に組み立てる", () => {
      const legend = gradientAxisLegend([0, 5]);
      expect(legend).toHaveLength(3);
      expect(legend[0].label).toBe("0%未満");
      expect(legend[1].label).toBe("0〜5%");
      expect(legend[2].label).toBe("5%以上");
    });

    it("省略時はGRADIENT_BOUNDARIESを使う", () => {
      const legend = gradientAxisLegend();
      expect(legend).toHaveLength(GRADIENT_BOUNDARIES.length + 1);
    });

    it("両端の色はCOLOR_DOWNHILL/GRADIENT_COLOR_HARDと一致する（buildGradientColorExpressionと同じ配色）", () => {
      const legend = gradientAxisLegend([0, 5]);
      expect(legend[0].color).toBe("#0284c7"); // COLOR_DOWNHILL
      expect(legend[legend.length - 1].color).toBe("#dc2626"); // GRADIENT_COLOR_HARD
    });
  });
});
