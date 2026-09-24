/**
 * `AxisMapDisplaySection.tsx`——「地図表示・公開」の節: 色分けしきい値のまとめ入力（読めたときだけ下書きへ入れ、
 * 読めない間は親の検証へ伝える）・地図で段にならない値の名指し・段階プレビュー・体感ラベル・チップの表示要素・公開。
 *
 * 地図で段になるか（`mapBands`）と段の配色（`mapBandColors`）は親が渡すものを与える。
 *
 * ここで見ないもの:
 * - まとめ入力の読み方・段数合わせ・地図の段への引き直し → `axisDraft.test.ts`
 * - 凡例の段のレンジ表記 → `lib/mapDisplay/mapColorLegend`
 * - 保存前の検証（読めない入力で止めること） → `AxisComposer.test.tsx`
 */
import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MapBandsOfThresholds } from "@/features/admin/adminApi";
import { AXIS_ICON_PALETTE } from "@/lib/mapDisplay/axisIconPalette";
import type { AxisDefinitionResponse } from "@/types/route";

import { AxisMapDisplaySection } from "./AxisMapDisplaySection";
import { emptyDraft, type Draft } from "./axisDraft";

const onThresholdErrorChange = vi.fn();

interface HarnessProps {
  initial: Draft;
  editing?: AxisDefinitionResponse | null;
  restrictedDisplayOnly?: boolean;
  republishing?: boolean;
  mapBandColors?: (boundaries: readonly number[]) => readonly string[];
  mapValueUnit?: string;
  mapBands?: MapBandsOfThresholds;
}

function Harness({ initial, editing = null, restrictedDisplayOnly = false, mapValueUnit = "", ...rest }: HarnessProps) {
  const [draft, setDraft] = useState(initial);
  return (
    <>
      <output data-testid="draft">{JSON.stringify(draft)}</output>
      <AxisMapDisplaySection
        draft={draft}
        setDraft={setDraft}
        editing={editing}
        restrictedDisplayOnly={restrictedDisplayOnly}
        mapValueUnit={mapValueUnit}
        onThresholdErrorChange={onThresholdErrorChange}
        {...rest}
      />
    </>
  );
}

function draftWith(overrides: Partial<Draft> = {}): Draft {
  return { ...emptyDraft([]), ...overrides };
}

function renderSection(props: Partial<HarnessProps> = {}) {
  const user = userEvent.setup();
  render(<Harness initial={draftWith()} {...props} />);
  return user;
}

const draft = (): Draft => JSON.parse(screen.getByTestId("draft").textContent!);
const thresholdInput = () => screen.getByRole("textbox", { name: "色分けのしきい値（まとめて入力）" });

async function typeThresholds(user: ReturnType<typeof userEvent.setup>, text: string) {
  await user.clear(thresholdInput());
  await user.type(thresholdInput(), text);
}

function editingAxis(kind: "ramp" | "none"): AxisDefinitionResponse {
  return {
    axis_id: "axis_x",
    label: "",
    description: "",
    weight_share_when_published: null,
    category: "推定",
    default_weight: 0,
    is_published: false,
    show_map_icon: true,
    time_scope: "always",
    dedicated_way_value_layer: false,
    dynamic_way_value_needs_time: false,
    dynamic_way_value_needs_bearing: false,
    dynamic_way_value_needs_speed: false,
    shape: { kind: "breakpoint_linear", terms: [], preprocess: "identity", breakpoints: [] },
    display: { kind, label: "", category: "" },
  };
}

beforeEach(() => {
  onThresholdErrorChange.mockReset();
});

describe("地図表示ができない軸の注記", () => {
  it("編集中の軸の地図表示が無いときだけ出し、新規作成中・地図表示のある軸には出さない", () => {
    const note = /地図表示用のデータ取得経路が用意されていません/;
    const { unmount } = render(<Harness initial={draftWith()} editing={editingAxis("none")} />);
    expect(screen.getByText(note)).toBeInTheDocument();
    unmount();

    const second = render(<Harness initial={draftWith()} editing={editingAxis("ramp")} />);
    expect(screen.queryByText(note)).not.toBeInTheDocument();
    second.unmount();

    render(<Harness initial={draftWith()} editing={null} />);
    expect(screen.queryByText(note)).not.toBeInTheDocument();
  });
});

