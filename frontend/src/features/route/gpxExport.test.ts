/**
 * `features/route/gpxExport.ts: downloadGpx`——候補1本をGPX（`<trk>`1本）のファイルとして落とす。
 * - ファイル: 名前は`ridecompass-<候補のid>.gpx`、種類は`application/gpx+xml`。落としたあとにリンクとURLを片付ける
 * - 中身: トラックの名前（方位と距離。XMLの特殊文字は逃がす）と、経路の点を順に並べたもの
 * - 点が上限より多い経路は上限以下へ間引く。残す点は折れ線の形から選び、両端は必ず残す。ずれは東西も南北も
 *   実際の距離で測る
 *
 * ここで見ないもの:
 * - どの候補をいつ書き出すか（ボタン） → `RouteOutcome/RouteOutcome.test.tsx`
 *
 * 差し替えたもの: ブラウザにファイルを保存させるところ（リンクの`click`と`URL.createObjectURL`・`URL.revokeObjectURL`）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeRouteCandidate } from "@/testing/routeFixtures";
import type { RouteCandidate } from "@/types/route";

import { downloadGpx } from "./gpxExport";

const METERS_PER_DEGREE_LATITUDE = 111_320;

interface Download {
  fileName: string;
  href: string;
  attached: boolean;
  blob: Blob;
}

let downloads: Download[];
let createdBlobs: Map<string, Blob>;

beforeEach(() => {
  downloads = [];
  createdBlobs = new Map();
  vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
    const url = `blob:gpx-${createdBlobs.size}`;
    createdBlobs.set(url, blob as Blob);
    return url;
  });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation((url) => {
    createdBlobs.delete(url);
  });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    const blob = createdBlobs.get(this.href);
    if (!blob) throw new Error(`落とすときにURLが生きていない: ${this.href}`);
    downloads.push({ fileName: this.download, href: this.href, attached: document.body.contains(this), blob });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function candidate(coordinates: GeoJSON.Position[], overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({
    id: "route-1",
    direction_label: "北",
    distance_km: 12.345,
    geometry: { type: "LineString", coordinates },
    ...overrides,
  });
}

/** 書き出して、落としたファイルの中身を読む。 */
async function exportGpx(route: RouteCandidate) {
  downloadGpx(route);
  expect(downloads).toHaveLength(1);
  const xml = await downloads[0].blob.text();
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  const points = [...doc.getElementsByTagName("trkpt")].map((p) => [
    Number(p.getAttribute("lon")),
    Number(p.getAttribute("lat")),
  ]);
  return { xml, doc, points };
}

/** (lon, lat)から東へ`eastM`・北へ`northM`進んだ点。 */
function offset([lon, lat]: GeoJSON.Position, eastM: number, northM: number): GeoJSON.Position {
  return [
    lon + eastM / (METERS_PER_DEGREE_LATITUDE * Math.cos((lat * Math.PI) / 180)),
    lat + northM / METERS_PER_DEGREE_LATITUDE,
  ];
}

/** 起点から1点ごとに東へ`stepEastM`・北へ`stepNorthM`ずつ進む`count`点の直線。 */
function straightLine(count: number, stepEastM: number, stepNorthM: number): GeoJSON.Position[] {
  const start: GeoJSON.Position = [139.7, 35.6];
  return Array.from({ length: count }, (_, i) => offset(start, stepEastM * i, stepNorthM * i));
}

