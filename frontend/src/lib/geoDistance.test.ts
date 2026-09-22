// @vitest-environment node
import { describe, expect, it } from "vitest";
import { cumulativeDistancesKm, haversineKm } from "./geoDistance";

// 緯度1度はおよそ111km。桁と単位（km）を取り違えていないことを、既知の値で押さえる。
describe("haversineKm", () => {
  it("同じ点は0", () => {
    expect(haversineKm({ latitude: 35.68, longitude: 139.76 }, { latitude: 35.68, longitude: 139.76 })).toBe(0);
  });

  it("緯度1度ぶんはおよそ111km", () => {
    const km = haversineKm({ latitude: 35, longitude: 139 }, { latitude: 36, longitude: 139 });
    expect(km).toBeGreaterThan(110);
    expect(km).toBeLessThan(112);
  });
});

describe("cumulativeDistancesKm", () => {
  const line: GeoJSON.Position[] = [
    [139, 35],
    [139, 35.1],
    [139, 35.2],
  ];

  it("座標と同じ長さで、先頭は0・末尾は各辺の和", () => {
    const cumulative = cumulativeDistancesKm(line);

    expect(cumulative).toHaveLength(line.length);
    expect(cumulative[0]).toBe(0);
    expect(cumulative.at(-1)).toBeGreaterThan(22);
    expect(cumulative.at(-1)).toBeLessThan(23);
  });

  it("点が1つ以下なら0だけ", () => {
    expect(cumulativeDistancesKm([[139, 35]])).toEqual([0]);
  });
});
