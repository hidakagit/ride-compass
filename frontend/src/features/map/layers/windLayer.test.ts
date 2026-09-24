// @vitest-environment node
import { describe, expect, it } from "vitest";

import palette from "@/types/generated/palette.json";
import windGridConfig from "@/types/generated/wind-grid-config.json";
import type { WindGridPoint } from "@/types/weather";

import {
  clampWindDetailBbox,
  mergeWindGridKeepingStale,
  trimWindGridToCurrentAndFuture,
  WIND_CALM_THRESHOLD_MS,
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
const jst = (text: string) => new Date(`${text}+09:00`);

describe("trimWindGridToCurrentAndFuture（今より前の時刻を落とす）", () => {
  it("今が属する1時間から先だけを、全格子点・全系列で同じだけ残す", () => {
    const [trimmed] = trimWindGridToCurrentAndFuture([point(HOURS)], jst("2026-09-24T10:59"));
    expect(trimmed.times).toEqual(HOURS.slice(1));
    expect(trimmed.wind_speed_ms).toHaveLength(2);
    expect(trimmed.wind_direction_deg).toHaveLength(2);
    expect(trimmed.precipitation_mm).toEqual([1, 2]);
  });

  it("正時ちょうどはその1時間に入る", () => {
    expect(trimWindGridToCurrentAndFuture([point(HOURS)], jst("2026-09-24T11:00"))[0].times).toEqual(HOURS.slice(2));
  });

  it("先頭がまだ来ていなければ何も落とさず、空は空", () => {
    expect(trimWindGridToCurrentAndFuture([point(HOURS)], jst("2026-09-24T08:30"))[0].times).toEqual(HOURS);
    expect(trimWindGridToCurrentAndFuture([], jst("2026-09-24T10:00"))).toEqual([]);
  });

  it("どの端末の時刻帯でも、格子の時刻は日本時間として読む", () => {
    // 協定世界時 01:30 = 日本時間 10:30
    expect(trimWindGridToCurrentAndFuture([point(HOURS)], new Date("2026-09-24T01:30:00Z"))[0].times).toEqual(
      HOURS.slice(1),
    );
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
    const payload = windArrows(grid, 0);
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
});

describe("風速の凡例", () => {
  it("先頭は矢印を出さない無風の範囲、続いて色の段1つにつき1行（同じ順・同じ色・段の名前）", () => {
    expect(WIND_SPEED_LEGEND_LEVELS[0]).toMatchObject({
      label: `無風・矢印なし（${WIND_CALM_THRESHOLD_MS}m/s未満）`,
      color: palette.semantic.no_data,
    });
    const bands = WIND_SPEED_LEGEND_LEVELS.slice(1);
    expect(bands.map((band) => band.color)).toEqual(WIND_SPEED_COLOR_STOPS.map((stop) => stop.color));
    bands.forEach((band, i) => expect(band.label.startsWith(`${WIND_SPEED_COLOR_STOPS[i].name}（`)).toBe(true));
  });

  it("最初の色の帯は無風の上から、最後の帯は上限なしで始まる", () => {
    const stops = WIND_SPEED_COLOR_STOPS;
    expect(WIND_SPEED_LEGEND_LEVELS[1].label).toContain(`（${WIND_CALM_THRESHOLD_MS}〜${stops[1].speedMs}m/s）`);
    expect(WIND_SPEED_LEGEND_LEVELS.at(-1)?.label).toContain(`（${stops.at(-1)?.speedMs}m/s以上）`);
  });
});

describe("詳細格子の間隔と範囲", () => {
  const spacings = windGridConfig.detail_allowed_spacings_deg;

  it("ズームの段（10・13・16・19）を越えるたびに、許された間隔を1段ずつ細かくする", () => {
    expect(windGridDetailSpacingDegForZoom(10)).toBe(spacings[0]);
    expect(windGridDetailSpacingDegForZoom(12.9)).toBe(spacings[0]);
    expect(windGridDetailSpacingDegForZoom(13)).toBe(spacings[1]);
    expect(windGridDetailSpacingDegForZoom(16)).toBe(spacings[2]);
    expect(windGridDetailSpacingDegForZoom(22)).toBe(spacings[3]);
  });

  it("狭い画面はそのまま、広い画面は中心から点数の上限に収まる範囲へ切る", () => {
    const small = { west: 139.7, south: 35.6, east: 139.72, north: 35.62, zoom: 15 };
    expect(clampWindDetailBbox(small, spacings[0])).toEqual({
      minLon: 139.7,
      minLat: 35.6,
      maxLon: 139.72,
      maxLat: 35.62,
    });

    const wide = { west: 139, south: 35, east: 141, north: 37, zoom: 10 };
    const bbox = clampWindDetailBbox(wide, spacings[0]);
    expect((bbox.minLon + bbox.maxLon) / 2).toBeCloseTo(140);
    expect((bbox.minLat + bbox.maxLat) / 2).toBeCloseTo(36);
    const side = Math.round((bbox.maxLon - bbox.minLon) / spacings[0]) + 1;
    expect(side * side).toBeLessThanOrEqual(windGridConfig.detail_max_points);
  });
});
