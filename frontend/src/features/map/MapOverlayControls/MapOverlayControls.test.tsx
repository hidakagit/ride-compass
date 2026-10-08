/**
 * `MapOverlayControls.tsx`——「表示」のボタンが開く一覧が、レイヤーを群（源泉の並び）へ束ね、行のチェックでON/OFFし、
 * ▶で内訳・案内・取得状態を読ませ、内訳から凡例を絞り込めること。
 *
 * 群・カテゴリの名前と並びはbackendの宣言（生成物）から導き、テストでも書き写さない。
 *
 * ここで見ないもの:
 * - 浮かせたパネルの位置取り・画面端での縮み・外を押すと閉じること → Radix Popover
 * - チェックボックスの一覧の描き方 → `LegendCheckboxList`
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import MapOverlayControls, { type LegendFilterSummaryAxis, type OverlayLayerChip } from "./MapOverlayControls";
import {
  LAYER_DATA_STATUS_LABELS,
  MAP_LAYER_CATEGORY_ORDER,
  MAP_OVERLAY_GROUP_LABELS,
  MAP_OVERLAY_GROUP_ORDER,
  mapOverlayGroupFor,
  type MapLayerCategory,
  type MapLayerId,
  type MapOverlayGroup,
} from "@/features/map/layers/mapLayers";

const TestIcon = () => <svg />;
const LIST_NAME = "地図に出す情報";

/** 群ごとの、源泉の並びのカテゴリ。 */
function categoriesOf(group: MapOverlayGroup): MapLayerCategory[] {
  return MAP_LAYER_CATEGORY_ORDER.filter((category) => mapOverlayGroupFor({ category }) === group);
}
const [ROAD] = MAP_OVERLAY_GROUP_ORDER;

function chip(id: string, overrides: Partial<OverlayLayerChip> = {}): OverlayLayerChip {
  return { id: id as MapLayerId, icon: TestIcon, label: id, on: false, ...overrides };
}

/** 道路の群の1件目のカテゴリに属するレイヤー。 */
function roadMember(id: string, overrides: Partial<OverlayLayerChip> = {}) {
  return chip(id, { category: categoriesOf(ROAD)[0], ...overrides });
}

function legend(axisId: string | undefined, keys: string[], hiddenKeys: string[] = []): LegendFilterSummaryAxis {
  return {
    label: `軸${axisId ?? ""}`,
    axisId,
    hiddenKeys,
    legend: keys.map((key) => ({ key, label: `項目${key}`, color: `#${key}${key}${key}` })),
  };
}

/** 描いて「表示」のボタンを押し、一覧を開く。 */
async function setup(layers: OverlayLayerChip[]) {
  const props = {
    layers,
    onToggle: vi.fn(),
    onLegendEntryToggle: vi.fn(),
    onLegendAxisSetHidden: vi.fn(),
  };
  const user = userEvent.setup();
  const view = render(<MapOverlayControls {...props} />);
  await user.click(screen.getByRole("button", { name: LIST_NAME }));
  return { user, props, list: screen.getByRole("dialog", { name: LIST_NAME }), ...view };
}

/** 行のtitle（行の名前のチェックボックスを包むラベルが持つ）。 */
const rowTitle = (name: string) => screen.getByRole("checkbox", { name }).closest("label")?.getAttribute("title");

