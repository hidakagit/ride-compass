// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  buildMapLayers,
  buildRoadSurfaceSharedLayerIds,
  isAxisStudioLayer,
  mapOverlayExclusiveDomainFor,
  mapOverlayGroupFor,
} from "./mapLayers";

describe("mapLayers（改善計画T440: axis_idハードコード比較の撤去）", () => {
  it("isAxisStudioLayer: windAxis/gradientAxisはaxis_idのハードコード比較ではなくDEDICATED_WAY_VALUE_LAYER_IDS（軸データ由来）でtrueになる", () => {
    expect(isAxisStudioLayer({ id: "windAxis" })).toBe(true);
    expect(isAxisStudioLayer({ id: "gradientAxis" })).toBe(true);
  });

  it("isAxisStudioLayer: dataNature===\"composite\"（ramp軸）もtrue", () => {
    expect(isAxisStudioLayer({ id: "roadType", dataNature: "composite" })).toBe(true);
  });

  it("isAxisStudioLayer: どちらにも該当しないレイヤーはfalse", () => {
    expect(isAxisStudioLayer({ id: "route" })).toBe(false);
    expect(isAxisStudioLayer({ id: "roadType", dataNature: "raw" })).toBe(false);
  });

  // 改善計画T446: windAxisのみ含みgradientAxisを含まない非対称のまま残っていた回帰テスト。
  // 両方ともroad_surfaceタイル（promoteId付きway_id）を共有する専用way_id配信層のため、
  // regionZoomTooWide判定（MapView.tsx: isRoadSurfaceGroupVisible）の対象として対称に
  // 含まれていなければならない。
  it("buildRoadSurfaceSharedLayerIds: windAxis/gradientAxisを対称に含む", () => {
    const ids = buildRoadSurfaceSharedLayerIds([]);
    expect(ids).toContain("windAxis");
    expect(ids).toContain("gradientAxis");
  });

  describe("災害チップ（雷・竜巻・落雷・キキクル4種を1つへ統合）", () => {
    const layers = buildMapLayers([]);
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

    it("「環境」グループに並ぶが、排他ドメインには属さない", () => {
      // 他の環境レイヤー（降水・風・標高図）を選んでいる間も災害情報が消えないようにする。
      expect(mapOverlayGroupFor(byId.disaster)).toBe("environment");
      expect(mapOverlayExclusiveDomainFor(byId.disaster)).toBeUndefined();
      expect(mapOverlayExclusiveDomainFor(byId.precipitationNowcast)).toBe("area");
    });
  });
});
