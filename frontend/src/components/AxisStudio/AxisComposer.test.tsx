/**
 * `AxisComposer.tsx`——軸の編集フォーム。
 *
 * ここで見るのは**このコンポーネント自身が決めていること**だけ。下書きとpayloadの変換は
 * `axisDraft.ts`（`axisDraft.test.ts`）、点数のつけ方の入力欄は`AxisScoringSection`、
 * 地図表示の入力欄は`AxisMapDisplaySection`が持つ。
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AxisComposer from "./AxisComposer";
import { baseAxisDefinition } from "@/testing/axisDefinitionFixtures";
import type { AxisDefinitionResponse } from "@/types/route";

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

function makeSaveSpy() {
  return vi.fn().mockResolvedValue(undefined);
}

/** フォームを1つ立ち上げ、材料カタログが届くまで待つ。 */
async function openComposer(
  options: {
    editing?: AxisDefinitionResponse | null;
    otherAxes?: readonly AxisDefinitionResponse[];
    onSave?: ReturnType<typeof makeSaveSpy>;
    onCancelEdit?: () => void;
  } = {},
) {
  const onSave = options.onSave ?? makeSaveSpy();
  const onCancelEdit = options.onCancelEdit ?? vi.fn(() => {});
  const user = userEvent.setup();
  render(
    <AxisComposer
      editing={options.editing ?? null}
      duplicateFrom={null}
      otherAxes={options.otherAxes}
      onCancelEdit={onCancelEdit}
      onSave={onSave}
    />,
  );
  await screen.findByRole("button", { name: /作成する|更新する/ });
  return { user, onSave, onCancelEdit };
}

async function save(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /作成する|更新する/ }));
}

describe("保存する値の組み立て", () => {
  it("編集欄を持たないフィールドは既存値のまま送り返し、編集した値だけを重ねる", async () => {
    const editing = baseAxisDefinition({
      label: "元",
      time_scope: "night_only",
      dedicated_way_value_layer: true,
    });
    const { user, onSave } = await openComposer({ editing });

    await user.clear(screen.getByRole("textbox", { name: "表示名" }));
    await user.type(screen.getByRole("textbox", { name: "表示名" }), "新");
    await save(user);

    const [payload] = onSave.mock.calls[0];
    // 編集した値は上書きされ、編集欄の無い値は落ちない。
    expect(payload.label).toBe("新");
    expect(payload.time_scope).toBe("night_only");
    expect(payload.dedicated_way_value_layer).toBe(true);
  });

  it("未入力の表示欄は空文字ではなくnullで送る（backendの「未設定」と同じ意味にする）", async () => {
    const { user, onSave } = await openComposer();

    await user.type(screen.getByRole("textbox", { name: "表示名" }), "軸");
    await save(user);

    const [payload] = onSave.mock.calls[0];
    expect(payload.icon_id).toBeNull();
    expect(payload.chip_label).toBeNull();
    expect(payload.panel_hint).toBeNull();
  });

  it("表示名の前後の空白は落として送る", async () => {
    const { user, onSave } = await openComposer();

    await user.type(screen.getByRole("textbox", { name: "表示名" }), "  軸  ");
    await save(user);

    expect(onSave.mock.calls[0][0].label).toBe("軸");
  });

  it("保存ボタンを押すまでonSaveは呼ばれない", async () => {
    const { user, onSave } = await openComposer();

    await user.type(screen.getByRole("textbox", { name: "表示名" }), "軸");

    expect(onSave).not.toHaveBeenCalled();
    await save(user);
    expect(onSave).toHaveBeenCalledTimes(1);
  });
});

