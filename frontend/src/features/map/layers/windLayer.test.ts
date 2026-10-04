// @vitest-environment node
import { describe, expect, it } from "vitest";

import palette from "@/types/generated/palette.json";
import windGridConfig from "@/types/generated/wind-grid-config.json";
import type { WindGridPoint } from "@/types/weather";

import {
  clampWindDetailBbox,
  gridAtTime,
  mergeWindGridKeepingStale,
  WIND_CALM_THRESHOLD_MS,
  WIND_DETAIL_MIN_ZOOM,
  WIND_SPEED_COLOR_STOPS,
  WIND_SPEED_LEGEND_LEVELS,
  windArrows,
  windGridDetailSpacingDegForZoom,
} from "./windLayer";

/** 格子点1つ。時刻はbackendと同じ日本時間・オフセット無し。 */
function point(
  times: string[],
  { latitude = 35, longitude = 139, speed = times.map(() => 2), direction = times.map(() => 90) } = {} as {
    latitude?: number;
    longitude?: number;
    speed?: (number | null)[];
    direction?: (number | null)[];
  },
): WindGridPoint {
  return {
    latitude,
    longitude,
    times,
    wind_speed_ms: speed,
    wind_direction_deg: direction,
    precipitation_mm: times.map((_, i) => i),
  } as WindGridPoint;
}

const HOURS = ["2026-09-24T09:00", "2026-09-24T10:00", "2026-09-24T11:00"];
const LATER_HOURS = ["2026-09-24T10:00", "2026-09-24T11:00", "2026-09-24T12:00"];

describe("gridAtTime（時刻ごとに描く格子）", () => {
  const coarse = [point(LATER_HOURS)];
  const detail = { spacingDeg: 0.01, points: [point(HOURS, { latitude: 35.61 })] };

  it("詳細格子がその時刻を持てば、詳細格子とその間隔", () => {
    expect(gridAtTime(coarse, detail, "2026-09-24T11:00")).toBe(detail);
  });

  it("詳細格子がその時刻を持たなければ（取った時刻が早く、先の端が手前で終わる）、粗い格子とその間隔", () => {
    expect(gridAtTime(coarse, detail, "2026-09-24T12:00")).toEqual({
      spacingDeg: windGridConfig.spacing_deg,
      points: coarse,
    });
  });

  it("詳細格子が無いか空なら粗い格子", () => {
    expect(gridAtTime(coarse, null, "2026-09-24T11:00").points).toBe(coarse);
    expect(gridAtTime(coarse, { spacingDeg: 0.01, points: [] }, "2026-09-24T11:00").points).toBe(coarse);
  });
});

describe("mergeWindGridKeepingStale（取り損ねた地点を前回の値で補う）", () => {
  it("今回の格子に、今回欠けた地点だけを前回から足す（同じ地点は今回の値）", () => {
    const previous = [point(HOURS, { latitude: 35 }), point(HOURS, { latitude: 35.1 })];
    const next = [point(HOURS, { latitude: 35, speed: [9, 9, 9] })];
    const merged = mergeWindGridKeepingStale(previous, next);
    expect(merged.map((p) => [p.latitude, p.wind_speed_ms[0]])).toEqual([
      [35, 9],
      [35.1, 2],
    ]);
  });
});

