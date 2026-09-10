import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AxisStudio from "./AxisStudio";
import { baseAxisDefinition } from "@/testing/axisDefinitionFixtures";

vi.mock("@/services/axisAdminApi", () => ({
  listAxisDefinitions: vi.fn(),
  createAxisDefinition: vi.fn(),
  updateAxisDefinition: vi.fn(),
  deleteAxisDefinition: vi.fn(),
  unpublishAxisDefinition: vi.fn(),
}));
vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));
vi.mock("@/services/axisPreviewApi", () => ({
  fetchAxisValueDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  fetchMaterialDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

import { listAxisDefinitions, unpublishAxisDefinition } from "@/services/axisAdminApi";

function published() {
  return { ...baseAxisDefinition(), axis_id: "stop_density", label: "停止密度", is_published: true };
}

describe("公開済み軸の「調整する」", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listAxisDefinitions).mockResolvedValue([published()]);
    vi.mocked(unpublishAxisDefinition).mockResolvedValue(undefined as never);
  });

  it("一度下書きへ戻してから編集画面を開く（材料・計算式を変えるための正規の手順）", async () => {
    const user = userEvent.setup();
    render(<AxisStudio />);
    await user.click(await screen.findByRole("tab", { name: /公開済み/ }));

    // 下書きへ戻った状態を返すようにしてから押す（実際のreloadと同じ順序）。
    vi.mocked(listAxisDefinitions).mockResolvedValue([{ ...published(), is_published: false }]);
    await user.click(await screen.findByRole("button", { name: "調整する" }));

    await waitFor(() => expect(unpublishAxisDefinition).toHaveBeenCalledWith("stop_density"));
    // 編集画面（モーダル）が開く
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("編集を中断したら、下書きのまま残ったことを必ず知らせる", async () => {
    const user = userEvent.setup();
    render(<AxisStudio />);
    await user.click(await screen.findByRole("tab", { name: /公開済み/ }));
    vi.mocked(listAxisDefinitions).mockResolvedValue([{ ...published(), is_published: false }]);
    await user.click(await screen.findByRole("button", { name: "調整する" }));
    await screen.findByRole("dialog");

    await user.keyboard("{Escape}");

    expect(await screen.findByText(/一般ユーザーには表示されません/)).toBeInTheDocument();
  });
});
