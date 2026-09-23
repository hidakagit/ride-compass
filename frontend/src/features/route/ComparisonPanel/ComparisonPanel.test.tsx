import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { makeRouteCandidate } from "@/testing/routeFixtures";
import type { ExperimentSlot } from "@/types/experimentSlot";
import type { GenerationConditions, RouteCandidate } from "@/types/route";

import ComparisonPanel from "./ComparisonPanel";

const axis = (axisId: string, label: string): PreferenceAxisDef => ({
  axisId,
  label,
  description: "",
  dedicatedWayValueLayer: false,
});
const AXES = [axis("wind", "風"), axis("slope", "勾配"), axis("night", "夜道")];

const material = (id: string, name: string, unit: string): AxisMaterialOption => ({
  id,
  name,
  label: `${name} - ${id}`,
  description: "",
  dtype: "numeric",
  unit,
});
const MATERIALS = [material("wind_load", "風の負荷", "W"), material("lit_ratio", "街灯の割合", "")];

function slot(
  id: string,
  candidate: Partial<RouteCandidate>,
  conditions: Partial<GenerationConditions> = {},
): ExperimentSlot {
  return {
    id,
    color: "#ff0000",
    conditions: {
      generated_at: "2026-09-24T09:05:30+09:00",
      route_preference: {},
      ...conditions,
    } as GenerationConditions,
    topCandidate: makeRouteCandidate({ distance_km: 30, ...candidate }),
  };
}

function renderPanel(slots: ExperimentSlot[], axisLabels: Record<string, string> = { wind: "風", slope: "勾配" }) {
  render(<ComparisonPanel slots={slots} axisLabels={axisLabels} axes={AXES} materials={MATERIALS} />);
}

/** 行見出し→各列の値。 */
function rows() {
  return Object.fromEntries(
    within(screen.getByRole("table"))
      .getAllByRole("rowheader")
      .map((header) => [
        header.textContent,
        [...header.parentElement!.querySelectorAll("td")].map((cell) => cell.textContent),
      ]),
  );
}

describe("ComparisonPanel 比べる相手がいない間", () => {
  it("まだ1回も生成していなければ、生成すると積まれることを出す", () => {
    renderPanel([]);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText(/ルートを生成すると、その回の結果がここへ積まれます/)).toBeInTheDocument();
  });

  it("1回だけなら、もう1回生成すると比べられることを出す", () => {
    renderPanel([slot("a", {})]);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("もう1回生成すると、前回との違いをここで並べて比べられます。")).toBeInTheDocument();
  });
});

describe("ComparisonPanel 表", () => {
  const slots = [
    slot(
      "a",
      {
        distance_km: 30.04,
        elevation_gain_m: 312.6,
        material_values: { wind_load: 1.234 },
        axis_difficulties: { wind: 40.25 },
        overall_difficulty: 35.56,
      },
      { route_preference: { wind: 0.6, slope: 0.4 } },
    ),
    slot(
      "b",
      {
        distance_km: 22,
        elevation_gain_m: null,
        material_values: { lit_ratio: 0.5, unknown_material: 9 },
        axis_difficulties: { slope: 12 },
        overall_difficulty: null,
      },
      { generated_at: "2026-09-24T09:40:00+09:00", route_preference: { wind: 0.5, retired: 0.5 } },
    ),
  ];

  it("回ごとに1列。列の見出しは生成した時刻（時:分）", () => {
    renderPanel(slots);
    // 時は見る人の端末の時刻帯で決まる（テストを動かす環境でも変わる）ため、分と形だけを見る。
    const [corner, ...headers] = within(screen.getByRole("table")).getAllByRole("columnheader");
    expect(corner).toHaveTextContent(/^$/);
    expect(headers.map((h) => h.textContent)).toEqual([
      expect.stringMatching(/^\d{2}:05$/),
      expect.stringMatching(/^\d{2}:40$/),
    ]);
  });

  it("列の見出しの補足に、正確な時刻とその回の重みを持つ。名前を引けない軸は件数だけ", () => {
    renderPanel(slots);
    const [, first, second] = within(screen.getByRole("table")).getAllByRole("columnheader");
    expect(first).toHaveAttribute("title", "2026-09-24T09:05:30+09:00 / pref 風0.6/勾配0.4");
    expect(second).toHaveAttribute("title", "2026-09-24T09:40:00+09:00 / pref 風0.5/ほか1軸");
  });

  it("行は、ルートの量→材料の実測値→軸ごとの難易度→総合難易度の順。材料と軸は、どれかの回が値を持ち名前を引けるものだけ", () => {
    renderPanel(slots);
    expect(Object.keys(rows())).toEqual([
      "距離",
      "獲得標高",
      "風の負荷",
      "街灯の割合",
      "風",
      "勾配",
      "総合難易度[絶対基準]",
    ]);
  });

  it("値の書き方と、値の無い回の「—」", () => {
    renderPanel(slots);
    expect(rows()).toEqual({
      距離: ["30.0 km", "22.0 km"],
      獲得標高: ["313 m", "—"],
      風の負荷: ["1.23 W", "—"],
      街灯の割合: ["—", "0.50"],
      風: ["40.3", "—"],
      勾配: ["—", "12.0"],
      "総合難易度[絶対基準]": ["35.6", "—"],
    });
  });

  it("何回分を並べているかを添える", () => {
    renderPanel(slots);
    expect(screen.getByText(/直近2回の生成結果を並べています/)).toBeInTheDocument();
  });

  it("時刻として読めない値は、そのまま見出しに出す", () => {
    renderPanel([slot("a", {}, { generated_at: "不明" }), slot("b", {})]);
    expect(within(screen.getByRole("table")).getAllByRole("columnheader")[1]).toHaveTextContent("不明");
  });
});
