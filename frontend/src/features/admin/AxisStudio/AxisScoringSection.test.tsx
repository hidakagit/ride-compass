/**
 * `AxisScoringSection.tsx`——点数のつけ方の入力欄。
 *
 * ここで見るのは**下書きがどう変わるか・何が読めるか**だけ。下書きをpayloadへ変える
 * 変換は`axisDraft.ts`（`axisDraft.test.ts`）、折れ点の編集は`BreakpointCurveEditor`と
 * `breakpointTools.ts`が持つ。
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { AxisScoringSection } from "./AxisScoringSection";
import { emptyDraft, type Draft } from "./axisDraft";
import { materialCatalogFixture } from "@/testing/materialCatalogFixture";
import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";

vi.mock("@/features/admin/axisPreviewApi", () => ({
  fetchAxisValueDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  fetchMaterialDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

const MATERIALS: readonly AxisMaterialOption[] = materialCatalogFixture().materials.map((m) => ({
  id: m.material_id,
  label: m.label,
  name: m.name,
  description: m.description,
  dtype: m.dtype,
  unit: m.unit,
  referencePoints: m.reference_points,
}));

function openSection() {
  const latest: { draft: Draft } = { draft: emptyDraft(MATERIALS) };

  function Harness() {
    const [draft, setDraft] = useState<Draft>(latest.draft);
    latest.draft = draft;
    return <AxisScoringSection draft={draft} setDraft={setDraft} materialOptions={MATERIALS} axisTermOptions={[]} />;
  }

  render(<Harness />);
  return { user: userEvent.setup(), latest };
}

describe("材料の説明アイコン", () => {
  it("選んでいる材料の説明を出す", async () => {
    const { user } = openSection();

    await user.click(screen.getByRole("button", { name: "数値の材料 - num_aの説明を表示" }));

    expect(screen.getByText("テスト用の数値材料。")).toBeInTheDocument();
  });

  it("材料を選び直すと、説明もその材料のものへ変わる", async () => {
    const { user } = openSection();

    await user.selectOptions(screen.getAllByRole("combobox")[0], "bool_a");
    await user.click(screen.getByRole("button", { name: "真偽の材料 - bool_aの説明を表示" }));

    expect(screen.getByText("テスト用の真偽材料。")).toBeInTheDocument();
  });

  it("「必須」の隣に、欠損したときどうなるかの説明がある", async () => {
    const { user } = openSection();

    await user.click(screen.getByRole("button", { name: "「必須」の説明を表示" }));

    expect(screen.getByText(/軸全体を「評価不能」として扱います/)).toBeInTheDocument();
  });
});
