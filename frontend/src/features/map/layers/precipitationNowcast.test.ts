// @vitest-environment node
import { describe, expect, it } from "vitest";

import type { WindGridPoint } from "@/types/weather";

import { PRECIPITATION_COLOR_STOPS, PRECIPITATION_INTENSITY_LEVELS, precipitationCells } from "./precipitationNowcast";

const gridPoint = (precipitation: (number | null)[], latitude: number, longitude = 139): WindGridPoint =>
  ({
    latitude,
    longitude,
    times: precipitation.map(() => "2026-09-24T12:00"),
    wind_speed_ms: precipitation.map(() => 1),
    wind_direction_deg: precipitation.map(() => 0),
    precipitation_mm: precipitation,
  }) as WindGridPoint;

describe("precipitationCells（格子の降水の塗り）", () => {
  it("描く格子の各点を中心とする正方形を、その時刻の降水量で塗る（欠けた点は飛ばす）", () => {
    const payload = precipitationCells([gridPoint([2.5], 35), gridPoint([null], 35.1)], 0, 0.1);
    expect(payload.kind).toBe("gridFill");
    const { features } = payload.kind === "gridFill" ? payload.geojson : { features: [] };
    expect(features).toHaveLength(1);
    expect(features[0].properties).toEqual({ mmPerHour: 2.5 });
    expect(features[0].geometry).toMatchObject({ type: "Polygon" });
  });
});

describe("降水強度の凡例", () => {
  it("色の段1つにつき1行、同じ順・同じ色で、帯の境界の値を名乗る", () => {
    expect(PRECIPITATION_INTENSITY_LEVELS.map((level) => level.color)).toEqual(
      PRECIPITATION_COLOR_STOPS.map((stop) => stop.color),
    );
    PRECIPITATION_INTENSITY_LEVELS.forEach((level, i) => {
      const next = PRECIPITATION_COLOR_STOPS[i + 1];
      if (next) expect(level.label).toContain(`${next.mmPerHour}mm/h`);
    });
  });
});
