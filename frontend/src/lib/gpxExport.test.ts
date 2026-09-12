import { describe, expect, it, vi } from "vitest";
import type { RouteCandidate } from "@/types/route";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import { buildGpxDocument, simplifyCoordinates, downloadGpx, MAX_GPX_TRACK_POINTS } from "./gpxExport";

// GPXの出力を見るテストのため、共有フィクスチャの空のgeometryへ既定の座標列を足す。
function makeCandidate(overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({
    geometry: {
      type: "LineString",
      coordinates: [
        [139.7, 35.7],
        [139.71, 35.71],
        [139.72, 35.72],
      ],
    },
    ...overrides,
  });
}

/** 東西に伸びるほぼ直線の座標列（約9m間隔）を作り、`detourAt`の位置だけ南へ張り出させる。 */
function straightLineWithDetours({
  length,
  detourAt,
  detourDeltaLat,
}: {
  length: number;
  detourAt: readonly number[];
  detourDeltaLat: number;
}): GeoJSON.Position[] {
  const detours = new Set(detourAt);
  return Array.from({ length }, (_, i) => [139.7 + i * 0.0001, 35.7 + (detours.has(i) ? detourDeltaLat : 0)]);
}

/** 元の各点が、間引き後の折れ線からどれだけ離れるか（m）の最大値。間引きの実装と同じ
 * 計算を共有すると実装の誤りごと通ってしまうため、ここで独立に測る。 */
function maxDeviationMeters(original: readonly GeoJSON.Position[], simplified: readonly GeoJSON.Position[]): number {
  const lonScale = Math.cos((35.7 * Math.PI) / 180);
  const toMeters = ([lon, lat]: GeoJSON.Position) => [lon * 111320 * lonScale, lat * 111320] as const;
  const segments = simplified.slice(0, -1).map((from, i) => [toMeters(from), toMeters(simplified[i + 1])] as const);
  return Math.max(
    ...original.map((position) => {
      const [px, py] = toMeters(position);
      return Math.min(
        ...segments.map(([[ax, ay], [bx, by]]) => {
          const dx = bx - ax;
          const dy = by - ay;
          const lengthSquared = dx * dx + dy * dy;
          const t = lengthSquared === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / lengthSquared;
          const clamped = Math.max(0, Math.min(1, t));
          return Math.hypot(px - (ax + clamped * dx), py - (ay + clamped * dy));
        })
      );
    })
  );
}

describe("simplifyCoordinates", () => {
  it("上限以下ならそのまま返す", () => {
    const coordinates: GeoJSON.Position[] = [
      [0, 0],
      [1, 1],
      [2, 2],
    ];
    expect(simplifyCoordinates(coordinates, 10)).toEqual(coordinates);
  });

  it("上限を超える場合は上限以下まで間引き、先頭・末尾は残す", () => {
    const coordinates: GeoJSON.Position[] = Array.from({ length: 2500 }, (_, i) => [i, i]);
    const result = simplifyCoordinates(coordinates, 1000);
    expect(result.length).toBeLessThanOrEqual(1000);
    expect(result[0]).toEqual(coordinates[0]);
    expect(result[result.length - 1]).toEqual(coordinates[coordinates.length - 1]);
  });

  it("残る点の間隔より短い区間に収まった曲がりを潰さない", () => {
    const coordinates = straightLineWithDetours({ length: 2000, detourAt: [1001], detourDeltaLat: -0.0005 });
    const result = simplifyCoordinates(coordinates, 1000);
    expect(result).toContainEqual(coordinates[1001]);
  });

  it("間引き後の折れ線が元の折れ線から大きく離れない", () => {
    // 直線区間が大半で、曲がりが点数の少ない張り出しとして現れる（実際の道なり形状と同じ）
    // 座標列を使う。等間隔に拾うと張り出しの頂点が落ち、その振幅ぶん元の形から離れる。
    const detourAt = Array.from({ length: 30 }, (_, i) => 100 * i + 51);
    const coordinates = straightLineWithDetours({ length: 3000, detourAt, detourDeltaLat: -0.0003 });
    const result = simplifyCoordinates(coordinates, 1000);
    expect(maxDeviationMeters(coordinates, result)).toBeLessThan(10);
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
