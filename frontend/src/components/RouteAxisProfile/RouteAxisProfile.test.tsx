import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights } from "@/types/route";
import type { RouteStyleMode, RouteStyleModeId } from "@/components/Map/routeStyleModes";
import RouteAxisProfile from "./RouteAxisProfile";

const AXES: PreferenceAxisDef[] = [
  { axisId: "car_stress", label: "車の圧迫感", description: "車の通行量の説明", dedicatedWayValueLayer: false },
  { axisId: "wind", label: "風", description: "風の影響の説明", dedicatedWayValueLayer: true },
  { axisId: "night", label: "夜間", description: "夜間の暗さの説明", dedicatedWayValueLayer: false },
];

const WEIGHTS: RoutePreferenceWeights = { car_stress: 0.5, wind: 0.3, night: 0.2 };
const AXIS_COLORS: Record<string, string> = { car_stress: "#111111", wind: "#222222", night: "#333333" };

const ROUTE_STYLE_MODES: RouteStyleMode[] = [
  {
    id: "difficulty",
    label: "総合難易度",
    legend: [
      { key: "easy", label: "易しい", color: "#16a34a", filter: [] },
      { key: "hard", label: "難しい", color: "#dc2626", filter: [] },
    ],
    colorExpression: [],
  },
  {
    id: "car_stress",
    label: "車の圧迫感の影響",
    legend: [{ key: "low", label: "低い", color: "#16a34a", filter: [] }],
    colorExpression: [],
  },
];

function baseProps(overrides: Partial<Parameters<typeof RouteAxisProfile>[0]> = {}) {
  return {
    axes: AXES,
    axisDifficulties: { car_stress: 72.4, night: 10 },
    overallDifficulty: 46,
    totalScore: 70,
    weights: WEIGHTS,
    axisColors: AXIS_COLORS,
    routeStyleModes: ROUTE_STYLE_MODES,
    routeStyleModeId: "difficulty" as RouteStyleModeId,
    onRouteStyleModeChange: vi.fn(),
    hiddenLegendKeys: [] as readonly string[],
    onToggleLegendKey: vi.fn(),
    ...overrides,
  };
}

