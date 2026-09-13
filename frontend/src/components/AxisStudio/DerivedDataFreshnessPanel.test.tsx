import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { DerivedDataFreshnessResponse, GenerationFreshnessEntry } from "@/types/route";
import DerivedDataFreshnessPanel from "./DerivedDataFreshnessPanel";
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

  it("鮮度不整合が無ければ「鮮度OK」を、比較対象・algorithm_versionともに表示する", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getAllByText("鮮度OK").length).toBeGreaterThan(0);
    expect(screen.queryByText("鮮度不整合あり")).not.toBeInTheDocument();
    expect(screen.getAllByText("事故取込").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/precompute_edge_attribute_counts\.ALGORITHM_VERSION/).length).toBeGreaterThan(0);
  });

  it("鮮度不整合があれば「鮮度不整合あり」バッジを出す", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue({
      ...FRESH_REPORT,
      generations: [
        generation({
          is_stale: true,
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
              latest_available_run_id: 12,
              earliest_reflected_run_id: 10,
              null_count: 0,
              is_stale: true,
            },
          ],
        }),
        ...FRESH_REPORT.generations.slice(1),
      ],
    });
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getAllByText("鮮度不整合あり").length).toBeGreaterThan(0);
  });

  it("designation_attributesはalgorithm_versionを表示しない", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    const designationHeading = screen.getByText("designation_attributes");
    const block = designationHeading.closest("div")?.parentElement;
    expect(block).not.toBeNull();
    expect(within(block as HTMLElement).queryByText(/ALGORITHM_VERSION/)).not.toBeInTheDocument();
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
    expect(screen.getAllByText("完成度（鮮度ではない）")).toHaveLength(FRESH_REPORT.completeness.length);
    expect(screen.getByText(/5,025,067件/)).toBeInTheDocument();
    expect(screen.getByText(/328件/)).toBeInTheDocument();
  });

  it("未計算が残っていれば印と再実行するバッチ名を出し、無ければ出さない", async () => {
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("未計算あり")).toBeInTheDocument();
    expect(screen.getByText(/precompute_elevation_attributes を実行する/)).toBeInTheDocument();
    expect(screen.getByText("計算済み")).toBeInTheDocument();
    expect(screen.queryByText(/precompute_road_node_degrees を実行する/)).not.toBeInTheDocument();
  });

  it("未計算を厳密に表せない列の但し書きを、その枠へ添える", async () => {
    // road_nodes.degreeはNOT NULL DEFAULT 0で、未計算と本当に次数0の行を区別できない。
    // 0件でも「正常」と言い切れないことが読み手に伝わらないと、判断を誤る。
    vi.mocked(getDerivedDataFreshness).mockResolvedValue(FRESH_REPORT);
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText(/未計算と本当に次数0の行を区別できない/)).toBeInTheDocument();
  });

  it("取得失敗時はエラーメッセージを表示する", async () => {
    vi.mocked(getDerivedDataFreshness).mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<DerivedDataFreshnessPanel />);

    await clickAggregate(user);

    expect(screen.getByText("集計失敗: boom")).toBeInTheDocument();
  });
});
