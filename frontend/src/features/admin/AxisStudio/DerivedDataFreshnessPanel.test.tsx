/**
 * `DerivedDataFreshnessPanel.tsx`——派生データの鮮度台帳を押したときだけ集計し、ソースごと・表ごとに「作り直しが
 * 要るか」を1行へまとめ、作り直し待ちの件数を先頭に出すこと。
 *
 * 行の組み立て（どの状態を手当て要とするか・開いた先に何を並べるか）はこのファイルの判断で、
 * 一覧の描き方そのものは `StatusRowList.test.tsx` が持つ。
 * 集計のカードの骨格（押すまで集計しない・集計中・失敗の表示・集計時刻）は `ReportCard.test.tsx` が持つ。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { onSameOrigin } from "@/testing/backendServer";

import type { DerivedDataFreshnessResponse } from "@/types/route";

import DerivedDataFreshnessPanel from "./DerivedDataFreshnessPanel";

type Source = DerivedDataFreshnessResponse["sources"][number];
type Table = DerivedDataFreshnessResponse["tables"][number];
type Column = Table["columns"][number];

function source(overrides: Partial<Source>): Source {
  return { source: "osm_way", derived_run_id: 1, latest_run_id: 1, needs_rebuild: false, ...overrides };
}

function table(overrides: Partial<Table>): Table {
  return {
    table_name: "derived_a",
    row_count: 0,
    columns: [],
    columns_change: { added: [], removed: [] },
    needs_rebuild: false,
    ...overrides,
  };
}

function column(overrides: Partial<Column>): Column {
  return { column: "value_a", null_count: 0, ...overrides };
}

function report(tables: Table[], sources: Source[] = []): DerivedDataFreshnessResponse {
  return { computed_at: "2026-09-24T01:02:03Z", sources, tables };
}

async function collect(response: DerivedDataFreshnessResponse) {
  onSameOrigin("GET", "/admin/api/derived-data/freshness", () => Response.json(response));
  const user = userEvent.setup();
  render(<DerivedDataFreshnessPanel />);
  await user.click(screen.getByRole("button", { name: "集計する" }));
  await screen.findByRole("button", { name: "再集計する" });
  return user;
}

function rowOf(name: string): HTMLElement {
  return screen.getByText(name).closest("details")!;
}

function detailOf(name: string): (string | null | undefined)[][] {
  return Array.from(rowOf(name).querySelectorAll("dt")).map((dt) => [dt.textContent, dt.nextSibling?.textContent]);
}

describe("DerivedDataFreshnessPanel", () => {
  it.each([
    [
      report(
        [table({ table_name: "target", needs_rebuild: true }), table({ table_name: "fresh" })],
        [source({ source: "accident", needs_rebuild: true }), source({ source: "osm_way" })],
      ),
      "2件が作り直し待ち",
    ],
    [report([table({ table_name: "fresh" })], [source({})]), "すべて最新"],
  ])(
    "作り直しが要るソースと表を合わせて作り直し待ちとして数え、無ければすべて最新と言う（%#）",
    async (given, verdict) => {
      await collect(given);
      expect(screen.getByText(verdict)).toBeInTheDocument();
    },
  );

  it("ソースの行は、開いた先に成功した最新の取込と作り直しに使った取込を並べ、無ければ理由とともに無いと言う", async () => {
    await collect(
      report(
        [],
        [
          source({ source: "accident", latest_run_id: 9, derived_run_id: 7 }),
          source({ source: "dem", latest_run_id: null, derived_run_id: null }),
        ],
      ),
    );

    expect(detailOf("accident")).toEqual([
      ["成功した最新の取込", "#9"],
      ["作り直しに使った取込", "#7"],
    ]);
    expect(detailOf("dem")).toEqual([
      ["成功した最新の取込", "なし（取込が1度も成功していない）"],
      ["作り直しに使った取込", "なし（まだ作り直しに使っていない）"],
    ]);
  });

  it("表の行は、開いた先に作り直しの後に足した列・消した列と、値なしのある列の件数を並べる", async () => {
    await collect(
      report([
        table({
          table_name: "edge_materials",
          columns_change: { added: ["new_a", "new_b"], removed: ["old_a"] },
          columns: [column({ column: "start_elevation_m", null_count: 1500 }), column({ column: "complete_col" })],
        }),
      ]),
    );

    expect(detailOf("edge_materials")).toEqual([
      ["作り直しの後に足した列", "new_a、new_b"],
      ["作り直しの後に消した列", "old_a"],
      ["start_elevation_m", "値なし 1,500件"],
    ]);
  });

  it("作ったときの列の記録が無い表はそう言い、列の変化も値なしも無い表には何も並べない", async () => {
    await collect(report([table({ table_name: "t", columns_change: null }), table({ table_name: "plain" })]));

    expect(detailOf("t")).toEqual([["作ったときの列", "記録なし（列を記録する作り直しをまだしていない）"]]);
    expect(detailOf("plain")).toEqual([]);
  });
});
