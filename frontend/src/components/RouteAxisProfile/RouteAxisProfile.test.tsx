import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import RouteAxisProfile from "./RouteAxisProfile";

const AXES: PreferenceAxisDef[] = [
  { axisId: "car_stress", label: "車の圧迫感", description: "車の通行量の説明", dedicatedWayValueLayer: false, rawValueUnit: "回/km" },
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
    axisRawValues: {},
    materialValues: {},
    distanceKm: 30,
    overallDifficulty: 46,
    difficultyLoad: null,
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

  it("重み0の軸はaxisContributionsにキー付きで値0.0を持つため、内訳バーからは除外され軸一覧には残る", () => {
    const { container } = render(
      <RouteAxisProfile {...baseProps({ axisContributions: { car_stress: 36.2, wind: 0, night: 2.9 } })} />
    );

    const segments = container.querySelectorAll('[class*="stackSegment"]');
    expect(segments).toHaveLength(2);
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

  it("総合難易度に説明ポップオーバーが付く", async () => {
    const user = userEvent.setup();
    render(<RouteAxisProfile {...baseProps()} />);

    await user.click(screen.getByRole("button", { name: "総合難易度の説明を表示" }));

    expect(await screen.findByText(/候補タブはこの値が小さい順に並びます/)).toBeInTheDocument();
  });
});

describe("軸単体で判断するための生値", () => {
  it("単位が定まる軸は、得点の隣に生値と経路全体の実数を出す", () => {
    render(
      <RouteAxisProfile
        {...baseProps({
          axisRawValues: { car_stress: 0.8 },
          distanceKm: 32.5,
        })}
      />,
    );

    // 0.8回/km × 32.5km ≒ 26回。得点だけでは「多いか少ないか」を判断できない。
    expect(screen.getByText("0.8回/km・約26回")).toBeInTheDocument();
  });

  it("単位が定まらない軸には何も出さない（意味を取れない数字を並べない）", () => {
    render(<RouteAxisProfile {...baseProps({ axisRawValues: { night: 1.5 }, distanceKm: 30 })} />);

    expect(screen.queryByText(/回\/km/)).not.toBeInTheDocument();
  });

  it("単位が定まらない軸は、材料まで分解した内訳を得点の隣に出す（既定は2件まで）", async () => {
    // 真偽値材料の値は0/1で運ばれるため、距離加重平均がそのまま延長割合になる。
    const axes: PreferenceAxisDef[] = [
      {
        axisId: "night",
        label: "夜間",
        description: "夜間の暗さの説明",
        dedicatedWayValueLayer: false,
        rawValueUnit: null,
        materialBreakdown: [
          { materialId: "lit", label: "街灯あり", dtype: "boolean", unit: "", share: 0.5 },
          { materialId: "has_tunnel", label: "トンネル", dtype: "boolean", unit: "", share: 0.5 },
          { materialId: "maxspeed_kmh", label: "制限速度", dtype: "numeric", unit: "km/h", share: 0.2 },
        ],
      },
    ];

    render(
      <RouteAxisProfile
        {...baseProps({
          axes,
          weights: { night: 0.5 },
          axisDifficulties: { night: 40 },
          axisContributions: { night: 20 },
          materialValues: { lit: 0.68, has_tunnel: 0.02, maxspeed_kmh: 42.3 },
        })}
      />
    );

    const item = within(screen.getByRole("list", { name: "軸別難易度" })).getAllByRole("listitem")[0];
    expect(item).toHaveTextContent("街灯あり 68%・トンネル 2%");
    // 3件目は行に出さず、軸の説明ポップオーバーへ回す。
    expect(item).not.toHaveTextContent("制限速度 42km/h");
    await userEvent.click(screen.getByRole("button", { name: "夜間の説明を表示" }));
    expect(screen.getByText(/制限速度 42km\/h/)).toBeInTheDocument();
  });

  it("単位が定まる軸は内訳ではなく従来どおり軸単位の生値を出す", () => {
    const axes: PreferenceAxisDef[] = [
      {
        axisId: "gradient",
        label: "勾配",
        description: "勾配の説明",
        dedicatedWayValueLayer: true,
        rawValueUnit: "%",
        materialBreakdown: [],
      },
    ];

    render(
      <RouteAxisProfile
        {...baseProps({
          axes,
          weights: { gradient: 0.5 },
          axisDifficulties: { gradient: 30 },
          axisContributions: { gradient: 15 },
          axisRawValues: { gradient: 3.2 },
        })}
      />
    );

    const item = within(screen.getByRole("list", { name: "軸別難易度" })).getAllByRole("listitem")[0];
    expect(item).toHaveTextContent("3.2%");
  });

  it("値が来ない材料（categorical等）は内訳から飛ばす", () => {
    const axes: PreferenceAxisDef[] = [
      {
        axisId: "car_stress",
        label: "車の圧迫感",
        description: "説明",
        dedicatedWayValueLayer: false,
        rawValueUnit: null,
        materialBreakdown: [
          { materialId: "highway", label: "道路種別", dtype: "categorical", unit: "", share: 0.2 },
          { materialId: "maxspeed_kmh", label: "制限速度", dtype: "numeric", unit: "km/h", share: 0.2 },
        ],
      },
    ];

    render(
      <RouteAxisProfile
        {...baseProps({
          axes,
          weights: { car_stress: 0.5 },
          axisDifficulties: { car_stress: 60 },
          axisContributions: { car_stress: 30 },
          materialValues: { maxspeed_kmh: 42.3 },
        })}
      />
    );

    const item = within(screen.getByRole("list", { name: "軸別難易度" })).getAllByRole("listitem")[0];
    expect(item).toHaveTextContent("制限速度 42km/h");
    expect(item).not.toHaveTextContent("道路種別");
  });
});
