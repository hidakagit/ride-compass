// AxisComposer.tsx（軸スタジオの中核フォーム、T270で新設・T332で4ステップウィザードへ
// 再構成）自体には今までテストが無かった（AxisStudio.test.tsxはAxisStudio経由の統合的な
// 導線確認が主で、buildShape()の4テンプレート・priority_overrides/display_overrideの
// 素通し保持・draftFromExisting往復までは踏み込んでいない）。ここではAxisComposerを
// 単体でレンダリングし（Dialog等の呼び出し元の関心事を持ち込まない）、ウィザードを
// userEventで実際に操作してonSaveへ渡るpayloadを検証する。
//
// 最優先: コメント（AxisComposer.tsx 138-144行目付近）にある通り、priority_overrides
// （改善計画T292、0次条件）・display_override（改善計画T310、地図ramp閾値の手書き上書き）は
// 「以前はコードレビュー指摘まで黙って失われていた」という実データ消失バグの修正対象。
// このフォームに編集欄を持たないこの2フィールドが、編集フォームを経由しても元の値の
// ままpayloadへ素通しされることを検証する回帰テストを最優先で書く。
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { AxisDefinitionResponse, AxisShape } from "@/types/route";
import AxisComposer from "./AxisComposer";

// AxisComposerが使うuseMaterialCatalog/useMaterialValuesの取得先。AxisStudio.test.tsxと
// 同じ方針で、静的フォールバック（AXIS_MATERIAL_OPTIONS、lib/axisMaterialsCatalog.ts）で
// 十分なため失敗させておく（実HTTPは呼ばない）。getMaterialValues（改善計画T340）も
// 失敗させ、値入力欄が既定の自由テキストのままになることをこのファイルの既存テストが
// 引き続き検証する（候補選択セレクトのテストはAxisComposer.materialValues.test.tsx参照）。
vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

function baseDefinition(overrides: Partial<AxisDefinitionResponse> = {}): AxisDefinitionResponse {
  return {
    axis_id: "gradient",
    label: "勾配",
    description: "",
    category: "観測",
    default_weight: 0.2,
    is_published: false,
    priority_overrides: [],
    show_map_icon: true,
    display_override: null,
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

function categoricalShape(material: string, mapping: Record<string, number>): AxisShape {
  return { kind: "categorical", material, mapping };
}

function flagSumShape(flags: [string, number][], cap: number | null): AxisShape {
  return { kind: "flag_sum", flags, cap };
}

async function clickNext(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "次へ" }));
}

