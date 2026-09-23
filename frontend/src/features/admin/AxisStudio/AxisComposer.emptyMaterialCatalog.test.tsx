// 材料が1件も無いとき、軸コンポーザーが落ちずに空状態を出すこと。
// このファイルだけ材料カタログを0件で解決させるため、他の AxisComposer のテストとは
// ファイルを分けてある（モックはファイル単位でしか切り替えられない）。
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AxisComposer from "./AxisComposer";
import { baseAxisDefinition } from "@/testing/axisDefinitionFixtures";

// 分布プレビューの2フック（useAxisValueDistribution/useMaterialDistribution）は
// マウント直後にフェッチする。モックしないとテストが実HTTPを発火する
// （このファイル冒頭が掲げる「実HTTPは呼ばない」方針どおり、ここで塞ぐ）。
vi.mock("@/features/admin/axisPreviewApi", () => ({
  fetchAxisValueDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  fetchMaterialDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockResolvedValue({ materials: [] }),
  getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

describe("AxisComposer 材料カタログが0件のとき", () => {
  it("新規作成モードでは、落ちずに空状態のメッセージを出す", async () => {
    render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText(/材料カタログを取得できませんでした/)).toBeInTheDocument();
    });
    expect(screen.queryByRole("textbox", { name: "表示名" })).not.toBeInTheDocument();
  });

  it("編集モードでも、初期化で落ちない", async () => {
    const editing = baseAxisDefinition();
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
