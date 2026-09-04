import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { MaterialCoverageEntry, MaterialCoverageResponse } from "@/types/route";
import MaterialCoveragePanel, { sortByMissingRatioDesc } from "./MaterialCoveragePanel";
import { getMaterialCoverage } from "@/services/materialCoverageApi";

vi.mock("@/services/materialCoverageApi", () => ({
  getMaterialCoverage: vi.fn(),
}));

function entry(overrides: Partial<MaterialCoverageEntry>): MaterialCoverageEntry {
  return {
    material_id: "surface",
    label: "路面種別 - surface",
    dtype: "categorical",
    population: "way",
    total: 1000,
    missing: 850,
    missing_ratio: 0.85,
    source: "osm_raw_ways.surface",
    missing_semantics: "unknown",
    excluded_reason: null,
    ...overrides,
  };
}

const REPORT: MaterialCoverageResponse = {
  computed_at: "2026-09-04T12:00:00+00:00",
  way_total: 1000,
  edge_total: 4000,
  materials: [
    entry({ material_id: "highway", label: "道路種別 - highway", missing: 0, missing_ratio: 0 }),
    entry({}),
    entry({
      material_id: "gradient_percent",
      label: "勾配%（符号付き） - gradient_percent",
      dtype: "numeric",
      population: "edge",
      total: 4000,
      missing: 3536,
      missing_ratio: 0.884,
      source: "elevation_attributes.average_grade の有無",
    }),
    entry({
      material_id: "has_tunnel",
      label: "トンネル - has_tunnel",
      dtype: "boolean",
      missing: 990,
      missing_ratio: 0.99,
      missing_semantics: "definite",
    }),
    entry({
      material_id: "wind_penalty",
      label: "向かい風ペナルティ - wind_penalty",
      dtype: "numeric",
      population: null,
      total: null,
      missing: null,
      missing_ratio: null,
      source: "",
      missing_semantics: null,
      excluded_reason: "動的材料でDBに静的な値を持たない",
    }),
  ],
};

async function clickAggregate(user: ReturnType<typeof userEvent.setup>) {
  await act(async () => {
    await user.click(screen.getByRole("button", { name: "集計する" }));
  });
}

describe("MaterialCoveragePanel", () => {
  it("開いた直後は集計せず、ボタン押下で初めてgetMaterialCoverageを呼ぶ", async () => {
    vi.mocked(getMaterialCoverage).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<MaterialCoveragePanel />);

    expect(getMaterialCoverage).not.toHaveBeenCalled();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    await clickAggregate(user);

    expect(getMaterialCoverage).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "再集計する" })).toBeInTheDocument();
  });

  it("集計対象の材料を欠損割合の高い順に、割合・件数・欠損時の扱い・根拠つきで表示する", async () => {
    vi.mocked(getMaterialCoverage).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<MaterialCoveragePanel />);

    await clickAggregate(user);

    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1); // ヘッダ行を除く
    expect(rows.map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual([
      "トンネル - has_tunnel",
      "勾配%（符号付き） - gradient_percent",
      "路面種別 - surface",
      "道路種別 - highway",
    ]);

    const surfaceRow = rows[2];
    const cells = within(surfaceRow).getAllByRole("cell").map((cell) => cell.textContent);
    expect(cells[1]).toBe("Way");
    expect(cells[2]).toBe("1,000");
    expect(cells[3]).toBe("850");
    expect(cells[4]).toContain("85.0%");
    expect(cells[5]).toBe("不明（軸は評価対象外）");
    expect(cells[6]).toBe("osm_raw_ways.surface");

    const gradientCells = within(rows[1]).getAllByRole("cell").map((cell) => cell.textContent);
    expect(gradientCells[1]).toBe("Edge");
    expect(gradientCells[2]).toBe("4,000");
    expect(gradientCells[4]).toContain("88.4%");

    const tunnelCells = within(rows[0]).getAllByRole("cell").map((cell) => cell.textContent);
    expect(tunnelCells[5]).toBe("確定値として評価");
    expect(rows[0]).toHaveAttribute("data-missing-semantics", "definite");

    expect(screen.getByText(/Way 1,000件/)).toBeInTheDocument();
    expect(screen.getByText(/Edge 4,000件/)).toBeInTheDocument();
  });

  it("集計対象外の材料は表には出さず、理由つきの折りたたみ一覧に出す", async () => {
    vi.mocked(getMaterialCoverage).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<MaterialCoveragePanel />);

    await clickAggregate(user);

    expect(within(screen.getByRole("table")).queryByText(/wind_penalty/)).not.toBeInTheDocument();
    expect(screen.getByText("集計対象外の材料（1件）")).toBeInTheDocument();
    expect(screen.getByText(/動的材料でDBに静的な値を持たない/)).toBeInTheDocument();
  });

  it("取得失敗時はエラーメッセージを表示する", async () => {
    vi.mocked(getMaterialCoverage).mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    render(<MaterialCoveragePanel />);

    await clickAggregate(user);

    expect(screen.getByText("集計失敗: boom")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("sortByMissingRatioDesc", () => {
  it("欠損割合の降順に並べ、nullは末尾へ送る", () => {
    const sorted = sortByMissingRatioDesc([
      entry({ material_id: "a", missing_ratio: 0.1 }),
      entry({ material_id: "b", missing_ratio: null }),
      entry({ material_id: "c", missing_ratio: 0.9 }),
    ]);

    expect(sorted.map((e) => e.material_id)).toEqual(["c", "a", "b"]);
  });
});
