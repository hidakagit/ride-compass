import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import type { RouteCandidate } from "@/types/route";
import RouteSplicePanel from "./RouteSplicePanel";

const AXES = [
  { axisId: "car_stress", label: "車の圧迫感", description: "", dedicatedWayValueLayer: false },
  { axisId: "gradient", label: "坂", description: "", dedicatedWayValueLayer: false },
] as unknown as PreferenceAxisDef[];

function candidate(overrides: Partial<RouteCandidate> = {}): RouteCandidate {
  return makeRouteCandidate({
    id: "route-00",
    direction_label: "目的地ルート",
    distance_km: 4.0,
    edge_ids: ["a", "b", "c"],
    overall_difficulty: 42,
    difficulty_load: 168,
    estimated_duration_seconds: 1080,
    axis_contributions: { car_stress: 20, gradient: 12 },
    ...overrides,
  });
}

function baseProps(overrides: Partial<Parameters<typeof RouteSplicePanel>[0]> = {}) {
  return {
    displayed: candidate(),
    appliedCount: 0,
    hasAlternatives: true,
    onUndo: vi.fn(),
    preview: null as RouteCandidate | null,
    previewing: false,
    onPreview: vi.fn(),
    onApply: vi.fn(),
    applying: false,
    error: null as string | null,
    onCancel: vi.fn(),
    axes: AXES,
    axisColors: { car_stress: "#dc7633", gradient: "#27ae60" },
    ...overrides,
  };
}

const PREVIEW = candidate({
  id: "route-spliced",
  distance_km: 4.3,
  overall_difficulty: 38,
  difficulty_load: 163,
  estimated_duration_seconds: 1140,
  axis_contributions: { car_stress: 16.9, gradient: 12.9 },
});

describe("RouteSplicePanel", () => {
  it("指標はルート結果と同じ項目で、評価前は編集後が空", () => {
    render(<RouteSplicePanel {...baseProps({ appliedCount: 1 })} />);

    for (const label of ["距離", "所要", "総合難易度", "負荷"]) {
      expect(screen.getByRole("rowheader", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByText("4.0km")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("評価できたら編集後の値と差が入る", () => {
    render(<RouteSplicePanel {...baseProps({ appliedCount: 1, preview: PREVIEW })} />);

    expect(screen.getByText("4.3km")).toBeInTheDocument();
    expect(screen.getByText("+0.3")).toBeInTheDocument();
    expect(screen.getByText("38")).toBeInTheDocument();
    expect(screen.getByText("−4")).toBeInTheDocument();
  });

  // 元と編集後のバーを2本並べると、同じ軸を目で突き合わせることになる。差だけを1本で出す。
  it("軸別は差だけを出し、動いた軸を大きい順に書く", () => {
    render(<RouteSplicePanel {...baseProps({ appliedCount: 1, preview: PREVIEW })} />);

    expect(screen.getByText(/車の圧迫感 −3\.1/)).toBeInTheDocument();
    expect(screen.getByText(/坂 \+0\.9/)).toBeInTheDocument();
  });

  it("動きが小さい軸は出さない（1pxの破片を並べない）", () => {
    const almostSame = candidate({ axis_contributions: { car_stress: 20.05, gradient: 12 } });
    render(<RouteSplicePanel {...baseProps({ appliedCount: 1, preview: almostSame })} />);

    expect(screen.queryByText(/車の圧迫感/)).toBeNull();
  });

  it("乗り換えていなければ、評価も作成もできない", () => {
    render(<RouteSplicePanel {...baseProps()} />);

    expect(screen.getByRole("button", { name: "差分を見る" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "新しいルートを作る" })).toBeDisabled();
    expect(screen.getByText("地図の破線をタップして乗り換えます")).toBeInTheDocument();
  });

  it("乗り換えた回数を出し、直前の1手を戻せる", async () => {
    const onUndo = vi.fn();
    render(<RouteSplicePanel {...baseProps({ appliedCount: 3, onUndo })} />);

    expect(screen.getByText("3回乗り換え")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "1つ戻す" }));

    expect(onUndo).toHaveBeenCalledTimes(1);
  });

  it("乗り換えていなければ戻すボタンは出さない", () => {
    render(<RouteSplicePanel {...baseProps()} />);

    expect(screen.queryByRole("button", { name: "1つ戻す" })).toBeNull();
  });

  it("乗り換え先が無いことを伝える", () => {
    render(<RouteSplicePanel {...baseProps({ hasAlternatives: false })} />);

    expect(screen.getByText("他の候補と別の道を通る区間がありません。")).toBeInTheDocument();
  });

  it("edge_idsを持たない候補では区間を出せないことを伝える", () => {
    render(<RouteSplicePanel {...baseProps({ displayed: candidate({ edge_ids: [] }) })} />);

    expect(screen.getByText(/Edge情報を持たない/)).toBeInTheDocument();
  });

  // 合成の失敗は「ルート結果」欄の空状態には出ない（候補がある間は描かれない）。押した場所へ
  // 出さないと「押しても何も起きない」に見える。
  it("合成に失敗した理由をこのパネルへ出す", () => {
    render(
      <RouteSplicePanel {...baseProps({ appliedCount: 1, error: "組み合わせたルートを評価できませんでした" })} />,
    );

    expect(screen.getByText("組み合わせたルートを評価できませんでした")).toBeInTheDocument();
  });

  it("編集をやめると親へ知らせる", async () => {
    const onCancel = vi.fn();
    render(<RouteSplicePanel {...baseProps({ onCancel })} />);

    await userEvent.click(screen.getByRole("button", { name: "編集をやめて候補へ戻る" }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  describe("評価中", () => {
    it("計算中は評価も作成も押せない", () => {
      render(<RouteSplicePanel {...baseProps({ appliedCount: 1, previewing: true })} />);

      const preview = screen.getByRole("button", { name: "差分を見る" });
      expect(preview).toBeDisabled();
      expect(preview).toHaveAttribute("aria-busy", "true");
      expect(screen.getByRole("button", { name: "新しいルートを作る" })).toBeDisabled();
    });

    it("作成中は戻すボタンも押せない", () => {
      render(<RouteSplicePanel {...baseProps({ appliedCount: 1, applying: true })} />);

      expect(screen.getByRole("button", { name: "1つ戻す" })).toBeDisabled();
    });
  });
});
