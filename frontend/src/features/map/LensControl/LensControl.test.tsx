import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LAYER_DATA_STATUS_LABELS } from "@/features/map/layers/mapLayers";
import { FIXED_LENS_LABELS, LENS_DIFFICULTY_ID, LENS_NONE_ID } from "@/lib/mapDisplay/routeStyleModes";

import LensControl, { type LensOption } from "./LensControl";

const option = (id: string, overrides: Partial<LensOption> = {}): LensOption => ({
  id,
  label: `${id}の軸`,
  color: "#123456",
  unused: false,
  routeOnly: false,
  ...overrides,
});
const OPTIONS = [option("used"), option("idle", { unused: true }), option("route", { routeOnly: true })];
const LEGEND = [
  { key: "step-0", label: "低い", color: "#00ff00", filter: [] },
  { key: "step-1", label: "高い", color: "#ff0000", filter: [] },
];

function renderLens(props: Partial<Parameters<typeof LensControl>[0]> = {}) {
  const handlers = {
    onLensChange: vi.fn(),
    onToggleLegendKey: vi.fn(),
    onSetHiddenLegendKeys: vi.fn(),
    onKeepAfterRouteChange: vi.fn(),
    onRouteShownChange: vi.fn(),
  };
  render(
    <LensControl
      lens="used"
      axisOptions={OPTIONS}
      legend={LEGEND}
      hiddenLegendKeys={[]}
      keepAfterRoute
      hasDetail={false}
      routeShown
      routeSelectable
      conditions={null}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}
const pill = () => screen.getByRole("button", { name: /^地図の色分け:/ });
const open = () => userEvent.click(pill());

describe("LensControl（レンズのピル）", () => {
  it.each([
    ["used", "usedの軸"],
    [LENS_DIFFICULTY_ID, FIXED_LENS_LABELS[LENS_DIFFICULTY_ID]],
  ])(
    "ピルは今のレンズ（%s）の名前（固定のレンズは固定の名前）を出し、隠していない段の色見本を並べる",
    (lens, label) => {
      renderLens({ lens, hiddenLegendKeys: ["step-1"], hasDetail: true });
      expect(pill()).toHaveAccessibleName(`地図の色分け: ${label}（タップで変更）`);
      const swatches = pill().querySelectorAll("[title]");
      expect([...swatches].map((swatch) => swatch.getAttribute("title"))).toEqual(["低い"]);
    },
  );

  it("取得状態は、ピルのtitleと、開いた先の文で伝える", async () => {
    renderLens({ dataStatus: "error" });
    expect(pill()).toHaveAttribute("title", LAYER_DATA_STATUS_LABELS.error);
    await open();
    expect(screen.getByRole("status")).toHaveTextContent(LAYER_DATA_STATUS_LABELS.error);
  });

  it("選択肢は「なし」「総合難易度」、評価軸に使用中の軸、未使用の軸の順で、使用中か未使用かは見出しで分け、ルート後のみの印を付ける（総合難易度にも）", async () => {
    renderLens();
    await open();
    const group = screen.getByRole("radiogroup", { name: "地図の色分け" });
    const labels = within(group)
      .getAllByRole("radio")
      .map((item) => item.textContent);
    expect(labels).toEqual([
      FIXED_LENS_LABELS[LENS_NONE_ID],
      `${FIXED_LENS_LABELS[LENS_DIFFICULTY_ID]}ルート後のみ`,
      "usedの軸",
      "routeの軸ルート後のみ",
      "idleの軸",
    ]);
    expect(within(group).getByText("評価軸に使用中")).toBeInTheDocument();
    expect(within(group).getByText("未使用")).toBeInTheDocument();
  });

  it.each([
    [LENS_DIFFICULTY_ID, `地図の色分け: ${FIXED_LENS_LABELS[LENS_DIFFICULTY_ID]}・ルート後のみ（タップで変更）`],
    ["route", "地図の色分け: routeの軸・ルート後のみ（タップで変更）"],
  ])("ルート前は、ルートの線にだけ色を付けるレンズ（%s）のピルにも「ルート後のみ」を付ける", (lens, name) => {
    renderLens({ lens });
    expect(pill()).toHaveAccessibleName(name);
    expect(within(pill()).getByText("ルート後のみ")).toBeInTheDocument();
  });

  it("走る条件で塗るレンズは、ピルと開いた先に条件を出す", async () => {
    renderLens({ conditions: "北へ走る・時速20km" });
    expect(pill()).toHaveAccessibleName("地図の色分け: usedの軸・北へ走る・時速20km（タップで変更）");
    expect(within(pill()).getByText("北へ走る・時速20km")).toBeInTheDocument();
    await open();
    expect(screen.getByText("周りの道は「北へ走る・時速20km」の条件で塗っています。")).toBeInTheDocument();
  });

  it("ルート確定後は「ルート後のみ」を付けず、使用中・未使用の見出しは中身があるときだけ", async () => {
    renderLens({ hasDetail: true, lens: LENS_DIFFICULTY_ID, axisOptions: [option("used")] });
    await open();
    expect(screen.queryByText("ルート後のみ")).not.toBeInTheDocument();
    expect(screen.queryByText("未使用")).not.toBeInTheDocument();
  });

  it("選ぶとレンズを変えて閉じる", async () => {
    const { onLensChange } = renderLens();
    await open();
    await userEvent.click(screen.getByRole("radio", { name: /idleの軸/ }));
    expect(onLensChange).toHaveBeenCalledWith("idle");
    expect(screen.queryByRole("radiogroup", { name: "地図の色分け" })).not.toBeInTheDocument();
  });

  it.each([
    [[], ["step-0", "step-1"]],
    [["step-0"], []],
  ])(
    "凡例の見出しのチェックは、全部表示中（隠している段: %j）なら全段を隠し、一部でも隠していれば全段を戻す",
    async (hidden, next) => {
      const { onSetHiddenLegendKeys } = renderLens({ hiddenLegendKeys: hidden });
      await open();
      await userEvent.click(screen.getByRole("checkbox", { name: "凡例の全段階をまとめて表示/非表示" }));
      expect(onSetHiddenLegendKeys).toHaveBeenCalledWith(next);
    },
  );

  it("凡例が無いレンズは、ピルにも開いた先にも凡例を出さない", async () => {
    renderLens({ legend: [] });
    expect(pill().querySelectorAll("[title]")).toHaveLength(0);
    await open();
    expect(screen.queryByText("凡例")).not.toBeInTheDocument();
  });

  it("一覧の「ルートを地図に出す」を押すと、出し入れを反転した値で知らせる", async () => {
    const { onRouteShownChange } = renderLens({ routeShown: true });
    await open();
    await userEvent.click(screen.getByRole("checkbox", { name: "ルートを地図に出す" }));
    expect(onRouteShownChange).toHaveBeenCalledWith(false);
  });

  it("候補を選ぶまでは、「ルートを地図に出す」を押せず、ONに見えない", async () => {
    renderLens({ routeShown: true, routeSelectable: false });
    await open();
    const route = screen.getByRole("checkbox", { name: "ルートを地図に出す" });
    expect(route).toBeDisabled();
    expect(route).not.toBeChecked();
  });
});