describe("RouteAxisProfile", () => {
  it("axisDifficultiesに値を持つ軸だけを、軸カタログの並び順で内訳表示する", () => {
    render(<RouteAxisProfile {...baseProps()} />);

    // 軸カタログの並び順（car_stress→wind→night）のうち、値を持つ2軸だけが表示される
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("車の圧迫感");
    expect(items[1]).toHaveTextContent("夜間");
    expect(screen.queryByText("風")).not.toBeInTheDocument();
  });

  it("axisDifficultiesが空のときは案内文を表示する", () => {
    render(<RouteAxisProfile {...baseProps({ axisDifficulties: {} })} />);

    expect(screen.getByText("このルートで表示できる評価軸データがありません")).toBeInTheDocument();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
  });

  it("難易度バーがdisplay:blockで描画される（review:ui F-2の再発防止。trackもbarも<span>のため、" +
    "displayを明示しない既定のinlineのままだとwidthスタイルがCSS仕様上無視され、バーが幅0で" +
    "描画されなくなる）", () => {
    const { container } = render(<RouteAxisProfile {...baseProps()} />);

    const bar = container.querySelector('[class*="bar"]');
    expect(bar).not.toBeNull();
    expect(getComputedStyle(bar as Element).display).toBe("block");
  });

  it("一般ユーザー向け画面のため、Basic認証必須の管理画面限定機能名「軸スタジオ」を含まない" +
    "（review:ui 2026-08-30 F-4の再発防止）", () => {
    const { container } = render(<RouteAxisProfile {...baseProps()} />);

    expect(container.textContent).not.toContain("軸スタジオ");
  });

  it("内訳の値は距離加重平均の生値ではなく、軸の重みで正規化した寄与度になる（改善計画T518）", () => {
    // rows = car_stress(raw72.4,weight0.5) + night(raw10,weight0.2)。windはaxisDifficulties
    // に値が無いため対象外（weightSumにも含まれない）。weightSum=0.7。
    // car_stress寄与度 = 72.4*0.5/0.7 ≈ 51.7 → 52、night寄与度 = 10*0.2/0.7 ≈ 2.9 → 3。
    const { container } = render(<RouteAxisProfile {...baseProps({ overallDifficulty: null, totalScore: null })} />);

    const values = Array.from(container.querySelectorAll('[class*="value"]')).map((el) => el.textContent);
    expect(values).toEqual(["52", "3"]);
    // 生の距離加重平均（72.4→72、10→10）が寄与度に置き換わっている（重みで薄められている）ため出ない
    expect(screen.queryByText("72")).not.toBeInTheDocument();
  });

  it("重み情報が全く無い（weightSum=0）場合は素の距離加重平均へフォールバックする", () => {
    const { container } = render(
      <RouteAxisProfile {...baseProps({ weights: {}, overallDifficulty: null, totalScore: null })} />
    );

    const values = Array.from(container.querySelectorAll('[class*="value"]')).map((el) => el.textContent);
    expect(values).toEqual(["72", "10"]);
  });

  it("おすすめ度と総合難易度の両方を表示する（別指標のため片方をもう片方の内訳として扱わない）", () => {
    render(<RouteAxisProfile {...baseProps()} />);

    expect(screen.getByText("70")).toBeInTheDocument();
    expect(screen.getAllByText(/おすすめ度/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("46")).toBeInTheDocument();
    // 「総合難易度」自体はチップ名とスコアラベルの2箇所に出るため複数件ヒットする
    expect(screen.getAllByText(/総合難易度/).length).toBeGreaterThanOrEqual(2);
  });

  it("総合難易度チップをクリックするとonRouteStyleModeChange('difficulty')が呼ばれる", async () => {
    const user = userEvent.setup();
    const onRouteStyleModeChange = vi.fn();
    render(<RouteAxisProfile {...baseProps({ routeStyleModeId: "car_stress", onRouteStyleModeChange })} />);

    await user.click(screen.getByRole("button", { name: "総合難易度で地図を色分け" }));

    expect(onRouteStyleModeChange).toHaveBeenCalledWith("difficulty");
  });

  it("軸チップをクリックするとonRouteStyleModeChange(axisId)が呼ばれる", async () => {
    const user = userEvent.setup();
    const onRouteStyleModeChange = vi.fn();
    render(<RouteAxisProfile {...baseProps({ onRouteStyleModeChange })} />);

    await user.click(screen.getByRole("button", { name: "車の圧迫感で地図を色分け" }));

    expect(onRouteStyleModeChange).toHaveBeenCalledWith("car_stress");
  });

  it("routeStyleModeIdに一致するチップがaria-pressed=trueになる（他は false）", () => {
    render(<RouteAxisProfile {...baseProps({ routeStyleModeId: "car_stress" })} />);

    expect(screen.getByRole("button", { name: "車の圧迫感で地図を色分け" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "総合難易度で地図を色分け" })).toHaveAttribute("aria-pressed", "false");
  });

  it("routeStyleModesに対応モードが無い軸（supports_route_coloring===false）はボタンにせず、" +
    "クリックしても地図の色分けが変わらない無反応チップにならないようにする（実機確認で発覚: " +
    "対応モードが無いidでonRouteStyleModeChangeを呼ぶと、page.tsx側のフォールバックeffectが" +
    "選択を即座に巻き戻していた）", () => {
    // ROUTE_STYLE_MODESにはcar_stressの色分けモードはあるが、nightのモードは無い
    // （AXES/axisDifficultiesの両方にnightは含まれる想定のfixture）。
    render(<RouteAxisProfile {...baseProps()} />);

    expect(screen.getByRole("button", { name: "車の圧迫感で地図を色分け" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "夜間で地図を色分け" })).not.toBeInTheDocument();
    expect(screen.getByText("夜間")).toBeInTheDocument();
  });

  it("凡例の表示設定トリガーで、選択中モードの凡例カテゴリがチェックボックスとして開き、" +
    "クリックでonToggleLegendKeyが呼ばれる", async () => {
    const user = userEvent.setup();
    const onToggleLegendKey = vi.fn();
    render(<RouteAxisProfile {...baseProps({ onToggleLegendKey })} />);

    await user.click(screen.getByRole("button", { name: "凡例の表示設定" }));
    const checkbox = await screen.findByRole("checkbox", { name: "易しい" });
    await user.click(checkbox);

    expect(onToggleLegendKey).toHaveBeenCalledWith("easy");
  });
});
