import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import RouteAxisProfile from "./RouteAxisProfile";

const AXES: PreferenceAxisDef[] = [
  { axisId: "car_stress", label: "車の圧迫感", description: "車の通行量の説明", dedicatedWayValueLayer: false },
  { axisId: "wind", label: "風", description: "風の影響の説明", dedicatedWayValueLayer: true },
  { axisId: "night", label: "夜間", description: "夜間の暗さの説明", dedicatedWayValueLayer: false },
];

const AXIS_COLORS: Record<string, string> = { car_stress: "#111111", wind: "#222222", night: "#333333" };

function baseProps(overrides: Partial<Parameters<typeof RouteAxisProfile>[0]> = {}) {
  return {
    axes: AXES,
    weights: { car_stress: 0.5, wind: 0.0, night: 0.5 },
    axisDifficulties: { car_stress: 72.4, night: 5.8 },
    axisContributions: { car_stress: 36.2, night: 2.9 },
    overallDifficulty: 46,
    axisColors: AXIS_COLORS,
    ...overrides,
  };
}

describe("RouteAxisProfile", () => {
  it("公開軸すべてを軸カタログの並び順で一覧し、重み0の軸は「未使用」、値が無い軸は「データなし」として残す", () => {
    render(<RouteAxisProfile {...baseProps()} />);

    const items = within(screen.getByRole("list", { name: "軸別難易度" })).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("車の圧迫感"),
      expect.stringContaining("風"),
      expect.stringContaining("夜間"),
    ]);
    expect(items[1]).toHaveTextContent("未使用");
    expect(items[1]).toHaveTextContent("データなし");
    expect(items[1]).toHaveAttribute("data-unused", "true");
    expect(items[0]).toHaveAttribute("data-unused", "false");
    expect(items[0]).toHaveTextContent("72");
    expect(items[2]).toHaveTextContent("6");
  });

  it("地図の色分け（レンズ）を選ぶボタンを持たない（入口は地図上の凡例ピルだけ）", () => {
    render(<RouteAxisProfile {...baseProps()} />);

    expect(screen.queryByRole("button", { name: /で地図を色分け/ })).not.toBeInTheDocument();
  });

  it("axisContributionsが空のときは内訳セクションだけ案内文を表示し、軸一覧は残る", () => {
    render(<RouteAxisProfile {...baseProps({ axisContributions: {} })} />);

    expect(screen.getByText("このルートで表示できる評価軸データがありません")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "軸別難易度" })).getAllByRole("listitem")).toHaveLength(3);
  });

  it("内訳バーは積み上げ1本バー（RouteSettingsPanel.module.cssのstackBar/stackSegmentを流用）として描画される", () => {
    const { container } = render(<RouteAxisProfile {...baseProps()} />);

    const bar = container.querySelector('[class*="stackBar"]');
    expect(bar).not.toBeNull();
    const segments = container.querySelectorAll('[class*="stackSegment"]');
    expect(segments).toHaveLength(2);
  });

  it("一般ユーザー向け画面のため、Basic認証必須の管理画面限定機能名「軸スタジオ」を含まない", () => {
    const { container } = render(<RouteAxisProfile {...baseProps()} />);

    expect(container.textContent).not.toContain("軸スタジオ");
  });

  it("内訳の値はbackendが算出したaxis_contributionsをそのまま表示する", () => {
    const { container } = render(
      <RouteAxisProfile {...baseProps({ axisContributions: { car_stress: 52.1, night: 2.9 } })} />
    );

    const values = Array.from(container.querySelectorAll('[class*="legendValue"]')).map((el) => el.textContent);
    expect(values).toEqual(["52.1", "2.9"]);
  });

  it("総合難易度（絶対基準0-100）を表示する", () => {
    render(<RouteAxisProfile {...baseProps()} />);

    expect(screen.getByText("46")).toBeInTheDocument();
  });

  it("各軸に(i)説明ポップオーバーが付き、クリックするとaxis.descriptionを表示する", async () => {
    const user = userEvent.setup();
    render(<RouteAxisProfile {...baseProps()} />);

    await user.click(screen.getByRole("button", { name: "車の圧迫感の説明を表示" }));

    expect(await screen.findByText("車の通行量の説明")).toBeInTheDocument();
  });
});
