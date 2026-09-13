import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DbStatusPanel from "./DbStatusPanel";
import { getDbStatus } from "@/services/dbStatusApi";
import type { DbStatusResponse } from "@/types/route";

vi.mock("@/services/dbStatusApi", () => ({ getDbStatus: vi.fn() }));

const REPORT: DbStatusResponse = {
  computed_at: "2026-09-14T03:00:00Z",
  imports: [
    {
      label: "OSM取込",
      latest_id: 4,
      latest_status: "succeeded",
      latest_finished_at: "2026-09-02T04:50:00Z",
      latest_identity: { pbf_name: "kanto-latest.osm.pbf" },
      latest_item_count: 1329632,
      latest_succeeded_id: 4,
      latest_succeeded_finished_at: "2026-09-02T04:50:00Z",
      needs_attention: false,
      note: "",
    },
    {
      label: "事故取込",
      latest_id: 7,
      latest_status: "failed",
      latest_finished_at: "2026-09-10T01:00:00Z",
      latest_identity: { occurred_year: "2024" },
      latest_item_count: null,
      latest_succeeded_id: 6,
      latest_succeeded_finished_at: "2026-09-01T01:00:00Z",
      needs_attention: true,
      note: "最後の取込がfailedのまま。派生データの基準は成功した#6のままで、それ以降の取り込みは反映されていない",
    },
  ],
  tables: [
    {
      table_name: "road_edges",
      row_count: 5047354,
      total_bytes: 240123904,
      dead_tuples: 0,
      analyzed_at: "2026-09-02T04:51:00Z",
      vacuumed_at: "2026-09-02T04:51:00Z",
      needs_attention: false,
      note: "",
    },
    {
      table_name: "elevation_attributes",
      row_count: 135385,
      total_bytes: 27262976,
      dead_tuples: 79,
      analyzed_at: null,
      vacuumed_at: null,
      needs_attention: true,
      note: "統計を一度も取っていない（プランナの行数推定が実数から外れ、クエリが遅いプランを選びうる）",
    },
  ],
  connections: {
    total: 2,
    max_connections: 100,
    idle_in_transaction: 0,
    longest_idle_transaction_seconds: 0,
    longest_query_seconds: 0,
    needs_attention: false,
    note: "",
  },
  database_bytes: 707788800,
};

async function clickAggregate(user: ReturnType<typeof userEvent.setup>) {
  await act(async () => {
    await user.click(screen.getByRole("button", { name: "集計する" }));
  });
}

describe("DbStatusPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("開いた直後は集計せず、ボタン押下で初めて取得する", async () => {
    vi.mocked(getDbStatus).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<DbStatusPanel />);

    expect(getDbStatus).not.toHaveBeenCalled();
    await clickAggregate(user);
    expect(getDbStatus).toHaveBeenCalledTimes(1);
  });

  it("注意が要る件数を先頭に出し、取込・接続は1件1行で並べる", async () => {
    vi.mocked(getDbStatus).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<DbStatusPanel />);

    await clickAggregate(user);

    // 取込1件（事故取込のfailed）＋テーブル1件（統計なし）。
    expect(screen.getByText("2件に注意")).toBeInTheDocument();
    for (const entry of REPORT.imports) {
      expect(screen.getByText(entry.label)).toBeInTheDocument();
    }
    expect(screen.getByText("接続")).toBeInTheDocument();
  });

  it("テーブルは注意のあるものだけを行にし、残りは1行へ畳む", async () => {
    // 本番では20件超あり、全部並べると注意すべき行が埋もれる。
    vi.mocked(getDbStatus).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<DbStatusPanel />);

    await clickAggregate(user);

    // 注意のあるものは行（summary）として出る。
    expect(screen.getByText("elevation_attributes").closest("summary")).not.toBeNull();
    // 注意の無いものは行にならず、畳んだ先にだけある（隠して終わりにしない）。
    const roadEdges = screen.getByText("road_edges");
    expect(roadEdges.closest("summary")).toBeNull();
    const rest = screen.getByText("その他1テーブル").closest("details");
    expect(roadEdges.closest("details")).toBe(rest);
  });

  it("失敗した取込は、派生データが今どのrunを基準にしているかまで示す", async () => {
    // 「失敗した」だけでは、鮮度タブが「最新」と出している意味を読み違える。
    vi.mocked(getDbStatus).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<DbStatusPanel />);

    await clickAggregate(user);

    const details = screen.getByText("事故取込").closest("details") as HTMLElement;
    expect(within(details).getByText(/成功した#6のまま/)).toBeInTheDocument();
    // 「成功した最新」の行にも同じrunが出る（注意文だけに埋もれさせない）。
    expect(within(details).getByText(/^#6 ・/)).toBeInTheDocument();
  });

  it("数字は開くまで出さない（1件1行を保つ）", async () => {
    vi.mocked(getDbStatus).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<DbStatusPanel />);

    await clickAggregate(user);

    const details = screen.getByText("elevation_attributes").closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(within(details).getByText("135,385件（実数）")).toBeInTheDocument();
  });

  it("注意が無ければその旨だけを出す", async () => {
    vi.mocked(getDbStatus).mockResolvedValue({
      ...REPORT,
      imports: REPORT.imports.map((e) => ({ ...e, needs_attention: false, note: "" })),
      tables: REPORT.tables.map((e) => ({ ...e, needs_attention: false, note: "" })),
    });
    const user = userEvent.setup();
    render(<DbStatusPanel />);

    await clickAggregate(user);

    expect(screen.getByText("注意はなし")).toBeInTheDocument();
  });

  it("取得失敗時はエラーを表示する", async () => {
    vi.mocked(getDbStatus).mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<DbStatusPanel />);

    await clickAggregate(user);

    expect(screen.getByText(/集計失敗: boom/)).toBeInTheDocument();
  });
});
