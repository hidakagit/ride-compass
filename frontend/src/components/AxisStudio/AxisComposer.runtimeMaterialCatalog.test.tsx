// T947（統合レビュー第11回・指摘26）: 材料カタログは実行時フェッチで後から入れ替わるのに、
// 下書きは`useState`の初期化でビルド時フォールバックの材料に固定されていた。backendを
// デプロイしてからfrontendをデプロイするまでの窓では、**新しい材料を使う軸の編集画面が
// 「組み合わせる軸」の画面として開く**（材料として引けないため軸参照へ倒れる）。
//
// 他の`AxisComposer.*.test.tsx`と同じ方針でファイルを分け、このファイルだけ
// getMaterialCatalogを「ビルド時フォールバックには無い材料」で解決させる。
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
    // この軸の材料はビルド時フォールバックに無い。下書きが取得完了前の材料一覧で
    // 固定されたままだと`isAxisReference`が真になり、画面は「組み合わせる軸」の側で
    // 開く（axisDraft.ts: draftFromExisting）。
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

    // 取得完了前は材料として引けず、「組み合わせる軸」として開いている。
    expect(screen.getByText("組み合わせる軸")).toBeInTheDocument();

    // 取得が解決したら材料として解決し直す。
    await waitFor(() => {
      expect(screen.queryByText("組み合わせる軸")).not.toBeInTheDocument();
    });
  });
});
