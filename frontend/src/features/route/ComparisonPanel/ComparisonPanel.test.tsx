/**
 * `features/route/ComparisonPanel/ComparisonPanel.tsx`——研究モードの、直近の生成結果を並べる比較表。
 *
 * 見るもの: 比べる相手がいない間（0回・1回）の案内、何回分を並べているかの添え書き、列（回ごと。見出しは生成した
 * 時刻を日本時間の時:分で、補足に正確な時刻とその回の重み。名前を引けない軸は件数だけ）、行の並び（ルートの量 →
 * 材料の値 → 軸ごとの難易度 → 総合難易度）と行に入る材料・軸（どれかの回が値を持ち、名前を引けるもの）、
 * 値の書き方と値の無い回の「—」。
 *
 * ここで見ないもの: 比べる軸をどの回の重みで絞るか → `features/route/RouteOutcome`。材料の値の書き方 →
 * `lib/axisMaterialsCatalog.ts`。
 *
 * 軸・材料は架空のもの（`axis_a`・`mat_a`等）をテストが組む。
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import { catalogAxisFromEntry } from "@/lib/catalogAxis";
import { catalogEntry } from "@/testing/catalogAxes";
import { makeGenerationConditions, makeRouteCandidate } from "@/testing/routeFixtures";
import type { ExperimentSlot } from "@/types/experimentSlot";
import type { RouteCandidate } from "@/types/route";
import ComparisonPanel from "./ComparisonPanel";

const A = catalogAxisFromEntry(catalogEntry({ axis_id: "axis_a", label: "軸A" }));
const B = catalogAxisFromEntry(catalogEntry({ axis_id: "axis_b", label: "軸B" }));
const C = catalogAxisFromEntry(catalogEntry({ axis_id: "axis_c", label: "軸C" }));

function material(id: string, name: string, unit: string): AxisMaterialOption {
  return { id, label: `${name} - ${id}`, name, description: "", dtype: "numeric", unit };
}
const MATERIALS = [material("mat_a", "材料A", "km/h"), material("mat_b", "材料B", "")];

function slot(
  id: string,
  generatedAt: string,
  candidate: Partial<RouteCandidate>,
  routePreference = {},
): ExperimentSlot {
  return {
    id,
    color: "rgb(1, 2, 3)",
    conditions: makeGenerationConditions({ generated_at: generatedAt, route_preference: routePreference }),
    topCandidate: makeRouteCandidate({ id, ...candidate }),
  };
}

const FIRST = slot(
  "first",
  "2026-10-04T00:05:00Z",
  {
    distance_km: 12.34,
    elevation_gain_m: 123.4,
    material_values: { mat_a: 31.456, unknown_material: 1 },
    axis_difficulties: { axis_b: 12.34 },
    overall_difficulty: { average: 33.33, load: 400 },
  },
  { axis_a: 0.5, axis_hidden: 0.2 },
);
const SECOND = slot(
  "second",
  "2026-10-04T01:30:00Z",
  {
    distance_km: 8,
    elevation_gain_m: null,
    material_values: { mat_b: 0.5 },
    axis_difficulties: { axis_a: 50 },
    overall_difficulty: null,
  },
  { axis_a: 0.5 },
);

function renderPanel(slots: ExperimentSlot[]) {
  return render(
    <ComparisonPanel slots={slots} axisLabels={{ axis_a: "軸A" }} axes={[A, B, C]} materials={MATERIALS} />,
  );
}

/** 本体の行を、見出しと各回の値の並びで。 */
function bodyRows(): string[][] {
  const [, ...rows] = screen.getAllByRole("row");
  return rows.map((row) => [
    within(row).getByRole("rowheader").textContent ?? "",
    ...within(row)
      .getAllByRole("cell")
      .map((cell) => cell.textContent ?? ""),
  ]);
}

describe("ComparisonPanel", () => {
  it("まだ1回も生成していなければ、生成すると積まれることを案内し、表を出さない", () => {
    renderPanel([]);
    expect(screen.getByText(/ルートを生成すると、その回の結果がここへ積まれます/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("1回だけなら、もう1回生成すると比べられることを案内し、表を出さない", () => {
    renderPanel([FIRST]);
    expect(screen.getByText("もう1回生成すると、前回との違いをここで並べて比べられます。")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("同じ分に生成した回も見分けられるよう、列の見出しに回の色を付ける", () => {
    renderPanel([FIRST, { ...SECOND, color: "rgb(4, 5, 6)" }]);
    const headers = within(screen.getAllByRole("row")[0]).getAllByRole("columnheader").slice(1);
    const dotColor = (header: HTMLElement) =>
      header.querySelector<HTMLElement>('[aria-hidden="true"]')?.style.background;
    expect(headers.map(dotColor)).toEqual(["rgb(1, 2, 3)", "rgb(4, 5, 6)"]);
  });

  it("2回以上なら、何回分を並べているかを添える", () => {
    renderPanel([FIRST, SECOND, slot("third", "2026-10-04T02:00:00Z", {})]);
    expect(screen.getByText(/直近3回の生成結果を並べています/)).toBeInTheDocument();
  });

  it("列は回ごとで、見出しは生成した時刻（日本時間の時:分）、補足に正確な時刻とその回の重みを持つ", () => {
    renderPanel([FIRST, SECOND]);
    const headers = within(screen.getAllByRole("row")[0]).getAllByRole("columnheader").slice(1);
    expect(headers.map((header) => header.textContent)).toEqual(["09:05", "10:30"]);
    // 名前を引けない軸は軸idを出さず、件数だけにする。
    expect(headers[0]).toHaveAttribute("title", "2026-10-04T00:05:00Z / pref 軸A0.5/ほか1軸");
    expect(headers[1]).toHaveAttribute("title", "2026-10-04T01:30:00Z / pref 軸A0.5");
  });

  it("行はルートの量・材料の値・軸ごとの難易度・総合難易度の順で、値の無い回は「—」", () => {
    renderPanel([FIRST, SECOND]);
    expect(bodyRows()).toEqual([
      ["距離", "12.3 km", "8.0 km"],
      ["獲得標高", "123 m", "—"],
      // 材料は名前を引けるものだけ。単位の無い材料は値だけ。
      ["材料A", "31.46 km/h", "—"],
      ["材料B", "—", "0.50"],
      // 軸はどれかの回が値を持つものだけを、渡された並びで。
      ["軸A", "—", "50.0"],
      ["軸B", "12.3", "—"],
      ["総合難易度[絶対基準]", "33.3", "—"],
    ]);
  });
});
