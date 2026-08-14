import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import MapLayerControls from "./MapLayerControls";

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
    onRefresh: vi.fn(),
  };
}

describe("MapLayerControls", () => {
  it("showElevation/showRoad/dynamicLayerOnの各チェックボックスがpropを反映する", () => {
    render(<MapLayerControls {...baseProps()} showElevation={true} showRoad={true} dynamicLayerOn={true} hasDetail={true} />);

    expect(screen.getByLabelText("標高（国土地理院 色別標高図）")).toBeChecked();
    expect(screen.getByLabelText("路面で色分け")).toBeChecked();
    expect(screen.getByLabelText("風の影響を表示")).toBeChecked();
  });

  it("各チェックボックスのクリックで対応するon*Toggleコールバックが呼ばれる", async () => {
    const user = userEvent.setup();
    const onShowElevationToggle = vi.fn();
    const onShowRoadToggle = vi.fn();
    const onDynamicLayerToggle = vi.fn();
    render(
      <MapLayerControls
        {...baseProps()}
        hasDetail={true}
        onShowElevationToggle={onShowElevationToggle}
        onShowRoadToggle={onShowRoadToggle}
        onDynamicLayerToggle={onDynamicLayerToggle}
      />,
    );

    await user.click(screen.getByLabelText("標高（国土地理院 色別標高図）"));
    expect(onShowElevationToggle).toHaveBeenCalledWith(true);

    await user.click(screen.getByLabelText("路面で色分け"));
    expect(onShowRoadToggle).toHaveBeenCalledWith(true);

    await user.click(screen.getByLabelText("風の影響を表示"));
    expect(onDynamicLayerToggle).toHaveBeenCalledWith(true);
  });

  it("hasDetail=falseのとき風の影響を表示チェックボックスがdisabled", () => {
    render(<MapLayerControls {...baseProps()} hasDetail={false} />);
    expect(screen.getByLabelText("風の影響を表示")).toBeDisabled();
  });

  it("showRoad=true && regionZoomTooWide=trueのときズーム警告文が表示される", () => {
    render(<MapLayerControls {...baseProps()} showRoad={true} regionZoomTooWide={true} />);
    expect(screen.getByText("表示範囲が広すぎます。地図をズームインしてください。")).toBeInTheDocument();
    expect(screen.queryByText("舗装路")).not.toBeInTheDocument();
  });

  it("showRoad=true && regionZoomTooWide=falseのとき道路の凡例が表示される", () => {
    render(<MapLayerControls {...baseProps()} showRoad={true} regionZoomTooWide={false} />);
    // 凡例のラベルはspan要素の間に挟まれた素のテキストノードで、隣接するspanの
    // テキストとまとめて1つの要素とはみなされないため正規表現マッチで確認する。
    expect(screen.getByText(/舗装路/)).toBeInTheDocument();
    expect(screen.getByText(/未舗装等/)).toBeInTheDocument();
    expect(screen.getByText(/不明/)).toBeInTheDocument();
    expect(screen.queryByText("表示範囲が広すぎます。地図をズームインしてください。")).not.toBeInTheDocument();
  });

  it("showRoad=falseのときは凡例もズーム警告も表示されない", () => {
    render(<MapLayerControls {...baseProps()} showRoad={false} regionZoomTooWide={true} />);
    expect(screen.queryByText(/舗装路/)).not.toBeInTheDocument();
    expect(screen.queryByText("表示範囲が広すぎます。地図をズームインしてください。")).not.toBeInTheDocument();
  });

  it("dynamicLayerOn=true && hasDetail=trueのとき風の凡例が表示される", () => {
    render(<MapLayerControls {...baseProps()} dynamicLayerOn={true} hasDetail={true} />);
    expect(screen.getByText(/易しい/)).toBeInTheDocument();
    expect(screen.getByText(/普通/)).toBeInTheDocument();
    expect(screen.getByText(/難しい/)).toBeInTheDocument();
  });

  it("「変わらないデータを更新」ボタンのクリックでonRefreshが呼ばれる", async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();
    render(<MapLayerControls {...baseProps()} onRefresh={onRefresh} />);

    await user.click(screen.getByRole("button", { name: "変わらないデータを更新" }));

    expect(onRefresh).toHaveBeenCalled();
  });
});
