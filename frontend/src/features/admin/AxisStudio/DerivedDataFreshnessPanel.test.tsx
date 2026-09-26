/**
 * `DerivedDataFreshnessPanel.tsx`——派生データの鮮度台帳を押したときだけ集計し、表ごとに「作り直しが
 * 要るか」を1行へまとめ、要るなら打つコマンドを1つだけ示すこと。
 *
 * 行の組み立て（どの状態を手当て要とするか・開いた先に何を並べるか）はこのファイルの判断で、
 * 一覧の描き方そのものは `StatusRowList.test.tsx` が持つ。
 * 集計のカードの骨格（押すまで集計しない・集計中・失敗の表示・集計時刻）は `ReportCard.test.tsx` が持つ。
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DerivedDataFreshnessResponse } from "@/types/route";

const api = vi.hoisted(() => ({ getDerivedDataFreshness: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => api);

import DerivedDataFreshnessPanel from "./DerivedDataFreshnessPanel";

type Table = DerivedDataFreshnessResponse["tables"][number];
type Column = Table["columns"][number];

function table(overrides: Partial<Table>): Table {
  return {
    table_name: "derived_a",
    row_count: 0,
    source: null,
    oldest_run_id: null,
    latest_run_id: null,
    is_stale: false,
    coverage_parent: null,
    coverage_parent_row_count: null,
    missing_rows: null,
    columns: [],
    needs_rebuild: false,
    ...overrides,
  };
}

function column(overrides: Partial<Column>): Column {
  return { column: "value_a", null_count: 0, is_incomplete: false, ...overrides };
}

function report(tables: Table[], computedAt = "2026-09-24T01:02:03Z"): DerivedDataFreshnessResponse {
  return { computed_at: computedAt, tables };
}

beforeEach(() => {
  api.getDerivedDataFreshness.mockReset();
});

async function collect(response: DerivedDataFreshnessResponse) {
  api.getDerivedDataFreshness.mockResolvedValue(response);
  const user = userEvent.setup();
  render(<DerivedDataFreshnessPanel />);
  await user.click(screen.getByRole("button", { name: "集計する" }));
  await screen.findByRole("button", { name: "再集計する" });
  return user;
}

function rowOf(tableName: string): HTMLElement {
  return screen.getByText(tableName).closest("details")!;
}

describe("DerivedDataFreshnessPanel", () => {
  it("手当て要の表が無ければ、すべて最新と言い、コマンドは出さない", async () => {
    await collect(report([table({ table_name: "fresh", columns: [column({ null_count: 5 })] })]));

    expect(screen.getByText("すべて最新")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "コピー" })).not.toBeInTheDocument();
    expect(within(rowOf("fresh")).getByText("最新")).toBeInTheDocument();
  });

  it("作り直しが要る表は、作り直し待ちとして数える", async () => {
    await collect(report([table({ table_name: "target", needs_rebuild: true }), table({ table_name: "fresh" })]));

    expect(screen.getByText("1件が作り直し待ち")).toBeInTheDocument();
    expect(within(rowOf("target")).getByText("作り直しが必要")).toBeInTheDocument();
    expect(within(rowOf("fresh")).getByText("最新")).toBeInTheDocument();
  });

  it("行は表の名前と行数を出し、開いた先に取込の世代・被覆・列ごとの未計算と確定した値なしを並べる", async () => {
    await collect(
      report([
        table({
          table_name: "edge_materials",
          row_count: 12345,
          source: "OSM",
          latest_run_id: 9,
          oldest_run_id: 7,
          coverage_parent: "road_edges",
          coverage_parent_row_count: 20000,
          missing_rows: 1500,
          columns: [
            column({ column: "gradient", null_count: 42, is_incomplete: true }),
            column({ column: "bridge_slope", null_count: 7, is_incomplete: false }),
            column({ column: "complete_col", null_count: 0, is_incomplete: false }),
          ],
        }),
      ]),
    );

    const row = rowOf("edge_materials");
    expect(within(row).getByText("12,345行")).toBeInTheDocument();
    const detail = Array.from(row.querySelectorAll("dt")).map((dt) => [dt.textContent, dt.nextSibling?.textContent]);
    expect(detail).toEqual([
      ["OSM", "最新 #9 / 反映 #7"],
      ["road_edges を覆う", "1,500件ぶん行が無い（母数 20,000）"],
      ["gradient", "未計算 42件"],
      ["bridge_slope", "値なし 7件（確定）"],
    ]);
  });

  it("取込の名前・世代が無い表は「取込」「-」で出し、親に欠けが無ければ母数とともにそう言う", async () => {
    await collect(
      report([
        table({
          table_name: "t",
          source: null,
          latest_run_id: null,
          oldest_run_id: null,
          coverage_parent: "osm_way",
          coverage_parent_row_count: 3000,
          missing_rows: 0,
        }),
      ]),
    );

    const detail = Array.from(rowOf("t").querySelectorAll("dt")).map((dt) => [
      dt.textContent,
      dt.nextSibling?.textContent,
    ]);
    expect(detail).toEqual([
      ["取込", "最新 - / 反映 -"],
      ["osm_way を覆う", "欠けなし（母数 3,000）"],
    ]);
  });

  it("親を覆うことを宣言していない表には、被覆の項目を出さない", async () => {
    await collect(report([table({ table_name: "plain", coverage_parent: null })]));

    const labels = Array.from(rowOf("plain").querySelectorAll("dt")).map((dt) => dt.textContent);
    expect(labels).toEqual(["取込"]);
  });
});