describe("保存前の検証", () => {
  it("表示名が空なら保存しない", async () => {
    const { user, onSave } = await openComposer();

    await save(user);

    expect(screen.getByText(/表示名を入力してください/)).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("表示名が4文字を超えるのにチップの略称が無ければ保存しない", async () => {
    const { user, onSave } = await openComposer();

    await user.type(screen.getByRole("textbox", { name: "表示名" }), "あいうえおか");
    await save(user);

    expect(screen.getByText(/チップの略称を設定してください/)).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("エラーが出たあと直して保存すると通る", async () => {
    const { user, onSave } = await openComposer();

    await save(user);
    await user.type(screen.getByRole("textbox", { name: "表示名" }), "軸");
    await save(user);

    expect(onSave).toHaveBeenCalledTimes(1);
  });
});

describe("保存の失敗", () => {
  it("失敗の理由を出し、もう一度押せる状態へ戻す", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("保存できませんでした"));
    const { user } = await openComposer({ onSave });

    await user.type(screen.getByRole("textbox", { name: "表示名" }), "軸");
    await save(user);

    expect(await screen.findByText("保存できませんでした")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "作成する" })).toBeEnabled();
  });
});

describe("公開済み軸の制限モード", () => {
  it("地図表示の項目だけを出し、材料や重みの入力欄は出さない", async () => {
    await openComposer({ editing: baseAxisDefinition({ is_published: true }) });

    expect(screen.getByText(/地図表示に関わる項目のみ編集できます/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "表示名" })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton", { name: "既定重み" })).not.toBeInTheDocument();
  });

  it("入力欄の無い節を検証しない（表示名が空でも行き止まりにしない）", async () => {
    const { user, onSave } = await openComposer({
      editing: baseAxisDefinition({ is_published: true, label: "" }),
    });

    await save(user);

    expect(onSave).toHaveBeenCalledTimes(1);
  });
});

describe("既定重みの相対表示", () => {
  it("他の軸を渡さなければ出さない", async () => {
    await openComposer();

    expect(screen.queryByText(/重み合計に対して約/)).not.toBeInTheDocument();
    expect(screen.queryByText(/重みはルート探索へ直接使われません/)).not.toBeInTheDocument();
  });

  it("非公開のうちは、重みが効かない旨だけを出す", async () => {
    await openComposer({
      editing: baseAxisDefinition({ is_published: false }),
      otherAxes: [baseAxisDefinition({ axis_id: "other", is_published: true, default_weight: 1 })],
    });

    expect(screen.getByText(/重みはルート探索へ直接使われません/)).toBeInTheDocument();
  });

  it("公開にすると、他の公開軸との比率を出す", async () => {
    // 比率が出るのは新規作成のときだけ——公開済みの軸を編集する画面は制限モードで、
    // 重みの欄自体を描かない。
    const { user } = await openComposer({
      otherAxes: [baseAxisDefinition({ axis_id: "axis_b", is_published: true, default_weight: 3 })],
    });

    const weight = screen.getByRole("spinbutton", { name: "既定重み" });
    await user.clear(weight);
    await user.type(weight, "1");
    await user.click(screen.getByRole("checkbox", { name: "公開する" }));

    // 1 / (3 + 1) = 25.0%。文は数値の埋め込みで分割されるため要素の全文で見る。
    const hint = screen.getByText(
      (_content, element) => element?.tagName === "P" && (element.textContent ?? "").startsWith("参考:"),
    );
    expect(hint.textContent).toContain("約25.0%");
  });
});

describe("ボタンの出し分け", () => {
  it("新規作成では「作成する」だけを出す", async () => {
    await openComposer();

    expect(screen.getByRole("button", { name: "作成する" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "編集をやめる" })).not.toBeInTheDocument();
  });

  it("編集では「更新する」と「編集をやめる」を出し、やめるとonCancelEditが呼ばれる", async () => {
    const { user, onCancelEdit } = await openComposer({ editing: baseAxisDefinition() });

    await user.click(screen.getByRole("button", { name: "編集をやめる" }));

    expect(screen.getByRole("button", { name: "更新する" })).toBeInTheDocument();
    expect(onCancelEdit).toHaveBeenCalledTimes(1);
  });
});

// このテストは解決しないPromiseをモジュール内の実行中スロットへ残すため、最後に置くこと。
describe("材料カタログが届くまで", () => {
  it("入力欄ではなく読み込み中を出す", async () => {
    const { getMaterialCatalog } = await import("@/services/materialCatalogApi");
    vi.mocked(getMaterialCatalog).mockReturnValue(new Promise(() => {}));

    render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={makeSaveSpy()} />);

    expect(screen.getByText(/材料カタログを読み込んでいます/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "表示名" })).not.toBeInTheDocument();
  });
});
