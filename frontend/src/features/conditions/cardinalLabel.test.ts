// @vitest-environment node
import { describe, expect, it } from "vitest";

import { mapDisplay } from "@/types/generated/mapDisplay";

import { cardinalLabel } from "./cardinalLabel";

// 8方位の呼び名は源泉（domain/geo.py）が北から時計回りに配る。
const LABELS = mapDisplay.compassLabels;

describe("cardinalLabel", () => {
  it("45度ごとの方位の呼び名を返す", () => {
    expect(LABELS).toHaveLength(8);
    LABELS.forEach((label, i) => expect(cardinalLabel(i * 45)).toBe(label));
  });

  it("境界はbackendと同じ四捨五入（22.5度は次の方位）", () => {
    expect(cardinalLabel(22.4)).toBe(LABELS[0]);
    expect(cardinalLabel(22.5)).toBe(LABELS[1]);
    expect(cardinalLabel(337.5)).toBe(LABELS[0]);
  });

  it("負の角度・360度以上は一周の中へ畳む", () => {
    expect(cardinalLabel(-45)).toBe(LABELS[7]);
    expect(cardinalLabel(405)).toBe(LABELS[1]);
    expect(cardinalLabel(360)).toBe(LABELS[0]);
  });
});
