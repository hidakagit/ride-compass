// 改善計画T340: 値ごとのスコア入力欄に添える「値の候補」セレクト（highway/surface/
// smoothnessのように実データの値一覧を動的取得できる材料向け）の回帰テスト。
// AxisComposer.test.tsxはgetMaterialValuesを常に失敗させる方針（自由テキスト入力の
// 既存挙動を検証）のため、成功レスポンスのケースはこのファイルへ分離する。
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AxisComposer from "./AxisComposer";

// 改善計画T345フォローアップ: ラベルはbackend（MaterialSpec.value_labels）が返す前提へ
// 変更したため、モック応答も{value, label}形式にする（frontend側の翻訳表は撤去済み）。
vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  getMaterialValues: vi.fn(async (materialId: string) => {
    if (materialId === "highway") {
      return {
        values: [
          { value: "residential", label: "住宅街の道路" },
          { value: "primary", label: "主要幹線道路" },
        ],
      };
    }
    return { values: [] };
  }),
}));

async function clickNext(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "次へ" }));
}

describe("AxisComposer 値の候補セレクト", () => {
  it("動的値一覧に対応する材料(highway)を選ぶと候補セレクトが現れ、選ぶと生のタグ値ではなくラベルが読み取り専用表示される", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

    await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸E");
    await clickNext(user);
    await user.click(screen.getByRole("radio", { name: /はい\/いいえ、または種類ごとに点数を決める/ }));
    await clickNext(user);

    await user.selectOptions(screen.getByRole("combobox", { name: "材料(material)" }), "highway");

    const candidateSelect = await screen.findByRole("combobox", { name: "値の候補" });
    // 改善計画T345フォローアップ（ユーザー指摘: 候補が存在する材料では生のタグ値を
    // 直接入力する必要は無いはず——material_catalogに無い値を書く実運用上の必要性は
    // 基本無く、タイプミスがそのまま静かに一致しない行として残る落とし穴になる）:
    // 候補一覧がある材料は候補セレクトでの選択のみを許可し、値欄はglobals.cssの
    // input共通スタイルを流用した読み取り専用input（実体はinput、typeできない）にする。
    const valueInput = screen.getByLabelText("値");
    expect(valueInput).toHaveValue("");
    expect(valueInput).toHaveAttribute("readonly");

    await user.selectOptions(candidateSelect, "residential");

    // 選択後は生のタグ値("residential")ではなくラベル("住宅街の道路")が値欄に表示される。
    expect(valueInput).toHaveValue("住宅街の道路");
    expect(screen.queryByText("residential")).not.toBeInTheDocument();
    // 候補セレクト自体は選択の起点（value=""）へ戻る（連続で別の値も選べるようにするため）。
    expect(candidateSelect).toHaveValue("");

    await clickNext(user);
    await user.click(screen.getByRole("button", { name: "作成する" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    const [payload] = onSave.mock.calls[0];
    // 保存されるvalue自体は表示用ラベルではなく、選択した生のタグ値のまま。
    expect(payload.shape).toEqual({ kind: "categorical", material: "highway", mapping: { residential: 0 } });
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
    // 候補セレクトはbackendが返すlabel（"住宅街の道路"）をそのまま表示し、物理値
    // "residential"併記（旧表示「住宅街の道路 (residential)」）は無いことを確認する。
    expect(screen.getByRole("option", { name: "住宅街の道路" })).toBeInTheDocument();
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
