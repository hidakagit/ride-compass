// @vitest-environment node
import { describe, expect, it } from "vitest";
import { buildRoadSurfaceSharedLayerIds, isAxisStudioLayer, isDedicatedWayValueLayerId } from "./mapLayers";

describe("mapLayers（改善計画T440: axis_idハードコード比較の撤去）", () => {
  it("isDedicatedWayValueLayerId: 実データでdedicated_way_value_layer=trueのwindAxis/gradientAxisをtrueと判定する", () => {
    expect(isDedicatedWayValueLayerId("windAxis")).toBe(true);
    expect(isDedicatedWayValueLayerId("gradientAxis")).toBe(true);
  });

  it("isDedicatedWayValueLayerId: 専用way_id配信層を持たないレイヤーIDはfalse", () => {
    expect(isDedicatedWayValueLayerId("gradientFill")).toBe(false);
    expect(isDedicatedWayValueLayerId("roadType")).toBe(false);
    expect(isDedicatedWayValueLayerId("unknown-layer-id")).toBe(false);
  });

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
});
