/**
 * `AxisStudio.tsx`——軸の一覧と、編集・複製・削除・公開取り消しの取り回し。
 *
 * ここで見るのは**このコンポーネント自身が決めていること**だけ。フォームの中身は
 * `AxisComposer`（`AxisComposer.test.tsx`）、公開済み軸を一度下書きへ戻して編集する流れは
 * `AxisStudio.adjustPublished.test.tsx`が持つ。
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AxisStudio from "./AxisStudio";
import { baseAxisDefinition } from "@/testing/axisDefinitionFixtures";

vi.mock("@/services/axisAdminApi", () => ({
  listAxisDefinitions: vi.fn(),
  createAxisDefinition: vi.fn().mockResolvedValue(undefined),
  updateAxisDefinition: vi.fn().mockResolvedValue(undefined),
  deleteAxisDefinition: vi.fn().mockResolvedValue(undefined),
  unpublishAxisDefinition: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/services/axisPreviewApi", () => ({
  fetchAxisValueDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  fetchMaterialDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

vi.mock("@/services/materialCatalogApi", async () => {
  const { materialCatalogFixture } = await import("@/testing/materialCatalogFixture");
  return {
    getMaterialCatalog: vi.fn().mockResolvedValue(materialCatalogFixture()),
    getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  };
});

import {
  createAxisDefinition,
  deleteAxisDefinition,
  listAxisDefinitions,
  unpublishAxisDefinition,
} from "@/services/axisAdminApi";

/** 一覧に載せる軸を用意する。**各テストが、自分が目印にする表示名を自分で決める。** */
function listing(...defs: ReturnType<typeof baseAxisDefinition>[]) {
  vi.mocked(listAxisDefinitions).mockResolvedValue(defs);
}

beforeEach(() => {
  vi.clearAllMocks();
  // happy-domはResizeObserverを持たない。Radix Checkboxは**`<form>`直下に置かれたときだけ**
  // 隠しinput（フォーム互換用）のサイズ同期でこれを呼ぶため、フォームの外で単体描画する
  // テストでは要らず、このモーダルを開くテストでだけ未定義のまま例外になる。
  class ResizeObserverMock {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
  }
  window.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;
  // happy-domは`window.confirm`を定義しないため、自分で差し込む（jsdomと違い関数自体が
  // 無いので、`vi.spyOn(window, "confirm")`では対象が見つからず失敗する）。
  window.confirm = vi.fn(() => true);
});

describe("一覧", () => {
  it("マウント時に読み込み、下書きと公開済みを件数つきで分ける", async () => {
    listing(
      baseAxisDefinition({ axis_id: "d1", is_published: false }),
      baseAxisDefinition({ axis_id: "d2", is_published: false }),
      baseAxisDefinition({ axis_id: "p1", is_published: true }),
    );
    render(<AxisStudio />);

    expect(await screen.findByRole("tab", { name: "下書き（2）" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "公開済み（1）" })).toBeInTheDocument();
  });

  it("下書きが1つも無ければ、その旨を出す", async () => {
    listing(baseAxisDefinition({ axis_id: "p1", is_published: true }));
    render(<AxisStudio />);

    expect(await screen.findByText("下書きの軸はありません。")).toBeInTheDocument();
  });

  it("読み込みに失敗したら、理由をそのまま出す", async () => {
    vi.mocked(listAxisDefinitions).mockRejectedValue(new Error("一覧を読めませんでした"));
    render(<AxisStudio />);

    expect(await screen.findByText("一覧を読めませんでした")).toBeInTheDocument();
  });

  it("材料として他の軸を指す行は、生の識別子ではなく参照先の表示名で要約する", async () => {
    listing(
      baseAxisDefinition({ axis_id: "inner", label: "内側の軸" }),
      baseAxisDefinition({
        axis_id: "outer",
        label: "外側の軸",
        shape: {
          kind: "breakpoint_linear",
          terms: [{ material: "inner", weight: 1, required: true }],
          preprocess: "identity",
          breakpoints: [
            [0, 0],
            [10, 100],
          ],
        },
      }),
    );
    render(<AxisStudio />);

    const row = (await screen.findByText("外側の軸")).closest("div");
    expect(row?.textContent).toContain("内側の軸");
    expect(row?.textContent).not.toContain("inner");
  });
});

