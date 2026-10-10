/**
 * `MapOverlayControls.tsx`——「表示」のボタンが開く一覧が、レイヤーを群（源泉の並び）へ束ね、行のチェックでON/OFFし、
 * ⓘ・▶を行のすぐ下に開いて説明・内訳・案内・取得状態を読ませ、内訳から凡例を絞り込めること。群はたため、群ごとに
 * 一覧に並べる項目を選べ、どちらも次の訪問でも保つこと。「表示する項目を選ぶ」の「すべて」で、群の項目をまとめて選べること。末尾のまとめての操作が、押せるときだけ押せること。
 *
 * 群・カテゴリの名前と並びはbackendの宣言（生成物）から導き、テストでも書き写さない。
 *
 * ここで見ないもの:
 * - 浮かせた一覧の位置取り・画面端での縮み・外を押すと閉じること → Radix Popover
 * - チェックボックスの一覧の描き方 → `LegendCheckboxList`
 * - 保存の読み書きの失敗の扱い → `useStoredState`
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

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
const ROAD_LABEL = MAP_OVERLAY_GROUP_LABELS[ROAD];
const chooser = () => screen.getByRole("button", { name: `${ROAD_LABEL}の表示項目を選ぶ` });

/** 1件のレイヤー。既定では道路の群の1件目のカテゴリに属する。 */
function chip(id: string, overrides: Partial<OverlayLayerChip> = {}): OverlayLayerChip {
  return { id: id as MapLayerId, icon: TestIcon, label: id, on: false, category: categoriesOf(ROAD)[0], ...overrides };
}

function legend(axisId: string | undefined, keys: string[], hiddenKeys: string[] = []): LegendFilterSummaryAxis {
  return {
    label: `軸${axisId ?? ""}`,
    axisId,
    hiddenKeys,
    legend: keys.map((key) => ({ key, label: `項目${key}`, color: `#${key}${key}${key}` })),
  };
}

function propsOf(layers: OverlayLayerChip[], overrides: { anyLegendHidden?: boolean } = {}) {
  return {
    layers,
    onToggle: vi.fn(),
    onLegendEntryToggle: vi.fn(),
    onLegendAxisSetHidden: vi.fn(),
    onHideAllLayers: vi.fn(),
    anyLegendHidden: false,
    onShowAllLegendRows: vi.fn(),
    ...overrides,
  };
}

/** 描いて「表示」のボタンを押し、一覧を開く。 */
async function setup(layers: OverlayLayerChip[], overrides: { anyLegendHidden?: boolean } = {}) {
  const props = propsOf(layers, overrides);
  const user = userEvent.setup();
  const view = render(<MapOverlayControls {...props} />);
  await user.click(screen.getByRole("button", { name: LIST_NAME }));
  return { user, props, list: screen.getByRole("dialog", { name: LIST_NAME }), ...view };
}

/** 一覧に並んでいる行の名前（行のチェックボックスの名前）。 */
const rowNames = (list: HTMLElement) =>
  within(list)
    .queryAllByRole("checkbox")
    .map((box) => box.getAttribute("aria-label"));

/** 行のtitle（行の名前のチェックボックスを包むラベルが持つ）。 */
const rowTitle = (name: string) => screen.getByRole("checkbox", { name }).closest("label")?.getAttribute("title");

afterEach(() => {
  window.localStorage.clear();
});

describe("一覧の行", () => {
  it("ONをチェックで表し、押すとレイヤーidと反転した値で知らせる", async () => {
    const { user, props } = await setup([chip("shown", { on: true }), chip("other")]);

    expect(screen.getByRole("checkbox", { name: "shown" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "shown" }));
    await user.click(screen.getByRole("checkbox", { name: "other" }));
    expect(props.onToggle.mock.calls).toEqual([
      ["shown", false],
      ["other", true],
    ]);
  });

  it("▶は、凡例があればOFFでも出し（ONにすると何が出るかを先に確かめられる）、中身が無ければ出さない。押すと内訳を一覧の中の行の下に開き、もう一度押すと閉じる", async () => {
    const { user, list } = await setup([
      chip("member", { legendDetails: [legend("a", ["1"])] }),
      chip("empty", { on: true }),
    ]);
    expect(screen.queryByRole("button", { name: "emptyの凡例" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "memberの凡例" }));
    expect(within(list).getByRole("region", { name: "memberの内訳" })).toHaveTextContent("項目1");
    await user.click(screen.getByRole("button", { name: "memberの凡例" }));
    expect(screen.queryByRole("region", { name: "memberの内訳" })).not.toBeInTheDocument();
  });

  it("説明のある行にだけⓘを出し、押すと説明を一覧の中の行の下に開き、もう一度押すと閉じる", async () => {
    const { user, list } = await setup([chip("with_hint", { panelHint: "説明文" }), chip("plain")]);
    expect(within(list).queryByRole("button", { name: /plainの説明/ })).not.toBeInTheDocument();
    await user.click(within(list).getByRole("button", { name: "with_hintの説明を表示" }));
    expect(within(list).getByText("説明文")).toBeInTheDocument();
    await user.click(within(list).getByRole("button", { name: "with_hintの説明を隠す" }));
    expect(screen.queryByText("説明文")).not.toBeInTheDocument();
  });
});

