import { describe, expect, it, vi } from "vitest";
import type { RouteCandidate } from "@/types/route";
import { buildGpxDocument, decimateCoordinates, downloadGpx, MAX_GPX_TRACK_POINTS } from "./gpxExport";

function makeCandidate(overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return {
    id: "route-000",
    direction_label: "北",
    distance_km: 12.3,
    geometry: {
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.71, 35.71],
        [139.72, 35.72],
      ],
    },
    elevation_gain_m: null,
    min_elevation_m: null,
    max_elevation_m: null,
    segments: null,
    overall_difficulty: null,
    difficulty_load: null,
    axis_difficulties: {},
    axis_contributions: {},
    material_values: {},
    ...overrides,
  };
}

describe("decimateCoordinates", () => {
  it("上限以下ならそのまま返す", () => {
    const coordinates: GeoJSON.Position[] = [
      [0, 0],
      [1, 1],
      [2, 2],
    ];
    expect(decimateCoordinates(coordinates, 10)).toEqual(coordinates);
  });

  it("上限を超える場合は上限以下まで間引き、先頭・末尾は残す", () => {
    const coordinates: GeoJSON.Position[] = Array.from({ length: 2500 }, (_, i) => [i, i]);
    const result = decimateCoordinates(coordinates, 1000);
    expect(result.length).toBeLessThanOrEqual(1000);
    expect(result[0]).toEqual(coordinates[0]);
    expect(result[result.length - 1]).toEqual(coordinates[coordinates.length - 1]);
  });
});

describe("buildGpxDocument", () => {
  it("trk/trksegを持ち、rte/wptは使わない（Suuntoがtrk以外を取り込めないため）", () => {
    const xml = buildGpxDocument(makeCandidate());
    expect(xml).toContain("<trk>");
    expect(xml).toContain("<trkseg>");
    expect(xml).not.toContain("<rte>");
    expect(xml).not.toContain("<wpt");
  });

  it("GeoJSONの[lon, lat]順をGPXのlat/lon属性へ正しく入れ替える", () => {
    const xml = buildGpxDocument(makeCandidate());
    expect(xml).toContain('<trkpt lat="35.7" lon="139.7"/>');
    expect(xml).toContain('<trkpt lat="35.72" lon="139.72"/>');
  });

  it("方位ラベルと距離を<name>に含める", () => {
    const xml = buildGpxDocument(makeCandidate({ direction_label: "南東", distance_km: 45.6 }));
    expect(xml).toContain("<name>RideCompass 南東 45.6km</name>");
  });

  it("上限を超える座標列は間引いてから出力する", () => {
    const coordinates: GeoJSON.Position[] = Array.from({ length: 2500 }, (_, i) => [i * 0.001, i * 0.001]);
    const xml = buildGpxDocument(makeCandidate({ geometry: { type: "LineString", coordinates } }));
    const trkptCount = (xml.match(/<trkpt /g) ?? []).length;
    expect(trkptCount).toBeLessThanOrEqual(MAX_GPX_TRACK_POINTS);
  });
});

describe("downloadGpx", () => {
  it("Blob+ObjectURL経由でaタグのdownloadをクリックし、後始末（revokeObjectURL）する", () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    let downloadedFilename: string | null = null;
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement
    ) {
      downloadedFilename = this.download;
    });

    downloadGpx(makeCandidate({ id: "route-042" }));

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    expect(blob.type).toBe("application/gpx+xml");
    expect(clickSpy).toHaveBeenCalledTimes(1);
    expect(downloadedFilename).toBe("ridecompass-route-042.gpx");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");

    clickSpy.mockRestore();
    vi.unstubAllGlobals();
  });
});
