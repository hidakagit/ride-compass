// @vitest-environment node
import { describe, expect, it } from "vitest";
import { boundsOf, tilesToGeojson } from "./SplitCoverageMap";
import { tileBoundsLonLat } from "@/components/Map/dynamicWayValues";

const TILES = [
  { zoom: 12, x: 3636, y: 1611, fetched_at: "2026-08-14T12:44:03Z" },
  { zoom: 12, x: 3637, y: 1612, fetched_at: "2026-08-14T12:44:03Z" },
];

describe("SplitCoverageMap", () => {
  it("タイル座標を境界ポリゴンへ写す（座標変換を自前で持たない）", () => {
    const geojson = tilesToGeojson(TILES);

    expect(geojson.features).toHaveLength(2);
    const ring = (geojson.features[0].geometry as GeoJSON.Polygon).coordinates[0];
    const bounds = tileBoundsLonLat(12, 3636, 1611);
    // 閉じた矩形（先頭と末尾が同じ点）。
    expect(ring).toHaveLength(5);
    expect(ring[0]).toEqual([bounds.west, bounds.north]);
    expect(ring[4]).toEqual(ring[0]);
  });

  it("全タイルを覆う範囲を返す（初期表示で全体が入る必要がある）", () => {
    const bounds = boundsOf(TILES);

    expect(bounds).not.toBeNull();
    const [[west, south], [east, north]] = bounds!;
    const first = tileBoundsLonLat(12, 3636, 1611);
    const second = tileBoundsLonLat(12, 3637, 1612);
    expect(west).toBeCloseTo(Math.min(first.west, second.west));
    expect(east).toBeCloseTo(Math.max(first.east, second.east));
    expect(south).toBeCloseTo(Math.min(first.south, second.south));
    expect(north).toBeCloseTo(Math.max(first.north, second.north));
  });

  it("タイルが1件も無ければ範囲は無い（地図を空の範囲へ合わせない）", () => {
    expect(boundsOf([])).toBeNull();
  });

  it("実データの座標が日本の範囲に収まる（XYZの軸を取り違えていない）", () => {
    // z12/3636/1611 は東京都心付近。x/yを入れ替えると全く別の場所になるため、
    // 変換そのものより「どの軸をどこへ渡すか」を間違えていないことを見る。
    const bounds = tileBoundsLonLat(12, 3636, 1611);
    expect(bounds.west).toBeGreaterThan(138);
    expect(bounds.east).toBeLessThan(141);
    expect(bounds.south).toBeGreaterThan(34);
    expect(bounds.north).toBeLessThan(37);
  });
});
