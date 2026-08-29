// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く
// （docs/testing.mdパターン3、windLayer.test.tsと同型）。
//
// 改善計画T423（T411の実施）: `tilesCoveringViewport`/`mergeWindWayPenalties`（材料非依存の
// タイル座標計算・複数タイル応答統合）はdynamicWayValues.tsへ抽出し、そちらのテスト
// （dynamicWayValues.test.ts）へ移設した。このファイルには風固有の配色・しきい値のテストだけが残る。
import { describe, expect, it } from "vitest";
import { windAxisColorExpression, WIND_AXIS_FEATURE_STATE_KEY, WIND_AXIS_THRESHOLDS } from "./windAxisLayer";

describe("windAxisLayer", () => {
  describe("windAxisColorExpression（改善計画T405: setFeatureState値の色分けexpression）", () => {
    it("feature-state未設定（null）の場合はCOLOR_UNKNOWN（不明の灰色）へ分岐するcase式を返す", () => {
      const expression = windAxisColorExpression();
      expect(expression[0]).toBe("case");
      expect(expression[1]).toEqual(["==", ["feature-state", WIND_AXIS_FEATURE_STATE_KEY], null]);
      expect(expression[2]).toBe("#9ca3af"); // axisLayers.ts: COLOR_UNKNOWNと同じ値
    });

    it("段階数はWIND_AXIS_THRESHOLDS.length+1（stepの[しきい値,色]ペア数と一致）", () => {
      const expression = windAxisColorExpression();
      const stepExpression = expression[3] as unknown[];
      expect(stepExpression[0]).toBe("step");
      // step式は ["step", value, color0, threshold1, color1, threshold2, color2, ...] の
      // 並び（MapLibreの仕様: 最初の色は先頭のフォールバック、以降がしきい値・色の対）。
      expect(stepExpression).toHaveLength(3 + WIND_AXIS_THRESHOLDS.length * 2);
    });
  });
});