describe("AxisComposer", () => {
  // ============================================================
  // buildShape(): 4テンプレート（+categoricalの2dtype）の変換結果検証
  // ============================================================
  describe("点数のつけ方(shape)テンプレートごとのpayload変換", () => {
    it("「数値の大きさに応じて点数を変える」(breakpoint_linear)で入力した係数・折れ点がそのままshapeになる", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸C");
      await clickNext(user); // basic -> shape_kind（既定でbreakpoint_linearが選択済み）
      await clickNext(user); // shape_kind -> shape_params

      const weightInput = screen.getByRole("spinbutton", { name: "係数" });
      await user.clear(weightInput);
      await user.type(weightInput, "2.5");

      await user.click(screen.getByRole("button", { name: "+ 折れ点を追加" }));
      const inputValueInputs = screen.getAllByRole("spinbutton", { name: "入力値" });
      const scoreInputs = screen.getAllByRole("spinbutton", { name: "スコア" });
      expect(inputValueInputs).toHaveLength(3);
      await user.clear(inputValueInputs[2]);
      await user.type(inputValueInputs[2], "20");
      await user.clear(scoreInputs[2]);
      await user.type(scoreInputs[2], "60");

      await clickNext(user); // shape_params -> display_publish
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload, isNew] = onSave.mock.calls[0];
      expect(isNew).toBe(true);
      expect(payload.shape).toEqual({
        kind: "breakpoint_linear",
        terms: [{ material: "gradient_percent", weight: 2.5, required: true }],
        preprocess: "identity",
        breakpoints: [
          [0, 0],
          [10, 100],
          [20, 60],
        ],
      });
    });

    it("「他の軸の計算結果をもとに点数を変える」(recipe_then_breakpoint_linear)を選ぶとkindがそれになり、前処理の変更も反映される", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸D");
      await clickNext(user);
      await user.click(screen.getByRole("radio", { name: /他の軸の計算結果をもとに点数を変える/ }));
      await clickNext(user);

      await user.selectOptions(screen.getByRole("combobox", { name: "前処理(preprocess)" }), "abs");

      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape).toEqual({
        kind: "recipe_then_breakpoint_linear",
        terms: [{ material: "gradient_percent", weight: 1.0, required: true }],
        preprocess: "abs",
        breakpoints: [
          [0, 0],
          [10, 100],
        ],
      });
    });

    it("「はい/いいえ、または種類ごとに点数を決める」(categorical・boolean材料)でtrue/falseスコアがmappingになる", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸A");
      await clickNext(user);
      await user.click(screen.getByRole("radio", { name: /はい\/いいえ、または種類ごとに点数を決める/ }));
      await clickNext(user);

      const trueInput = screen.getByRole("spinbutton", { name: "該当時(true)のスコア" });
      const falseInput = screen.getByRole("spinbutton", { name: "非該当時(false)のスコア" });
      await user.clear(trueInput);
      await user.type(trueInput, "15");
      await user.clear(falseInput);
      await user.type(falseInput, "85");

      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape).toEqual(categoricalShape("surface_good", { true: 15, false: 85 }));
    });

    it("「はい/いいえ、または種類ごとに点数を決める」(categorical・多値材料)で値ごとのスコア行がmappingになり、空行は除外される", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸B");
      await clickNext(user);
      await user.click(screen.getByRole("radio", { name: /はい\/いいえ、または種類ごとに点数を決める/ }));
      await clickNext(user);

      await user.selectOptions(screen.getByRole("combobox", { name: "材料(material)" }), "bicycle_infra");
      let valueInputs = screen.getAllByLabelText("値");
      await user.type(valueInputs[0], "separated");
      let scoreInputs = screen.getAllByLabelText("スコア");
      await user.clear(scoreInputs[0]);
      await user.type(scoreInputs[0], "60");

      await user.click(screen.getByRole("button", { name: "+ 値を追加" }));
      valueInputs = screen.getAllByLabelText("値");
      await user.type(valueInputs[1], "none");
      scoreInputs = screen.getAllByLabelText("スコア");
      await user.clear(scoreInputs[1]);
      await user.type(scoreInputs[1], "10");

      // 3行目は値を空のまま残す（buildShapeがtrim()===""の行を除外することの確認）。
      await user.click(screen.getByRole("button", { name: "+ 値を追加" }));

      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape).toEqual(categoricalShape("bicycle_infra", { separated: 60, none: 10 }));
    });

    it("「複数の要素の有無を数えて減点・加点する」(flag_sum)で加点・上限の入力がそのままshapeになる", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸F");
      await clickNext(user);
      await user.click(screen.getByRole("radio", { name: /複数の要素の有無を数えて減点・加点する/ }));
      await clickNext(user);

      // 負の数値をuser.typeで1文字ずつ入力すると、"-"のみ入力された瞬間の中間状態で
      // Number("-")===NaNとなり、この<input>を制御しているReactの状態がNaNへ倒れて
      // 入力済みの"-"ごと失われる（実測: 最終的に"-20"ではなく"20"になる）。
      // 実際のユーザー操作（ペースト等、中間状態を経ない一括入力）に近いfireEvent.changeで
      // 最終値を直接設定する。
      const pointsInput = screen.getByRole("spinbutton", { name: "加点" });
      fireEvent.change(pointsInput, { target: { value: "-20" } });
      const capInput = screen.getByRole("spinbutton", { name: "上限(cap、任意)" });
      await user.clear(capInput);
      await user.type(capInput, "40");

      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape).toEqual(flagSumShape([["surface_good", -20]], 40));
    });
  });

  // ============================================================
  // 最優先の回帰テスト: priority_overrides / display_override の素通し保持
  // ============================================================
  describe("priority_overrides・display_overrideの素通し保持（回帰テスト）", () => {
    it("編集フォームに欄を持たないpriority_overrides/display_overrideが、他フィールドの変更だけを経て編集前の値のまま保存される", async () => {
      const priorityOverrides = [{ material: "no_lit", equals: "true", value: -1000 }];
      const displayOverride = {
        kind: "ramp" as const,
        label: "テスト表示",
        category: "trafficSafety",
        tile_inputs: [
          {
            property: "gradient_abs",
            weight: 1,
            boolean: false,
            invert: false,
            true_value: 0,
            false_value: 0,
            has_unknown_fallback: false,
          },
        ],
        thresholds: [10, 50, 90],
        unit: "%",
        note: "test note",
      };
      const editing = baseDefinition({
        priority_overrides: priorityOverrides,
        display_override: displayOverride,
      });
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      // 「基本情報」ステップでラベルと重みだけを変更する。shape・display系の欄には触れない。
      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "改");
      const weightInput = screen.getByRole("spinbutton", { name: "既定重み(default_weight)" });
      await user.clear(weightInput);
      await user.type(weightInput, "0.35");

      await clickNext(user); // basic -> shape_kind
      await clickNext(user); // shape_kind -> shape_params
      await clickNext(user); // shape_params -> display_publish
      await user.click(screen.getByRole("button", { name: "更新する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload, isNew] = onSave.mock.calls[0];
      expect(isNew).toBe(false);
      expect(payload.label).toBe("勾配改");
      expect(payload.default_weight).toBeCloseTo(0.35);
      // 本題: このフォームに編集欄を持たない2フィールドが編集前の値のまま渡ること。
      expect(payload.priority_overrides).toEqual(priorityOverrides);
      expect(payload.display_override).toEqual(displayOverride);
    });

    it("priority_overridesが空配列・display_overrideがnullの既存軸を編集しても、[]・nullのまま保存され欠落しない", async () => {
      const editing = baseDefinition({ priority_overrides: [], display_override: null });
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await clickNext(user);
      await clickNext(user);
      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "更新する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.priority_overrides).toEqual([]);
      expect(payload.display_override).toBeNull();
    });
  });

  // ============================================================
  // draftFromExisting往復: 各shape種別の既存軸を編集モードで開いたときの初期表示
  // ============================================================
  describe("既存軸の編集読み込み(draftFromExisting往復)", () => {
    it("breakpoint_linear軸を編集で開くと、対応するカードが選択済みで係数・折れ点が反映される", async () => {
      const editing = baseDefinition({
        shape: {
          kind: "breakpoint_linear",
          terms: [{ material: "gradient_percent", weight: 3.0, required: false }],
          preprocess: "abs",
          breakpoints: [
            [0, 10],
            [5, 90],
          ],
        },
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      expect(screen.getByRole("radio", { name: /^数値の大きさに応じて点数を変える/ })).toBeChecked();
      await clickNext(user);

      expect(screen.getByRole("spinbutton", { name: "係数" })).toHaveValue(3);
      const inputValueInputs = screen.getAllByRole("spinbutton", { name: "入力値" }) as HTMLInputElement[];
      const scoreInputs = screen.getAllByRole("spinbutton", { name: "スコア" }) as HTMLInputElement[];
      expect(inputValueInputs.map((el) => el.valueAsNumber)).toEqual([0, 5]);
      expect(scoreInputs.map((el) => el.valueAsNumber)).toEqual([10, 90]);
    });

    it("recipe_then_breakpoint_linear軸を編集で開くと、上級者向けカードが選択済みになる", async () => {
      const editing = baseDefinition({
        shape: {
          kind: "recipe_then_breakpoint_linear",
          terms: [{ material: "gradient_percent", weight: 1.0, required: true }],
          preprocess: "identity",
          breakpoints: [
            [0, 0],
            [10, 100],
          ],
        },
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      expect(screen.getByRole("radio", { name: /他の軸の計算結果をもとに点数を変える/ })).toBeChecked();
      expect(screen.getByRole("radio", { name: /^数値の大きさに応じて点数を変える/ })).not.toBeChecked();
    });

    it("categorical(boolean材料)軸を編集で開くと、true/falseスコアが反映される", async () => {
      const editing = baseDefinition({
        shape: categoricalShape("no_lit", { true: -30, false: 5 }),
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      expect(screen.getByRole("radio", { name: /はい\/いいえ、または種類ごとに点数を決める/ })).toBeChecked();
      await clickNext(user);

      expect(screen.getByRole("spinbutton", { name: "該当時(true)のスコア" })).toHaveValue(-30);
      expect(screen.getByRole("spinbutton", { name: "非該当時(false)のスコア" })).toHaveValue(5);
    });

    it("categorical(多値材料)軸を編集で開くと、材料選択と値ごとのスコア行が反映される", async () => {
      const editing = baseDefinition({
        shape: categoricalShape("bicycle_infra", { separated: 80, none: -10 }),
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      await clickNext(user);

      expect(screen.getByRole("combobox", { name: "材料(material)" })).toHaveValue("bicycle_infra");
      const valueInputs = screen.getAllByLabelText("値") as HTMLInputElement[];
      const scoreInputs = screen.getAllByLabelText("スコア") as HTMLInputElement[];
      const rows = valueInputs.map((el, i) => [el.value, scoreInputs[i].valueAsNumber]);
      expect(rows).toEqual(
        expect.arrayContaining([
          ["separated", 80],
          ["none", -10],
        ]),
      );
    });

    it("flag_sum軸を編集で開くと、フラグの加点・上限が反映される", async () => {
      const editing = baseDefinition({
        shape: flagSumShape(
          [
            ["no_lit", -30],
            ["has_tunnel", -20],
          ],
          50,
        ),
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      expect(screen.getByRole("radio", { name: /複数の要素の有無を数えて減点・加点する/ })).toBeChecked();
      await clickNext(user);

      const pointsInputs = screen.getAllByRole("spinbutton", { name: "加点" });
      expect(pointsInputs.map((el) => (el as HTMLInputElement).valueAsNumber)).toEqual([-30, -20]);
      expect(screen.getByRole("spinbutton", { name: "上限(cap、任意)" })).toHaveValue(50);
    });
  });

  // ============================================================
  // バリデーション
  // ============================================================
  describe("バリデーション", () => {
    it("表示名(label)が空のまま「次へ」を押すと、ステップは進まずエラーが出る", async () => {
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);

      expect(screen.getByText("表示名(label)を入力してください。")).toBeInTheDocument();
      expect(screen.getByText("ステップ 1/4: 基本情報")).toBeInTheDocument();
    });

    it("categorical(多値材料)で値ごとのスコアを1件も設定しないまま次へ進もうとすると、進まずエラーが出る", async () => {
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸E");
      await clickNext(user);
      await user.click(screen.getByRole("radio", { name: /はい\/いいえ、または種類ごとに点数を決める/ }));
      await clickNext(user);
      await user.selectOptions(screen.getByRole("combobox", { name: "材料(material)" }), "bicycle_infra");

      await clickNext(user);

      expect(screen.getByText("値ごとのスコアを少なくとも1件設定してください。")).toBeInTheDocument();
      expect(screen.getByText("ステップ 3/4: 点数の詳細を設定")).toBeInTheDocument();
    });

    it("表示名(label)が4文字を超えchip_labelを未設定のまま保存しようとすると、エラーが出て保存されない", async () => {
      const onSave = vi.fn();
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "とても長い表示名");
      await clickNext(user);
      await clickNext(user);
      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "作成する" }));

      expect(
        screen.getByText("表示名(label)が4文字を超えています。地図チップの略称(chip_label)を設定してください。"),
      ).toBeInTheDocument();
      expect(screen.getByText("ステップ 4/4: 地図表示・公開")).toBeInTheDocument();
      expect(onSave).not.toHaveBeenCalled();
    });

    it("表示名(label)が4文字を超えていてもchip_labelを設定すれば保存できる", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "とても長い表示名");
      await clickNext(user);
      await clickNext(user);
      await clickNext(user);
      await user.type(screen.getByRole("textbox", { name: "地図チップの略称(chip_label)" }), "長い");
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.chip_label).toBe("長い");
    });
  });

  // ============================================================
  // onSave失敗時のエラー表示
  // ============================================================
  describe("保存失敗時の挙動", () => {
    it("onSaveがreject(失敗)すると、そのエラーメッセージが表示され保存ボタンが再び押せる状態に戻る", async () => {
      const onSave = vi.fn().mockRejectedValue(new Error("サーバーで保存に失敗しました"));
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸G");
      await clickNext(user);
      await clickNext(user);
      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(screen.getByText("サーバーで保存に失敗しました")).toBeInTheDocument());
      const saveButton = screen.getByRole("button", { name: "作成する" });
      expect(saveButton).not.toBeDisabled();
    });
  });
});