describe("モーダルの開き方", () => {
  it("「編集」は、その軸の表示名を見出しに出して開く", async () => {
    listing(baseAxisDefinition({ label: "編集する軸" }));
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click(await screen.findByRole("button", { name: "編集" }));

    expect(screen.getByRole("dialog", { name: "軸を編集: 編集する軸" })).toBeInTheDocument();
    // axis_idはフォームに無い（表示名で識別する）。
    expect(screen.queryByRole("textbox", { name: "axis_id" })).not.toBeInTheDocument();
  });

  it("公開済みの「表示だけ編集」は、制限モードと分かる見出しで開く", async () => {
    listing(baseAxisDefinition({ label: "公開中の軸", is_published: true }));
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click(await screen.findByRole("tab", { name: /公開済み/ }));
    await user.click(await screen.findByRole("button", { name: "表示だけ編集" }));

    expect(screen.getByRole("dialog", { name: "表示専用フィールドを編集: 公開中の軸" })).toBeInTheDocument();
  });

  it("「複製して新規作成」は、複製元の名前を見出しに出して新規作成で開く", async () => {
    listing(baseAxisDefinition({ label: "複製元の軸", default_weight: 0.42 }));
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click(await screen.findByRole("button", { name: "複製して新規作成" }));

    expect(screen.getByRole("dialog", { name: "「複製元の軸」を複製して新しい軸を作る" })).toBeInTheDocument();
    // 複製元の値は引き継ぐ。
    expect(screen.getByRole("textbox", { name: "表示名" })).toHaveValue("複製元の軸");
    expect(screen.getByRole("spinbutton", { name: "既定重み" })).toHaveValue(0.42);
  });

  it("「+ 新しい軸を作る」は空で開く", async () => {
    listing(baseAxisDefinition());
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click(await screen.findByRole("button", { name: "+ 新しい軸を作る" }));

    expect(screen.getByRole("dialog", { name: "新しい軸を作る" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "表示名" })).toHaveValue("");
  });

  it("閉じてもモーダルが消えるだけで、一覧は残る", async () => {
    listing(baseAxisDefinition({ label: "一覧に残る軸" }));
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click(await screen.findByRole("button", { name: "編集" }));
    await user.click(screen.getByRole("button", { name: "閉じる" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("一覧に残る軸")).toBeInTheDocument();
  });
});

describe("削除", () => {
  function twoAxes() {
    listing(
      baseAxisDefinition({ axis_id: "target", label: "消す軸" }),
      baseAxisDefinition({ axis_id: "other", label: "残す軸" }),
    );
  }

  function referencedPair() {
    listing(
      baseAxisDefinition({ axis_id: "target", label: "消す軸" }),
      baseAxisDefinition({
        axis_id: "user_axis",
        label: "参照している軸",
        shape: {
          kind: "breakpoint_linear",
          terms: [{ material: "target", weight: 1, required: true }],
          preprocess: "identity",
          breakpoints: [
            [0, 0],
            [10, 100],
          ],
        },
      }),
    );
  }

  it("他の軸から参照されていなければ、確認せずに消す", async () => {
    twoAxes();
    const confirmSpy = vi.spyOn(window, "confirm");
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click((await screen.findAllByRole("button", { name: "削除" }))[0]);

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(deleteAxisDefinition).toHaveBeenCalledWith("target");
    confirmSpy.mockRestore();
  });

  it("参照されていたら、参照元の名前を挙げて確認する", async () => {
    referencedPair();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click((await screen.findAllByRole("button", { name: "削除" }))[0]);

    expect(confirmSpy.mock.calls[0][0]).toContain("参照している軸");
    // 断ったら消さない。
    expect(deleteAxisDefinition).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("確認で承知したら、参照されていても消す", async () => {
    referencedPair();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click((await screen.findAllByRole("button", { name: "削除" }))[0]);

    expect(deleteAxisDefinition).toHaveBeenCalledWith("target");
    confirmSpy.mockRestore();
  });

  it("最後の1軸は消せない（理由を添えて押させない）", async () => {
    listing(baseAxisDefinition({ axis_id: "only", label: "唯一の軸" }));
    render(<AxisStudio />);

    const button = await screen.findByRole("button", { name: "削除" });

    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "最後の1軸は削除できません");
  });

  it("削除に失敗したら、理由をそのまま出す", async () => {
    twoAxes();
    vi.mocked(deleteAxisDefinition).mockRejectedValue(new Error("消せませんでした"));
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click((await screen.findAllByRole("button", { name: "削除" }))[0]);

    expect(await screen.findByText("消せませんでした")).toBeInTheDocument();
  });
});

describe("公開の取り消し", () => {
  it("押すと取り消して一覧を読み直す", async () => {
    vi.mocked(listAxisDefinitions)
      .mockResolvedValueOnce([baseAxisDefinition({ axis_id: "a", is_published: true })])
      .mockResolvedValue([baseAxisDefinition({ axis_id: "a", is_published: false })]);
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click(await screen.findByRole("tab", { name: /公開済み/ }));
    await user.click(await screen.findByRole("button", { name: "非公開に戻す" }));

    expect(unpublishAxisDefinition).toHaveBeenCalledWith("a");
    // 読み直した結果が反映され、ボタンが消える。
    await waitFor(() => expect(screen.queryByRole("button", { name: "非公開に戻す" })).not.toBeInTheDocument());
  });

  it("失敗したら、理由をそのまま出す", async () => {
    listing(baseAxisDefinition({ axis_id: "a", is_published: true }));
    vi.mocked(unpublishAxisDefinition).mockRejectedValue(new Error("戻せませんでした"));
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click(await screen.findByRole("tab", { name: /公開済み/ }));
    await user.click(await screen.findByRole("button", { name: "非公開に戻す" }));

    expect(await screen.findByText("戻せませんでした")).toBeInTheDocument();
  });
});

describe("保存", () => {
  it("新規作成を保存すると、作ってから一覧を読み直し、モーダルを閉じる", async () => {
    listing(baseAxisDefinition());
    const user = userEvent.setup();
    render(<AxisStudio />);

    await user.click(await screen.findByRole("button", { name: "+ 新しい軸を作る" }));
    await user.type(await screen.findByRole("textbox", { name: "表示名" }), "新軸");
    const callsBeforeSave = vi.mocked(listAxisDefinitions).mock.calls.length;
    await user.click(screen.getByRole("button", { name: "作成する" }));

    await waitFor(() => expect(createAxisDefinition).toHaveBeenCalledTimes(1));
    expect(vi.mocked(createAxisDefinition).mock.calls[0][0].label).toBe("新軸");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(vi.mocked(listAxisDefinitions).mock.calls.length).toBe(callsBeforeSave + 1);
  });
});
