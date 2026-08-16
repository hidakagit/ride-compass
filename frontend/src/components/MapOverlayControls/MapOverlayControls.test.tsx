import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import MapOverlayControls, { type OverlayLayerChip } from "./MapOverlayControls";

function baseLayers(): OverlayLayerChip[] {
  return [
    { id: "elevation", label: "標高図", on: false },
    { id: "road", label: "路面", on: false },
    { id: "route", label: "ルート", on: false },
  ];
}

function baseProps() {
  return {
    layers: baseLayers(),
    onToggle: vi.fn(),
    onSummaryClick: vi.fn(),
  };
}

// 凡例・絞り込み編集・色分けモード選択などの「細かな設定」はすべてサイドバー側
// （MapLayersPanel.test.tsx）で検証する。ここは地図の上に残った最小限の要素
// （ON/OFFチップと条件サマリ行）だけを見る。このコンポーネントはレイヤー固有の
// 知識を持たない汎用描画係のため、テストもpropsで渡した表示状態の反映のみを確認する。
describe("MapOverlayControls", () => {
  it("各チップがON状態をaria-pressedで反映する", () => {
    const layers = baseLayers().map((layer) => ({ ...layer, on: true }));
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    expect(screen.getByRole("button", { name: "標高図" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "路面" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "ルート" })).toHaveAttribute("aria-pressed", "true");
  });

  it("チップのクリックでonToggleがレイヤーIDと現在値の反転で呼ばれる", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const layers = baseLayers();
    layers[1].on = true; // 路面だけON
    render(<MapOverlayControls {...baseProps()} layers={layers} onToggle={onToggle} />);

    await user.click(screen.getByRole("button", { name: "標高図" }));
    expect(onToggle).toHaveBeenCalledWith("elevation", true);

    await user.click(screen.getByRole("button", { name: "路面" }));
    expect(onToggle).toHaveBeenCalledWith("road", false);
  });

  it("disabledのチップは押せず、on=trueでもaria-pressedはfalseのまま", () => {
    const layers = baseLayers();
    layers[2] = { ...layers[2], on: true, disabled: true };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    const routeChip = screen.getByRole("button", { name: "ルート" });
    expect(routeChip).toBeDisabled();
    expect(routeChip).toHaveAttribute("aria-pressed", "false");
  });

  it("ONのレイヤーにsummaryがあれば▶トグルが出るが、押すまでサマリ行は隠れている", async () => {
    const user = userEvent.setup();
    const onSummaryClick = vi.fn();
    const layers = baseLayers();
    layers[1] = { ...layers[1], on: true, summary: "アスファルトのみ" };
    render(<MapOverlayControls {...baseProps()} layers={layers} onSummaryClick={onSummaryClick} />);

    // 既定では条件サマリを表示せず、開閉トグルだけが出る
    expect(screen.queryByRole("button", { name: /路面:.*アスファルトのみ/ })).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "路面の絞り込み条件を表示" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const summaryButton = screen.getByRole("button", { name: /路面:.*アスファルトのみ/ });
    await user.click(summaryButton);
    expect(onSummaryClick).toHaveBeenCalledWith("road");
  });

  it("summarySwatchesがあれば▶を開いたときにサマリ行の先頭に色ドット・太さバーが並ぶ", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = {
      ...layers[1],
      on: true,
      summary: "石畳・敷石以外",
      summarySwatches: [
        {
          excluded: true,
          entries: [{ key: "stones", label: "石畳・敷石", color: "#7c3aed", filter: ["literal", true] }],
        },
        {
          excluded: false,
          entries: [
            { key: "track", label: "農道・林道", color: "#92400e", width: 1.75, filter: ["literal", true] },
          ],
        },
      ],
    };
    const { container } = render(<MapOverlayControls {...baseProps()} layers={layers} />);
    await user.click(screen.getByRole("button", { name: "路面の絞り込み条件を表示" }));

    const dot = container.querySelector('[style*="background: rgb(124, 58, 237)"]');
    expect(dot).toBeInTheDocument();
    // 太さ軸のカテゴリは色ではなく太さバー（swatchBarクラス）で表す
    expect(container.querySelector('span[class*="swatchBar"]')).toBeInTheDocument();
  });

  it("legendDetailsがあれば▶を開いたときに軸ごとの全カテゴリ内訳(表示中/非表示)が出る", async () => {
    const user = userEvent.setup();
    const layers = baseLayers();
    layers[1] = {
      ...layers[1],
      on: true,
      summary: "コンクリート以外",
      legendDetails: [
        {
          label: "路面の種類",
          legend: [
            { key: "asphalt", label: "アスファルト", color: "#16a34a", filter: ["literal", true] },
            { key: "concrete", label: "コンクリート", color: "#0d9488", filter: ["literal", true] },
          ],
          hiddenKeys: ["concrete"],
        },
      ],
    };
    render(<MapOverlayControls {...baseProps()} layers={layers} />);
    await user.click(screen.getByRole("button", { name: "路面の絞り込み条件を表示" }));

    // 1行要約だけでなく、軸見出し・非表示分を含む全カテゴリがそれ単体で読める形で出る
    expect(screen.getByText("路面の種類")).toBeInTheDocument();
    expect(screen.getByText("アスファルト")).toBeInTheDocument();
    expect(screen.getByText("コンクリート")).toBeInTheDocument();
    expect(screen.getByText("非表示")).toBeInTheDocument();
  });

  it("OFF・disabled・summary無しのレイヤーにはサマリ行が出ない", () => {
    const layers: OverlayLayerChip[] = [
      { id: "elevation", label: "標高図", on: true, summary: null }, // 条件なし
      { id: "road", label: "路面", on: false, summary: "アスファルトのみ" }, // OFF
      { id: "route", label: "ルート", on: true, disabled: true, summary: "色分け: 風の影響" }, // disabled
    ];
    render(<MapOverlayControls {...baseProps()} layers={layers} />);

    expect(screen.queryByRole("button", { name: /アスファルトのみ/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /色分け/ })).not.toBeInTheDocument();
  });
});
