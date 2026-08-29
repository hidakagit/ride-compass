// @vitest-environment node
import { describe, expect, it } from "vitest";
import { cardinalLabel } from "./WindBearingSlider";

describe("cardinalLabel", () => {
  it.each([
    [0, "北"],
    [45, "北東"],
    [90, "東"],
    [135, "南東"],
    [180, "南"],
    [225, "南西"],
    [270, "西"],
    [315, "北西"],
    [360, "北"],
  ])("maps %d degrees to %s", (deg, expected) => {
    expect(cardinalLabel(deg)).toBe(expected);
  });

  it("normalizes negative degrees", () => {
    expect(cardinalLabel(-45)).toBe("北西");
  });

  it("rounds to the nearest 8-point cardinal", () => {
    expect(cardinalLabel(20)).toBe("北");
    expect(cardinalLabel(30)).toBe("北東");
  });
});
