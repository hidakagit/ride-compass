/**
 * `AxisComposer`の値ごとのスコア欄——**実データの値一覧が返ってきたとき**の振る舞い。
 *
 * 一覧を取得できないときの自由入力は`AxisComposer.test.tsx`が持つ（あちらは
 * `getMaterialValues`を常に失敗させる）。ここは応答の中身だけで分かれる分岐を見る。
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AxisComposer from "./AxisComposer";
import { getMaterialValues } from "@/services/materialCatalogApi";

// 分布プレビューはマウント直後に取りに行く。塞がないと実HTTPが飛ぶ。
vi.mock("@/services/axisPreviewApi", () => ({
  fetchAxisValueDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  fetchMaterialDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

vi.mock("@/services/materialCatalogApi", async () => {
  const { materialCatalogFixture } = await import("@/testing/materialCatalogFixture");
  return {
    getMaterialCatalog: vi.fn().mockResolvedValue(materialCatalogFixture()),
    getMaterialValues: vi.fn(async () => ({
      available: true,
      values: [
        { value: "v_one", label: "ひとつ目 - v_one" },
        { value: "v_two", label: "ふたつ目 - v_two" },
      ],
    })),
  };
});

/** 新規作成を開き、分類の材料を選んだ状態にする。 */
async function chooseCategoricalMaterial(onSave = vi.fn().mockResolvedValue(undefined)) {
  const user = userEvent.setup();
  render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

  await user.type(await screen.findByRole("textbox", { name: "表示名" }), "対象軸");
  await user.selectOptions(screen.getByRole("combobox", { name: "点数のもとになるもの" }), "cat_a");
  return { user, onSave };
}

describe("値の候補が返る材料", () => {
  it("候補から選ぶ形になり、値欄は直接書けない", async () => {
    const { user } = await chooseCategoricalMaterial();

    const candidateSelect = await screen.findByRole("combobox", { name: "値の候補" });
    const valueInput = screen.getByLabelText("値");
    expect(valueInput).toHaveValue("");
    expect(valueInput).toHaveAttribute("readonly");

    await user.selectOptions(candidateSelect, "v_one");

    // 値欄には応答のラベルが出る。生のタグ値は画面に出さない。
    expect(valueInput).toHaveValue("ひとつ目 - v_one");
    // 続けて別の値も選べるよう、セレクト自体は起点へ戻る。
    expect(candidateSelect).toHaveValue("");
  });

  it("候補の選択肢は、応答のラベルをそのまま出す", async () => {
    await chooseCategoricalMaterial();

    await screen.findByRole("combobox", { name: "値の候補" });

    expect(screen.getByRole("option", { name: "ひとつ目 - v_one" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "ふたつ目 - v_two" })).toBeInTheDocument();
  });

  it("保存されるのは表示用のラベルではなく、選んだ生の値", async () => {
    const { user, onSave } = await chooseCategoricalMaterial();

    await user.selectOptions(await screen.findByRole("combobox", { name: "値の候補" }), "v_one");
    await user.click(screen.getByRole("button", { name: "作成する" }));

    expect(onSave).toHaveBeenCalledTimes(1);
    const [payload] = onSave.mock.calls[0];
    expect(payload.shape).toEqual({ kind: "categorical", material: "cat_a", mapping: { v_one: 0 } });
  });
});

describe("値の候補が1件も無い材料", () => {
  it("候補セレクトを出さず、値は自由に書ける", async () => {
    vi.mocked(getMaterialValues).mockResolvedValue({ available: true, values: [] });
    const { user } = await chooseCategoricalMaterial();

    const valueInput = await screen.findByLabelText("値");
    await user.type(valueInput, "書いた値");

    expect(valueInput).toHaveValue("書いた値");
    expect(screen.queryByRole("combobox", { name: "値の候補" })).not.toBeInTheDocument();
  });
});
