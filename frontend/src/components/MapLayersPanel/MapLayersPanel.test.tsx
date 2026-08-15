import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import MapLayersPanel from "./MapLayersPanel";

function baseProps() {
  return {
    layerVisibility: { elevation: false, road: false, trafficStress: false, bicycleInfra: false, route: false },
    onLayerToggle: vi.fn(),
    roadHiddenKeysByMode: { surface: [], highway: [] } as Record<"surface" | "highway", readonly string[]>,
    onRoadLegendToggle: vi.fn(),
    onRoadAxisSetHidden: vi.fn(),
    regionZoomTooWide: false,
    routeStyleModeId: "wind" as const,
    onRouteStyleModeChange: vi.fn(),
    hiddenRouteLegendKeys: [] as string[],
    onRouteLegendToggle: vi.fn(),
    hasDetail: false,
  };
}

// パネルの枠組み（レイヤーカタログからのセクション生成・表示チップ・凡例チェックの
// 出し分け・ルートの色分け選択）を見る。道路情報の絞り込みは即時反映（T31で
// 旧RoadFilterEditorの下書き→適用を廃止し、ルート凡例と同じチェック方式へ統一）。
describe("MapLayersPanel", () => {
  it("レイヤーカタログの全レイヤーが、役割ごとのグループ見出しの下にセクションとして並ぶ", () => {
    const { container } = render(<MapLayersPanel {...baseProps()} />);

    expect(screen.getByText("地図に重ねる情報")).toBeInTheDocument();
    expect(screen.getByText("生成したルートの色分け")).toBeInTheDocument();
    // 地図上の条件サマリからのスクロール先になるDOM id（layerSectionDomId）が振られている
    expect(container.querySelector("#map-layer-section-elevation")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-road")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-trafficStress")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-bicycleInfra")).toBeInTheDocument();
    expect(container.querySelector("#map-layer-section-route")).toBeInTheDocument();
  });

  it("各レイヤーの表示チップがON/OFF状態をaria-pressedで反映し、操作でonLayerToggleが呼ばれる", async () => {
    const user = userEvent.setup();
    const onLayerToggle = vi.fn();
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{ elevation: true, road: false, trafficStress: false, bicycleInfra: false, route: false }}
        onLayerToggle={onLayerToggle}
      />,
    );

    expect(screen.getByRole("button", { name: "標高図レイヤーを表示" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "道路情報レイヤーを表示" })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "道路情報レイヤーを表示" }));
    expect(onLayerToggle).toHaveBeenCalledWith("road", true);

    await user.click(screen.getByRole("button", { name: "標高図レイヤーを表示" }));
    expect(onLayerToggle).toHaveBeenCalledWith("elevation", false);
  });

  it("道路情報OFFのときはOFF案内が出て、絞り込みチェックはOFF中でも操作できる", () => {
    render(<MapLayersPanel {...baseProps()} />);
    expect(screen.getByText(/絞り込みを操作すると自動でONになります/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeInTheDocument();
  });

  it("絞り込みチェックの操作でonRoadLegendToggleが呼ばれ、レイヤーOFFなら自動でONになる", async () => {
    const user = userEvent.setup();
    const onRoadLegendToggle = vi.fn();
    const onLayerToggle = vi.fn();
    render(<MapLayersPanel {...baseProps()} onRoadLegendToggle={onRoadLegendToggle} onLayerToggle={onLayerToggle} />);

    await user.click(screen.getByRole("checkbox", { name: /アスファルト/ }));

    expect(onRoadLegendToggle).toHaveBeenCalledWith("surface", "asphalt");
    expect(onLayerToggle).toHaveBeenCalledWith("road", true);
  });

  it("「すべて隠す」で軸の全カテゴリキーがonRoadAxisSetHiddenへ渡る", async () => {
    const user = userEvent.setup();
    const onRoadAxisSetHidden = vi.fn();
    render(<MapLayersPanel {...baseProps()} onRoadAxisSetHidden={onRoadAxisSetHidden} />);

    // 一括ボタンは軸ごとにあるため、1つ目（色＝路面の種類の軸）を操作する
    await user.click(screen.getAllByRole("button", { name: "すべて隠す" })[0]);

    expect(onRoadAxisSetHidden).toHaveBeenCalledWith("surface", [
      "asphalt",
      "concrete",
      "stones",
      "gravel",
      "dirt",
      "unknown",
    ]);
  });

  it("道路情報ON && regionZoomTooWide=trueのときズーム警告が表示される（絞り込みは操作可能なまま）", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{ elevation: false, road: true, trafficStress: false, bicycleInfra: false, route: false }}
        regionZoomTooWide={true}
      />,
    );
    expect(screen.getByText("表示範囲が広すぎます。ズームインしてください。")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeInTheDocument();
  });

  it("道路情報ONのとき色・太さ両方の軸見出しが表示される", () => {
    render(
      <MapLayersPanel {...baseProps()} layerVisibility={{ elevation: false, road: true, trafficStress: false, bicycleInfra: false, route: false }} />,
    );
    expect(screen.getByText(/色：路面の種類/)).toBeInTheDocument();
    expect(screen.getByText(/太さ：道路の種類/)).toBeInTheDocument();
    expect(screen.queryByText("表示範囲が広すぎます。ズームインしてください。")).not.toBeInTheDocument();
  });

  it("非表示中のカテゴリはチェックが外れた状態で表示される", () => {
    render(
      <MapLayersPanel
        {...baseProps()}
        layerVisibility={{ elevation: false, road: true, trafficStress: false, bicycleInfra: false, route: false }}
        roadHiddenKeysByMode={{ surface: ["gravel"], highway: [] }}
      />,
    );
    expect(screen.getByRole("checkbox", { name: /砂利・締固め/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /アスファルト/ })).toBeChecked();
  });

  it("hasDetail=falseのときルート欄は案内のみで、表示チップも非活性", () => {
    render(<MapLayersPanel {...baseProps()} hasDetail={false} />);
    expect(screen.getByText(/ルートを生成・選択すると使えます/)).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "ルートの色分け" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ルートレイヤーを表示" })).toBeDisabled();
  });

  it("hasDetail=falseの案内からonGoToGenerateで「ルートを作る」へ誘導できる", async () => {
    const user = userEvent.setup();
    const onGoToGenerate = vi.fn();
    render(<MapLayersPanel {...baseProps()} hasDetail={false} onGoToGenerate={onGoToGenerate} />);

    await user.click(screen.getByRole("button", { name: "「ルートを作る」へ" }));

    expect(onGoToGenerate).toHaveBeenCalled();
  });

  it("hasDetail=trueのときルートのモード選択・凡例チェックボックスが表示される", () => {
    render(<MapLayersPanel {...baseProps()} hasDetail={true} />);
    expect(screen.getByRole("radio", { name: "風の影響" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("checkbox", { name: /易しい/ })).toBeInTheDocument();
  });

  it("ルートのモード選択でonRouteStyleModeChangeが呼ばれ、レイヤーOFFなら自動でONにする", async () => {
    const user = userEvent.setup();
    const onRouteStyleModeChange = vi.fn();
    const onLayerToggle = vi.fn();
    render(
      <MapLayersPanel
        {...baseProps()}
        hasDetail={true}
        layerVisibility={{ elevation: false, road: false, trafficStress: false, bicycleInfra: false, route: false }}
        onRouteStyleModeChange={onRouteStyleModeChange}
        onLayerToggle={onLayerToggle}
      />,
    );

    await user.click(screen.getByRole("radio", { name: "勾配" }));

    expect(onRouteStyleModeChange).toHaveBeenCalledWith("gradient");
    expect(onLayerToggle).toHaveBeenCalledWith("route", true);
  });

  it("ルートのモード選択時、レイヤーが既にONならonLayerToggleは呼ばれない", async () => {
    const user = userEvent.setup();
    const onLayerToggle = vi.fn();
    render(
      <MapLayersPanel
        {...baseProps()}
        hasDetail={true}
        layerVisibility={{ elevation: false, road: false, trafficStress: false, bicycleInfra: false, route: true }}
        onLayerToggle={onLayerToggle}
      />,
    );

    await user.click(screen.getByRole("radio", { name: "勾配" }));

    expect(onLayerToggle).not.toHaveBeenCalled();
  });

  it("ルートの凡例チェックボックス操作でonRouteLegendToggleが呼ばれる", async () => {
    const user = userEvent.setup();
    const onRouteLegendToggle = vi.fn();
    render(
      <MapLayersPanel
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
