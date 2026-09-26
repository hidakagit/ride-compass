/**
 * `MapOverlayControls.tsx`——地図のチップ列が、レイヤーをグループ（源泉の並び）へ束ね、押すとON/OFFし、▶で内訳・案内・
 * 取得状態を読ませ、内訳から凡例を絞り込め、グループの開閉と「表示する項目」を次の訪問でも保つこと。
 *
 * グループ・カテゴリの名前と並びはbackendの宣言（生成物）から導き、テストでも書き写さない。
 *
 * ここで見ないもの:
 * - 浮かせたパネルの位置取り・画面端での縮み・外を押すと閉じること（同時に開くのは1つ） → Radix Popover
 * - チェックボックスの一覧の描き方 → `LegendCheckboxList`
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import MapOverlayControls, { type LegendFilterSummaryAxis, type OverlayLayerChip } from "./MapOverlayControls";
import {
  LAYER_DATA_STATUS_LABELS,
  MAP_LAYER_CATEGORY_ORDER,
  MAP_OVERLAY_GROUP_LABELS,
  MAP_OVERLAY_GROUP_ORDER,
  MAP_OVERLAY_MAX_EXPANDED_GROUPS,
  mapOverlayGroupFor,
  type MapLayerCategory,
  type MapLayerId,
  type MapOverlayGroup,
} from "@/features/map/layers/mapLayers";

const TestIcon = () => <svg />;

/** グループごとの、源泉の並びで先頭のカテゴリ。 */
function categoriesOf(group: MapOverlayGroup): MapLayerCategory[] {
  return MAP_LAYER_CATEGORY_ORDER.filter(
    (category) => mapOverlayGroupFor({ id: "x" as MapLayerId, category }) === group,
  );
}
const [ROAD, ENVIRONMENT] = MAP_OVERLAY_GROUP_ORDER;
const ROAD_LABEL = MAP_OVERLAY_GROUP_LABELS[ROAD];
const ENVIRONMENT_LABEL = MAP_OVERLAY_GROUP_LABELS[ENVIRONMENT];

function chip(id: string, overrides: Partial<OverlayLayerChip> = {}): OverlayLayerChip {
  return { id: id as MapLayerId, icon: TestIcon, label: id, on: false, ...overrides };
}

/** 道路グループの1件目のカテゴリに属するレイヤー。 */
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