describe("▶の内訳", () => {
  async function openDetails(layer: OverlayLayerChip) {
    const view = await setup([layer]);
    await view.user.click(screen.getByRole("button", { name: `${layer.label}の凡例` }));
    return { ...view, panel: screen.getByRole("region", { name: `${layer.label}の内訳` }) };
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
    const { rerender } = render(<MapOverlayControls {...propsOf([chip("on", { on: true }), chip("off")])} />);
    expect(screen.getByRole("button", { name: LIST_NAME })).toHaveAttribute("title", `${LIST_NAME}[1件を表示中]`);

    rerender(
      <MapOverlayControls {...propsOf([chip("filtered", { on: true, legendDetails: [legend("a", ["1"], ["1"])] })])} />,
    );
    expect(screen.getByRole("button", { name: LIST_NAME })).toHaveAttribute(
      "title",
      `${LIST_NAME}[1件を表示中]・絞り込み中`,
    );
  });
});

describe("群", () => {
  it("レイヤーを源泉の群へ束ね、群の並びで並べる", async () => {
    const members = MAP_OVERLAY_GROUP_ORDER.map((group) =>
      chip(`member_${group}`, { category: categoriesOf(group)[0] }),
    );
    const { list } = await setup(members.reverse());

    expect(
      within(list)
        .getAllByRole("region")
        .map((section) => section.getAttribute("aria-label")),
    ).toEqual(MAP_OVERLAY_GROUP_ORDER.map((group) => MAP_OVERLAY_GROUP_LABELS[group]));
    expect(rowNames(list)).toEqual(MAP_OVERLAY_GROUP_ORDER.map((group) => `member_${group}`));
  });

  it("群の中の行は、源泉のカテゴリの並びで並べる", async () => {
    const [first, second] = categoriesOf(ROAD);
    const { list } = await setup([chip("later", { category: second ?? first }), chip("earlier", { category: first })]);
    expect(rowNames(list)).toEqual(second ? ["earlier", "later"] : ["later", "earlier"]);
  });

  it("群の見出しを押すと中身をたたみ、もう一度押すと開く。たたんだ群は次の訪問でも保つ", async () => {
    const first = await setup([chip("member")]);
    const heading = () =>
      within(screen.getByRole("dialog", { name: LIST_NAME })).getByRole("button", { name: ROAD_LABEL });
    expect(heading()).toHaveAttribute("aria-expanded", "true");

    await first.user.click(heading());

    expect(heading()).toHaveAttribute("aria-expanded", "false");
    expect(rowNames(first.list)).toEqual([]);
    first.unmount();

    const second = await setup([chip("member")]);
    expect(rowNames(second.list)).toEqual([]);
    await second.user.click(heading());
    expect(rowNames(second.list)).toEqual(["member"]);
  });

  it("「表示する項目を選ぶ」で外した項目は一覧に並べず（地図に出していればOFFにする）、次の訪問でも保ち、並べ直してもONにはしない", async () => {
    const first = await setup([chip("kept"), chip("dropped", { on: true })]);

    await first.user.click(chooser());
    await first.user.click(screen.getByRole("checkbox", { name: "droppedを一覧に並べる" }));
    await first.user.click(chooser());

    expect(first.props.onToggle.mock.calls).toEqual([["dropped", false]]);
    expect(rowNames(first.list)).toEqual(["kept"]);
    first.unmount();

    const second = await setup([chip("kept"), chip("dropped")]);
    expect(rowNames(second.list)).toEqual(["kept"]);
    await second.user.click(chooser());
    expect(screen.getByRole("checkbox", { name: "droppedを一覧に並べる" })).not.toBeChecked();
    await second.user.click(screen.getByRole("checkbox", { name: "droppedを一覧に並べる" }));
    await second.user.click(chooser());
    expect(rowNames(second.list)).toEqual(["kept", "dropped"]);
    expect(second.props.onToggle).not.toHaveBeenCalled();
  });

  it("「表示する項目を選ぶ」の「すべて」は、1つでも外れていれば全部並べ、全部並んでいれば全部外す（外す項目のONはOFFにする）", async () => {
    const { user, props, list } = await setup([chip("shown", { on: true }), chip("off"), chip("dropped")]);
    const all = () => screen.getByRole("checkbox", { name: `${ROAD_LABEL}の項目をすべて選ぶ/外す` });

    await user.click(chooser());
    expect(all()).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "droppedを一覧に並べる" }));
    expect(all()).not.toBeChecked();
    await user.click(all());
    await user.click(chooser());
    expect(rowNames(list)).toEqual(["shown", "off", "dropped"]);
    expect(props.onToggle).not.toHaveBeenCalled();

    await user.click(chooser());
    await user.click(all());
    await user.click(chooser());
    expect(rowNames(list)).toEqual([]);
    expect(props.onToggle.mock.calls).toEqual([["shown", false]]);
  });
});

describe("まとめての操作", () => {
  it("「表示中のレイヤーをすべて非表示」は出している行があるときだけ、「絞り込みをすべて解除」は凡例で隠している間だけ押せる", async () => {
    const shown = await setup([chip("on", { on: true })], { anyLegendHidden: false });
    expect(screen.getByRole("button", { name: "絞り込みをすべて解除" })).toBeDisabled();
    await shown.user.click(screen.getByRole("button", { name: "表示中のレイヤーをすべて非表示" }));
    expect(shown.props.onHideAllLayers).toHaveBeenCalledOnce();
    shown.unmount();

    const filtered = await setup([chip("off")], { anyLegendHidden: true });
    expect(screen.getByRole("button", { name: "表示中のレイヤーをすべて非表示" })).toBeDisabled();
    await filtered.user.click(screen.getByRole("button", { name: "絞り込みをすべて解除" }));
    expect(filtered.props.onShowAllLegendRows).toHaveBeenCalledOnce();
  });
});
