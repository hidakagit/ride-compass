// @vitest-environment node
import { describe, expect, it } from "vitest";
import { DEDICATED_WAY_VALUE_AXES, dedicatedWayValueMapLayerId } from "./axisLayers";
import {
  buildMapLayers,
  buildRoadSurfaceSharedLayerIds,
  deriveFetchLayerStatus,
  isAxisStudioLayer,
  mapOverlayGroupFor,
} from "./mapLayers";

describe("mapLayers（改善計画T440: axis_idハードコード比較の撤去）", () => {
  it("isAxisStudioLayer: 専用way値配信軸の記述子は、axis_idのハードコード比較ではなく軸カタログ由来のフラグでtrueになる", () => {
    const layers = buildMapLayers([], DEDICATED_WAY_VALUE_AXES);
    for (const axis of DEDICATED_WAY_VALUE_AXES) {
      const descriptor = layers.find((layer) => layer.id === dedicatedWayValueMapLayerId(axis.axisId));
      expect(descriptor).toBeDefined();
      expect(isAxisStudioLayer(descriptor!)).toBe(true);
    }
  });

  it("isAxisStudioLayer: dataNature===\"composite\"（ramp軸）もtrue", () => {
    expect(isAxisStudioLayer({ id: "roadType", dataNature: "composite" })).toBe(true);
  });

  it("isAxisStudioLayer: どちらにも該当しないレイヤーはfalse", () => {
    expect(isAxisStudioLayer({ id: "route" })).toBe(false);
    expect(isAxisStudioLayer({ id: "roadType", dataNature: "raw" })).toBe(false);
  });

  // 専用way値配信軸（dedicated_way_value_layer=true）はどれも同じroad_surfaceタイル
  // （promoteId付きway_id）を共有するため、regionZoomTooWide判定
  // （MapView.tsx: isRoadSurfaceGroupVisible）の対象として軸の件数に関係なく全件が
  // 含まれていなければならない。
  it("buildRoadSurfaceSharedLayerIds: 専用way値配信軸を件数によらず全件含む", () => {
    const ids = buildRoadSurfaceSharedLayerIds([], DEDICATED_WAY_VALUE_AXES);
    for (const axis of DEDICATED_WAY_VALUE_AXES) {
      expect(ids).toContain(dedicatedWayValueMapLayerId(axis.axisId));
    }
    expect(DEDICATED_WAY_VALUE_AXES.map((axis) => axis.axisId)).toEqual(
      expect.arrayContaining(["wind", "gradient"])
    );
  });

  // 3件目の軸を軸スタジオで公開したときに、地図レイヤーの登録・ズーム範囲外判定・
  // 地図UIからの除外がすべて自動で追従すること（軸ごとのハードコードが残っていないこと）。
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
    // 「表示範囲が広すぎます」判定の対象にも含まれる。
    expect(buildRoadSurfaceSharedLayerIds([], extended)).toContain(layerId);
  });

  describe("災害チップ（雷・竜巻・落雷・キキクル4種を1つへ統合）", () => {
    const layers = buildMapLayers([], DEDICATED_WAY_VALUE_AXES);
    const byId = Object.fromEntries(layers.map((layer) => [layer.id, layer]));

    it("category=\"disaster\"・dataNature=\"dynamic\"のMapLayerDescriptorを1つだけ持つ", () => {
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
