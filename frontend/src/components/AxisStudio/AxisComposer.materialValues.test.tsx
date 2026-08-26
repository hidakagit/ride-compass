// 改善計画T340: 値ごとのスコア入力欄に添える「値の候補」セレクト（highway/surface/
// smoothnessのように実データの値一覧を動的取得できる材料向け）の回帰テスト。
// AxisComposer.test.tsxはgetMaterialValuesを常に失敗させる方針（自由テキスト入力の
// 既存挙動を検証）のため、成功レスポンスのケースはこのファイルへ分離する。
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AxisComposer from "./AxisComposer";

vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  getMaterialValues: vi.fn(async (materialId: string) => {
    if (materialId === "highway") {
      return { values: ["residential", "primary"] };
    }
    return { values: [] };
  }),
}));

async function clickNext(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "次へ" }));
}

describe("AxisComposer 値の候補セレクト", () => {
  it("動的値一覧に対応する材料(highway)を選ぶと候補セレクトが現れ、選ぶと生のタグ値ではなくラベルが表示される", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸E");
    await clickNext(user);
    await user.click(screen.getByRole("radio", { name: /はい\/いいえ、または種類ごとに点数を決める/ }));
    await clickNext(user);

    await user.selectOptions(screen.getByRole("combobox", { name: "材料(material)" }), "highway");

    const candidateSelect = await screen.findByRole("combobox", { name: "値の候補" });
    // 改善計画T345フォローアップ: 値が未設定の間はラベルが引けないため入力欄のまま。
    const valueInput = screen.getByLabelText("値");
    expect(valueInput).toHaveValue("");

    await user.selectOptions(candidateSelect, "residential");

    // 実機フィードバック: 候補から選んだ後は生のタグ値("residential")を画面に出さず、
    // ラベル("生活道路")だけを読み取り専用表示する（候補セレクトのoption文字列としても
    // 同じ文字列が存在するため、表示用span要素に絞って探す）。
    expect(screen.getByText("生活道路", { selector: "span" })).toBeInTheDocument();
    expect(screen.queryByLabelText("値")).not.toBeInTheDocument();
    expect(screen.queryByText("residential")).not.toBeInTheDocument();
    // 候補セレクト自体は選択の起点（value=""）へ戻る（連続で別の値も選べるようにするため）。
    expect(candidateSelect).toHaveValue("");

    // 「直接入力する」を押すと生のタグ値の入力欄へ戻り、候補に無い値も設定できる。
    await user.click(screen.getByRole("button", { name: "直接入力する" }));
    const reopenedInput = screen.getByLabelText("値");
    expect(reopenedInput).toHaveValue("residential");
    await user.clear(reopenedInput);
    await user.type(reopenedInput, "primary");
    expect(reopenedInput).toHaveValue("primary");

    await clickNext(user);
    await user.click(screen.getByRole("button", { name: "作成する" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const [payload] = onSave.mock.calls[0];
    expect(payload.shape).toEqual({ kind: "categorical", material: "highway", mapping: { primary: 0 } });
  });

  it("改善計画T345回帰テスト: 候補セレクトの選択肢は論理名(ラベル)のみを表示し、物理値(タグ生値)を併記しない", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸G");
    await clickNext(user);
    await user.click(screen.getByRole("radio", { name: /はい\/いいえ、または種類ごとに点数を決める/ }));
    await clickNext(user);

    await user.selectOptions(screen.getByRole("combobox", { name: "材料(material)" }), "highway");

    const candidateSelect = await screen.findByRole("combobox", { name: "値の候補" });
    // "residential"はlib/materialValueLabels.ts経由でroadFilterAxes.tsのHIGHWAY_GROUPSから
    // 「生活道路」というラベルを引く。物理値"residential"併記（旧表示「生活道路 (residential)」）
    // が無いことを確認する。
    expect(screen.getByRole("option", { name: "生活道路" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /residential/ })).not.toBeInTheDocument();
    expect(candidateSelect).toBeInTheDocument();
  });

  it("動的値一覧に対応しない材料(bicycle_infra)を選んでいる間は候補セレクトが出ない", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸F");
    await clickNext(user);
    await user.click(screen.getByRole("radio", { name: /はい\/いいえ、または種類ごとに点数を決める/ }));
    await clickNext(user);

    await user.selectOptions(screen.getByRole("combobox", { name: "材料(material)" }), "bicycle_infra");

    await waitFor(() => expect(screen.getAllByLabelText("値").length).toBeGreaterThan(0));
    expect(screen.queryByRole("combobox", { name: "値の候補" })).not.toBeInTheDocument();
  });
});
