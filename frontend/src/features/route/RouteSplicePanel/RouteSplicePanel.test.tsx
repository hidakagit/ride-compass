import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { makeRouteCandidate } from "@/testing/routeFixtures";

import RouteSplicePanel from "./RouteSplicePanel";

const axis = (axisId: string, label: string): PreferenceAxisDef => ({
  axisId,
  label,
  description: "",
  dedicatedWayValueLayer: false,
});
const AXES = [axis("wind", "風"), axis("slope", "勾配"), axis("stops", "停止")];

const DISPLAYED = makeRouteCandidate({
  id: "base",
  distance_km: 30,
  estimated_duration_seconds: 90 * 60,
  overall_difficulty: 40.2,
  difficulty_load: 1206,
  edge_ids: ["e1", "e2"],
  axis_contributions: { wind: 20, slope: 10, stops: 10.2 },
});

type Props = React.ComponentProps<typeof RouteSplicePanel>;

function renderPanel(overrides: Partial<Props> = {}) {
  const props: Props = {
    displayed: DISPLAYED,
    appliedCount: 0,
    hasAlternatives: true,
    onUndo: vi.fn(),
    onReset: vi.fn(),
    preview: null,
    previewing: false,
    onPreview: vi.fn(),
    onApply: vi.fn(),
    applying: false,
    error: null,
    onCancel: vi.fn(),
    axes: AXES,
    axisColors: { wind: "#0000ff" },
    ...overrides,
  };
  render(<RouteSplicePanel {...props} />);
  return props;
}

/** 指標1つ（名前・元・→・後・差）の文字の並び。 */
function metric(label: string) {
  const cells = [screen.getByText(label, { selector: "dt" })];
  for (let i = 0; i < 4; i += 1) cells.push(cells.at(-1)!.nextElementSibling as HTMLElement);
  return cells.slice(1);
}

describe("RouteSplicePanel 操作", () => {
  it("戻る操作で編集をやめる", async () => {
    const props = renderPanel();
    await userEvent.click(screen.getByRole("button", { name: "編集をやめて候補へ戻る" }));
    expect(props.onCancel).toHaveBeenCalled();
  });

  it("乗り換えていない間は、戻す操作を出さず、差分・作成も押せない", () => {
    renderPanel({ appliedCount: 0 });
    expect(screen.queryByRole("button", { name: "1つ戻す" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "全部戻す" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "差分を見る" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "新しいルートを作成" })).toBeDisabled();
  });

  it("乗り換えたら回数を出し、戻す・差分・作成の操作をそれぞれの処理へつなぐ", async () => {
    const props = renderPanel({ appliedCount: 2 });
    expect(screen.getByText("2回")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "1つ戻す" }));
    await userEvent.click(screen.getByRole("button", { name: "全部戻す" }));
    await userEvent.click(screen.getByRole("button", { name: "差分を見る" }));
    await userEvent.click(screen.getByRole("button", { name: "新しいルートを作成" }));
    expect(props.onUndo).toHaveBeenCalled();
    expect(props.onReset).toHaveBeenCalled();
    expect(props.onPreview).toHaveBeenCalled();
    expect(props.onApply).toHaveBeenCalled();
  });

  it("評価を待っている間は、どの操作も押せず、待っている操作に待ち中の印を付ける", () => {
    renderPanel({ appliedCount: 1, previewing: true });
    for (const name of ["1つ戻す", "全部戻す", "差分を見る", "新しいルートを作成"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(screen.getByRole("button", { name: "差分を見る" })).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "新しいルートを作成" })).toHaveAttribute("aria-busy", "false");
  });

  it("作成を待っている間も同じ（作成の側に待ち中の印）", () => {
    renderPanel({ appliedCount: 1, applying: true });
    expect(screen.getByRole("button", { name: "1つ戻す" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "新しいルートを作成" })).toHaveAttribute("aria-busy", "true");
  });

  it("失敗の理由を、押した場所から見える所に出す", () => {
    renderPanel({ appliedCount: 1, error: "合成に失敗しました" });
    expect(screen.getByText("合成に失敗しました")).toBeInTheDocument();
  });
});

