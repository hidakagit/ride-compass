/**
 * `MaterialCoveragePanel.tsx`——材料ごとの欠損割合を押したときだけ集計し、「欠損時の扱い」の群ごとに欠損割合の
 * 高い順の表で出すこと。どの群にも入らない材料は別の群で拾い、集計対象外の材料は理由つきで畳む。
 *
 * 群の見出し・説明と母集団の名前はbackendの宣言（生成物 `vocabulary.ts`）が配るため、期待値もそこから引く。
 * 集計のカードの骨格（押すまで集計しない・集計中・失敗の表示・集計時刻）は `ReportCard.test.tsx` が持つ。
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { vocabulary } from "@/types/generated/vocabulary";
import type { MaterialCoverageEntry, MaterialCoverageResponse } from "@/types/route";

const api = vi.hoisted(() => ({ getMaterialCoverage: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);

import MaterialCoveragePanel from "./MaterialCoveragePanel";

type Semantics = NonNullable<MaterialCoverageEntry["missing_semantics"]>;
type Population = NonNullable<MaterialCoverageEntry["population"]>;

const semanticsGroups = vocabulary.materialMissingSemantics;
const [firstGroup, secondGroup] = semanticsGroups;
const populations = vocabulary.materialPopulations;

function entry(overrides: Partial<MaterialCoverageEntry>): MaterialCoverageEntry {
  return {
    material_id: "material_a",
    label: "材料A",
    dtype: "numeric",
    population: null,
    total: null,
    missing: null,
    missing_ratio: null,
    source: "",
    missing_semantics: firstGroup.key as Semantics,
    excluded_reason: null,
    ...overrides,
  };
}

function response(materials: MaterialCoverageEntry[], overrides: Partial<MaterialCoverageResponse> = {}) {
  return { computed_at: "2026-09-24T01:02:03Z", way_total: 0, edge_total: 0, materials, ...overrides };
}

beforeEach(() => {
  api.getMaterialCoverage.mockReset();
});

async function collect(result: MaterialCoverageResponse) {
  api.getMaterialCoverage.mockResolvedValue(result);
  const user = userEvent.setup();
  render(<MaterialCoveragePanel />);
  await user.click(screen.getByRole("button", { name: "集計する" }));
  await screen.findByRole("button", { name: "再集計する" });
  return user;
}

function rowLabels(section: HTMLElement): (string | null)[] {
  return within(section)
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0].textContent);
}

describe("MaterialCoveragePanel", () => {
  it("集計時刻の前に、Way・Edgeの総数を出す", async () => {
    await collect(response([], { computed_at: "2026-09-24T01:02:03Z", way_total: 123456, edge_total: 789 }));
    expect(screen.getByText("Way 123,456件 ・ Edge 789件 ・ 9/24 10:02")).toBeInTheDocument();
  });

  it("欠損時の扱いごとに、宣言の見出し・説明つきの群へ分け、材料の無い群は出さない", async () => {
    await collect(
      response([entry({ material_id: "m1", label: "一つ目", missing_semantics: secondGroup.key as Semantics })]),
    );

    const section = screen.getByRole("region", { name: secondGroup.title });
    expect(within(section).getByText(secondGroup.hint)).toBeInTheDocument();
    expect(rowLabels(section)).toEqual(["一つ目"]);
    expect(screen.queryByRole("region", { name: firstGroup.title })).not.toBeInTheDocument();
  });

  it("群の中は欠損割合の高い順で、同率は届いた順、割合の無い材料は最後", async () => {
    await collect(
      response([
        entry({ material_id: "none", label: "割合なし", missing_ratio: null }),
        entry({ material_id: "low", label: "低い", missing_ratio: 0.1 }),
        entry({ material_id: "tie_a", label: "同率A", missing_ratio: 0.5 }),
        entry({ material_id: "high", label: "高い", missing_ratio: 0.9 }),
        entry({ material_id: "tie_b", label: "同率B", missing_ratio: 0.5 }),
      ]),
    );

    expect(rowLabels(screen.getByRole("region", { name: firstGroup.title }))).toEqual([
      "高い",
      "同率A",
      "同率B",
      "低い",
      "割合なし",
    ]);
  });

  it("行は材料名（判定根拠は名前の説明に）・母集団の名前・欠損割合と「欠損 / 総数」を出す", async () => {
    const population = populations[0];
    await collect(
      response([
        entry({
          material_id: "m",
          label: "路面",
          source: "OSM wayのタグ surface",
          population: population.key as Population,
          missing: 1234,
          total: 5000,
          missing_ratio: 0.2468,
        }),
        entry({ material_id: "blank", label: "未集計", population: null }),
      ]),
    );

    const [row, blank] = within(screen.getByRole("region", { name: firstGroup.title }))
      .getAllByRole("row")
      .slice(1);
    const [name, pop, ratio] = within(row).getAllByRole("cell");
    expect(name).toHaveTextContent("路面");
    expect(name).toHaveAttribute("title", "OSM wayのタグ surface");
    expect(pop).toHaveTextContent(population.label);
    expect(ratio).toHaveTextContent("24.7%");
    expect(ratio).toHaveTextContent("1,234 / 5,000");

    const [, blankPop, blankRatio] = within(blank).getAllByRole("cell");
    expect(blankPop.textContent).toBe("-");
    expect(blankRatio).toHaveTextContent("-");
    expect(blankRatio).toHaveTextContent("- / -");
  });

  it("行へ、欠損の扱いが評価に効くかを印として付ける（効かない扱いの棒を薄く塗るため）", async () => {
    await collect(
      response(
        semanticsGroups.map((group) =>
          entry({ material_id: group.key, label: group.key, missing_semantics: group.key as Semantics }),
        ),
      ),
    );
    for (const group of semanticsGroups) {
      expect(screen.getByText(group.key).closest("tr")).toHaveAttribute(
        "data-affects-evaluation",
        String(group.affects_evaluation),
      );
    }
  });

  // backendを先に出すと、フロントの生成物にまだ無い扱いが届く。
  it("欠損時の扱いが無い・宣言に無い材料は、表から消さずに「不明」の群で拾う", async () => {
    await collect(
      response([
        entry({ material_id: "null", label: "扱いなし", missing_semantics: null }),
        entry({ material_id: "unknown", label: "宣言に無い扱い", missing_semantics: "not-declared" as Semantics }),
      ]),
    );

    const section = screen.getByRole("region", { name: "欠損時の扱いが不明な材料" });
    expect(rowLabels(section)).toEqual(["扱いなし", "宣言に無い扱い"]);
    for (const group of semanticsGroups) {
      expect(screen.queryByRole("region", { name: group.title })).not.toBeInTheDocument();
    }
  });

  it("集計対象外の材料は表へ入れず、件数つきの折りたたみに理由を添えて並べる", async () => {
    await collect(
      response([
        entry({ material_id: "in", label: "対象" }),
        entry({ material_id: "out", label: "対象外", excluded_reason: "ルート文脈が要る" }),
      ]),
    );

    expect(rowLabels(screen.getByRole("region", { name: firstGroup.title }))).toEqual(["対象"]);
    const summary = screen.getByText("集計対象外の材料（1件）");
    expect(summary.closest("details")).toHaveTextContent("対象外: ルート文脈が要る");
  });

  it("集計対象外が無ければ、折りたたみを出さない", async () => {
    await collect(response([entry({})]));
    expect(screen.queryByText(/集計対象外の材料/)).not.toBeInTheDocument();
  });
});
