import { describe, expect, it, vi } from "vitest";
import type { RouteCandidate } from "@/types/route";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import { downloadGpx } from "./gpxExport";

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

/** `downloadGpx`が実際に書き出した中身。**組み立ての途中へ口を開けない**——間引きも整形も、
 * 出口から見れば同じ1本の結果として確かめられる。 */
async function exportedGpx(candidate: RouteCandidate): Promise<string> {
  const createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
  vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
  const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

  downloadGpx(candidate);

  const blob = createObjectURL.mock.calls[0][0] as Blob;
  const xml = await blob.text();
  clickSpy.mockRestore();
  vi.unstubAllGlobals();
  return xml;
}

/** 書き出されたGPXの軌跡点を、GeoJSONと同じ[lon, lat]の並びで取り出す。 */
async function exportedCoordinates(coordinates: readonly GeoJSON.Position[]): Promise<GeoJSON.Position[]> {
  const xml = await exportedGpx(
    makeCandidate({ geometry: { type: "LineString", coordinates: [...coordinates] } }),
  );
  return [...xml.matchAll(/<trkpt lat="([-0-9.]+)" lon="([-0-9.]+)"\/>/g)].map(([, lat, lon]) => [
    Number(lon),
    Number(lat),
  ]);
}

// 座標の間引きは`downloadGpx`の途中段階で、外へ口を持たない。ここで見ているのは
// 「書き出されたGPXの軌跡点」で、間引きの結果がそのまま現れる。
describe("軌跡点の間引き", () => {
  it("少ない座標列はそのまま全部出る", async () => {
    const coordinates: GeoJSON.Position[] = [
      [139.7, 35.7],
      [139.71, 35.71],
      [139.72, 35.72],
    ];

    expect(await exportedCoordinates(coordinates)).toEqual(coordinates);
  });

  it("長い座標列は間引かれ、先頭・末尾は残る", async () => {
    const coordinates = straightLineWithDetours({ length: 2500, detourAt: [], detourDeltaLat: 0 });

    const result = await exportedCoordinates(coordinates);

    expect(result.length).toBeLessThan(coordinates.length);
    expect(result[0]).toEqual(coordinates[0]);
    expect(result.at(-1)).toEqual(coordinates.at(-1));
  });

  it("さらに長くしても軌跡点は増えない（上限で頭打ち）", async () => {
    // 上限の値は借りない。借りると、上限を変えたときテストも一緒に動いて
    // 「頭打ちになる」ことを誰も見なくなる。
    const shorter = await exportedCoordinates(straightLineWithDetours({ length: 2500, detourAt: [], detourDeltaLat: 0 }));
    const longer = await exportedCoordinates(straightLineWithDetours({ length: 5000, detourAt: [], detourDeltaLat: 0 }));

    expect(longer.length).toBeLessThanOrEqual(shorter.length);
  });

  it("残る点の間隔より短い区間に収まった曲がりを潰さない", async () => {
    const coordinates = straightLineWithDetours({ length: 2000, detourAt: [1001], detourDeltaLat: -0.0005 });

    expect(await exportedCoordinates(coordinates)).toContainEqual(coordinates[1001]);
  });

  it("間引き後の折れ線が元の折れ線から大きく離れない", async () => {
    // 直線区間が大半で、曲がりが点数の少ない張り出しとして現れる（実際の道なり形状と同じ）
    // 座標列を使う。等間隔に拾うと張り出しの頂点が落ち、その振幅ぶん元の形から離れる。
    const detourAt = Array.from({ length: 30 }, (_, i) => 100 * i + 51);
    const coordinates = straightLineWithDetours({ length: 3000, detourAt, detourDeltaLat: -0.0003 });

    const result = await exportedCoordinates(coordinates);

    expect(maxDeviationMeters(coordinates, result)).toBeLessThan(10);
  });
});

describe("書き出すGPXの形", () => {
  it("trk/trksegを持ち、rte/wptは使わない（Suuntoがtrk以外を取り込めないため）", async () => {
    const xml = await exportedGpx(makeCandidate());

    expect(xml).toContain("<trk>");
    expect(xml).toContain("<trkseg>");
    expect(xml).not.toContain("<rte>");
    expect(xml).not.toContain("<wpt");
  });

  it("GeoJSONの[lon, lat]順をGPXのlat/lon属性へ正しく入れ替える", async () => {
    const xml = await exportedGpx(makeCandidate());

    expect(xml).toContain('<trkpt lat="35.7" lon="139.7"/>');
    expect(xml).toContain('<trkpt lat="35.72" lon="139.72"/>');
  });

  it("方位ラベルと距離を<name>に含める", async () => {
    const xml = await exportedGpx(makeCandidate({ direction_label: "南東", distance_km: 45.6 }));

    expect(xml).toContain("<name>RideCompass 南東 45.6km</name>");
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
