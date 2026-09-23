// @vitest-environment node
// `overlayChips.ts`——地図上チップ1枚ずつの状態と、レイヤーのON/OFFから導く地図側の値。
//
// ここで見ないもの:
// - チップの描き方・▶パネルの開閉 → `MapOverlayControls.test.tsx`
// - 絞り込みの宣言（道路の線・点の凡例の中身）→ `scene/legends.test.ts`
import { describe, expect, it } from "vitest";

import {
  buildDefaultLayerVisibility,
  type MapLayerDescriptor,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import type { SecondaryAxisSummary } from "@/components/Map/secondaryAxes";
import type { OverlayLayerChip } from "@/components/MapOverlayControls/MapOverlayControls";
import { mapDisplay } from "@/types/generated/mapDisplay";
import { primaryAttributes } from "@/types/generated/primaryAttributes";

import {
  deserializeLayerVisibility,
  hasVisibleLegendFilter,
  layerVisibilityChanged,
  overlayChips,
  secondaryAxisCasingLayerIds,
  serializeLayerVisibility,
  versionMissingStatus,
} from "./overlayChips";

const ICON = (() => null) as unknown as MapLayerDescriptor["icon"];

// 架空のレイヤー。idは型を満たすために`MapLayerId`へ寄せるだけで、実在のレイヤーを指さない。
function layer(id: string, overrides: Partial<MapLayerDescriptor> = {}): MapLayerDescriptor {
  return {
    id: id as MapLayerId,
    label: id,
    kind: "static",
    icon: ICON,
    dataSource: "ownFetch",
    description: `${id}の説明`,
    ...overrides,
  };
}

function chipsOf(options: Partial<Parameters<typeof overlayChips>[0]> & { layers: MapLayerDescriptor[] }) {
  return overlayChips({
    visibility: {} as MapLayerVisibility,
    dataStatus: {},
    versionMissingLayerIds: [],
    zoomTooWideLayerIds: [],
    hidden: {},
    screenLegends: {},
    hasRoutes: true,
    ...options,
  });
}

const A = "layer_a" as MapLayerId;

describe("チップの案内", () => {
  it("世代が届いていないレイヤーには、ズーム不足より先に世代の案内を出す", () => {
    const [chip] = chipsOf({ layers: [layer(A)], versionMissingLayerIds: [A], zoomTooWideLayerIds: [A] });
    expect(chip.notice).toBe("配信情報を取得できず表示できません");
  });

  it("ズーム不足のレイヤーには、ONかどうかに関わらずズームの案内を出す", () => {
    const [chip] = chipsOf({ layers: [layer(A)], zoomTooWideLayerIds: [A] });
    expect(chip.on).toBe(false);
    expect(chip.notice).toBe("ズームインすると表示されます");
  });

  it("どちらでもなければ案内を出さない", () => {
    expect(chipsOf({ layers: [layer(A)] })[0].notice).toBeNull();
  });
});

describe("versionMissingStatus（世代が無いレイヤーの状態ドット）", () => {
  it("カタログを取りに行っている間は読み込み中、取り終えたのに世代が無ければ失敗", () => {
    expect(versionMissingStatus([A], false)).toEqual({ [A]: "loading" });
    expect(versionMissingStatus([A], true)).toEqual({ [A]: "error" });
  });
});

describe("チップの母集団", () => {
  it("軸スタジオ由来のレイヤーはチップにしない", () => {
    const chips = chipsOf({
      layers: [layer(A), layer("dedicated", { axisStudioLayer: true }), layer("ramp", { dataNature: "composite" })],
    });
    expect(chips.map((chip) => chip.id)).toEqual([A]);
  });

  it("ルートにひもづくレイヤーは、候補が無い間は押せない", () => {
    const route = layer("route_like", { kind: "dynamic" });
    expect(chipsOf({ layers: [route], hasRoutes: false })[0].disabled).toBe(true);
    expect(chipsOf({ layers: [route], hasRoutes: true })[0].disabled).toBe(false);
  });
});

describe("チップの凡例（▶パネル）", () => {
  const legend = [
    { key: "k1", label: "1", color: "#111" },
    { key: "k2", label: "2", color: "#222" },
  ];

  it("絞り込める凡例には、いま凡例に実在する隠した鍵だけを渡す", () => {
    const [chip] = chipsOf({
      layers: [layer(A)],
      hidden: { saved: ["k1", "gone"] },
      screenLegends: { [A]: [{ label: "", legend, axisId: "saved" }] },
    });
    expect(chip.legendDetails).toEqual([{ label: "", legend, hiddenKeys: ["k1"], axisId: "saved" }]);
  });

  it("保存先を持たない凡例は読み取り専用（隠した鍵を持たない）", () => {
    const [chip] = chipsOf({ layers: [layer(A, { readOnlyLegend: [{ label: "見出し", legend }] })] });
    expect(chip.legendDetails).toEqual([{ label: "見出し", legend, hiddenKeys: [] }]);
  });
});

describe("hasVisibleLegendFilter（「絞り込みをすべて解除する」の対象があるか）", () => {
  const legendDetails = [{ label: "", legend: [], hiddenKeys: ["k1"], axisId: "a" }];
  const chip = (on: boolean, hiddenKeys: string[]): OverlayLayerChip => ({
    id: A,
    label: "",
    icon: ICON,
    on,
    legendDetails: [{ ...legendDetails[0], hiddenKeys }],
  });

  it("ONのチップで行を隠していれば対象がある", () => {
    expect(hasVisibleLegendFilter([chip(true, ["k1"])], [])).toBe(true);
  });

  it("OFFのチップで隠している行は、描いていないので数えない", () => {
    expect(hasVisibleLegendFilter([chip(false, ["k1"])], [])).toBe(false);
    expect(hasVisibleLegendFilter([chip(true, [])], [])).toBe(false);
  });

  it("レンズの凡例で隠していれば対象がある", () => {
    expect(hasVisibleLegendFilter([], ["step-0"])).toBe(true);
  });
});

describe("secondaryAxisCasingLayerIds（ramp軸の下敷き）", () => {
  // 地図に表示レイヤーを持つ一次属性。材料として軸に使われうる。
  const layerIds: readonly string[] = mapDisplay.layerIds;
  const materials = primaryAttributes.map((attr) => attr.attr_id).filter((id) => layerIds.includes(id));
  const material = materials[0] as MapLayerId;
  const axes: SecondaryAxisSummary[] = [
    { axisId: "x", label: "", description: "", chipLabel: "", layerId: "axis:x", primaryAttributeIds: [material] },
    { axisId: "y", label: "", description: "", chipLabel: "", primaryAttributeIds: [material] },
  ];

  it("材料の表示レイヤーがONのramp軸だけを下敷きにする", () => {
    expect(materials.length).toBeGreaterThan(0);
    const visibility = buildDefaultLayerVisibility();
    expect(secondaryAxisCasingLayerIds(axes, { ...visibility, [material]: true })).toEqual(["axis:x"]);
    expect(secondaryAxisCasingLayerIds(axes, { ...visibility, [material]: false })).toEqual([]);
  });
});

describe("レイヤーのON/OFFの保存と既定", () => {
  const defaults = buildDefaultLayerVisibility();
  const [someId] = Object.keys(defaults) as MapLayerId[];

  it("既定から1つでも変えたら「まとめて元に戻す」の対象になる", () => {
    expect(layerVisibilityChanged(defaults)).toBe(false);
    expect(layerVisibilityChanged({ ...defaults, [someId]: !defaults[someId] })).toBe(true);
  });

  it("保存値のうち、いまのカタログにある鍵の真偽値だけを読み、無い鍵は既定のまま", () => {
    const flipped = { ...defaults, [someId]: !defaults[someId] };
    expect(deserializeLayerVisibility(serializeLayerVisibility(flipped))).toEqual(flipped);
    expect(deserializeLayerVisibility(JSON.stringify({ [someId]: "yes", unknown_layer: true }))).toEqual(defaults);
  });

  it("形の合わない保存値は読まない", () => {
    expect(deserializeLayerVisibility("not json")).toBeNull();
    expect(deserializeLayerVisibility("[]")).toBeNull();
  });
});
