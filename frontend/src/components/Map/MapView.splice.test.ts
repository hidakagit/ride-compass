// @vitest-environment node
import { createExpression, latest } from "@maplibre/maplibre-gl-style-spec";
import { describe, expect, it } from "vitest";

import {
  SPLICE_DASH_EXPRESSION,
  SPLICE_HIT_LAYER_ID,
  SPLICE_HIT_WIDTH,
  SPLICED_ROUTE_LAYER_ID,
  SPLICED_ROUTE_WIDTH,
  SPLICE_LAYER_ID,
  SPLICE_OPACITY_EXPRESSION,
  SPLICE_WIDTH_EXPRESSION,
  drawSpliceStretches,
  drawSplicedRoute,
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

// 帯そのものは幅3〜5pxで、指では狙えない（実機のスマホでほぼ選べなかった）。
describe("乗り換え区間の当たり判定", () => {
  function fakeMap() {
    const layers: { id: string; paint?: Record<string, unknown> }[] = [];
    return {
      layers,
      // runWhenStyleReadyはこの印で「スタイル準備済み」と判断する
      __rcStyleReady: true,
      isStyleLoaded: () => true,
      getSource: () => undefined,
      addSource: () => {},
      addLayer: (spec: { id: string; paint?: Record<string, unknown> }) => layers.push(spec),
      getLayer: (id: string) => layers.find((layer) => layer.id === id),
      setLayoutProperty: () => {},
      on: () => {},
      once: () => {},
      off: () => {},
    };
  }

  it("見た目の帯より太い、透明な当たり判定レイヤーを重ねる", () => {
    const map = fakeMap();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    drawSpliceStretches(map as any, [
      { index: 0, taken: false, coordinates: [[139.7, 35.7], [139.71, 35.7]] },
    ]);

    const hit = map.layers.find((layer) => layer.id === SPLICE_HIT_LAYER_ID);
    expect(hit).toBeDefined();
    expect(hit?.paint?.["line-width"]).toBe(SPLICE_HIT_WIDTH);
    expect(hit?.paint?.["line-opacity"]).toBe(0);
    // 見た目の帯は残す（当たり判定で置き換えない）
    expect(map.layers.some((layer) => layer.id === SPLICE_LAYER_ID)).toBe(true);
  });
  it("いま作っているルートを、帯より太い実線で描く", () => {
    const map = fakeMap();

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    drawSplicedRoute(map as any, [[139.7, 35.7], [139.71, 35.7]]);

    const line = map.layers.find((layer) => layer.id === SPLICED_ROUTE_LAYER_ID);
    expect(line?.paint?.["line-width"]).toBe(SPLICED_ROUTE_WIDTH);
    // 乗り換え先の帯（選んでいない道）より太い＝いま通る道が主役
    expect(SPLICED_ROUTE_WIDTH).toBeGreaterThan(5);
  });
});
