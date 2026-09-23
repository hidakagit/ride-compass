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
  };
  render(
    <LensControl
      lens="used"
      axisOptions={OPTIONS}
      legend={LEGEND}
      hiddenLegendKeys={[]}
      keepAfterRoute
      hasDetail={false}
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}
const pill = () => screen.getByRole("button", { name: /^レンズ:/ });
const open = () => userEvent.click(pill());

describe("LensControl（レンズのピル）", () => {
  it("ピルは今のレンズの名前（固定のレンズは固定の名前）を出し、隠していない段の色見本を並べる", () => {
    renderLens({ hiddenLegendKeys: ["step-1"] });
    expect(pill()).toHaveAccessibleName("レンズ: usedの軸（タップで変更）");
    const swatches = pill().querySelectorAll("[title]");
    expect([...swatches].map((swatch) => swatch.getAttribute("title"))).toEqual(["低い"]);
  });

  it("固定のレンズ（なし・総合難易度）は固定の名前", () => {
    renderLens({ lens: LENS_DIFFICULTY_ID });
    expect(pill()).toHaveAccessibleName(`レンズ: ${FIXED_LENS_LABELS[LENS_DIFFICULTY_ID]}（タップで変更）`);
  });

  it("取得状態は、ピルのtitleと、開いた先の文で伝える", async () => {
    renderLens({ dataStatus: "error" });
    expect(pill()).toHaveAttribute("title", LAYER_DATA_STATUS_LABELS.error);
    await open();
    expect(screen.getByRole("status")).toHaveTextContent(LAYER_DATA_STATUS_LABELS.error);
  });

  it("選択肢は「なし」「総合難易度」、評価に使用中の軸、未使用の軸の順で、未使用・ルート後のみの印を付ける", async () => {
    renderLens();
    await open();
    const group = screen.getByRole("radiogroup", { name: "レンズ" });
    const labels = within(group)
      .getAllByRole("radio")
      .map((item) => item.textContent);
    expect(labels).toEqual([
      FIXED_LENS_LABELS[LENS_NONE_ID],
      FIXED_LENS_LABELS[LENS_DIFFICULTY_ID],
      "usedの軸",
      "routeの軸ルート後のみ",
      "idleの軸未使用",
    ]);
    expect(within(group).getByText("評価に使用中")).toBeInTheDocument();
    // 見出しの「未使用」と、未使用の軸の印
    expect(within(group).getAllByText("未使用")).toHaveLength(2);
  });

  it("ルート確定後は「ルート後のみ」を付けず、使用中・未使用の見出しは中身があるときだけ", async () => {
    renderLens({ hasDetail: true, axisOptions: [option("used")] });
    await open();
    expect(screen.queryByText("ルート後のみ")).not.toBeInTheDocument();
    expect(screen.queryByText("未使用")).not.toBeInTheDocument();
  });

  it("選ぶとレンズを変えて閉じる", async () => {
    const { onLensChange } = renderLens();
    await open();
    await userEvent.click(screen.getByRole("radio", { name: /idleの軸/ }));
    expect(onLensChange).toHaveBeenCalledWith("idle");
    expect(screen.queryByRole("radiogroup", { name: "レンズ" })).not.toBeInTheDocument();
  });

  it("ルート後も周囲を塗るかを切り替えられる", async () => {
    const { onKeepAfterRouteChange } = renderLens();
    await open();
    await userEvent.click(screen.getByRole("checkbox", { name: "ルート後も周囲の道路を薄く塗る" }));
    expect(onKeepAfterRouteChange).toHaveBeenCalledWith(false);
  });

  it("凡例の見出しのチェックは、全段を隠す／全段を戻す", async () => {
    const first = renderLens();
    await open();
    await userEvent.click(screen.getByRole("checkbox", { name: "凡例の全段階をまとめて表示/非表示" }));
    expect(first.onSetHiddenLegendKeys).toHaveBeenCalledWith(["step-0", "step-1"]);
    await userEvent.click(screen.getByRole("checkbox", { name: "低い" }));
    expect(first.onToggleLegendKey).toHaveBeenCalledWith("step-0");
  });

  it("一部でも隠していれば、見出しのチェックは全段を戻す", async () => {
    const { onSetHiddenLegendKeys } = renderLens({ hiddenLegendKeys: ["step-0"] });
    await open();
    await userEvent.click(screen.getByRole("checkbox", { name: "凡例の全段階をまとめて表示/非表示" }));
    expect(onSetHiddenLegendKeys).toHaveBeenCalledWith([]);
  });

  it("凡例が無いレンズは、ピルにも開いた先にも凡例を出さない", async () => {
    renderLens({ legend: [] });
    expect(pill().querySelectorAll("[title]")).toHaveLength(0);
    await open();
    expect(screen.queryByText("凡例")).not.toBeInTheDocument();
  });
});