describe("一覧の行", () => {
  it("ONをチェックで表し、押すとレイヤーidと反転した値で知らせる。使えない行は押せずONに見えない", async () => {
    const { user, props } = await setup([
      chip("route", { on: true }),
      chip("other"),
      chip("off_limits", { on: true, disabled: true }),
    ]);

    expect(screen.getByRole("checkbox", { name: "route" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "route" }));
    await user.click(screen.getByRole("checkbox", { name: "other" }));
    expect(props.onToggle.mock.calls).toEqual([
      ["route", false],
      ["other", true],
    ]);

    const disabled = screen.getByRole("checkbox", { name: "off_limits" });
    expect(disabled).toBeDisabled();
    expect(disabled).not.toBeChecked();
  });

  it("群に属さない行の▶は、ONで中身があるときだけ出す（OFF・使えない・中身が無いときは出さない）", async () => {
    const withLegend = { legendDetails: [legend("a", ["1"])] };
    await setup([
      chip("on_with_legend", { on: true, ...withLegend }),
      chip("off_with_legend", withLegend),
      chip("disabled_with_legend", { on: true, disabled: true, ...withLegend }),
      chip("on_without_content", { on: true }),
    ]);
    expect(screen.getByRole("button", { name: "on_with_legendの凡例" })).toBeInTheDocument();
    for (const name of ["off_with_legend", "disabled_with_legend", "on_without_content"]) {
      expect(screen.queryByRole("button", { name: `${name}の凡例` })).not.toBeInTheDocument();
    }
  });

  it("群の行の▶は、凡例があればOFFでも出す（ONにすると何が出るかを先に確かめられる）", async () => {
    const { user } = await setup([roadMember("member", { legendDetails: [legend("a", ["1"])] })]);
    await user.click(screen.getByRole("button", { name: "memberの凡例" }));
    expect(screen.getByRole("dialog", { name: "memberの内訳" })).toHaveTextContent("項目1");
  });

  it("説明のある行にだけⓘを出し、押すと説明を読める", async () => {
    const { user, list } = await setup([roadMember("with_hint", { panelHint: "説明文" }), roadMember("plain")]);
    expect(within(list).queryByRole("button", { name: /plainの説明/ })).not.toBeInTheDocument();
    await user.click(within(list).getByRole("button", { name: "with_hintの説明を表示" }));
    expect(screen.getByText("説明文")).toBeInTheDocument();
  });
});

describe("▶の内訳", () => {
  async function openDetails(layer: OverlayLayerChip) {
    const view = await setup([layer]);
    await view.user.click(screen.getByRole("button", { name: `${layer.label}の凡例` }));
    return { ...view, panel: screen.getByRole("dialog", { name: `${layer.label}の内訳` }) };
  }

  it("絞り込める軸は、軸の名前の見出しを持ち、1行ずつと見出しでまとめて切り替えられる（全部表示中なら全部隠し、1つでも隠れていれば全部出す）", async () => {
    const { user, props, panel } = await openDetails(
      chip("layer", { on: true, legendDetails: [legend("a", ["1", "2"]), legend("b", ["3", "4"], ["4"])] }),
    );
    expect(within(panel).getByText("軸a")).toBeInTheDocument();
    await user.click(within(panel).getByRole("checkbox", { name: /項目1/ }));
    await user.click(within(panel).getByRole("checkbox", { name: "軸aをまとめて表示/非表示" }));
    await user.click(within(panel).getByRole("checkbox", { name: "軸bをまとめて表示/非表示" }));

    expect(props.onLegendEntryToggle).toHaveBeenCalledWith("a", "1");
    expect(props.onLegendAxisSetHidden.mock.calls).toEqual([
      ["a", ["1", "2"]],
      ["b", []],
    ]);
  });

  it("絞り込めない軸（axisIdが無い）はチェックボックスを出さず、非表示の行に印を付ける", async () => {
    const { panel } = await openDetails(
      chip("layer", { on: true, legendDetails: [legend(undefined, ["1", "2"], ["2"])] }),
    );
    expect(within(panel).queryByRole("checkbox")).not.toBeInTheDocument();
    const [shown, hidden] = within(panel).getAllByRole("listitem");
    expect(shown).not.toHaveTextContent("非表示");
    expect(hidden).toHaveTextContent("非表示");
  });

  it("案内文があれば、凡例の有無にかかわらず凡例の代わりに案内文を出す", async () => {
    const { panel } = await openDetails(
      chip("layer", { on: true, notice: "ズームインすると表示されます", legendDetails: [legend("a", ["1"])] }),
    );
    expect(panel).toHaveTextContent("ズームインすると表示されます");
    expect(within(panel).queryByText("項目1")).not.toBeInTheDocument();
  });

  it("取得状態があれば、凡例の上へ同じ文言を出す（凡例が無くても▶を出す）", async () => {
    const { panel, unmount } = await openDetails(
      chip("layer", { on: true, dataStatus: "error", legendDetails: [legend("a", ["1"])] }),
    );
    expect(within(panel).getByRole("status")).toHaveTextContent(LAYER_DATA_STATUS_LABELS.error);
    expect(within(panel).getByText("項目1")).toBeInTheDocument();
    unmount();

    await setup([chip("status_only", { on: true, dataStatus: "empty" })]);
    expect(screen.getByRole("button", { name: "status_onlyの凡例" })).toBeInTheDocument();
  });
});

