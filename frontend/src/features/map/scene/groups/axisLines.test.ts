// @vitest-environment node
import { describe, expect, it } from "vitest";

import { mapDisplay } from "@/types/generated/mapDisplay";

import { axisLineGroup, type AxisLineState } from "./axisLines";

// 地図全体の「薄い＝対象外、濃い＝分類あり」という読み方を、レンズの線にも効かせる。
// 方位を指定すると値を示せない道が街区の半分近くを占めうるため、濃いまま塗ると
// 値のある道がそこへ埋もれる。
const BANDS = [
  { key: "b0", lowerBound: 0, color: "#16a34a" },
  { key: "b1", lowerBound: 5, color: "#dc2626" },
];

function opacityOf(value: AxisLineState["axes"][number]["value"], underlay = false): unknown {
  const state: AxisLineState = {
    sourceLayer: "road",
    axes: [{ axisId: "gradient", visible: true, bands: BANDS, value, hiddenBandKeys: [], underlay }],
  };
  return axisLineGroup.build(state).layers[0].paint?.["line-opacity"];
}

describe("レンズの線の濃さ", () => {
  it("値を受け取れなかった道は薄く、値を持つ道は濃く塗る", () => {
    const opacity = opacityOf({ kind: "delivered", values: new Map(), loading: false }) as unknown[];

    expect(opacity[0]).toBe("case");
    expect(opacity[2]).toBe(mapDisplay.road.unknownOpacity);
    expect(opacity[3]).toBe(mapDisplay.road.knownOpacity);
    expect(mapDisplay.road.unknownOpacity).toBeLessThan(mapDisplay.road.knownOpacity);
  });

  it("取得中は薄くしない（「取得中」と「対象外」が見分けられなくなるため）", () => {
    expect(opacityOf({ kind: "delivered", values: new Map(), loading: true })).toBe(mapDisplay.road.knownOpacity);
  });

  it("材料が同時に出ているときの下敷きは、全体を薄く敷く", () => {
    expect(opacityOf({ kind: "delivered", values: new Map(), loading: false }, true)).toBe(
      mapDisplay.road.unknownOpacity,
    );
  });
});