describe("RouteSplicePanel 指標", () => {
  it("評価する前は元の値だけを出す（矢印も出さない）。値が無ければ「—」", () => {
    renderPanel({ displayed: { ...DISPLAYED, difficulty_load: null } });
    expect(metric("距離").map((cell) => cell.textContent)).toEqual(["30.0", "", "", ""]);
    expect(metric("所要")[0]).toHaveTextContent("1時間30分");
    expect(metric("総合難易度")[0]).toHaveTextContent(/^40$/);
    expect(metric("負荷")[0]).toHaveTextContent("—");
  });

  it("評価したら元→後と差を出す（距離は小数1桁、ほかは整数。所要の差は分）", () => {
    const preview = makeRouteCandidate({
      distance_km: 31.25,
      estimated_duration_seconds: 85 * 60,
      overall_difficulty: 40.4,
      difficulty_load: 1263,
      axis_contributions: DISPLAYED.axis_contributions,
    });
    renderPanel({ appliedCount: 1, preview });
    expect(metric("距離").map((cell) => cell.textContent)).toEqual(["30.0", "→", "31.3km", "+1.3"]);
    expect(metric("所要").map((cell) => cell.textContent)).toEqual(["1時間30分", "→", "1時間25分", "−5"]);
    expect(metric("総合難易度").map((cell) => cell.textContent)).toEqual(["40", "→", "40", "±0"]);
    expect(metric("負荷").map((cell) => cell.textContent)).toEqual(["1206", "→", "1263", "+57"]);
  });

  it("増えた指標は悪くなった印、減った指標は良くなった印。表示で±0なら印を付けない", () => {
    const preview = makeRouteCandidate({
      distance_km: 31.25,
      estimated_duration_seconds: 85 * 60,
      overall_difficulty: 40.4,
      difficulty_load: 1263,
    });
    renderPanel({ appliedCount: 1, preview });
    expect(metric("距離")[3]).toHaveAttribute("data-worse", "true");
    expect(metric("所要")[3]).toHaveAttribute("data-better", "true");
    const unchanged = metric("総合難易度")[3];
    expect(unchanged).toHaveAttribute("data-worse", "false");
    expect(unchanged).toHaveAttribute("data-better", "false");
  });

  it("どちらかの値が無い指標は、差を出さない", () => {
    const preview = makeRouteCandidate({ distance_km: 30, estimated_duration_seconds: null });
    renderPanel({ appliedCount: 1, preview });
    expect(metric("所要").map((cell) => cell.textContent)).toEqual(["1時間30分", "", "", ""]);
  });

  it("経路のEdgeを持たない候補では、区間を出せない旨だけを出す", () => {
    renderPanel({ displayed: { ...DISPLAYED, edge_ids: [] }, appliedCount: 1 });
    expect(screen.getByText("この候補は経路のEdge情報を持たないため、区間を出せません。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "差分を見る" })).not.toBeInTheDocument();
    expect(screen.queryByText("距離", { selector: "dt" })).not.toBeInTheDocument();
  });
});

describe("RouteSplicePanel 軸ごとの差", () => {
  // 風 −8、勾配 +3、停止 +0.05（0.1未満は出さない）。
  const preview = makeRouteCandidate({ axis_contributions: { wind: 12, slope: 13, stops: 10.25 } });

  it("動いた軸を差の大きい順に1本の棒へ並べ、差が0.1未満の軸は出さない", () => {
    renderPanel({ appliedCount: 1, preview });
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "風 −8.0、勾配 +3.0");
  });

  it("減った軸は中央の左、増えた軸は右に、最も大きい差を半分の幅として比で伸ばし、軸の色で塗る", () => {
    renderPanel({ appliedCount: 1, preview });
    const [left, , right] = [...screen.getByRole("img").children] as HTMLElement[];
    expect([...left.children].map((bar) => (bar as HTMLElement).style.width)).toEqual(["50%"]);
    expect([...right.children].map((bar) => (bar as HTMLElement).style.width)).toEqual(["18.75%"]);
    // 色は軸の色。色を持たない軸は弱い文字色で塗る。
    expect((left.children[0] as HTMLElement).style.background).toBe("#0000ff");
    expect((right.children[0] as HTMLElement).style.background).toBe("var(--color-muted)");
  });

  it("寄与の値を持たない軸は0として差を取る", () => {
    const withNewAxis = makeRouteCandidate({ axis_contributions: { ...DISPLAYED.axis_contributions, fresh: 5 } });
    renderPanel({ appliedCount: 1, preview: withNewAxis, axes: [...AXES, axis("fresh", "新しい軸")] });
    expect(screen.getByRole("img")).toHaveAttribute("aria-label", "新しい軸 +5.0");
  });

  it("差の大きい2軸を、数値つきで書き出す", () => {
    renderPanel({ appliedCount: 1, preview });
    expect(screen.getByText("風 −8.0")).toBeInTheDocument();
    expect(screen.getByText("勾配 +3.0")).toBeInTheDocument();
  });

  it("乗り換えた後、評価する前は、評価のしかたを出す", () => {
    renderPanel({ appliedCount: 1 });
    expect(screen.getByText("「差分」を押すと、乗り換えた結果が出ます")).toBeInTheDocument();
  });

  it("乗り換える前は、乗り換えられる区間があるかで一言が変わる", () => {
    renderPanel({ appliedCount: 0, hasAlternatives: true });
    expect(screen.getByText("地図の破線をタップして乗り換えます")).toBeInTheDocument();
  });

  it("乗り換えられる区間が無ければ、その旨を出す", () => {
    renderPanel({ appliedCount: 0, hasAlternatives: false });
    expect(screen.getByText("他の候補と別の道を通る区間がありません。")).toBeInTheDocument();
  });
});
