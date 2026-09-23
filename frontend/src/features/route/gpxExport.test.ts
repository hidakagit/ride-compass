import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeRouteCandidate } from "@/testing/routeFixtures";

import { downloadGpx } from "./gpxExport";

// GPXの中身は`downloadGpx`が作るBlobから読む（ファイルを作る入口はこの関数だけ）。
let blobs: Blob[];
let clicked: HTMLAnchorElement[];

beforeEach(() => {
  blobs = [];
  clicked = [];
  vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
    blobs.push(blob as Blob);
    return "blob:gpx";
  });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicked.push(this);
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function exportGpx(coordinates: GeoJSON.Position[], overrides = {}) {
  downloadGpx(
    makeRouteCandidate({
      id: "c1",
      direction_label: "北",
      distance_km: 30,
      geometry: { type: "LineString", coordinates },
      ...overrides,
    }),
  );
  const xml = await blobs[0].text();
  const points = [...xml.matchAll(/<trkpt lat="([^"]+)" lon="([^"]+)"\/>/g)].map((m) => [Number(m[2]), Number(m[1])]);
  return { xml, points };
}

/** 東へ一直線に並ぶn点（約1m間隔）。 */
function straightLine(n: number): GeoJSON.Position[] {
  return Array.from({ length: n }, (_, i) => [139.7 + i * 0.00001, 35.6]);
}

describe("downloadGpx", () => {
  it("候補のidを名前に持つGPXファイルを1回ダウンロードさせ、使ったリンクとURLを片付ける", async () => {
    await exportGpx(straightLine(3));
    expect(blobs).toHaveLength(1);
    expect(blobs[0].type).toBe("application/gpx+xml");
    expect(clicked).toHaveLength(1);
    expect(clicked[0].download).toBe("ridecompass-c1.gpx");
    expect(clicked[0].href).toBe("blob:gpx");
    expect(clicked[0].isConnected).toBe(false);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:gpx");
  });

  it("点は<trk>のトラック点として、経路の順に緯度・経度で書く（GarminとSuuntoの両方が取り込める形）", async () => {
    const coordinates = [
      [139.7, 35.6],
      [139.71, 35.61],
      [139.72, 35.6],
    ];
    const { xml, points } = await exportGpx(coordinates);
    expect(xml).toContain("<trk>");
    expect(xml).not.toContain("<rte>");
    expect(points).toEqual(coordinates);
  });

  it("名前は方向と距離（小数1桁）。XMLの特殊文字は書き換える", async () => {
    const { xml } = await exportGpx(straightLine(2), { direction_label: `北&<東>"`, distance_km: 42.26 });
    expect(xml).toContain("<name>RideCompass 北&amp;&lt;東&gt;&quot; 42.3km</name>");
  });

  it("1000点以下なら間引かない", async () => {
    const coordinates = straightLine(1000);
    const { points } = await exportGpx(coordinates);
    expect(points).toEqual(coordinates);
  });

  it("1000点を超えたら1000点以下へ間引き、両端は残す", async () => {
    const coordinates = straightLine(3000);
    const { points } = await exportGpx(coordinates);
    expect(points.length).toBeLessThanOrEqual(1000);
    expect(points[0]).toEqual(coordinates[0]);
    expect(points.at(-1)).toEqual(coordinates.at(-1));
  });

  it("間引いても曲がり角は残す（点の間隔より短い曲がりも直線に潰さない）", async () => {
    const coordinates = straightLine(3000);
    const corner: GeoJSON.Position = [coordinates[1500][0], 35.6 + 0.0005];
    coordinates[1500] = corner;
    const { points } = await exportGpx(coordinates);
    expect(points).toContainEqual(corner);
  });

  it("どの点も形に効いていても、上限に収まるまで許すずれを広げて1000点以下にする", async () => {
    // 東へ進みながら南北へ約11mずつ振れるジグザグ。どの点も隣の2点を結ぶ線から3m以上外れる。
    // 上限を少し超える点数にする（間引きは点の数の2乗で重くなる）。
    const coordinates = Array.from({ length: 1200 }, (_, i) => [139.7 + i * 0.00001, 35.6 + (i % 2) * 0.0001]);
    const { points } = await exportGpx(coordinates);
    expect(points.length).toBeLessThanOrEqual(1000);
    expect(points[0]).toEqual(coordinates[0]);
    expect(points.at(-1)).toEqual(coordinates.at(-1));
  });

  it("周回（始点と終点が同じ点）でも、形を潰さずに間引く", async () => {
    // 半径約1kmの円を1周して始点へ戻る3001点。
    const coordinates = Array.from({ length: 3001 }, (_, i) => {
      const angle = (i / 3000) * 2 * Math.PI;
      return [139.7 + 0.011 * Math.cos(angle), 35.6 + 0.009 * Math.sin(angle)];
    });
    coordinates[3000] = coordinates[0];
    const { points } = await exportGpx(coordinates);
    expect(points.length).toBeLessThanOrEqual(1000);
    // 円の反対側（半周の点）まで届いている＝始点と終点だけに潰れていない。
    expect(points.some(([lon]) => lon < 139.7 - 0.01)).toBe(true);
  });
});
