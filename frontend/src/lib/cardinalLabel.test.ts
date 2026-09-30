// @vitest-environment node
import { describe, expect, it } from "vitest";

import geoExpectations from "@/types/generated/geo-expectations.json";
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

  it("backendの表（区分の境界・負の角度・一周を超える角度）と同じ呼び名", () => {
    const rows = geoExpectations.compass_label;
    expect(rows.length).toBeGreaterThan(0);
    for (const { bearing_deg, label } of rows) {
      expect(cardinalLabel(bearing_deg), `${bearing_deg}度`).toBe(label);
    }
  });
});
