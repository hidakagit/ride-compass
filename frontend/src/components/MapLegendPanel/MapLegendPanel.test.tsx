import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import MapLegendPanel from "./MapLegendPanel";

function baseProps() {
  return {
    showRoad: false,
    roadHiddenKeysByMode: { surface: [], highway: [] } as Record<"surface" | "highway", string[]>,
    regionZoomTooWide: false,
    routeLayerOn: false,
    onRouteLayerToggle: vi.fn(),
    routeStyleModeId: "wind" as const,
    onRouteStyleModeChange: vi.fn(),
    hiddenRouteLegendKeys: [] as string[],
    onRouteLegendToggle: vi.fn(),
    hasDetail: false,
  };
}

describe("MapLegendPanel", () => {
  it("showRoad=falseのときは「ONにすると表示されます」の案内のみで、凡例は出ない", () => {
    render(<MapLegendPanel {...baseProps()} showRoad={false} />);
    expect(screen.getByText(/ONにすると地図に表示されます/)).toBeInTheDocument();
    expect(screen.queryByText("アスファルト")).not.toBeInTheDocument();
  });

  it("showRoad=true && regionZoomTooWide=trueのときズーム警告が表示され凡例は出ない", () => {
    render(<MapLegendPanel {...baseProps()} showRoad={true} regionZoomTooWide={true} />);
    expect(screen.getByText("表示範囲が広すぎます。ズームインしてください。")).toBeInTheDocument();
    expect(screen.queryByText("アスファルト")).not.toBeInTheDocument();
  });

  // 色（路面の種類）・太さ（道路の種類）の両方の凡例が独立して出る
  it("showRoad=true && regionZoomTooWide=falseのとき色・太さ両方の凡例が表示される", () => {
    render(<MapLegendPanel {...baseProps()} showRoad={true} regionZoomTooWide={false} />);
    expect(screen.getByText(/色：路面の種類/)).toBeInTheDocument();
    expect(screen.getByText("アスファルト")).toBeInTheDocument();
    expect(screen.getByText(/太さ：道路の種類/)).toBeInTheDocument();
    expect(screen.getByText("幹線道路")).toBeInTheDocument();
    expect(screen.queryByText("表示範囲が広すぎます。ズームインしてください。")).not.toBeInTheDocument();
  });

  it("非表示中の凡例カテゴリは薄く表示される（参照表示、操作はしない）", () => {
    render(
      <MapLegendPanel {...baseProps()} showRoad={true} roadHiddenKeysByMode={{ surface: ["gravel"], highway: [] }} />,
    );
    expect(screen.getByText("砂利・締固め").closest("span")?.className).toMatch(/legendItemHidden/);
  });

  it("hasDetail=falseのときルート欄は案内のみでモード選択は出ない", () => {
    render(<MapLegendPanel {...baseProps()} hasDetail={false} />);
    expect(screen.getByText("ルートを生成・選択すると使えます")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "ルートの色分け" })).not.toBeInTheDocument();
  });

  it("hasDetail=trueのときルートのモード選択・凡例チェックボックスが常に表示される", () => {
    render(<MapLegendPanel {...baseProps()} hasDetail={true} />);
    expect(screen.getByRole("radio", { name: "風の影響" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("checkbox", { name: /易しい/ })).toBeInTheDocument();
  });

  it("ルートのモード選択でonRouteStyleModeChangeが呼ばれ、レイヤーOFFなら自動でONにする", async () => {
    const user = userEvent.setup();
    const onRouteStyleModeChange = vi.fn();
    const onRouteLayerToggle = vi.fn();
    render(
      <MapLegendPanel
        {...baseProps()}
        hasDetail={true}
        routeLayerOn={false}
        onRouteStyleModeChange={onRouteStyleModeChange}
        onRouteLayerToggle={onRouteLayerToggle}
      />,
    );

    await user.click(screen.getByRole("radio", { name: "勾配" }));

    expect(onRouteStyleModeChange).toHaveBeenCalledWith("gradient");
    expect(onRouteLayerToggle).toHaveBeenCalledWith(true);
  });

  it("ルートのモード選択時、レイヤーが既にONならonRouteLayerToggleは呼ばれない", async () => {
    const user = userEvent.setup();
    const onRouteLayerToggle = vi.fn();
    render(
      <MapLegendPanel {...baseProps()} hasDetail={true} routeLayerOn={true} onRouteLayerToggle={onRouteLayerToggle} />,
    );

    await user.click(screen.getByRole("radio", { name: "勾配" }));

    expect(onRouteLayerToggle).not.toHaveBeenCalled();
  });

  it("ルートの凡例チェックボックス操作でonRouteLegendToggleが呼ばれる", async () => {
    const user = userEvent.setup();
    const onRouteLegendToggle = vi.fn();
    render(
      <MapLegendPanel
        {...baseProps()}
        hasDetail={true}
        routeStyleModeId="gradient"
        onRouteLegendToggle={onRouteLegendToggle}
      />,
    );

    await user.click(screen.getByRole("checkbox", { name: /下り/ }));

    expect(onRouteLegendToggle).toHaveBeenCalledWith("downhill");
  });
});