describe("色分けしきい値", () => {
  it("上書きしていなければ設定の口だけを置き、押すと空の入力欄を出す（下書きは空の上書き）", async () => {
    const user = renderSection();
    expect(screen.queryByRole("textbox", { name: /しきい値/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
    expect(thresholdInput()).toHaveValue("");
    expect(draft().displayThresholdsOverride).toEqual([]);
  });

  it("入力欄は、下書きのしきい値をまとめた形で始まる", () => {
    renderSection({ initial: draftWith({ displayThresholdsOverride: [1, 2.5] }) });
    expect(thresholdInput()).toHaveValue("1, 2.5");
  });

  it("読めた入力は下書きへ入れ、誤りなしを親へ伝える", async () => {
    const user = renderSection({ initial: draftWith({ displayThresholdsOverride: [] }) });
    await typeThresholds(user, "1 3");
    expect(draft().displayThresholdsOverride).toEqual([1, 3]);
    expect(onThresholdErrorChange).toHaveBeenLastCalledWith(null);
  });

  it("読めない入力は下書きへ入れず（直前の並びを残す）、理由を出して親へ伝える。直せば理由は消える", async () => {
    const user = renderSection({ initial: draftWith({ displayThresholdsOverride: [1, 2] }) });
    await user.type(thresholdInput(), ", x");

    expect(draft().displayThresholdsOverride).toEqual([1, 2]);
    const [message] = onThresholdErrorChange.mock.lastCall!;
    expect(message).toEqual(expect.stringContaining("x"));
    expect(screen.getByText(message)).toBeInTheDocument();

    await typeThresholds(user, "1, 2, 4");
    expect(draft().displayThresholdsOverride).toEqual([1, 2, 4]);
    expect(onThresholdErrorChange).toHaveBeenLastCalledWith(null);
    expect(screen.queryByText(message)).not.toBeInTheDocument();
  });

  it("体感ラベルを上書きしているとき、しきい値の数が変わればラベルの数を段の数へ合わせる", async () => {
    const user = renderSection({
      initial: draftWith({ displayThresholdsOverride: [1], displayBandLabelsOverride: ["低", "高"] }),
    });
    await user.type(thresholdInput(), " 2 3");
    expect(draft().displayBandLabelsOverride).toEqual(["低", "高", "", ""]);
  });

  it("「自動計算に戻す」で、しきい値と体感ラベルの上書きを両方外し、誤りも消す", async () => {
    const user = renderSection({
      initial: draftWith({ displayThresholdsOverride: [1], displayBandLabelsOverride: ["低", "高"] }),
    });
    await user.type(thresholdInput(), "x");
    await user.click(screen.getByRole("button", { name: "自動計算に戻す" }));

    expect(draft()).toMatchObject({ displayThresholdsOverride: null, displayBandLabelsOverride: null });
    expect(onThresholdErrorChange).toHaveBeenLastCalledWith(null);
    expect(screen.getByRole("button", { name: "+ しきい値を自分で設定する" })).toBeInTheDocument();
  });

  it("地図で段にならない値があれば、入力欄の下で名指しする。入力が読めない間は出さない", async () => {
    const mapBands = { droppedOnMap: [2], bandsOnMap: [0, 2] };
    const user = renderSection({ initial: draftWith({ displayThresholdsOverride: [1, 2, 3] }), mapBands });
    expect(screen.getByText("地図では効かない: 2")).toBeInTheDocument();

    await user.type(thresholdInput(), "x");
    expect(screen.queryByText(/地図では効かない/)).not.toBeInTheDocument();
  });
});

describe("段階プレビュー", () => {
  const preview = () => screen.getByLabelText(/色分けプレビュー/);

  it("しきい値が無ければ出さない", () => {
    renderSection({ initial: draftWith({ displayThresholdsOverride: [] }) });
    expect(screen.queryByLabelText(/色分けプレビュー/)).not.toBeInTheDocument();
  });

  it("段の数は、地図で段にならない値を除いた境界で数え、配色も残った境界で決める", () => {
    const mapBandColors = vi.fn((boundaries: readonly number[]) =>
      Array.from({ length: boundaries.length + 1 }, (_, i) => `rgb(${i}, 0, 0)`),
    );
    renderSection({
      initial: draftWith({ displayThresholdsOverride: [1, 2, 3] }),
      mapBands: { droppedOnMap: [2], bandsOnMap: [0, 2, 3] },
      mapBandColors,
    });

    expect(preview()).toHaveTextContent("3段階になります");
    expect(mapBandColors).toHaveBeenLastCalledWith([1, 3]);
    const swatches = Array.from(preview().querySelectorAll("li > span[aria-hidden]")) as HTMLElement[];
    expect(swatches.map((swatch) => swatch.style.background)).toEqual(["rgb(0, 0, 0)", "rgb(1, 0, 0)", "rgb(2, 0, 0)"]);
    expect(screen.queryByText(/配色はまだ決まっていません/)).not.toBeInTheDocument();
  });

  it("配色が決まっていない軸は、色を付けず、その旨を添える", () => {
    renderSection({ initial: draftWith({ displayThresholdsOverride: [1] }) });
    expect(preview().querySelectorAll("li > span[aria-hidden]")).toHaveLength(0);
    expect(screen.getByText(/配色はまだ決まっていません/)).toBeInTheDocument();
  });

  it("体感ラベルは、地図の各段に当たる入力の段のラベルを添える", () => {
    renderSection({
      initial: draftWith({ displayThresholdsOverride: [1, 2], displayBandLabelsOverride: ["低", "中", "高"] }),
      mapBands: { droppedOnMap: [2], bandsOnMap: [0, 2] },
    });
    const items = within(preview()).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("低");
    expect(items[1]).toHaveTextContent("高");
    expect(preview()).not.toHaveTextContent("中");
  });

  it("段のレンジへ、渡された単位を添える", () => {
    renderSection({ initial: draftWith({ displayThresholdsOverride: [10] }), mapValueUnit: "km/h" });
    expect(preview()).toHaveTextContent("km/h");
  });
});

describe("体感ラベル", () => {
  it("しきい値を上書きしていなければ、体感ラベルの欄自体を出さない", () => {
    renderSection();
    expect(screen.queryByRole("button", { name: "+ 体感ラベルを設定する" })).not.toBeInTheDocument();
  });

  it("設定すると段の数ぶんの空欄を出し、段ごとに打てる。やめると上書きを外す", async () => {
    const user = renderSection({ initial: draftWith({ displayThresholdsOverride: [1, 2] }) });
    await user.click(screen.getByRole("button", { name: "+ 体感ラベルを設定する" }));
    expect(draft().displayBandLabelsOverride).toEqual(["", "", ""]);

    await user.type(screen.getByRole("textbox", { name: "体感ラベル2" }), "中");
    expect(draft().displayBandLabelsOverride).toEqual(["", "中", ""]);

    await user.click(screen.getByRole("button", { name: "体感ラベルの設定をやめる" }));
    expect(draft().displayBandLabelsOverride).toBeNull();
    expect(draft().displayThresholdsOverride).toEqual([1, 2]);
  });

  it("地図の段に当たらない入力の段のラベル欄には、地図には出ないと印を付ける。判定が無ければ付けない", () => {
    const initial = draftWith({ displayThresholdsOverride: [1, 2], displayBandLabelsOverride: ["低", "中", "高"] });
    const { unmount } = render(<Harness initial={initial} mapBands={{ droppedOnMap: [2], bandsOnMap: [0, 2] }} />);
    const marked = [1, 2, 3].map(
      (n) =>
        within(screen.getByRole("textbox", { name: `体感ラベル${n}` }).parentElement!).queryByText("地図には出ない") !==
        null,
    );
    expect(marked).toEqual([false, true, false]);
    unmount();

    render(<Harness initial={initial} />);
    expect(screen.queryByText("地図には出ない")).not.toBeInTheDocument();
  });
});

describe("チップの表示要素", () => {
  it("地図に出すか・アイコン・略称・レイヤー一覧の説明を下書きへ入れる", async () => {
    const iconIds = Object.keys(AXIS_ICON_PALETTE);
    expect(iconIds.length).toBeGreaterThan(0);
    const user = renderSection({ initial: draftWith({ showMapIcon: true }) });

    await user.click(screen.getByRole("checkbox", { name: "地図に出す" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "アイコン" }), iconIds[0]);
    await user.type(screen.getByRole("textbox", { name: "チップの略称" }), "略称");
    await user.type(screen.getByRole("textbox", { name: /panel_hint/ }), "説明");

    expect(draft()).toMatchObject({ showMapIcon: false, iconId: iconIds[0], chipLabel: "略称", panelHint: "説明" });
  });

  it("アイコンは未設定（汎用）も選べる", async () => {
    const user = renderSection({ initial: draftWith({ iconId: Object.keys(AXIS_ICON_PALETTE)[0] }) });
    await user.selectOptions(screen.getByRole("combobox", { name: "アイコン" }), "");
    expect(draft().iconId).toBe("");
  });
});

describe("公開", () => {
  it("下書きの軸は、公開するかを切り替えられる", async () => {
    const user = renderSection({ initial: draftWith({ isPublished: false }) });
    await user.click(screen.getByRole("checkbox", { name: "公開する" }));
    expect(draft().isPublished).toBe(true);
  });

  it("公開済みの軸を表示だけ編集している間は、公開の切り替えを出さない", () => {
    renderSection({ restrictedDisplayOnly: true });
    expect(screen.queryByRole("checkbox", { name: "公開する" })).not.toBeInTheDocument();
  });

  it("「調整する」で下書きへ戻している間は、切り替えの代わりに、保存すると公開へ戻ると言う", () => {
    renderSection({ republishing: true });
    expect(screen.queryByRole("checkbox", { name: "公開する" })).not.toBeInTheDocument();
    expect(screen.getByText(/保存すると公開へ戻ります/)).toBeInTheDocument();
  });
});
