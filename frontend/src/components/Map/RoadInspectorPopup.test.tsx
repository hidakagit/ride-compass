import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { fetchAxisInspector } from "@/services/regionApi";
import RoadInspectorPopup from "./RoadInspectorPopup";

vi.mock("@/services/regionApi", () => ({ fetchAxisInspector: vi.fn() }));

const AXES: PreferenceAxisDef[] = [
  { axisId: "car_stress", label: "車の圧迫感", description: "車の通行量の説明", dedicatedWayValueLayer: false },
  { axisId: "night", label: "夜間", description: "夜間の暗さの説明", dedicatedWayValueLayer: false },
];
const AXIS_COLORS: Record<string, string> = { car_stress: "#111111", night: "#222222" };

function inspectorResult() {
  return {
    highway: "residential",
    tags: { lit: "yes", name: "明治通り" },
    is_designated: false,
    axes: [
      { axis_id: "car_stress", difficulty: 60, weight: 1, available: true, contribution: 30 },
      { axis_id: "night", difficulty: 20, weight: 1, available: true, contribution: 10 },
      { axis_id: "gradient", difficulty: null, weight: 1, available: false, contribution: null },
    ],
    composite_difficulty: 40,
    covered_weight_fraction: 0.8,
  };
}

describe("RoadInspectorPopup", () => {
  beforeEach(() => {
    vi.mocked(fetchAxisInspector).mockReset();
  });

  it("事実だけを先に出し、評価は押したときに取りに行く（クリックのたびに引かない）", () => {
    render(
      <RoadInspectorPopup
        properties={{ osm_way_id: 1, name: "明治通り", surface_good: true }}
        axes={AXES}
        axisColors={AXIS_COLORS}
      />,
    );

    expect(screen.getByText("明治通り")).toBeInTheDocument();
    expect(screen.getByText("舗装路")).toBeInTheDocument();
    expect(fetchAxisInspector).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "この道の評価を見る" })).toBeInTheDocument();
  });

  it("評価はルート結果と同じ寄与度で出し、算出できない軸は並べない", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchAxisInspector).mockResolvedValue(inspectorResult());
    render(
      <RoadInspectorPopup properties={{ osm_way_id: 1, surface_good: true }} axes={AXES} axisColors={AXIS_COLORS} />,
    );

    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));

    // 寄与度バーの凡例は軸アイコン＋値（ルート結果と同じ部品）。
    expect(await screen.findByText("30.0")).toBeInTheDocument();
    expect(screen.getByText("10.0")).toBeInTheDocument();
    // 進む向きが決まらないと出せない軸（勾配）はそもそも並ばない。
    expect(screen.queryByLabelText("勾配の詳細を表示")).not.toBeInTheDocument();
  });

  it("合成は注記として出す（実際の探索コストとは一致しないため主役にしない）", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchAxisInspector).mockResolvedValue(inspectorResult());
    render(
      <RoadInspectorPopup properties={{ osm_way_id: 1, surface_good: true }} axes={AXES} axisColors={AXIS_COLORS} />,
    );

    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));

    expect(await screen.findByText(/この道だけで見た合成: 40\.0\/100/)).toBeInTheDocument();
    expect(screen.getByText(/重みの約80%/)).toBeInTheDocument();
  });

  it("カタログ外の生タグは畳んで置く（数が読めないため、開いたときだけ縦に伸ばす）", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchAxisInspector).mockResolvedValue(inspectorResult());
    render(
      <RoadInspectorPopup properties={{ osm_way_id: 1, surface_good: true }} axes={AXES} axisColors={AXIS_COLORS} />,
    );

    await user.click(screen.getByRole("button", { name: "この道の評価を見る" }));

    await waitFor(() => expect(screen.getByText("その他のタグ")).toBeInTheDocument());
    // 登録済みの属性は畳まずに出す。
    expect(screen.getByText("yes")).toBeInTheDocument();
  });

  it("OSMの生値はタグとして解釈されない（第三者が編集できるデータのため）", () => {
    const attack = '<img src=x onerror="alert(1)">';
    const { container } = render(
      <RoadInspectorPopup properties={{ osm_way_id: 1, name: attack }} axes={AXES} axisColors={AXIS_COLORS} />,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain(attack);
  });
});
