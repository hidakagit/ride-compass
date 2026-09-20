import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DerivedDataFreshnessResponse } from "@/types/route";
import DerivedDataFreshnessPanel, { REBUILD_COMMAND } from "./DerivedDataFreshnessPanel";
import { getDerivedDataFreshness } from "@/services/derivedDataFreshnessApi";

vi.mock("@/services/derivedDataFreshnessApi", () => ({
  getDerivedDataFreshness: vi.fn(),
}));

type TableEntry = DerivedDataFreshnessResponse["tables"][number];

function table(overrides: Partial<TableEntry>): TableEntry {
  return {
    table_name: "edge_materials",
    row_count: 5000,
    source: "osm_way",
    oldest_run_id: 10,
    latest_run_id: 10,
    is_stale: false,
    coverage_parent: "road_edges",
    coverage_parent_row_count: 5000,
    missing_rows: 0,
    columns: [
      { column: "accident_count", null_count: 0, is_incomplete: false },
      // 橋・トンネルは値を持たない。件数は出すが作り直しの対象にはしない。
      { column: "average_grade", null_count: 500, is_incomplete: false },
    ],
    ...overrides,
  };
}

const FRESH_REPORT: DerivedDataFreshnessResponse = {
  computed_at: "2026-09-04T12:00:00+00:00",
  tables: [table({}), table({ table_name: "way_materials" }), table({ table_name: "road_edges", columns: [] })],
};

async function clickAggregate(user: ReturnType<typeof userEvent.setup>) {
  await act(async () => {
    await user.click(screen.getByRole("button", { name: "集計する" }));
  });
}

describe("DerivedDataFreshnessPanel", () => {
  it("開いた直後は集計せず、ボタン押下で初めてgetDerivedDataFreshnessを呼ぶ", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    expect(getDerivedDataFreshness).not.toHaveBeenCalled();
    expect(screen.queryByText("edge_materials")).not.toBeInTheDocument();

    await clickAggregate(user);

    expect(getDerivedDataFreshness).toHaveBeenCalledTimes(1);
    expect(screen.getByText("edge_materials")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "再集計する" })).toBeInTheDocument();
  });

  it("すべて最新なら、作り直しを促さずその旨だけを出す", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("すべて最新")).toBeInTheDocument();
    // 打つべきコマンドが無いときに出すと、何もしなくてよい状態が読み取れない。
    expect(screen.queryByRole("button", { name: "コピー" })).not.toBeInTheDocument();
  });

  it("確定して値が無い列だけなら、作り直し待ちにしない", async () => {
    // average_gradeのNULL（橋・トンネル）で鳴ると、直しようのない件数を毎回見ることになる。
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("すべて最新")).toBeInTheDocument();
    const details = screen.getByText("edge_materials").closest("details") as HTMLElement;
    expect(within(details).getByText("値なし 500件（確定）")).toBeInTheDocument();
  });

  it("行そのものが無いときも作り直し待ちにする", async () => {
    // 鮮度（世代）でも完成度（NULL）でも表に出ない。行が無ければ古くもなければNULLでもない。
    vi.mocked(getDerivedDataFreshness).mockResolvedValue({
      ...FRESH_REPORT,
      tables: [table({ missing_rows: 37, coverage_parent_row_count: 5037 })],
    });
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("1件が作り直し待ち")).toBeInTheDocument();
    const details = screen.getByText("edge_materials").closest("details") as HTMLElement;
    expect(within(details).getByText("37件ぶん行が無い（母数 5,037）")).toBeInTheDocument();
  });

  it("覆うことを宣言していない表は、母数の行を出さない", async () => {
    // node_materialsは形状頂点の行を持たない。母数を出すと欠けがあるように読める。
    vi.mocked(getDerivedDataFreshness).mockResolvedValue({
      ...FRESH_REPORT,
      tables: [
        table({
          table_name: "node_materials",
          coverage_parent: null,
          coverage_parent_row_count: null,
          missing_rows: null,
        }),
      ],
    });
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("すべて最新")).toBeInTheDocument();
    const details = screen.getByText("node_materials").closest("details") as HTMLElement;
    expect(within(details).queryByText(/を覆う/)).not.toBeInTheDocument();
  });

  it("作り直しが要る件数と、次に打つ1コマンドを出す", async () => {
    // 古い世代と未計算の両方を数える。読み手が次に打つのはどちらでも同じ1コマンドなので、
    // 行ごとにバッチ名を散らさない。
    vi.mocked(getDerivedDataFreshness).mockResolvedValue({
      ...FRESH_REPORT,
      tables: [
        table({ is_stale: true, oldest_run_id: 9 }),
        table({
          table_name: "way_materials",
          columns: [{ column: "divided", null_count: 12, is_incomplete: true }],
        }),
        FRESH_REPORT.tables[2],
      ],
    });
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("2件が作り直し待ち")).toBeInTheDocument();
    // 改行を含むので既定の空白正規化では一致しない。要素のtextContentと丸ごと比べる。
    expect(screen.getByText((_, element) => element?.textContent === REBUILD_COMMAND)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "コピー" })).toBeInTheDocument();
  });

  // 出すコマンドは本番へ効かせる形でなければならない。稼働中コンテナの中で走らせる形
  // （`docker exec`）や、打つ場所の分からない素のモジュール名へ戻すと、手元の開発DBを
  // 作り直して本番が古いまま残るか、本番のサービスごと止まる。
  it("作り直しのコマンドは、本番で安全に実行できる形になっている", () => {
    expect(REBUILD_COMMAND).toContain("docker run --rm");
    expect(REBUILD_COMMAND).toContain("--memory=");
    expect(REBUILD_COMMAND).not.toContain("docker exec");
  });

  it("一覧は1件1行で、run番号などの数字は開くまで出さない", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    // 名前は最初から見える（何が検査対象かが分かる）。
    expect(screen.getByText("edge_materials")).toBeInTheDocument();
    // 中身（比較対象の行）は畳んだ先にある。
    const summary = screen.getByText("edge_materials").closest("summary");
    expect(summary).not.toBeNull();
    const details = summary?.closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(within(details).getByText(/#10/)).toBeInTheDocument();
  });

  it("一覧はbackendが返した表ぶん並ぶ（表が増えてもフロントは追従する）", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    for (const entry of FRESH_REPORT.tables) {
      expect(screen.getByText(entry.table_name)).toBeInTheDocument();
    }
  });

  it("取得失敗時はエラーメッセージを表示する", async () => {
    vi.mocked(getDerivedDataFreshness).mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("集計失敗: boom")).toBeInTheDocument();
  });
});