function setup(layers: OverlayLayerChip[]) {
  const props = {
    layers,
    onToggle: vi.fn(),
    onLegendEntryToggle: vi.fn(),
    onLegendAxisSetHidden: vi.fn(),
  };
  const user = userEvent.setup();
  const view = render(<MapOverlayControls {...props} />);
  return { user, props, ...view };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("単独のチップ（どのグループにも属さないレイヤー）", () => {
  it("ONをaria-pressedで表し、押すとレイヤーidと反転した値で知らせる。使えないチップは押せずONに見えない", async () => {
    const { user, props } = setup([
      chip("route", { on: true }),
      chip("other"),
      chip("off_limits", { on: true, disabled: true }),
    ]);

    expect(screen.getByRole("button", { name: "route" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "route" }));
    await user.click(screen.getByRole("button", { name: "other" }));
    expect(props.onToggle.mock.calls).toEqual([
      ["route", false],
      ["other", true],
    ]);

    const disabled = screen.getByRole("button", { name: "off_limits" });
    expect(disabled).toBeDisabled();
    expect(disabled).toHaveAttribute("aria-pressed", "false");
  });

  it("▶はONで中身があるときだけ出す（OFF・使えない・中身が無いときは出さない）", () => {
    const withLegend = { legendDetails: [legend("a", ["1"])] };
    setup([
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
});

describe("▶の内訳", () => {
  async function openDetails(layer: OverlayLayerChip) {
    const view = setup([layer]);
    await view.user.click(screen.getByRole("button", { name: `${layer.label}の凡例` }));
    return { ...view, panel: screen.getByRole("dialog", { name: `${layer.label}の内訳` }) };
  }

  it("軸ごとに全カテゴリを、非表示のものも含めて並べる", async () => {
    const { panel } = await openDetails(chip("layer", { on: true, legendDetails: [legend("a", ["1", "2"], ["2"])] }));
    expect(within(panel).getByText("軸a")).toBeInTheDocument();
    expect(within(panel).getByRole("checkbox", { name: /項目1/ })).toBeChecked();
    expect(within(panel).getByRole("checkbox", { name: /項目2/ })).not.toBeChecked();
  });

  it("絞り込める軸は、1行ずつと見出しでまとめて切り替えられる（全部表示中なら全部隠し、1つでも隠れていれば全部出す）", async () => {
    const { user, props, panel } = await openDetails(
      chip("layer", { on: true, legendDetails: [legend("a", ["1", "2"]), legend("b", ["3", "4"], ["4"])] }),
    );
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
    const { panel } = await openDetails(
      chip("layer", { on: true, dataStatus: "error", legendDetails: [legend("a", ["1"])] }),
    );
    expect(within(panel).getByRole("status")).toHaveTextContent(LAYER_DATA_STATUS_LABELS.error);
    expect(within(panel).getByText("項目1")).toBeInTheDocument();

    setup([chip("status_only", { on: true, dataStatus: "empty" })]);
    expect(screen.getByRole("button", { name: "status_onlyの凡例" })).toBeInTheDocument();
  });
});

describe("チップの印", () => {
  it("取得状態は、ONの間だけtitleへ添える（OFF・状態なしは添えない）", () => {
    setup([
      chip("loading", { on: true, dataStatus: "loading", title: "説明" }),
      chip("off", { dataStatus: "error", title: "説明" }),
      chip("normal", { on: true, title: "説明" }),
    ]);
    expect(screen.getByRole("button", { name: "loading" })).toHaveAttribute(
      "title",
      `説明（${LAYER_DATA_STATUS_LABELS.loading}）`,
    );
    expect(screen.getByRole("button", { name: "off" })).toHaveAttribute("title", "説明");
    expect(screen.getByRole("button", { name: "normal" })).toHaveAttribute("title", "説明");
  });

  it("凡例の一部を隠しているONのチップだけ、titleに「絞り込み中」を添える", () => {
    setup([
      chip("filtered", { on: true, legendDetails: [legend("a", ["1"], ["1"])] }),
      chip("filtered_but_off", { legendDetails: [legend("a", ["1"], ["1"])] }),
      chip("unfiltered", { on: true, legendDetails: [legend("a", ["1"])] }),
    ]);
    expect(screen.getByRole("button", { name: "filtered" })).toHaveAttribute("title", "絞り込み中");
    expect(screen.getByRole("button", { name: "filtered_but_off" })).not.toHaveAttribute("title");
    expect(screen.getByRole("button", { name: "unfiltered" })).not.toHaveAttribute("title");
  });
});

describe("グループ", () => {
  it("レイヤーを源泉のグループへ束ね、グループの並びのあとに単独のチップを並べる。軸スタジオ由来のレイヤーは出さない", () => {
    const members = MAP_OVERLAY_GROUP_ORDER.map((group) =>
      chip(`member_${group}`, { category: categoriesOf(group)[0] }),
    );
    setup([
      chip("route"),
      ...members.reverse(),
      roadMember("ramp_axis", { dataNature: "composite" }),
      chip("dedicated_axis", { axisStudioLayer: true }),
    ]);
    const chipNames = screen
      .getAllByRole("button")
      .filter((button) => !button.getAttribute("aria-label"))
      .map((button) => button.textContent);
    expect(chipNames).toEqual([...MAP_OVERLAY_GROUP_ORDER.map((group) => MAP_OVERLAY_GROUP_LABELS[group]), "route"]);
  });

  it("見出しはON/OFFではなく開閉を表し、開くとメンバーをカテゴリの並びで出し、メンバーを押すとON/OFFする", async () => {
    const [first, second] = categoriesOf(ROAD);
    const { user, props } = setup([
      roadMember("later", { category: second ?? first }),
      roadMember("earlier", { category: first }),
    ]);
    const header = screen.getByRole("button", { name: ROAD_LABEL });
    expect(header).not.toHaveAttribute("aria-pressed");
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "earlier" })).not.toBeInTheDocument();

    await user.click(header);
    expect(header).toHaveAttribute("aria-expanded", "true");
    const names = screen.getAllByRole("button", { pressed: false }).map((button) => button.textContent);
    expect(names).toEqual(second ? ["earlier", "later"] : ["later", "earlier"]);

    await user.click(screen.getByRole("button", { name: "earlier" }));
    expect(props.onToggle).toHaveBeenCalledWith("earlier", true);
    // 開閉で見出しを作り直さない（作り直すとフォーカスが外れる）。
    expect(screen.getByRole("button", { name: ROAD_LABEL })).toBe(header);
  });

  it("メンバーの▶は、凡例があればOFFでも出す（ONにすると何が出るかを先に確かめられる）", async () => {
    const { user } = setup([roadMember("member", { legendDetails: [legend("a", ["1"])] })]);
    await user.click(screen.getByRole("button", { name: ROAD_LABEL }));
    await user.click(screen.getByRole("button", { name: "memberの凡例" }));
    expect(screen.getByRole("dialog", { name: "memberの内訳" })).toHaveTextContent("項目1");
  });

  it("別のグループを開くと、開いておける数を超えたぶんを古いものから畳む", async () => {
    const { user } = setup([roadMember("road_member"), chip("env_member", { category: categoriesOf(ENVIRONMENT)[0] })]);
    await user.click(screen.getByRole("button", { name: ROAD_LABEL }));
    await user.click(screen.getByRole("button", { name: ENVIRONMENT_LABEL }));
    const expanded = [ROAD_LABEL, ENVIRONMENT_LABEL].filter(
      (name) => screen.getByRole("button", { name }).getAttribute("aria-expanded") === "true",
    );
    expect(expanded).toEqual([ROAD_LABEL, ENVIRONMENT_LABEL].slice(-MAP_OVERLAY_MAX_EXPANDED_GROUPS));
  });

  it("畳んだ見出しは、メンバーのどれかが凡例を絞り込んでいれば「絞り込み中」を添える（開くとメンバーが持つ）", async () => {
    const { user } = setup([roadMember("member", { on: true, legendDetails: [legend("a", ["1"], ["1"])] })]);
    const header = screen.getByRole("button", { name: ROAD_LABEL });
    expect(header.getAttribute("title")).toContain("絞り込み中");
    await user.click(header);
    expect(header.getAttribute("title")).not.toContain("絞り込み中");
    expect(screen.getByRole("button", { name: "member" })).toHaveAttribute("title", "絞り込み中");
  });
});

describe("表示する項目を選ぶ", () => {
  async function openSettings(layers: OverlayLayerChip[]) {
    const view = setup(layers);
    await view.user.click(screen.getByRole("button", { name: `${ROAD_LABEL}の表示項目` }));
    return { ...view, panel: screen.getByRole("dialog", { name: `${ROAD_LABEL}の表示項目` }) };
  }

  it("畳んだグループにだけ入口を出す（開いたグループはメンバーが見えるため出さない）", async () => {
    const { user } = setup([roadMember("member")]);
    expect(screen.getByRole("button", { name: `${ROAD_LABEL}の表示項目` })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: ROAD_LABEL }));
    expect(screen.queryByRole("button", { name: `${ROAD_LABEL}の表示項目` })).not.toBeInTheDocument();
  });

  it("隠した項目は開いたグループに出さず、ONだったならOFFにする。出し直してもONにはしない", async () => {
    const { user, props, panel } = await openSettings([roadMember("shown"), roadMember("hidden_on", { on: true })]);
    await user.click(within(panel).getByRole("checkbox", { name: "hidden_onを表示しない" }));
    expect(props.onToggle).toHaveBeenCalledWith("hidden_on", false);

    await user.click(within(panel).getByRole("checkbox", { name: "hidden_onを表示する" }));
    expect(props.onToggle).toHaveBeenCalledTimes(1);
    await user.click(within(panel).getByRole("checkbox", { name: "hidden_onを表示しない" }));

    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: ROAD_LABEL }));
    expect(screen.getByRole("button", { name: "shown" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "hidden_on" })).not.toBeInTheDocument();
  });

  it("開いた一覧は、押す前のtitleを読めないスマホでも何の一覧かを見出しで示す", async () => {
    const { panel } = await openSettings([roadMember("member")]);
    expect(within(panel).getByText("表示する項目")).toBeVisible();
  });

  it("説明のある項目にだけⓘを出し、押すと説明を読める", async () => {
    const { user, panel } = await openSettings([roadMember("with_hint", { panelHint: "説明文" }), roadMember("plain")]);
    expect(within(panel).queryByRole("button", { name: /plainの説明/ })).not.toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "with_hintの説明を表示" }));
    expect(screen.getByText("説明文")).toBeInTheDocument();
  });
});

