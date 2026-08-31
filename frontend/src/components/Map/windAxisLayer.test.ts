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

    // 改善計画T513: 段階ごとの体感ラベル（例:「強い向かい風」）は軸スタジオの
    // display_band_labels_override（page.tsx経由）から任意の第2引数として渡す。
    // このファイル自身は固定ラベルを持たない（改善計画T512で風専用のハードコード配列
    // だったものを、ユーザー指摘「軸スタジオで設定できるものをベタで書かないで」を受け
    // 汎用フィールドへ置き換えた）。
    it("labelsを渡すと、要素数が段階数と一致する間だけ数値レンジの前に添える", () => {
      const labels = ["強い追い風", "軽い追い風", "風の影響は小さい", "軽い向かい風", "強い向かい風"];
      const legend = windAxisLegend(undefined, labels);
      expect(legend).toHaveLength(5);
      expect(legend[0].label).toBe("強い追い風（-6m/s未満）");
      expect(legend[4].label).toBe("強い向かい風（6m/s以上）");
    });

    it("軸スタジオのdisplay_thresholds_overrideで境界値だけ調整しても段階数が変わらなければlabelsは付く", () => {
      const labels = ["強い追い風", "軽い追い風", "風の影響は小さい", "軽い向かい風", "強い向かい風"];
      const legend = windAxisLegend([-8, -3, 3, 8], labels);
      expect(legend).toHaveLength(5);
      expect(legend[0].label).toBe("強い追い風（-8m/s未満）");
      expect(legend[4].label).toBe("強い向かい風（8m/s以上）");
    });

    it("labelsの要素数が段階数と異なる場合はlabelsを付けず数値レンジのみになる（不整合な保存データへの防御）", () => {
      const legend = windAxisLegend([-2, 2], ["強い追い風", "軽い追い風"]);
      expect(legend[0].label).toBe("-2m/s未満");
      expect(legend[1].label).toBe("-2〜2m/s");
      expect(legend[2].label).toBe("2m/s以上");
    });

    it("labelsを渡さない場合は数値レンジのみになる", () => {
      const legend = windAxisLegend();
      expect(legend[0].label).toBe("-6m/s未満");
    });
  });
});
