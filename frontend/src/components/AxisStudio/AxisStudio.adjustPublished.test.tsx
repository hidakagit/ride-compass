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
vi.mock("@/services/materialCatalogApi", async () => {
  const { materialCatalogFixture } = await import("@/testing/materialCatalogFixture");
  return {
    getMaterialCatalog: vi.fn().mockResolvedValue(materialCatalogFixture()),
    getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  };
});
vi.mock("@/services/axisPreviewApi", () => ({
  fetchAxisValueDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  fetchMaterialDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

import { listAxisDefinitions, unpublishAxisDefinition, updateAxisDefinition } from "@/services/axisAdminApi";

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
  it("調整して保存すると公開へ戻し、「下書きのまま残った」とは知らせない", async () => {
    const user = userEvent.setup();
    vi.mocked(updateAxisDefinition).mockResolvedValue(undefined as never);
    render(<AxisStudio />);
    await user.click(await screen.findByRole("tab", { name: /公開済み/ }));
    vi.mocked(listAxisDefinitions).mockResolvedValue([{ ...published(), is_published: false }]);
    await user.click(await screen.findByRole("button", { name: "調整する" }));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "更新する" }));

    // 保存は公開へ戻す（unpublish→更新→再公開をボタン1つに畳んだ手順の後半）。
    await waitFor(() =>
      expect(updateAxisDefinition).toHaveBeenCalledWith(
        "stop_density",
        expect.objectContaining({ is_published: true }),
      ),
    );
    // 成功した直後に中断の通知を出さない。setRepublishAxisId(null)の直後に
    // closeComposerを呼ぶと、そのレンダーのクロージャは古い値のままで必ず出てしまう。
    expect(screen.queryByText(/一般ユーザーには表示されません/)).not.toBeInTheDocument();
  });

  it("調整中は「公開する」を操作させず、保存が公開へ戻すことだけを示す", async () => {
    const user = userEvent.setup();
    render(<AxisStudio />);
    await user.click(await screen.findByRole("tab", { name: /公開済み/ }));
    vi.mocked(listAxisDefinitions).mockResolvedValue([{ ...published(), is_published: false }]);
    await user.click(await screen.findByRole("button", { name: "調整する" }));
    await screen.findByRole("dialog");

    // 操作できるチェックボックスを出すと、外して保存しても公開へ戻り操作結果が無言で反転する。
    expect(screen.queryByLabelText("公開する")).not.toBeInTheDocument();
    expect(screen.getByText(/保存すると公開へ戻ります/)).toBeInTheDocument();
  });
});
