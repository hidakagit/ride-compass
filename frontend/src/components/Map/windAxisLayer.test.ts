// @vitest-environment node
// DOM/MapLibreを一切使わない純粋関数のみを検証するため、jsdom環境構築コストを省く
// （docs/testing.mdパターン3、windLayer.test.tsと同型）。
//
// 改善計画T423（T411の実施）: `tilesCoveringViewport`/`mergeWindWayPenalties`（材料非依存の
// タイル座標計算・複数タイル応答統合）はdynamicWayValues.tsへ抽出し、そちらのテスト
// （dynamicWayValues.test.ts）へ移設した。このファイルには風固有の配色・しきい値のテストだけが残る。
import { describe, expect, it } from "vitest";
import { windAxisColorExpression, WIND_AXIS_FEATURE_STATE_KEY, WIND_AXIS_THRESHOLDS, windAxisLegend } from "./windAxisLayer";
import { rampColorForBand } from "./axisLayers";

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

  // ユーザー要望（2026-08-31、「地図上の色付の凡例が欲しい」）: 地図の色分けが実際に塗る
  // 段階（windAxisColorExpressionと同じ配色・しきい値）と、凡例に出す段階のラベル・色が
  // 一致することを検証する。
  describe("windAxisLegend", () => {
    it("段階数はboundaries.length+1で、境界値からラベルを機械的に組み立てる", () => {
      const legend = windAxisLegend([-2, 2]);
      expect(legend).toHaveLength(3);
      expect(legend[0].label).toBe("-2m/s未満");
      expect(legend[1].label).toBe("-2〜2m/s");
      expect(legend[2].label).toBe("2m/s以上");
    });

    it("省略時はWIND_AXIS_THRESHOLDSを使う", () => {
      const legend = windAxisLegend();
      expect(legend).toHaveLength(WIND_AXIS_THRESHOLDS.length + 1);
    });

    it("色はrampColorForBandと一致する（windAxisColorExpressionと同じ配色）", () => {
      const legend = windAxisLegend([-2, 2]);
      expect(legend[0].color).toBe(rampColorForBand(0, 3));
      expect(legend[1].color).toBe(rampColorForBand(1, 3));
      expect(legend[2].color).toBe(rampColorForBand(2, 3));
    });

    // ユーザー要望（2026-08-31「風も降水のように体感で分かる凡例ラベルにしたい
    // （色の指定は不要）」）: 段階数が既定のWIND_AXIS_THRESHOLDS（5段階）と一致する間は、
    // 数値レンジの前に体感ラベル（強い向かい風/軽い向かい風等）を添える。
    it("段階数が既定(5段階)と一致する場合、数値レンジの前に体感ラベルが付く", () => {
      const legend = windAxisLegend();
      expect(legend).toHaveLength(5);
      expect(legend[0].label).toBe("強い追い風（-6m/s未満）");
      expect(legend[1].label).toBe("軽い追い風（-6〜-2m/s）");
      expect(legend[2].label).toBe("風の影響は小さい（-2〜2m/s）");
      expect(legend[3].label).toBe("軽い向かい風（2〜6m/s）");
      expect(legend[4].label).toBe("強い向かい風（6m/s以上）");
    });

    it("軸スタジオのdisplay_thresholds_overrideで境界値だけ調整しても段階数が5のままなら体感ラベルは付く", () => {
      const legend = windAxisLegend([-8, -3, 3, 8]);
      expect(legend).toHaveLength(5);
      expect(legend[0].label).toBe("強い追い風（-8m/s未満）");
      expect(legend[4].label).toBe("強い向かい風（8m/s以上）");
    });

    it("段階数が既定(5段階)と異なる場合は体感ラベルを付けず数値レンジのみになる", () => {
      const legend = windAxisLegend([-2, 2]);
      expect(legend[0].label).toBe("-2m/s未満");
      expect(legend[1].label).toBe("-2〜2m/s");
      expect(legend[2].label).toBe("2m/s以上");
    });
  });
});
