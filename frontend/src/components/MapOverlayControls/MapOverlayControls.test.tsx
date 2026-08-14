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
    roadStyleModeId: "paved" as const,
    onRoadStyleModeChange: vi.fn(),
    hiddenRoadLegendKeys: [] as string[],
    onRoadLegendToggle: vi.fn(),
    routeLayerOn: false,
    onRouteLayerToggle: vi.fn(),
    routeStyleModeId: "wind" as const,
    onRouteStyleModeChange: vi.fn(),
    hiddenRouteLegendKeys: [] as string[],
    onRouteLegendToggle: vi.fn(),
    hasDetail: false,
    regionZoomTooWide: false,
  };
}

describe("MapOverlayControls", () => {
  it("各チップがON状態をaria-pressedで反映する", () => {
    render(
      <MapOverlayControls {...baseProps()} showElevation={true} showRoad={true} routeLayerOn={true} hasDetail={true} />,
    );

    expect(screen.getByRole("button", { name: "標高" })).toHaveAttribute("aria-pressed", "true");
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

    await user.click(screen.getByRole("button", { name: "標高" }));
    expect(onShowElevationToggle).toHaveBeenCalledWith(true);

    await user.click(screen.getByRole("button", { name: "路面" }));
    expect(onShowRoadToggle).toHaveBeenCalledWith(true);

    await user.click(screen.getByRole("button", { name: "ルート" }));
    expect(onRouteLayerToggle).toHaveBeenCalledWith(true);
  });

  it("hasDetail=falseのときルートチップと▾がdisabledになり、aria-pressedもfalseのまま", () => {
    // routeLayerOn=trueでもルート未選択（hasDetail=false）なら実際には描画されないため、
    // 見た目（押下状態）もfalse側に倒す。有向データはルートが決まって初めて意味を持つ
    render(<MapOverlayControls {...baseProps()} routeLayerOn={true} hasDetail={false} />);
    const routeChip = screen.getByRole("button", { name: "ルート" });
    expect(routeChip).toBeDisabled();
    expect(routeChip).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "ルートの色分けを選択" })).toBeDisabled();
  });

  it("showRoad=true && regionZoomTooWide=trueのときズーム警告が表示され凡例は出ない", () => {
    render(<MapOverlayControls {...baseProps()} showRoad={true} regionZoomTooWide={true} />);
    expect(screen.getByText("表示範囲が広すぎます。ズームインしてください。")).toBeInTheDocument();
    expect(screen.queryByText(/舗装路/)).not.toBeInTheDocument();
  });

  it("showRoad=true && regionZoomTooWide=falseのとき路面の凡例が表示される", () => {
    render(<MapOverlayControls {...baseProps()} showRoad={true} regionZoomTooWide={false} />);
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

  it("routeLayerOn=true && hasDetail=trueのときルートの凡例（風モード）が表示される", () => {
    render(<MapOverlayControls {...baseProps()} routeLayerOn={true} hasDetail={true} />);
    expect(screen.getByText(/易しい/)).toBeInTheDocument();
    expect(screen.getByText(/普通/)).toBeInTheDocument();
    expect(screen.getByText(/難しい/)).toBeInTheDocument();
    expect(screen.getByText(/データなし/)).toBeInTheDocument();
  });

  it("▾ボタンで色分けモードのメニューが開閉し、選択中モードがaria-checkedで示される", async () => {
    const user = userEvent.setup();
    render(<MapOverlayControls {...baseProps()} roadStyleModeId="surface" />);

    expect(screen.queryByRole("radiogroup", { name: "路面の色分け" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "路面の色分けを選択" }));
    expect(screen.getByRole("radiogroup", { name: "路面の色分け" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "路面の種類" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "舗装/未舗装" })).toHaveAttribute("aria-checked", "false");

    await user.click(screen.getByRole("button", { name: "路面の色分けを選択" }));
    expect(screen.queryByRole("radiogroup", { name: "路面の色分け" })).not.toBeInTheDocument();
  });

  it("メニューでモードを選ぶとonRoadStyleModeChangeが呼ばれメニューが閉じる", async () => {
    const user = userEvent.setup();
    const onRoadStyleModeChange = vi.fn();
    render(
      <MapOverlayControls {...baseProps()} showRoad={true} onRoadStyleModeChange={onRoadStyleModeChange} />,
    );

    await user.click(screen.getByRole("button", { name: "路面の色分けを選択" }));
    await user.click(screen.getByRole("radio", { name: "道路の種類" }));

    expect(onRoadStyleModeChange).toHaveBeenCalledWith("highway");
    expect(screen.queryByRole("radiogroup", { name: "路面の色分け" })).not.toBeInTheDocument();
  });

  it("路面レイヤーOFF中にモードを選ぶとレイヤーもONになる（選んだのに何も出ないのを防ぐ）", async () => {
    const user = userEvent.setup();
    const onShowRoadToggle = vi.fn();
    render(<MapOverlayControls {...baseProps()} showRoad={false} onShowRoadToggle={onShowRoadToggle} />);

    await user.click(screen.getByRole("button", { name: "路面の色分けを選択" }));
    await user.click(screen.getByRole("radio", { name: "路面の種類" }));

    expect(onShowRoadToggle).toHaveBeenCalledWith(true);
  });

  it("ルートの▾でモードメニューが開き、選択でonRouteStyleModeChangeとレイヤーONが呼ばれる", async () => {
    const user = userEvent.setup();
    const onRouteStyleModeChange = vi.fn();
    const onRouteLayerToggle = vi.fn();
    render(
      <MapOverlayControls
        {...baseProps()}
        hasDetail={true}
        routeLayerOn={false}
        onRouteStyleModeChange={onRouteStyleModeChange}
        onRouteLayerToggle={onRouteLayerToggle}
      />,
    );

    await user.click(screen.getByRole("button", { name: "ルートの色分けを選択" }));
    expect(screen.getByRole("radio", { name: "風の影響" })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("radio", { name: "勾配" }));

    expect(onRouteStyleModeChange).toHaveBeenCalledWith("gradient");
    expect(onRouteLayerToggle).toHaveBeenCalledWith(true);
    expect(screen.queryByRole("radiogroup", { name: "ルートの色分け" })).not.toBeInTheDocument();
  });

  it("片方の▾を開いた状態でもう片方の▾を押すと、開くメニューが切り替わる", async () => {
    const user = userEvent.setup();
    render(<MapOverlayControls {...baseProps()} hasDetail={true} />);

    await user.click(screen.getByRole("button", { name: "路面の色分けを選択" }));
    expect(screen.getByRole("radiogroup", { name: "路面の色分け" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ルートの色分けを選択" }));
    expect(screen.queryByRole("radiogroup", { name: "路面の色分け" })).not.toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "ルートの色分け" })).toBeInTheDocument();
  });

  it("凡例は選択中の色分けモードに追従する（路面の種類モードはカテゴリ凡例）", () => {
    render(<MapOverlayControls {...baseProps()} showRoad={true} roadStyleModeId="surface" />);
    expect(screen.getByText("アスファルト")).toBeInTheDocument();
    expect(screen.getByText("砂利・締固め")).toBeInTheDocument();
    expect(screen.getByText("不明・他")).toBeInTheDocument();
    expect(screen.queryByText("舗装路")).not.toBeInTheDocument();
  });

  it("路面凡例のタップでonRoadLegendToggleがそのカテゴリのキーで呼ばれる", async () => {
    const user = userEvent.setup();
    const onRoadLegendToggle = vi.fn();
    render(<MapOverlayControls {...baseProps()} showRoad={true} onRoadLegendToggle={onRoadLegendToggle} />);

    await user.click(screen.getByRole("button", { name: "未舗装等" }));

    expect(onRoadLegendToggle).toHaveBeenCalledWith("bad");
  });

  it("ルート凡例（勾配モード）のタップでonRouteLegendToggleが呼ばれる", async () => {
    const user = userEvent.setup();
    const onRouteLegendToggle = vi.fn();
    render(
      <MapOverlayControls
        {...baseProps()}
        routeLayerOn={true}
        hasDetail={true}
        routeStyleModeId="gradient"
        onRouteLegendToggle={onRouteLegendToggle}
      />,
    );

    await user.click(screen.getByRole("button", { name: "下り" }));

    expect(onRouteLegendToggle).toHaveBeenCalledWith("downhill");
  });

  it("非表示中の凡例カテゴリはaria-pressed=falseになる", () => {
    render(<MapOverlayControls {...baseProps()} showRoad={true} hiddenRoadLegendKeys={["bad"]} />);

    expect(screen.getByRole("button", { name: "未舗装等" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "舗装路" })).toHaveAttribute("aria-pressed", "true");
  });
});
