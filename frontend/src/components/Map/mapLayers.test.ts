// @vitest-environment node
import { describe, expect, it } from "vitest";
import { DEDICATED_WAY_VALUE_AXES, dedicatedWayValueMapLayerId } from "./axisLayers";
import {
  buildDefaultLayerVisibility,
  buildMapLayers,
  deriveFetchLayerStatus,
  isAxisStudioLayer,
  mapOverlayGroupFor,
  tileZoomTooWideLayerIds,
} from "./mapLayers";
import { LANDCOVER_TILE_MIN_ZOOM, ROAD_TILE_MIN_ZOOM } from "@/services/regionApi";

describe("mapLayers（改善計画T440: axis_idハードコード比較の撤去）", () => {
  it("isAxisStudioLayer: 専用way値配信軸の記述子は、axis_idのハードコード比較ではなく軸カタログ由来のフラグでtrueになる", () => {
    const layers = buildMapLayers([], DEDICATED_WAY_VALUE_AXES);
    for (const axis of DEDICATED_WAY_VALUE_AXES) {
      const descriptor = layers.find((layer) => layer.id === dedicatedWayValueMapLayerId(axis.axisId));
      expect(descriptor).toBeDefined();
      expect(isAxisStudioLayer(descriptor!)).toBe(true);
    }
  });

  it('isAxisStudioLayer: dataNature==="composite"（ramp軸）もtrue', () => {
    expect(isAxisStudioLayer({ id: "roadType", dataNature: "composite" })).toBe(true);
  });

  it("isAxisStudioLayer: どちらにも該当しないレイヤーはfalse", () => {
    expect(isAxisStudioLayer({ id: "route" })).toBe(false);
    expect(isAxisStudioLayer({ id: "roadType", dataNature: "raw" })).toBe(false);
  });

  // 3件目の軸を軸スタジオで公開したときに、地図レイヤーの登録・地図UIからの除外が
  // すべて自動で追従すること（軸ごとのハードコードが残っていないこと）。
  it("軸スタジオで公開した3件目の専用way値配信軸へ自動追従する", () => {
    const extended = [
      ...DEDICATED_WAY_VALUE_AXES,
      { axisId: "surface_temp", label: "路面温度", needsTime: true, needsBearing: false, needsSpeed: false },
    ];
    const layerId = dedicatedWayValueMapLayerId("surface_temp");

    const descriptor = buildMapLayers([], extended).find((layer) => layer.id === layerId);
    expect(descriptor).toBeDefined();
    // 地図上チップ・サイドバーの両方から除外される（レンズだけが起動導線）。
    expect(isAxisStudioLayer(descriptor!)).toBe(true);
    expect(mapOverlayGroupFor(descriptor!)).toBeUndefined();
  });

  describe("災害チップ（雷・竜巻・落雷・キキクル4種を1つへ統合）", () => {
    const layers = buildMapLayers([], DEDICATED_WAY_VALUE_AXES);
    const byId = Object.fromEntries(layers.map((layer) => [layer.id, layer]));

    it('category="disaster"・dataNature="dynamic"のMapLayerDescriptorを1つだけ持つ', () => {
      expect(byId.disaster).toBeDefined();
      expect(byId.disaster.category).toBe("disaster");
      expect(byId.disaster.dataNature).toBe("dynamic");
      for (const removed of [
        "thunderNowcast",
        "tornadoNowcast",
        "liden",
        "landslideRisk",
        "heavyRainRisk",
        "inundationRisk",
        "floodRisk",
      ]) {
        expect(byId[removed]).toBeUndefined();
      }
    });

    it("「環境」グループに並ぶ（降水・風・標高図と同じグループ）", () => {
      expect(mapOverlayGroupFor(byId.disaster)).toBe("environment");
      expect(mapOverlayGroupFor(byId.precipitationNowcast)).toBe("environment");
    });
  });
});

// --- deriveFetchLayerStatus（"empty"は「読込済みだが値なし」だけを指す） ---

describe("deriveFetchLayerStatus", () => {
  it("まだ取りに行っていない間は状態を返さない（未取得を「データがありません」と断定しない）", () => {
    // レイヤーを有効化した直後や、配線ミスでフェッチ自体が走っていない状態がここに該当する。
    expect(deriveFetchLayerStatus(false, null, false, false)).toBeUndefined();
  });

  it("取得を終えて値が無ければempty", () => {
    expect(deriveFetchLayerStatus(false, null, false, true)).toBe("empty");
  });

  it("取得を終えて値があれば状態を返さない", () => {
    expect(deriveFetchLayerStatus(false, null, true, true)).toBeUndefined();
  });

  it("読込中はloading（取得済みかどうかによらない）", () => {
    expect(deriveFetchLayerStatus(true, null, false, false)).toBe("loading");
    expect(deriveFetchLayerStatus(true, null, false, true)).toBe("loading");
  });

  it("エラーが最優先", () => {
    expect(deriveFetchLayerStatus(true, "failed", true, true)).toBe("error");
    expect(deriveFetchLayerStatus(false, "failed", false, false)).toBe("error");
  });
});