describe("downloadGpx", () => {
  it("候補のidを名前に持つGPXのファイルを落とし、落としたあとはリンクを外してURLを捨てる", () => {
    downloadGpx(
      candidate([
        [139.7, 35.6],
        [139.71, 35.61],
      ]),
    );
    expect(downloads).toEqual([expect.objectContaining({ fileName: "ridecompass-route-1.gpx", attached: true })]);
    expect(downloads[0].blob.type).toBe("application/gpx+xml");
    expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(downloads[0].href);
  });

  it("GPX 1.1のトラック1本に、方位と距離（小数1桁）の名前と、経路の点を順に並べる", async () => {
    const coordinates = [
      [139.7, 35.6],
      [139.705, 35.602],
      [139.71, 35.61],
    ];
    const { doc, points } = await exportGpx(candidate(coordinates));
    expect(doc.documentElement.tagName).toBe("gpx");
    expect(doc.documentElement.getAttribute("version")).toBe("1.1");
    expect(doc.getElementsByTagName("trk")).toHaveLength(1);
    expect(doc.getElementsByTagName("rte")).toHaveLength(0);
    expect(doc.querySelector("trk > name")?.textContent).toBe("RideCompass 北 12.3km");
    expect(points).toEqual(coordinates);
  });

  it("名前に含まれるXMLの特殊文字は逃がして書く", async () => {
    const { xml, doc } = await exportGpx(
      candidate(
        [
          [139.7, 35.6],
          [139.71, 35.61],
        ],
        { direction_label: `<北&"東">` },
      ),
    );
    expect(xml).toContain("<name>RideCompass &lt;北&amp;&quot;東&quot;&gt; 12.3km</name>");
    expect(doc.querySelector("trk > name")?.textContent).toBe(`RideCompass <北&"東"> 12.3km`);
  });

  it("上限ちょうどの点数なら、一直線でも間引かない", async () => {
    const line = straightLine(1000, 5, 0);
    const { points } = await exportGpx(candidate(line));
    expect(points).toEqual(line);
  });

  it("上限を超える点数なら、一直線の途中の点は落として両端だけを残す", async () => {
    const line = straightLine(1001, 5, 0);
    const { points } = await exportGpx(candidate(line));
    expect(points).toEqual([line[0], line[1000]]);
  });

  it("上限を超える点数なら、曲がり角は残す", async () => {
    // 東へ600点進んでから北へ600点進む。
    const east = straightLine(600, 5, 0);
    const north = Array.from({ length: 600 }, (_, i) => offset(east[599], 0, 5 * (i + 1)));
    const route = [...east, ...north];
    const { points } = await exportGpx(candidate(route));
    expect(points).toEqual([route[0], route[599], route[1199]]);
  });

  it("始点と終点が同じ周回でも、上限以下へ間引いて角を残す", async () => {
    // 1辺300点の正方形を一周して始点へ戻る。
    const corners: GeoJSON.Position[] = [[139.7, 35.6]];
    const route: GeoJSON.Position[] = [];
    for (const [east, north] of [
      [5, 0],
      [0, 5],
      [-5, 0],
      [0, -5],
    ]) {
      const from = corners.at(-1)!;
      for (let i = 0; i < 300; i += 1) route.push(offset(from, east * i, north * i));
      corners.push(offset(from, east * 300, north * 300));
    }
    route.push(route[0]);
    const { points } = await exportGpx(candidate(route));
    expect(points.length).toBeLessThanOrEqual(1000);
    expect(points[0]).toEqual(route[0]);
    expect(points.at(-1)).toEqual(route[0]);
    for (const index of [300, 600, 900]) expect(points).toContainEqual(route[index]);
  });

  it("細かく揺れる経路で形を保てる点が上限より多くても、上限以下へ収め、両端を残す", async () => {
    const route = straightLine(3000, 5, 0).map((point, i) => offset(point, 0, i % 2 === 0 ? 0 : 40));
    const { points } = await exportGpx(candidate(route));
    expect(points.length).toBeLessThanOrEqual(1000);
    expect(points.length).toBeGreaterThanOrEqual(2);
    expect(points[0]).toEqual(route[0]);
    expect(points.at(-1)).toEqual(route.at(-1));
  });

  it("東西へのずれも南北へのずれも、同じ実際の距離なら同じく残す・落とす", async () => {
    const outcomes = new Set<boolean>();
    for (const bumpM of [1, 2, 2.9, 3.1, 4, 6, 10]) {
      // 東西へ伸びる直線の真ん中を北へずらしたものと、南北へ伸びる直線の真ん中を東へずらしたもの。
      const eastWest = straightLine(1001, 5, 0);
      eastWest[500] = offset(eastWest[500], 0, bumpM);
      const northSouth = straightLine(1001, 0, 5);
      northSouth[500] = offset(northSouth[500], bumpM, 0);
      const keptEastWest = (await exportGpx(candidate(eastWest))).points.some((p) => p[1] === eastWest[500][1]);
      downloads = [];
      const keptNorthSouth = (await exportGpx(candidate(northSouth))).points.some((p) => p[0] === northSouth[500][0]);
      downloads = [];
      expect(keptNorthSouth, `${bumpM}m`).toBe(keptEastWest);
      outcomes.add(keptEastWest);
    }
    // ずれの大きさで、落とすと残すの両方が起きている。
    expect([...outcomes].sort()).toEqual([false, true]);
  });
});
