// 下書きは`useState`の初期化で一度作られるが、そのとき材料カタログはまだ空である。
// **カタログが届いたら作り直さないと**、材料として引けない項目が軸参照とみなされ、
// 編集画面が「組み合わせる軸」の側で開く（axisDraft.ts: draftFromExisting）。
//
// このファイルだけカタログの中身を固定したいためファイルを分けてある。
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AxisComposer from "./AxisComposer";
import { baseAxisDefinition } from "@/testing/axisDefinitionFixtures";

vi.mock("@/services/axisPreviewApi", () => ({
  fetchAxisValueDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  fetchMaterialDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

const RUNTIME_ONLY_MATERIAL = "zzz_runtime_only_material";

vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockResolvedValue({
    materials: [
      {
        material_id: "zzz_runtime_only_material",
        label: "実行時にだけある材料",
        description: "",
        dtype: "numeric",
        unit: "",
        reference_points: null,
      },
    ],
  }),
  getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

describe("AxisComposer 実行時の材料カタログ", () => {
  it("既存軸の編集で、実行時にだけある材料が「材料」として解決される", async () => {
    const definition = {
      ...baseAxisDefinition(),
      shape: {
        kind: "breakpoint_linear" as const,
        terms: [{ material: RUNTIME_ONLY_MATERIAL, weight: 1, required: true }],
        preprocess: "identity" as const,
        breakpoints: [
          [0, 0],
          [10, 100],
        ] as [number, number][],
      },
    };

    render(
      <AxisComposer editing={definition} duplicateFrom={null} otherAxes={[]} onCancelEdit={vi.fn()} onSave={vi.fn()} />,
    );

    // 取得が解決したら、材料として解決し直した状態で開く。
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "表示名" })).toBeInTheDocument();
    });
    expect(screen.queryByText("組み合わせる軸")).not.toBeInTheDocument();
  });
});
