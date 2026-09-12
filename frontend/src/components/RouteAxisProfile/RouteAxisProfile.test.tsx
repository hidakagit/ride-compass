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
    materialCategoryShares: {},
    distanceKm: 30,
    overallDifficulty: 46,
    difficultyLoad: null,
    axisColors: AXIS_COLORS,
    ...overrides,
  };
}

/** 軸チップ（押せる／押せないの両方）。 */
function chips() {
  return within(screen.getByRole("list")).getAllByRole("listitem");
}

describe("RouteAxisProfile", () => {
  it("軸を1行ずつ並べる一覧は持たず、寄与度の凡例チップが軸ごとの詳細の入口になる", async () => {
    const user = userEvent.setup();
    render(<RouteAxisProfile {...baseProps({ axisRawValues: { car_stress: 0.8 }, distanceKm: 32.5 })} />);

    expect(screen.queryByRole("list", { name: "軸別難易度" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "車の圧迫感の詳細を表示" }));

    // 重みを掛ける前の軸単体の難易度。チップの数字（重み付き寄与度36.2）とは別物。
    expect(await screen.findByText("軸別難易度 72/100")).toBeInTheDocument();
    // 0.8回/km × 32.5km ≒ 26回。得点だけでは「多いか少ないか」を判断できない。
    expect(screen.getByText("0.8回/km・約26回")).toBeInTheDocument();
    expect(screen.getByText("車の通行量の説明")).toBeInTheDocument();
  });

  it("公開軸すべてをチップとして並べ、評価に使っていない軸（重み0）は押せないチップで残す", () => {
    // ルート設定パネルの「重み配分」と同じチップの形。押せるかどうかが、その軸を評価に
    // 使ったかどうかの区別になる。
    render(<RouteAxisProfile {...baseProps()} />);

    const items = chips();
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("車の圧迫感"),
      expect.stringContaining("風"),
      expect.stringContaining("夜間"),
    ]);
    expect(items[1]).toHaveAttribute("data-checked", "false");
    expect(within(items[1]).queryByRole("button")).not.toBeInTheDocument();
    expect(items[0]).toHaveAttribute("data-checked", "true");
    expect(within(items[0]).getByRole("button", { name: "車の圧迫感の詳細を表示" })).toBeInTheDocument();
  });

  it("重みが入っていれば、寄与の値が来ない軸のチップも押せる（詳細が「データなし」を示す）", async () => {
    const user = userEvent.setup();
    render(<RouteAxisProfile {...baseProps({ weights: { car_stress: 0.5, wind: 0.2, night: 0.5 } })} />);

    const wind = chips()[1];
    expect(wind).toHaveAttribute("data-checked", "true");

    await user.click(within(wind).getByRole("button", { name: "風の詳細を表示" }));

    expect(await screen.findByText("データなし")).toBeInTheDocument();
  });

  it("地図の色分け（レンズ）を選ぶボタンを持たない（入口は地図上の凡例ピルだけ）", () => {
    render(<RouteAxisProfile {...baseProps()} />);

    expect(screen.queryByRole("button", { name: /で地図を色分け/ })).not.toBeInTheDocument();
  });

  it("axisContributionsが空のときは案内文だけを表示する（帯も凡例も描かない）", () => {
    render(<RouteAxisProfile {...baseProps({ axisContributions: {} })} />);

    expect(screen.getByText("このルートで表示できる評価軸データがありません")).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("重み0の軸はaxisContributionsにキー付きで値0.0を持つため、帯には出ずチップの数値も出ない", () => {
    const { container } = render(
      <RouteAxisProfile {...baseProps({ axisContributions: { car_stress: 36.2, wind: 0, night: 2.9 } })} />
    );

    const segments = container.querySelectorAll('[class*="stackSegment"]');
    expect(segments).toHaveLength(2);
    expect(chips()[1]).toHaveTextContent("風");
    expect(chips()[1]).toHaveAttribute("data-checked", "false");
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

  it("総合難易度に説明ポップオーバーが付く", async () => {
    const user = userEvent.setup();
    render(<RouteAxisProfile {...baseProps()} />);

    await user.click(screen.getByRole("button", { name: "総合難易度の説明を表示" }));

    expect(await screen.findByText(/候補タブはこの値が小さい順に並びます/)).toBeInTheDocument();
  });
});

describe("軸単体で判断するための物理量（詳細ポップオーバーの中身）", () => {
  it("単位が定まらない軸には生値を出さない（意味を取れない数字を並べない）", async () => {
    const user = userEvent.setup();
    render(<RouteAxisProfile {...baseProps({ axisRawValues: { night: 1.5 }, distanceKm: 30 })} />);

    await user.click(screen.getByRole("button", { name: "夜間の詳細を表示" }));

    expect(await screen.findByText("夜間の暗さの説明")).toBeInTheDocument();
    expect(screen.queryByText(/回\/km/)).not.toBeInTheDocument();
  });

  it("単位が定まらない軸は、材料まで分解した内訳を全件出す", async () => {
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

    await userEvent.click(screen.getByRole("button", { name: "夜間の詳細を表示" }));

    expect(screen.getByText("この軸の内訳: 街灯あり 68%・トンネル 2%・制限速度 42km/h")).toBeInTheDocument();
  });

  it("単位が定まる軸は内訳ではなく軸単位の生値を出す", async () => {
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

    await userEvent.click(screen.getByRole("button", { name: "勾配の詳細を表示" }));

    expect(screen.getByText("3.2%")).toBeInTheDocument();
  });

  it("categorical材料は最も延長の長い値のラベルと割合を出す", async () => {
    const axes: PreferenceAxisDef[] = [
      {
        axisId: "car_stress",
        label: "車の圧迫感",
        description: "説明",
        dedicatedWayValueLayer: false,
        rawValueUnit: null,
        materialBreakdown: [
          {
            materialId: "highway",
            label: "道路種別",
            dtype: "categorical",
            unit: "",
            share: 0.2,
            valueLabels: { residential: "住宅街の道", secondary: "主要な道" },
          },
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
          // backendが割合の降順で返す（フロントは並べ替えを持たない）。
          materialCategoryShares: { highway: { residential: 0.62, secondary: 0.38 } },
        })}
      />
    );

    await userEvent.click(screen.getByRole("button", { name: "車の圧迫感の詳細を表示" }));

    expect(screen.getByText("この軸の内訳: 住宅街の道 62%・制限速度 42km/h")).toBeInTheDocument();
    // 2件目以降の値は出さない（どの値を束ねるかの判断表をフロントが持たないため）。
    expect(screen.queryByText(/主要な道/)).not.toBeInTheDocument();
  });

  it("値が来ないcategorical材料は内訳から飛ばす", async () => {
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

    await userEvent.click(screen.getByRole("button", { name: "車の圧迫感の詳細を表示" }));

    expect(screen.getByText("この軸の内訳: 制限速度 42km/h")).toBeInTheDocument();
    expect(screen.queryByText(/道路種別/)).not.toBeInTheDocument();
  });
});
