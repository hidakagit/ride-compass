// @vitest-environment node
// `overlayChips.ts`——地図上チップ1枚ずつの状態と、レイヤーのON/OFFの保存形式。
//
// ここで見ないもの:
// - チップの描き方・▶パネルの開閉 → `MapOverlayControls.test.tsx`
// - 絞り込みの宣言（道路の線・点の凡例の中身）→ `scene/legends.test.ts`
import { describe, expect, it } from "vitest";

import {
  buildDefaultLayerVisibility,
  buildMapLayers,
  type MapLayerDescriptor,
  type MapLayerId,
  type MapLayerVisibility,
} from "@/components/Map/mapLayers";
import { DISASTER_LAYER_ID } from "@/features/map/scene/legends";
import { mapDisplay } from "@/types/generated/mapDisplay";

import { deserializeLayerVisibility, overlayChips } from "./overlayChips";

const ICON = (() => null) as unknown as MapLayerDescriptor["icon"];

// 架空のレイヤー。idは型を満たすために`MapLayerId`へ寄せるだけで、実在のレイヤーを指さない。
function layer(id: string, overrides: Partial<MapLayerDescriptor> = {}): MapLayerDescriptor {
  return {
    id: id as MapLayerId,
    label: id,
    kind: "static",
    icon: ICON,
    dataSource: "ownFetch",
    description: "",
    ...overrides,
  };
}

function chipsOf(options: Partial<Parameters<typeof overlayChips>[0]> & { layers: MapLayerDescriptor[] }) {
  return overlayChips({
    visibility: {} as MapLayerVisibility,
    hidden: {},
    screenLegends: {},
    dataStatus: {},
    zoomTooWideLayerIds: [],
    versionMissingLayerIds: [],
    catalogSettled: false,
    hasSelectedRoute: true,
    ...options,
  });
}

const A = "layer_a" as MapLayerId;

describe("世代が届いていないレイヤー", () => {
  it("カタログを取りに行っている間は読み込み中として示し、「取得できない」とは言わない", () => {
    const [chip] = chipsOf({ layers: [layer(A)], versionMissingLayerIds: [A], zoomTooWideLayerIds: [A] });
    expect(chip.dataStatus).toBe("loading");
    expect(chip.notice).toBe("ズームインすると表示されます");
  });

  it("取り終えたのに世代が無ければ失敗として示し、ズーム不足より先に理由を出す", () => {
    const [chip] = chipsOf({
      layers: [layer(A)],
      versionMissingLayerIds: [A],
      zoomTooWideLayerIds: [A],
      catalogSettled: true,
    });
    expect(chip.dataStatus).toBe("error");
    expect(chip.notice).toBe("配信情報を取得できず表示できません");
  });
});

describe("チップの母集団と押せる条件", () => {
  it("軸スタジオ由来のレイヤーはチップにしない", () => {
    const chips = chipsOf({
      layers: [layer(A), layer("dedicated", { axisStudioLayer: true }), layer("ramp", { dataNature: "composite" })],
    });
    expect(chips.map((chip) => chip.id)).toEqual([A]);
  });

  it("ルートにひもづくレイヤーは、候補を選ぶまで押せない", () => {
    const route = layer("route_like", { kind: "dynamic" });
    expect(chipsOf({ layers: [route], hasSelectedRoute: false })[0].disabled).toBe(true);
    expect(chipsOf({ layers: [route], hasSelectedRoute: true })[0].disabled).toBe(false);
  });
});

describe("チップの凡例（▶パネル）", () => {
  const legend = [{ key: "k1", label: "1", color: "#111" }];

  it("保存先を持つ凡例には、いま凡例に実在する隠した行だけを渡し、持たない凡例は隠した行を持たない", () => {
    const [chip] = chipsOf({
      layers: [layer(A, { readOnlyLegend: [{ label: "読み方", legend }] })],
      hidden: { saved: ["k1", "gone"] },
      screenLegends: { [A]: [{ label: "", legend, axisId: "saved" }] },
    });
    expect(chip.legendDetails).toEqual([
      { label: "読み方", legend, hiddenKeys: [] },
      { label: "", legend, hiddenKeys: ["k1"], axisId: "saved" },
    ]);
  });

  it("災害チップには、源泉が宣言した災害の要素がすべて、宣言した名前で切り替えの行として並ぶ", () => {
    const disaster = buildMapLayers([], []).filter((entry) => entry.id === DISASTER_LAYER_ID);
    const [chip] = chipsOf({ layers: disaster });
    const toggles = chip.legendDetails?.find((axis) => axis.axisId === DISASTER_LAYER_ID);
    const declared = new Map(
      mapDisplay.weatherElements
        .filter((element) => element.group === DISASTER_LAYER_ID)
        .map((element) => [element.source, element.label]),
    );
    expect(new Map(toggles?.legend.map((entry) => [entry.key, entry.label]))).toEqual(declared);
  });
});

describe("レイヤーのON/OFFの保存値", () => {
  const defaults = buildDefaultLayerVisibility();
  const [someId] = Object.keys(defaults) as MapLayerId[];

  it("いまのカタログにある鍵の真偽値だけを読み、無い鍵・形の合わない値は既定のまま", () => {
    const flipped = { ...defaults, [someId]: !defaults[someId] };
    expect(deserializeLayerVisibility(JSON.stringify(flipped))).toEqual(flipped);
    expect(deserializeLayerVisibility(JSON.stringify({ [someId]: "yes", unknown_layer: true }))).toEqual(defaults);
    expect(deserializeLayerVisibility("[]")).toEqual(defaults);
  });
});