describe("windArrows（風の矢印）", () => {
  it("矢印は風が吹いていく向き（風向+180度）を指し、風速か風向の欠けた地点は描かない", () => {
    const grid = [
      point(["t"], { longitude: 139, speed: [4], direction: [270] }),
      point(["t"], { longitude: 139.1, speed: [null], direction: [0] }),
      point(["t"], { longitude: 139.2, speed: [3], direction: [null] }),
    ];
    const payload = windArrows(grid, "t");
    expect(payload.kind).toBe("gridMark");
    const features = payload.kind === "gridMark" ? payload.geojson.features : [];
    expect(features).toEqual([
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [139, 35] },
        properties: { speed: 4, bearing: 90 },
      },
    ]);
  });

  it("点ごとにその時刻の値を引き（取った時刻で列の先頭が違う点が同居する）、その時刻を持たない点は描かない", () => {
    const grid = [
      point(LATER_HOURS, { longitude: 139, speed: [10, 11, 12] }),
      point(HOURS, { longitude: 139.1, speed: [9, 10, 11] }),
      point(HOURS.slice(0, 2), { longitude: 139.2, speed: [9, 10] }),
    ];
    const payload = windArrows(grid, "2026-09-24T11:00");
    const features = payload.kind === "gridMark" ? payload.geojson.features : [];
    expect(
      features.map((feature) => [(feature.geometry as GeoJSON.Point).coordinates[0], feature.properties?.speed]),
    ).toEqual([
      [139, 11],
      [139.1, 11],
    ]);
  });
});

describe("風速の凡例", () => {
  it("先頭は矢印を出さない無風の範囲、続いて色の段1つにつき1行（同じ順・同じ色・段の名前）", () => {
    expect(WIND_SPEED_LEGEND_LEVELS[0]).toMatchObject({
      label: `無風・矢印なし[${WIND_CALM_THRESHOLD_MS}m/s未満]`,
      color: palette.semantic.no_data,
    });
    const bands = WIND_SPEED_LEGEND_LEVELS.slice(1);
    expect(bands.map((band) => band.color)).toEqual(WIND_SPEED_COLOR_STOPS.map((stop) => stop.color));
    bands.forEach((band, i) => expect(band.label.startsWith(`${WIND_SPEED_COLOR_STOPS[i].name}[`)).toBe(true));
  });

  it("最初の色の帯は無風の上から、最後の帯は上限なしで始まる", () => {
    const stops = WIND_SPEED_COLOR_STOPS;
    expect(WIND_SPEED_LEGEND_LEVELS[1].label).toContain(`[${WIND_CALM_THRESHOLD_MS}〜${stops[1].speedMs}m/s]`);
    expect(WIND_SPEED_LEGEND_LEVELS.at(-1)?.label).toContain(`[${stops.at(-1)?.speedMs}m/s以上]`);
  });
});

describe("詳細格子の間隔と範囲", () => {
  const coarsest = windGridDetailSpacingDegForZoom(WIND_DETAIL_MIN_ZOOM);

  it("ズームを上げても間隔は粗くならず、最も拡大してもbackendが受け付ける下限を下回らない", () => {
    const zooms = Array.from({ length: (24 - WIND_DETAIL_MIN_ZOOM) * 4 + 1 }, (_, i) => WIND_DETAIL_MIN_ZOOM + i / 4);
    const spacings = [...zooms, Infinity].map(windGridDetailSpacingDegForZoom);
    spacings.slice(1).forEach((spacing, i) => expect(spacing).toBeLessThanOrEqual(spacings[i]));
    expect(Math.min(...spacings)).toBeGreaterThanOrEqual(windGridConfig.detail_min_spacing_deg);
  });

  it("狭い画面はそのまま、広い画面は中心から点数の上限に収まる範囲へ切る", () => {
    const small = { west: 139.7, south: 35.6, east: 139.72, north: 35.62, zoom: 15 };
    expect(clampWindDetailBbox(small, coarsest)).toEqual({
      minLon: 139.7,
      minLat: 35.6,
      maxLon: 139.72,
      maxLat: 35.62,
    });

    const wide = { west: 139, south: 35, east: 141, north: 37, zoom: 10 };
    const bbox = clampWindDetailBbox(wide, coarsest);
    expect((bbox.minLon + bbox.maxLon) / 2).toBeCloseTo(140);
    expect((bbox.minLat + bbox.maxLat) / 2).toBeCloseTo(36);
    const side = Math.round((bbox.maxLon - bbox.minLon) / coarsest) + 1;
    expect(side * side).toBeLessThanOrEqual(windGridConfig.detail_max_points);
  });
});
