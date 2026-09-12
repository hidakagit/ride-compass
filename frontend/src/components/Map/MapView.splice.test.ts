// @vitest-environment node
import { createExpression, latest } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";

import {
  SPLICE_DASH_EXPRESSION,
  SPLICE_OPACITY_EXPRESSION,
  SPLICE_WIDTH_EXPRESSION,
  spliceStretchesToFeatureCollection,
} from "./MapView";

function evaluate(expression: unknown[], properties: Record<string, unknown>) {
  const parsed = createExpression(expression);
  if (parsed.result !== "success") throw new Error("式の構築に失敗しました");
  return parsed.value.evaluate({ zoom: 14 }, { type: "Unknown", properties });
}

describe("乗り換え区間の描画式", () => {
  it("line-dasharrayはこの版のstyle-specでfeature式を受け付ける", () => {
    // 受け付けない版へ上げると、破線/実線の出し分けが実機で黙って効かなくなる。
    expect(latest["paint_line"]["line-dasharray"].expression?.parameters).toContain("feature");
  });

  it("選んだ区間は太く・不透明・実線になる", () => {
    expect(evaluate(SPLICE_WIDTH_EXPRESSION, { taken: true })).toBeGreaterThan(
      evaluate(SPLICE_WIDTH_EXPRESSION, { taken: false }) as number,
    );
    expect(evaluate(SPLICE_OPACITY_EXPRESSION, { taken: true })).toBeGreaterThan(
      evaluate(SPLICE_OPACITY_EXPRESSION, { taken: false }) as number,
    );
    // 実線は隙間0、未選択は隙間あり
    expect((evaluate(SPLICE_DASH_EXPRESSION, { taken: true }) as number[])[1]).toBe(0);
    expect((evaluate(SPLICE_DASH_EXPRESSION, { taken: false }) as number[])[1]).toBeGreaterThan(0);
  });
});

describe("spliceStretchesToFeatureCollection", () => {
  it("区間ごとにLineStringを作り、indexとtakenを持たせる", () => {
    const data = spliceStretchesToFeatureCollection([
      { index: 0, taken: false, coordinates: [[139.7, 35.7], [139.71, 35.7]] },
    ]);

    expect(data.features).toHaveLength(1);
    expect(data.features[0].properties).toEqual({ index: 0, taken: false });
    expect(data.features[0].geometry.coordinates).toHaveLength(2);
  });

  it("選んだ区間を最前面（配列の最後）へ回す", () => {
    // 未選択の帯が上に重なると、差し替えた先が破線に隠れて変化が見えない
    const data = spliceStretchesToFeatureCollection([
      { index: 0, taken: true, coordinates: [[139.7, 35.7], [139.71, 35.7]] },
      { index: 1, taken: false, coordinates: [[139.72, 35.7], [139.73, 35.7]] },
    ]);

    expect(data.features.map((f) => f.properties.taken)).toEqual([false, true]);
  });
});
