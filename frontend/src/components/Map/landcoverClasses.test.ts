// @vitest-environment node
import { describe, expect, it } from "vitest";
import { LANDCOVER_CLASSES } from "./landcoverClasses";
import { buildMapLayers, mapOverlayGroupFor } from "./mapLayers";
import { LANDCOVER_TILE_MAX_ZOOM, LANDCOVER_TILE_MIN_ZOOM, landcoverTileUrl } from "@/services/regionApi";

describe("土地被覆レイヤー", () => {
  it("クラスの表示名・色はbackendの生成物から来る（凡例と地図の塗りが同じ値を見る）", () => {
    expect(LANDCOVER_CLASSES.length).toBeGreaterThan(0);
    for (const cls of LANDCOVER_CLASSES) {
      expect(cls.label).not.toBe("");
      expect(cls.color).toMatch(/^#[0-9A-Fa-f]{6}$/);
      expect(cls.percentField).toMatch(/_percent$/);
    }
    // 同じ割合列を2つのクラスが名乗ると、区間インスペクタの行が重複する。
    const fields = LANDCOVER_CLASSES.map((cls) => cls.percentField);
    expect(new Set(fields).size).toBe(fields.length);
    // 画素値も重複しない（重なると後勝ちで塗り分けが消える）。
    const values = LANDCOVER_CLASSES.map((cls) => cls.value);
    expect(new Set(values).size).toBe(values.length);
  });

  it("タイルURLは世代を持つ（ラスタ差し替え時に古いタイルを踏まない）", () => {
    expect(landcoverTileUrl()).toContain("/api/region/landcover-tiles/{z}/{x}/{y}.png?v=");
  });

  it("ズーム範囲はbackendの生成物から来る", () => {
    expect(LANDCOVER_TILE_MIN_ZOOM).toBeLessThan(LANDCOVER_TILE_MAX_ZOOM);
  });

  it("地図チップの「環境」グループに属する（標高図と同じ、地域に固定の面レイヤー）", () => {
    const descriptor = buildMapLayers([], []).find((layer) => layer.id === "landcover");
    expect(descriptor).toBeDefined();
    expect(mapOverlayGroupFor(descriptor!)).toBe("environment");
  });
});
