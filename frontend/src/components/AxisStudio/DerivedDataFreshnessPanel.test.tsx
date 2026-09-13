import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DerivedDataFreshnessResponse, GenerationFreshnessEntry } from "@/types/route";
import DerivedDataFreshnessPanel, { REBUILD_COMMAND } from "./DerivedDataFreshnessPanel";
import { getDerivedDataFreshness } from "@/services/derivedDataFreshnessApi";

vi.mock("@/services/derivedDataFreshnessApi", () => ({
  getDerivedDataFreshness: vi.fn(),
}));

function generation(overrides: Partial<GenerationFreshnessEntry>): GenerationFreshnessEntry {
  return {
    table_name: "edge_attribute_counts",
    row_count: 5000,
    sources: [
      {
        label: "事故取込",
        run_table: "accident_import_runs",
        latest_available_run_id: 3,
        earliest_reflected_run_id: 3,
        null_count: 0,
        is_stale: false,
      },
      {
        label: "OSM取込",
        run_table: "osm_import_runs",
        latest_available_run_id: 10,
        earliest_reflected_run_id: 10,
        null_count: 0,
        is_stale: false,
      },
    ],
    algorithm_version: {
      owner: "precompute_edge_attribute_counts.ALGORITHM_VERSION",
      current_version: "v1",
      oldest_version: "v1",
      null_count: 0,
      is_stale: false,
    },
    is_stale: false,
    ...overrides,
  };
}

const FRESH_REPORT: DerivedDataFreshnessResponse = {
  computed_at: "2026-09-04T12:00:00+00:00",
  generations: [
    generation({}),
    generation({ table_name: "way_attribute_counts" }),
    generation({
      table_name: "designation_attributes",
      sources: [
        {
          label: "OSM取込",
          run_table: "osm_import_runs",
          latest_available_run_id: 10,
          earliest_reflected_run_id: 10,
          null_count: 0,
          is_stale: false,
        },
      ],
      algorithm_version: null,
    }),
  ],
  completeness: [
    {
      label: "elevation_attributes",
      population: 5025067,
      uncalculated_count: 328,
      owner: "precompute_elevation_attributes",
      note: "",
      is_incomplete: true,
    },
    {
      label: "road_nodes.degree",
      population: 3000000,
      uncalculated_count: 0,
      owner: "precompute_road_node_degrees",
      note: "この列はNOT NULL DEFAULT 0のため、未計算と本当に次数0の行を区別できない",
      is_incomplete: false,
    },
  ],
};

/** すべて最新の状態（完成度の未計算も0）。 */
const ALL_FRESH_REPORT = {
  ...FRESH_REPORT,
  completeness: FRESH_REPORT.completeness.map((entry) => ({
    ...entry,
    uncalculated_count: 0,
    is_incomplete: false,
  })),
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
    expect(screen.queryByText("edge_attribute_counts")).not.toBeInTheDocument();

    await clickAggregate(user);

    expect(getDerivedDataFreshness).toHaveBeenCalledTimes(1);
    expect(screen.getByText("edge_attribute_counts")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "再集計する" })).toBeInTheDocument();
  });

  it("すべて最新なら、作り直しを促さずその旨だけを出す", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(ALL_FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("すべて最新")).toBeInTheDocument();
    // 打つべきコマンドが無いときに出すと、何もしなくてよい状態が読み取れない。
    expect(screen.queryByRole("button", { name: "コピー" })).not.toBeInTheDocument();
  });

  it("作り直しが要る件数と、次に打つ1コマンドを出す", async () => {
    // 件数は行の状態から数える（古い世代・未計算の両方が対象）。読み手が次に打つのは
    // どちらでも同じ1コマンドなので、行ごとにバッチ名を散らさない。
    vi.mocked(getDerivedDataFreshness).mockResolvedValue({
      ...FRESH_REPORT,
      generations: [generation({ is_stale: true }), ...FRESH_REPORT.generations.slice(1)],
    });
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    // 世代1件（is_stale）＋完成度1件（elevationのis_incomplete）。
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
    expect(REBUILD_COMMAND).toContain("--skip-landcover");
    expect(REBUILD_COMMAND).not.toContain("docker exec");
  });

  it("一覧は1件1行で、run番号などの数字は開くまで出さない", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    // 名前は最初から見える（何が検査対象かが分かる）。
    expect(screen.getByText("edge_attribute_counts")).toBeInTheDocument();
    // 中身（比較対象の行）は畳んだ先にある。
    const summary = screen.getByText("edge_attribute_counts").closest("summary");
    expect(summary).not.toBeNull();
    const details = summary?.closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(within(details).getByText("事故取込")).toBeInTheDocument();
  });

  it("designation_attributesは版数を持たないため、その行に版数の項目が出ない", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    const details = screen.getByText("designation_attributes").closest("details") as HTMLElement;
    expect(within(details).queryByText("版数")).not.toBeInTheDocument();
    expect(within(details).getByText("OSM取込")).toBeInTheDocument();
  });

  it("系譜列を持たない派生データは完成度として別枠に、backendが返した件数ぶん並べる", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    // 対象はbackendの宣言が決めるため、軸・テーブルが増えてもフロントは追従する。
    for (const entry of FRESH_REPORT.completeness) {
      expect(screen.getByText(entry.label)).toBeInTheDocument();
    }
    const details = screen.getByText("elevation_attributes").closest("details") as HTMLElement;
    expect(within(details).getByText("5,025,067件")).toBeInTheDocument();
    expect(within(details).getByText("328件")).toBeInTheDocument();
  });

  it("未計算の有無を行の見出しに出し、担当バッチは開いた先に置く", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("未計算 328")).toBeInTheDocument();
    expect(screen.getByText("未計算なし")).toBeInTheDocument();
    const details = screen.getByText("elevation_attributes").closest("details") as HTMLElement;
    expect(within(details).getByText("precompute_elevation_attributes")).toBeInTheDocument();
  });

  it("未計算を厳密に表せない列の但し書きを、その枠へ添える", async () => {
    // road_nodes.degreeはNOT NULL DEFAULT 0で、未計算と本当に次数0の行を区別できない。
    // 0件でも「正常」と言い切れないことが読み手に伝わらないと、判断を誤る。
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    const details = screen.getByText("road_nodes.degree").closest("details") as HTMLElement;
    expect(within(details).getByText(/未計算と本当に次数0の行を区別できない/)).toBeInTheDocument();
  });

  it("取得失敗時はエラーメッセージを表示する", async () => {
    vi.mocked(getDerivedDataFreshness).mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("集計失敗: boom")).toBeInTheDocument();
  });
});
