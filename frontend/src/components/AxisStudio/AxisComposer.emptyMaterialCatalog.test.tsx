// T424回帰テスト（docs/tasks/T424.md、2026-08-30起票のP0バグ修正）: emptyDraft()・
// draftFromExisting()が`materialOptions[0].id`を無条件参照しており、materialOptionsが
// 空配列のときマウント直後にTypeErrorでクラッシュしていた。useMaterialCatalog()は
// 2026-08-25の修正で「取得成功したがmaterialsが0件」の場合、静的フォールバック
// （AXIS_MATERIAL_OPTIONS）へは戻さず空配列をそのままsetMaterialsする仕様（
// useMaterialCatalog.test.tsの「取得成功したがmaterialsが0件のレスポンスは、静的
// フォールバックへ戻さずそのまま空を返す」参照）のため、backend側material_catalog.pyが
// 運用上の何らかの理由で0件を返すと即座に発生しうる。
//
// AxisComposer.test.tsx/AxisComposer.materialValues.test.tsxと同じ方針でファイルを分け、
// このファイルだけgetMaterialCatalogを「成功だが0件」で解決させる
// （AxisComposer.test.tsxは全体を通じて失敗させる方針のため、0件成功のケースは
// 混ぜずここへ分離する）。
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AxisDefinitionResponse } from "@/types/route";
import AxisComposer from "./AxisComposer";

vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockResolvedValue({ materials: [] }),
  getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

function baseDefinition(overrides: Partial<AxisDefinitionResponse> = {}): AxisDefinitionResponse {
  return {
    axis_id: "gradient",
    label: "勾配",
    description: "",
    category: "観測",
    default_weight: 0.2,
    is_published: false,
    priority_overrides: [],
    show_map_icon: true,
    time_scope: "always",
    supports_route_coloring: false,
    shape: {
      kind: "breakpoint_linear",
      terms: [{ material: "gradient_percent", weight: 1.0, required: true }],
      preprocess: "identity",
      breakpoints: [
        [0, 0],
        [10, 100],
      ],
    },
    display: { kind: "none", label: "勾配", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
    ...overrides,
  };
}

describe("AxisComposer 材料カタログ0件時のフォールバック(T424)", () => {
  it("新規作成モードで材料カタログが0件でも、マウント直後にクラッシュせず空状態のエラーメッセージへフォールバックする", async () => {
    render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

    // マウント直後は取得完了前のためAXIS_MATERIAL_OPTIONS静的フォールバックで
    // 通常のウィザード（「表示名(label)」欄）が見えている。
    expect(screen.getByRole("textbox", { name: "表示名(label)" })).toBeInTheDocument();

    // getMaterialCatalogが解決し材料0件がsetMaterialsされると、通常のウィザードUIから
    // 空状態のエラーメッセージへ切り替わる（クラッシュしない）。
    await waitFor(() => {
      expect(screen.getByText(/材料カタログを取得できませんでした/)).toBeInTheDocument();
    });
    expect(screen.queryByRole("textbox", { name: "表示名(label)" })).not.toBeInTheDocument();
  });

  it("編集モードで材料カタログが0件でも、draftFromExisting()の初期化でクラッシュしない", async () => {
    const editing = baseDefinition();
    render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/材料カタログを取得できませんでした/)).toBeInTheDocument();
    });
  });

  it("空状態の「閉じる」ボタンを押すとonCancelEditが呼ばれる", async () => {
    const onCancelEdit = vi.fn();
    render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={onCancelEdit} onSave={vi.fn()} />);

    const closeButton = await screen.findByRole("button", { name: "閉じる" });
    closeButton.click();

    expect(onCancelEdit).toHaveBeenCalledTimes(1);
  });
});
