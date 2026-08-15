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

  it("ONのレイヤーにsummaryがあればサマリ行が表示され、タップでonSummaryClickが呼ばれる", async () => {
    const user = userEvent.setup();
    const onSummaryClick = vi.fn();
    const layers = baseLayers();
    layers[1] = { ...layers[1], on: true, summary: "アスファルトのみ" };
    render(<MapOverlayControls {...baseProps()} layers={layers} onSummaryClick={onSummaryClick} />);

    const summaryButton = screen.getByRole("button", { name: /路面:.*アスファルトのみ/ });
    await user.click(summaryButton);

    expect(onSummaryClick).toHaveBeenCalledWith("road");
  });

  it("trailingButtonを渡すとレイヤー一覧の下に区切り線付きで表示され、クリックでonClickが呼ばれる", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <MapOverlayControls
        {...baseProps()}
        trailingButton={{
          icon: <span>icon</span>,
          label: "ログ",
          active: true,
          onClick,
          ariaLabel: "デバッグログを閉じる",
        }}
      />
    );

    const trailing = screen.getByRole("button", { name: "デバッグログを閉じる" });
    expect(trailing).toHaveAttribute("aria-pressed", "true");
    await user.click(trailing);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("trailingButtonを渡さなければ表示されない", () => {
    render(<MapOverlayControls {...baseProps()} />);
    expect(screen.queryByRole("button", { name: "ログ" })).not.toBeInTheDocument();
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
