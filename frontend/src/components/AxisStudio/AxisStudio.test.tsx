import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AxisDefinitionResponse } from "@/types/route";
import { setAdminCredentials } from "@/lib/adminToken";
import AxisStudio from "./AxisStudio";

// 改善計画T304: 「編集ボタンを押した後にそのまま編集画面がポップアップ起動してほしい。
// 下部エリアの編集エリアまで目が行かない」という実機フィードバックへの対応の回帰テスト。
// 一覧・作成・更新・削除はbackendの管理APIへ実際に飛ぶため、ここではaxisAdminApi.ts全体を
// モックする（RouteSettingsPanel.test.tsxと同じ方針、実HTTPは呼ばない）。
vi.mock("@/services/axisAdminApi", () => ({
  listAxisDefinitions: vi.fn(),
  createAxisDefinition: vi.fn(),
  updateAxisDefinition: vi.fn(),
  deleteAxisDefinition: vi.fn(),
  unpublishAxisDefinition: vi.fn(),
}));
// AxisComposerが使うuseMaterialCatalogの取得先。フォールバック（静的9材料）で十分なため
// 失敗させておく。
vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

import { listAxisDefinitions } from "@/services/axisAdminApi";

function definition(overrides: Partial<AxisDefinitionResponse> = {}): AxisDefinitionResponse {
  return {
    axis_id: "gradient",
    label: "勾配",
    description: "",
    category: "観測",
    default_weight: 0.2,
    is_published: false,
    priority_overrides: [],
    shape: {
      kind: "breakpoint_linear",
      terms: [{ material: "gradient_percent", weight: 1.0, required: true }],
      preprocess: "identity",
      breakpoints: [
        [0, 0],
        [10, 100],
      ],
    },
    ...overrides,
  };
}

describe("AxisStudio", () => {
  beforeEach(() => {
    setAdminCredentials({ username: "admin", password: "secret" });
  });

  it("「編集」を押すとその軸の内容で編集モーダルが即座に開く", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "編集" }));

    expect(screen.getByRole("dialog", { name: "軸を編集: gradient" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "axis_id" })).toHaveValue("gradient");
  });

  it("「+ 新しい軸を作る」を押すと空のモーダルが開く", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition(), definition({ axis_id: "surface_q", label: "舗装状況" })]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "+ 新しい軸を作る" }));

    expect(screen.getByRole("dialog", { name: "新しい軸を作る" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "axis_id" })).toHaveValue("");
  });

  it("モーダルを閉じるとダイアログが消え、一覧はそのまま残る", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([definition()]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "編集" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "閉じる" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("勾配")).toBeInTheDocument();
  });

  it("公開済み軸には「非公開に戻す」ボタンが表示され、下書き軸には表示されない", async () => {
    vi.mocked(listAxisDefinitions).mockResolvedValue([
      definition({ axis_id: "gradient", is_published: true }),
      definition({ axis_id: "draft_axis", label: "下書き軸", is_published: false }),
    ]);
    render(<AxisStudio />);

    await waitFor(() => expect(screen.getByText("勾配")).toBeInTheDocument());

    expect(screen.getAllByRole("button", { name: "非公開に戻す" })).toHaveLength(1);
  });
});
