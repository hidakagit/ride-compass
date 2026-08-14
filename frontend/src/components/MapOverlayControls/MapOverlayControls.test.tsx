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
    dynamicLayerOn: false,
    onDynamicLayerToggle: vi.fn(),
    hasDetail: false,
    regionZoomTooWide: false,
  };
}

describe("MapOverlayControls", () => {
  it("各チップがON状態をaria-pressedで反映する", () => {
    render(
      <MapOverlayControls {...baseProps()} showElevation={true} showRoad={true} dynamicLayerOn={true} hasDetail={true} />,
    );

    expect(screen.getByRole("button", { name: "標高" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "路面" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "風" })).toHaveAttribute("aria-pressed", "true");
  });

  it("各チップのクリックで対応するon*Toggleコールバックが現在値の反転で呼ばれる", async () => {
    const user = userEvent.setup();
    const onShowElevationToggle = vi.fn();
    const onShowRoadToggle = vi.fn();
    const onDynamicLayerToggle = vi.fn();
    render(
      <MapOverlayControls
        {...baseProps()}
        hasDetail={true}
        onShowElevationToggle={onShowElevationToggle}
        onShowRoadToggle={onShowRoadToggle}
        onDynamicLayerToggle={onDynamicLayerToggle}
      />,
    );

    await user.click(screen.getByRole("button", { name: "標高" }));
    expect(onShowElevationToggle).toHaveBeenCalledWith(true);

    await user.click(screen.getByRole("button", { name: "路面" }));
    expect(onShowRoadToggle).toHaveBeenCalledWith(true);

    await user.click(screen.getByRole("button", { name: "風" }));
    expect(onDynamicLayerToggle).toHaveBeenCalledWith(true);
  });

  it("hasDetail=falseのとき風チップがdisabledになり、aria-pressedもfalseのまま", () => {
    // dynamicLayerOn=trueでもルート未選択（hasDetail=false）なら実際には描画されないため、
    // 見た目（押下状態）もfalse側に倒す
    render(<MapOverlayControls {...baseProps()} dynamicLayerOn={true} hasDetail={false} />);
    const windChip = screen.getByRole("button", { name: "風" });
    expect(windChip).toBeDisabled();
    expect(windChip).toHaveAttribute("aria-pressed", "false");
  });

  it("showRoad=true && regionZoomTooWide=trueのときズーム警告が表示され凡例は出ない", () => {
    render(<MapOverlayControls {...baseProps()} showRoad={true} regionZoomTooWide={true} />);
    expect(screen.getByText("表示範囲が広すぎます。ズームインしてください。")).toBeInTheDocument();
    expect(screen.queryByText(/舗装路/)).not.toBeInTheDocument();
  });

  it("showRoad=true && regionZoomTooWide=falseのとき路面の凡例が表示される", () => {
    render(<MapOverlayControls {...baseProps()} showRoad={true} regionZoomTooWide={false} />);
    // 凡例のラベルはspan要素の間に挟まれた素のテキストノードのため正規表現マッチで確認する。
    expect(screen.getByText(/舗装路/)).toBeInTheDocument();
    expect(screen.getByText(/未舗装等/)).toBeInTheDocument();
    expect(screen.getByText(/不明/)).toBeInTheDocument();
    expect(screen.queryByText("表示範囲が広すぎます。ズームインしてください。")).not.toBeInTheDocument();
  });

  it("showRoad=falseのときは凡例もズーム警告も表示されない", () => {
    render(<MapOverlayControls {...baseProps()} showRoad={false} regionZoomTooWide={true} />);
    expect(screen.queryByText(/舗装路/)).not.toBeInTheDocument();
    expect(screen.queryByText("表示範囲が広すぎます。ズームインしてください。")).not.toBeInTheDocument();
  });

  it("dynamicLayerOn=true && hasDetail=trueのとき風の凡例が表示される", () => {
    render(<MapOverlayControls {...baseProps()} dynamicLayerOn={true} hasDetail={true} />);
    expect(screen.getByText(/易しい/)).toBeInTheDocument();
    expect(screen.getByText(/普通/)).toBeInTheDocument();
    expect(screen.getByText(/難しい/)).toBeInTheDocument();
  });
});