describe("次の訪問でも保つもの", () => {
  it("開いたグループと隠した項目を、作り直した後も復元する", async () => {
    const layers = [roadMember("kept"), roadMember("dropped")];
    const { user, unmount } = setup(layers);
    await user.click(screen.getByRole("button", { name: `${ROAD_LABEL}の表示項目` }));
    await user.click(screen.getByRole("checkbox", { name: "droppedを表示しない" }));
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: ROAD_LABEL }));
    unmount();

    setup(layers);
    expect(screen.getByRole("button", { name: ROAD_LABEL })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "kept" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "dropped" })).not.toBeInTheDocument();
  });

  it("開いておける数を超えて保存された状態も、復元した時点で収める", () => {
    window.localStorage.setItem(
      "ridecompass:map-overlay-expanded-groups",
      JSON.stringify(MAP_OVERLAY_GROUP_ORDER.map((group) => `group:${group}`)),
    );
    setup(MAP_OVERLAY_GROUP_ORDER.map((group) => chip(`member_${group}`, { category: categoriesOf(group)[0] })));
    const expanded = MAP_OVERLAY_GROUP_ORDER.filter(
      (group) =>
        screen.getByRole("button", { name: MAP_OVERLAY_GROUP_LABELS[group] }).getAttribute("aria-expanded") === "true",
    );
    expect(expanded).toHaveLength(Math.min(MAP_OVERLAY_MAX_EXPANDED_GROUPS, MAP_OVERLAY_GROUP_ORDER.length));
  });
});