describe("既定ONのレイヤー", () => {
  it("記述子を持つレイヤーには必ず初期値がある（レイヤーを足しても書き足す場所が無い）", () => {
    const visibility = buildDefaultLayerVisibility();

    for (const layer of buildMapLayers([], [])) {
      expect(visibility).toHaveProperty(layer.id);
    }
  });

  it("地図を覆う静的レイヤーで既定ONなのは防災級のものだけ", () => {
    // 既定ONは性質で決める。ここが「1つずつ手で書く」形に戻ると、防災系が2つ目に増えた
    // ときに片方だけONという説明できない状態が生まれる。
    const onByNature = buildMapLayers([], [])
      .filter((layer) => layer.kind === "static" && layer.defaultOn === true)
      .map((layer) => layer.category);

    expect(new Set(onByNature)).toEqual(new Set(["disaster"]));
  });

  it("軸スタジオ由来のレイヤーは初期値を持たない（表示はレンズだけが決める）", () => {
    const visibility = buildDefaultLayerVisibility();

    for (const layer of buildMapLayers([], DEDICATED_WAY_VALUE_AXES)) {
      if (!isAxisStudioLayer(layer)) continue;
      expect(visibility).not.toHaveProperty(layer.id);
    }
  });
});

describe("タイルの最小ズーム（ズーム不足の案内）", () => {
  it("宣言したレイヤーは、そのズームを下回ると全件が対象になる", () => {
    // 同じタイルを共有するのに一部のレイヤーだけ案内が出ない、という状態を作らせない。
    const declared = buildMapLayers([], []).filter((layer) => layer.tileMinZoom !== undefined);
    expect(declared.length).toBeGreaterThan(0);

    const widest = Math.min(...declared.map((layer) => layer.tileMinZoom!));
    const tooWide = tileZoomTooWideLayerIds(widest - 0.5);

    expect([...tooWide].sort()).toEqual(declared.map((layer) => layer.id).sort());
  });

  it("宣言していないレイヤーは、どれだけ広げても対象にならない", () => {
    const undeclared = buildMapLayers([], [])
      .filter((layer) => layer.tileMinZoom === undefined)
      .map((layer) => layer.id);
    expect(undeclared.length).toBeGreaterThan(0);

    const tooWide = tileZoomTooWideLayerIds(0);

    for (const id of undeclared) {
      expect(tooWide).not.toContain(id);
    }
  });

  it("充分に寄れば1件も対象にならない", () => {
    const deepest = Math.max(
      ...buildMapLayers([], [])
        .filter((layer) => layer.tileMinZoom !== undefined)
        .map((layer) => layer.tileMinZoom!),
    );

    expect(tileZoomTooWideLayerIds(deepest)).toEqual([]);
  });

  it("道路タイルと土地被覆タイルの閾値を、それぞれの配信元の値から取っている", () => {
    const byId = Object.fromEntries(buildMapLayers([], []).map((layer) => [layer.id, layer]));

    expect(byId.roadSurface.tileMinZoom).toBe(ROAD_TILE_MIN_ZOOM);
    expect(byId.landcover.tileMinZoom).toBe(LANDCOVER_TILE_MIN_ZOOM);
  });

  it("POIタイル由来のレイヤーも閾値を宣言している（ONにしても何も出ないズームで案内が出る）", () => {
    // POIタイルは道路タイルと同じズーム範囲で配信される。宣言が無いと、広域でONにした
    // 利用者には「出ない理由」が何も示されない。
    const byId = Object.fromEntries(buildMapLayers([], []).map((layer) => [layer.id, layer]));

    expect(byId.stopPoi.tileMinZoom).toBe(ROAD_TILE_MIN_ZOOM);
    expect(byId.supplyPoi.tileMinZoom).toBe(ROAD_TILE_MIN_ZOOM);
    expect(tileZoomTooWideLayerIds(ROAD_TILE_MIN_ZOOM - 0.5)).toEqual(expect.arrayContaining(["stopPoi", "supplyPoi"]));
  });
});
