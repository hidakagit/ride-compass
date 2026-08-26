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
  it("動的値一覧に対応する材料(highway)を選ぶと候補セレクトが現れ、選ぶと値入力欄へ反映される", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸E");
    await clickNext(user);
    await user.click(screen.getByRole("radio", { name: /はい\/いいえ、または種類ごとに点数を決める/ }));
    await clickNext(user);

    await user.selectOptions(screen.getByRole("combobox", { name: "材料(material)" }), "highway");

    const candidateSelect = await screen.findByRole("combobox", { name: "値の候補" });
    const valueInput = screen.getByLabelText("値");
    expect(valueInput).toHaveValue("");

    await user.selectOptions(candidateSelect, "residential");

    expect(valueInput).toHaveValue("residential");
    // 候補セレクト自体は選択の起点（value=""）へ戻る（連続で別の値も選べるようにするため）。
    expect(candidateSelect).toHaveValue("");

    await user.clear(valueInput);
    await user.type(valueInput, "primary");
    expect(valueInput).toHaveValue("primary"); // 候補セレクトを経由しない直接入力も引き続き可能

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
