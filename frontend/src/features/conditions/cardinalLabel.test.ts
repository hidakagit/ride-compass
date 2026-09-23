// @vitest-environment node
import { describe, expect, it } from "vitest";

import { mapDisplay } from "@/types/generated/mapDisplay";

import { cardinalLabel } from "./cardinalLabel";

// 方位の呼び名は源泉（domain/geo.py）が北から時計回りに配り、区分の幅はその数で決まる。
const LABELS = mapDisplay.compassLabels;
const SECTOR = 360 / LABELS.length;

describe("cardinalLabel", () => {
  it("区分の中心の角度は、その区分の呼び名", () => {
    expect(LABELS).not.toHaveLength(0);
    LABELS.forEach((label, i) => expect(cardinalLabel(i * SECTOR)).toBe(label));
  });

  it("境界はbackendと同じ四捨五入（ちょうど半分は次の方位）", () => {
    expect(cardinalLabel(SECTOR / 2 - 0.1)).toBe(LABELS[0]);
    expect(cardinalLabel(SECTOR / 2)).toBe(LABELS[1]);
    expect(cardinalLabel(360 - SECTOR / 2)).toBe(LABELS[0]);
  });

  it("負の角度・360度以上は一周の中へ畳む", () => {
    expect(cardinalLabel(-SECTOR)).toBe(LABELS.at(-1));
    expect(cardinalLabel(360 + SECTOR)).toBe(LABELS[1]);
    expect(cardinalLabel(360)).toBe(LABELS[0]);
  });
});
