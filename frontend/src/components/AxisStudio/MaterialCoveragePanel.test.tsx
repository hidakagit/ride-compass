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

function rowsOf(table: HTMLElement): HTMLElement[] {
  return within(table).getAllByRole("row").slice(1); // ヘッダ行を除く
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
    expect(screen.getByRole("button", { name: "再集計する" })).toBeInTheDocument();
  });

  it("欠損時の扱いでグループ分けし、各グループ内は欠損割合の高い順に割合・件数つきで表示する", async () => {
    vi.mocked(getMaterialCoverage).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<MaterialCoveragePanel />);

    await clickAggregate(user);

    const unknownGroup = screen.getByRole("region", { name: "評価に影響する欠損" });
    const unknownRows = rowsOf(within(unknownGroup).getByRole("table"));
    expect(unknownRows.map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual([
      "勾配%（符号付き） - gradient_percent",
      "路面種別 - surface",
      "道路種別 - highway",
    ]);

    const surfaceCells = within(unknownRows[1]).getAllByRole("cell");
    expect(surfaceCells[0]).toHaveAttribute("title", "osm_raw_ways.surface");
    expect(surfaceCells[1].textContent).toBe("Way");
    expect(surfaceCells[2].textContent).toContain("85.0%");
    expect(surfaceCells[3].textContent).toBe("850 / 1,000");

    const gradientCells = within(unknownRows[0]).getAllByRole("cell").map((cell) => cell.textContent);
    expect(gradientCells[1]).toBe("Edge");
    expect(gradientCells[2]).toContain("88.4%");
    expect(gradientCells[3]).toBe("3,536 / 4,000");

    const definiteGroup = screen.getByRole("region", { name: "タグ不在を確定値として評価する材料（参考）" });
    const definiteRows = rowsOf(within(definiteGroup).getByRole("table"));
    expect(definiteRows.map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual([
      "トンネル - has_tunnel",
    ]);
    expect(definiteRows[0]).toHaveAttribute("data-missing-semantics", "definite");

    expect(screen.getByText(/Way 1,000件/)).toBeInTheDocument();
    expect(screen.getByText(/Edge 4,000件/)).toBeInTheDocument();
  });

  it("説明文は見出し脇の(i)ポップオーバーに畳み、常時は表示しない", async () => {
    vi.mocked(getMaterialCoverage).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<MaterialCoveragePanel />);

    expect(screen.queryByText(/距離加重ではない/)).not.toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "欠損割合の見方" }));
    });

    expect(screen.getByText(/距離加重ではない/)).toBeInTheDocument();
  });

  it("集計対象外の材料は表には出さず、理由つきの折りたたみ一覧に出す", async () => {
    vi.mocked(getMaterialCoverage).mockResolvedValue(REPORT);
    const user = userEvent.setup();
    render(<MaterialCoveragePanel />);

    await clickAggregate(user);

    for (const table of screen.getAllByRole("table")) {
      expect(within(table).queryByText(/wind_penalty/)).not.toBeInTheDocument();
    }
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