describe("行の印", () => {
  it("取得状態は、ONの間だけtitleへ添える（OFF・状態なしは添えない）", async () => {
    await setup([
      chip("loading", { on: true, dataStatus: "loading", title: "説明" }),
      chip("off", { dataStatus: "error", title: "説明" }),
      chip("normal", { on: true, title: "説明" }),
    ]);
    expect(rowTitle("loading")).toBe(`説明[${LAYER_DATA_STATUS_LABELS.loading}]`);
    expect(rowTitle("off")).toBe("説明");
    expect(rowTitle("normal")).toBe("説明");
  });

  it("凡例の一部を隠しているONの行だけ、titleに「絞り込み中」を添える", async () => {
    await setup([
      chip("filtered", { on: true, legendDetails: [legend("a", ["1"], ["1"])] }),
      chip("filtered_but_off", { legendDetails: [legend("a", ["1"], ["1"])] }),
      chip("unfiltered", { on: true, legendDetails: [legend("a", ["1"])] }),
    ]);
    expect(rowTitle("filtered")).toBe("絞り込み中");
    expect(rowTitle("filtered_but_off")).toBeNull();
    expect(rowTitle("unfiltered")).toBeNull();
  });

  it("「表示」のボタンは、地図に出している件数と、どれかの行が凡例を絞り込んでいれば「絞り込み中」をtitleに添える", () => {
    const props = { onToggle: vi.fn(), onLegendEntryToggle: vi.fn(), onLegendAxisSetHidden: vi.fn() };
    const { rerender } = render(
      <MapOverlayControls
        {...props}
        layers={[roadMember("on", { on: true }), roadMember("disabled", { on: true, disabled: true })]}
      />,
    );
    expect(screen.getByRole("button", { name: LIST_NAME })).toHaveAttribute("title", `${LIST_NAME}[1件を表示中]`);

    rerender(
      <MapOverlayControls
        {...props}
        layers={[roadMember("filtered", { on: true, legendDetails: [legend("a", ["1"], ["1"])] })]}
      />,
    );
    expect(screen.getByRole("button", { name: LIST_NAME })).toHaveAttribute(
      "title",
      `${LIST_NAME}[1件を表示中]・絞り込み中`,
    );
  });
});

describe("群", () => {
  it("レイヤーを源泉の群へ束ね、群の並びのあとに群に属さない行を並べる", async () => {
    const members = MAP_OVERLAY_GROUP_ORDER.map((group) =>
      chip(`member_${group}`, { category: categoriesOf(group)[0] }),
    );
    const { list } = await setup([chip("route"), ...members.reverse()]);

    expect(
      within(list)
        .getAllByRole("heading")
        .map((heading) => heading.textContent),
    ).toEqual(MAP_OVERLAY_GROUP_ORDER.map((group) => MAP_OVERLAY_GROUP_LABELS[group]));
    expect(
      within(list)
        .getAllByRole("checkbox")
        .map((box) => box.getAttribute("aria-label")),
    ).toEqual([...MAP_OVERLAY_GROUP_ORDER.map((group) => `member_${group}`), "route"]);
  });

  it("群の中の行は、源泉のカテゴリの並びで並べる", async () => {
    const [first, second] = categoriesOf(ROAD);
    const { list } = await setup([
      roadMember("later", { category: second ?? first }),
      roadMember("earlier", { category: first }),
    ]);
    const names = within(list)
      .getAllByRole("checkbox")
      .map((box) => box.getAttribute("aria-label"));
    expect(names).toEqual(second ? ["earlier", "later"] : ["later", "earlier"]);
  });
});
