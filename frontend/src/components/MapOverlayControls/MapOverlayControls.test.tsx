import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import MapOverlayControls from "./MapOverlayControls";

function baseProps() {
  return {
    showElevation: false,
    onShowElevationToggle: vi.fn(),
    showRoad: false,
    onShowRoadToggle: vi.fn(),
    roadHiddenKeysByMode: { surface: [], highway: [] } as Record<"surface" | "highway", string[]>,
    onRoadSettingsSave: vi.fn(),
    routeLayerOn: false,
    onRouteLayerToggle: vi.fn(),
    hasDetail: false,
  };
}

// 凡例・絞り込み内容の詳細・ルートの色分け選択パネルはすべてサイドバー側の
// MapLegendPanel.test.tsxで検証する。ここでは地図の上に残った最小限の要素
// （チップの押下状態・⚙でのダイアログ起動・絞り込み中を示すドット）だけを見る。
describe("MapOverlayControls", () => {
  it("各チップがON状態をaria-pressedで反映する", () => {
    render(<MapOverlayControls {...baseProps()} showElevation={true} showRoad={true} routeLayerOn={true} hasDetail={true} />);

    expect(screen.getByRole("button", { name: "標高図" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "路面" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "ルート" })).toHaveAttribute("aria-pressed", "true");
  });

  it("各チップのクリックで対応するon*Toggleコールバックが現在値の反転で呼ばれる", async () => {
    const user = userEvent.setup();
    const onShowElevationToggle = vi.fn();
    const onShowRoadToggle = vi.fn();
    const onRouteLayerToggle = vi.fn();
    render(
      <MapOverlayControls
        {...baseProps()}
        hasDetail={true}
        onShowElevationToggle={onShowElevationToggle}
        onShowRoadToggle={onShowRoadToggle}
        onRouteLayerToggle={onRouteLayerToggle}
      />,
    );

    await user.click(screen.getByRole("button", { name: "標高図" }));
    expect(onShowElevationToggle).toHaveBeenCalledWith(true);

    await user.click(screen.getByRole("button", { name: "路面" }));
    expect(onShowRoadToggle).toHaveBeenCalledWith(true);

    await user.click(screen.getByRole("button", { name: "ルート" }));
    expect(onRouteLayerToggle).toHaveBeenCalledWith(true);
  });

  it("hasDetail=falseのときルートチップがdisabledになり、aria-pressedもfalseのまま", () => {
    render(<MapOverlayControls {...baseProps()} routeLayerOn={true} hasDetail={false} />);
    const routeChip = screen.getByRole("button", { name: "ルート" });
    expect(routeChip).toBeDisabled();
    expect(routeChip).toHaveAttribute("aria-pressed", "false");
  });

  it("路面の⚙ボタンでRoadFilterDialogが開く", async () => {
    const user = userEvent.setup();
    render(<MapOverlayControls {...baseProps()} />);

    expect(screen.queryByRole("dialog", { name: "路面の表示設定" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "路面の表示設定を開く" }));
    expect(screen.getByRole("dialog", { name: "路面の表示設定" })).toBeInTheDocument();
  });

  it("保存済みの絞り込みが無ければ⚙のaria-labelに「絞り込み中」は付かない", () => {
    render(<MapOverlayControls {...baseProps()} />);
    expect(screen.getByRole("button", { name: "路面の表示設定を開く" })).toHaveAccessibleName(
      "路面の表示設定を開く",
    );
  });

  it("保存済みの絞り込みがあれば⚙のaria-labelに「絞り込み中」が付く", () => {
    render(
      <MapOverlayControls {...baseProps()} roadHiddenKeysByMode={{ surface: ["gravel"], highway: [] }} />,
    );
    expect(screen.getByRole("button", { name: "路面の表示設定を開く（絞り込み中）" })).toBeInTheDocument();
  });

  it("ダイアログで保存するとonRoadSettingsSaveが呼ばれ、ダイアログが閉じる", async () => {
    const user = userEvent.setup();
    const onRoadSettingsSave = vi.fn();
    render(<MapOverlayControls {...baseProps()} onRoadSettingsSave={onRoadSettingsSave} />);

    await user.click(screen.getByRole("button", { name: "路面の表示設定を開く" }));
    await user.click(screen.getByRole("checkbox", { name: /砂利・締固め/ }));
    await user.click(screen.getByRole("button", { name: "保存" }));

    expect(onRoadSettingsSave).toHaveBeenCalledWith({ surface: ["gravel"], highway: [] });
    expect(screen.queryByRole("dialog", { name: "路面の表示設定" })).not.toBeInTheDocument();
  });
});
