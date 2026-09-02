// AxisComposer.tsx（軸スタジオの中核フォーム、T270で新設・T332で4ステップウィザードへ
// 再構成）自体には今までテストが無かった（AxisStudio.test.tsxはAxisStudio経由の統合的な
// 導線確認が主で、buildShape()の4テンプレート・priority_overridesの素通し保持・
// draftFromExisting往復までは踏み込んでいない）。ここではAxisComposerを
// 単体でレンダリングし（Dialog等の呼び出し元の関心事を持ち込まない）、ウィザードを
// userEventで実際に操作してonSaveへ渡るpayloadを検証する。
//
// 最優先: コメント（AxisComposer.tsx 138-144行目付近）にある通り、priority_overrides
// （改善計画T292、0次条件）は「以前はコードレビュー指摘まで黙って失われていた」という
// 実データ消失バグの修正対象。このフォームに編集欄を持たないこのフィールドが、編集
// フォームを経由しても元の値のままpayloadへ素通しされることを検証する回帰テストを
// 最優先で書く。
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
    time_scope: "always",
    dedicated_way_value_layer: false,
    dynamic_way_value_needs_time: false,
    dynamic_way_value_needs_bearing: false,
    shape: {
      kind: "breakpoint_linear",
      terms: [{ material: "gradient_percent", weight: 1.0, required: true }],
      preprocess: "identity",
      breakpoints: [
        [0, 0],
        [10, 100],
      ],
    },
    // 改善計画T404: displayはAxisDefinitionResponseの必須フィールド（axis_display_for()の
    // 計算結果）。gradient_percentはタイル非依存のためkind="none"が実際の値と一致する。
    display: { kind: "none", label: "勾配", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
    ...overrides,
  };
}

function categoricalShape(material: string, mapping: Record<string, number>): AxisShape {
  return { kind: "categorical", material, mapping };
}

// 改善計画T396: 旧flag_sumはbreakpoint_linearの特殊形（全termがboolean材料、
// breakpoints=[[0,0],[cap,cap]]の恒等クランプ）として保存される（AxisComposer.tsx:
// buildShapeの同コメント参照）。cap未指定時は達成しうる最大合計を既定値にする。
function flagSumShape(flags: [string, number][], cap: number | null): AxisShape {
  const resolvedCap = cap ?? flags.reduce((sum, [, points]) => sum + points, 0);
  return {
    kind: "breakpoint_linear",
    terms: flags.map(([material, points]) => ({ material, weight: points, required: true })),
    preprocess: "identity",
    breakpoints: [
      [0, 0],
      [resolvedCap, resolvedCap],
    ],
  };
}

async function clickNext(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "次へ" }));
}

describe("AxisComposer", () => {
  // ============================================================
  // buildShape(): 4テンプレート（+categoricalの2dtype）の変換結果検証
  // ============================================================
  describe("点数のつけ方(shape)テンプレートごとのpayload変換", () => {
    it("「なめらか評価」(breakpoint_linear)で入力した係数・折れ点がそのままshapeになる", async () => {
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

    it("改善計画T425回帰テスト: 折れ点の横軸が昇順でないまま次へ進もうとすると、進まずエラーが出る", async () => {
      // 「+ 折れ点を追加」は新しい折れ点を既定値[0, 0]で末尾に追加するため、既存の
      // 最後の点(10, 100)より横軸が小さく、追加しただけで非昇順になる（そのまま
      // 気づかず保存すると、backend側のnp.interpが前提とする不変条件が破れ評価結果が
      // 未定義動作になっていた——ゼロベース網羅レビュー指摘、items 12）。
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸E");
      await clickNext(user);
      await clickNext(user);

      await user.click(screen.getByRole("button", { name: "+ 折れ点を追加" }));
      await clickNext(user);

      expect(
        screen.getByText("折れ点は横軸（左の入力欄）の値が小さい順になるようにしてください（同じ値は使えません）。"),
      ).toBeInTheDocument();
      expect(screen.getByText("ステップ 3/4: 点数の詳細を設定")).toBeInTheDocument();
    });

    it("改善計画T342回帰テスト: breakpoint_linearの材料(terms)にboolean材料も選べる（backend側のBreakpointLinearShapeは元々bool値を1/0として係数と掛け合わせて評価できていたが、GUIのセレクトがnumeric限定で選べなかった）", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸D");
      await clickNext(user);
      await clickNext(user);

      // termRow先頭の材料セレクト（アクセシブルネーム無し、前処理(preprocess)セレクトは
      // <label>で名前付けされているため区別できる）。静的フォールバックカタログ
      // （lib/axisMaterialsCatalog.ts）のboolean材料の1つを選ぶ。
      const materialSelect = screen.getAllByRole("combobox")[0] as HTMLSelectElement;
      await user.selectOptions(materialSelect, "surface_good");

      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape.terms[0].material).toBe("surface_good");
    });

    // ユーザー指摘（軸同士の線形結合nX+mYがGUIから組めない）への対応の回帰テスト。
    // 以前はこのテンプレートの材料セレクトがMATERIAL_CATALOGの材料しか出しておらず、
    // 「他の軸の計算結果を材料として使う」という説明どおりに他の軸を選ぶ手段がGUI上に
    // 存在しなかった（backend側は元々MaterialTerm.materialへ他axis_idを指定できる設計
    // だったが、GUIが対応していなかった実装漏れ）。改善計画T397: 「かけあわせ評価」は
    // 純粋な重み付き結合に絞ったため、下ごしらえ(preprocess)・折れ点の編集UIは出ない
    // （常にpreprocess="identity"・恒等クランプ[[0,0],[100,100]]のまま送信される）。
    it("「かけあわせ評価」(recipe_then_breakpoint_linear)を選ぶと材料セレクトが他の軸一覧になり、下ごしらえ・折れ点の編集UIは出ない", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      const otherAxes = [baseDefinition({ axis_id: "wind", label: "風" })];
      render(
        <AxisComposer editing={null} duplicateFrom={null} otherAxes={otherAxes} onCancelEdit={vi.fn()} onSave={onSave} />,
      );

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸D");
      await clickNext(user);
      await user.click(screen.getByRole("radio", { name: /かけあわせ評価/ }));
      await clickNext(user);

      // 材料セレクトがMATERIAL_CATALOGの材料（勾配%等）ではなく、他の軸(風)の一覧になっている。
      expect(screen.getByRole("option", { name: "風" })).toBeInTheDocument();
      expect(screen.queryByRole("option", { name: /勾配%/ })).not.toBeInTheDocument();
      // 純粋な重み付き結合に絞ったため、下ごしらえ・折れ点の編集UIは表示されない。
      expect(screen.queryByText("下ごしらえ")).not.toBeInTheDocument();
      expect(screen.queryByText("折れ点")).not.toBeInTheDocument();

      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape).toEqual({
        kind: "breakpoint_linear",
        terms: [{ material: "wind", weight: 1.0, required: true }],
        preprocess: "identity",
        breakpoints: [
          [0, 0],
          [100, 100],
        ],
      });
    });

    it("軸を2つ選んで係数(n, m)を設定すると、nX + mYの重み付き線形結合としてpayloadに反映される", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      const otherAxes = [
        baseDefinition({ axis_id: "gradient", label: "勾配" }),
        baseDefinition({ axis_id: "wind", label: "風" }),
      ];
      render(
        <AxisComposer editing={null} duplicateFrom={null} otherAxes={otherAxes} onCancelEdit={vi.fn()} onSave={onSave} />,
      );

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "複合軸");
      await clickNext(user);
      await user.click(screen.getByRole("radio", { name: /かけあわせ評価/ }));
      await clickNext(user);

      await user.selectOptions(screen.getAllByRole("combobox")[0], "gradient");
      await user.clear(screen.getByRole("spinbutton", { name: "係数" }));
      await user.type(screen.getByRole("spinbutton", { name: "係数" }), "2");

      await user.click(screen.getByRole("button", { name: "+ 軸を追加" }));
      await user.selectOptions(screen.getAllByRole("combobox")[1], "wind");
      const weightInputs = screen.getAllByRole("spinbutton", { name: "係数" });
      await user.clear(weightInputs[1]);
      await user.type(weightInputs[1], "1");

      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape).toEqual({
        kind: "breakpoint_linear",
        terms: [
          { material: "gradient", weight: 2, required: true },
          { material: "wind", weight: 1, required: false },
        ],
        preprocess: "identity",
        breakpoints: [
          [0, 0],
          [100, 100],
        ],
      });
    });

    it("組み合わせられる他の軸が無いときは、その旨のヒントが表示され「+ 軸を追加」が無効化される", async () => {
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸E");
      await clickNext(user);
      await user.click(screen.getByRole("radio", { name: /かけあわせ評価/ }));
      await clickNext(user);

      expect(screen.getByText(/組み合わせられる他の軸がまだありません/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "+ 軸を追加" })).toBeDisabled();
    });

    it("「ぴったり評価」(categorical・boolean材料)でtrue/falseスコアがmappingになる", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸A");
      await clickNext(user);
      await user.click(screen.getByRole("radio", { name: /ぴったり評価/ }));
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

    it("「ぴったり評価」(categorical・多値材料)で値ごとのスコア行がmappingになり、空行は除外される", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸B");
      await clickNext(user);
      await user.click(screen.getByRole("radio", { name: /ぴったり評価/ }));
      await clickNext(user);

      await user.selectOptions(screen.getByRole("combobox", { name: "材料(material)" }), "tracktype");
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
      expect(payload.shape).toEqual(categoricalShape("tracktype", { separated: 60, none: 10 }));
    });

    // 改善計画T397: 旧「複数の要素の有無を数えて減点・加点する」(flag_sum)カードは
    // 「なめらか評価」に吸収された。boolean材料をterms(材料)に追加し、係数(旧points相当)を
    // 入力するだけで同じ結果（terms×breakpoints=[[0,0],[cap,cap]]の恒等クランプ）を
    // 組めることを確認する。
    it("「なめらか評価」でboolean材料の係数をマイナスにできる（旧flag_sumの減点相当）", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸F");
      await clickNext(user);
      await clickNext(user); // 既定でbreakpoint_linear（なめらか評価）が選択済み

      const materialSelect = screen.getAllByRole("combobox")[0] as HTMLSelectElement;
      await user.selectOptions(materialSelect, "surface_good");

      // 負の数値をuser.typeで1文字ずつ入力すると、"-"のみ入力された瞬間の中間状態で
      // Number("-")===NaNとなり、この<input>を制御しているReactの状態がNaNへ倒れて
      // 入力済みの"-"ごと失われる（実測: 最終的に"-20"ではなく"20"になる）。
      // 実際のユーザー操作（ペースト等、中間状態を経ない一括入力）に近いfireEvent.changeで
      // 最終値を直接設定する。
      const weightInput = screen.getByRole("spinbutton", { name: "係数" });
      fireEvent.change(weightInput, { target: { value: "-20" } });

      await clickNext(user);
      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape.terms).toEqual([{ material: "surface_good", weight: -20, required: true }]);
    });
  });

  // ============================================================
  // 最優先の回帰テスト: priority_overrides の素通し保持
  // ============================================================
  describe("priority_overridesの素通し保持（回帰テスト）", () => {
    it("編集フォームに欄を持たないpriority_overridesが、他フィールドの変更だけを経て編集前の値のまま保存される", async () => {
      const priorityOverrides = [{ material: "no_lit", equals: "true", value: -1000 }];
      const editing = baseDefinition({
        priority_overrides: priorityOverrides,
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
      // 本題: このフォームに編集欄を持たないフィールドが編集前の値のまま渡ること。
      expect(payload.priority_overrides).toEqual(priorityOverrides);
    });

    it("priority_overridesが空配列の既存軸を編集しても、[]のまま保存され欠落しない", async () => {
      const editing = baseDefinition({ priority_overrides: [] });
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
    });
  });

  // ============================================================
  // 改善計画T404: 地図の色分けしきい値(display_thresholds_override)編集UI・
  // kind="none"の注記
  // ============================================================
  describe("地図の色分けしきい値(display_thresholds_override)編集", () => {
    it("既定は上書きオフで、「+ しきい値を自分で設定する」を押すと1件の入力欄が現れる", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸D");
      await clickNext(user); // basic -> shape_kind
      await clickNext(user); // shape_kind -> shape_params
      await clickNext(user); // shape_params -> display_publish

      expect(screen.queryByLabelText("しきい値1")).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      expect(screen.getByLabelText("しきい値1")).toHaveValue(1);

      await user.click(screen.getByRole("button", { name: "作成する" }));
      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.display_thresholds_override).toEqual([1]);
    });

    it("しきい値を追加・編集・削除でき、「自動計算に戻す」でnullへ戻る", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸E");
      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.click(screen.getByRole("button", { name: "+ しきい値を追加" }));
      const thresholdInput1 = screen.getByLabelText("しきい値1") as HTMLInputElement;
      const thresholdInput2 = screen.getByLabelText("しきい値2") as HTMLInputElement;
      await user.clear(thresholdInput1);
      await user.type(thresholdInput1, "1");
      await user.clear(thresholdInput2);
      await user.type(thresholdInput2, "4");

      await user.click(screen.getByRole("button", { name: "自動計算に戻す" }));
      expect(screen.queryByLabelText("しきい値1")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "作成する" }));
      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.display_thresholds_override).toBeNull();
    });

    // 改善計画T513: 段階ごとの体感ラベル（display_band_labels_override）は
    // display_thresholds_overrideと対になる軸スタジオ設定可能なフィールド。しきい値の
    // 上書きが無効の間は編集欄自体を出さない（段階数が決まらないため）。
    it("しきい値の上書きが無効の間は体感ラベルの編集欄自体が出ない", async () => {
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      expect(screen.queryByRole("button", { name: "+ 体感ラベルを設定する" })).not.toBeInTheDocument();
      expect(screen.queryByLabelText("体感ラベル1")).not.toBeInTheDocument();
    });

    it("しきい値の上書きを設定すると体感ラベルの編集欄が使え、段階数ぶんの入力欄が現れ保存される", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸G");
      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.click(screen.getByRole("button", { name: "+ しきい値を追加" }));
      // この時点でしきい値2件(段階数3)。
      await user.click(screen.getByRole("button", { name: "+ 体感ラベルを設定する" }));
      expect(screen.getByLabelText("体感ラベル1")).toHaveValue("");
      expect(screen.getByLabelText("体感ラベル2")).toHaveValue("");
      expect(screen.getByLabelText("体感ラベル3")).toHaveValue("");

      await user.type(screen.getByLabelText("体感ラベル1"), "強い追い風");

      await user.click(screen.getByRole("button", { name: "作成する" }));
      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.display_band_labels_override).toEqual(["強い追い風", "", ""]);
    });

    it("しきい値を1件追加すると体感ラベルの入力欄も1件増え、「自動計算に戻す」で体感ラベルも一緒にnullへ戻る", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸H");
      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      // 「+ しきい値を自分で設定する」の時点でしきい値1件(段階数2)のため、体感ラベルを
      // 有効化すると最初から2件の入力欄（体感ラベル1・2）が現れる。
      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.click(screen.getByRole("button", { name: "+ 体感ラベルを設定する" }));
      expect(screen.getByLabelText("体感ラベル1")).toBeInTheDocument();
      expect(screen.getByLabelText("体感ラベル2")).toBeInTheDocument();
      expect(screen.queryByLabelText("体感ラベル3")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "+ しきい値を追加" }));
      expect(screen.getByLabelText("体感ラベル3")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "自動計算に戻す" }));
      expect(screen.queryByLabelText("体感ラベル1")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "+ 体感ラベルを設定する" })).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "作成する" }));
      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.display_band_labels_override).toBeNull();
    });

    it("既存軸のdisplay_band_labels_overrideが編集フォームへ初期反映される", async () => {
      const editing = baseDefinition({
        display_thresholds_override: [2],
        display_band_labels_override: ["低い", "高い"],
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      expect(screen.getByLabelText("体感ラベル1")).toHaveValue("低い");
      expect(screen.getByLabelText("体感ラベル2")).toHaveValue("高い");
    });

    it("改善計画T513回帰テスト: 複製元のdisplay_band_labels_overrideは複製先へ引き継がずnullへリセットされる", async () => {
      const source = baseDefinition({
        display_thresholds_override: [2],
        display_band_labels_override: ["低い", "高い"],
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={source} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      // しきい値自体も複製時にリセットされる（既存の回帰テスト参照）ため、体感ラベルの
      // 編集欄はそもそも出ない（しきい値の上書きが無効のため）。
      expect(screen.queryByRole("button", { name: "+ 体感ラベルを設定する" })).not.toBeInTheDocument();
    });

    it("しきい値が降順・同値だと保存直前の検証でエラーになりステップが進まない", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸F");
      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.click(screen.getByRole("button", { name: "+ しきい値を追加" }));
      const thresholdInput1 = screen.getByLabelText("しきい値1") as HTMLInputElement;
      const thresholdInput2 = screen.getByLabelText("しきい値2") as HTMLInputElement;
      await user.clear(thresholdInput1);
      await user.type(thresholdInput1, "4");
      await user.clear(thresholdInput2);
      await user.type(thresholdInput2, "1");

      await user.click(screen.getByRole("button", { name: "作成する" }));

      expect(screen.getByText(/小さい順に並べてください/)).toBeInTheDocument();
      expect(onSave).not.toHaveBeenCalled();
    });

    it("編集中の軸がkind=noneの場合、地図表示用のデータ取得経路が無い旨の注記が出る", async () => {
      const editing = baseDefinition({
        display: { kind: "none", label: "勾配", category: "trafficSafety", tile_inputs: [], thresholds: [], unit: "", note: "" },
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      expect(
        screen.getByText(
          "この軸で使っている材料の一部は、まだ地図表示用のデータ取得経路が用意されていません（ルート探索のコストには反映されます）",
        ),
      ).toBeInTheDocument();
    });

    it("編集中の軸がkind=rampの場合、注記は出ない", async () => {
      const editing = baseDefinition({
        display: {
          kind: "ramp",
          label: "勾配",
          category: "trafficSafety",
          tile_inputs: [
            {
              property: "dummy_per_km",
              weight: 1.0,
              boolean: false,
              invert: false,
              true_value: 0,
              false_value: 0,
              has_unknown_fallback: false,
              needs_runtime_scale: false,
            },
          ],
          thresholds: [1.0],
          unit: "",
          note: "",
        },
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      expect(screen.queryByText(/まだ地図表示用のデータ取得経路が用意されていません/)).not.toBeInTheDocument();
    });

    it("新規作成中（editing=null）は注記を出さない", async () => {
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸G");
      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      expect(screen.queryByText(/まだ地図表示用のデータ取得経路が用意されていません/)).not.toBeInTheDocument();
    });

    it("既存軸のdisplay_thresholds_overrideが編集フォームへ初期反映される", async () => {
      const editing = baseDefinition({ display_thresholds_override: [1, 2, 4] });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      expect(screen.getByLabelText("しきい値1")).toHaveValue(1);
      expect(screen.getByLabelText("しきい値2")).toHaveValue(2);
      expect(screen.getByLabelText("しきい値3")).toHaveValue(4);
    });

    it("改善計画T501回帰テスト: 複製元のdisplay_thresholds_overrideは複製先へ引き継がず自動計算(null)へリセットされる", async () => {
      const source = baseDefinition({ axis_id: "gradient", display_thresholds_override: [-2, 2, 6, 10] });
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={source} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      await clickNext(user);
      await clickNext(user);

      expect(screen.queryByLabelText("しきい値1")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "+ しきい値を自分で設定する" })).toBeInTheDocument();
    });
  });

  // ============================================================
  // 改善計画T501: 公開済み軸を編集対象に開いた場合の制限モード
  // （表示専用フィールドのみ編集、材料・計算式・重みのステップは出さない）
  // ============================================================
  describe("公開済み軸の表示専用フィールド編集(制限モード)", () => {
    it("ステッパー・戻る/次へボタンを出さず、表示専用フィールドの編集画面のみを表示する", async () => {
      const editing = baseDefinition({ is_published: true });
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      expect(screen.getByLabelText("地図チップの略称(chip_label)")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "次へ" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "戻る" })).not.toBeInTheDocument();
      expect(screen.queryByRole("checkbox", { name: "公開する" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "更新する" })).toBeInTheDocument();
    });

    it("表示専用フィールドだけを変更して保存すると、材料・計算式・重み・is_publishedは既存のまま送信される", async () => {
      const editing = baseDefinition({
        is_published: true,
        default_weight: 0.42,
        icon_id: "old_icon",
      });
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByLabelText("地図チップの略称(chip_label)"), "新称");
      await user.click(screen.getByRole("button", { name: "更新する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalled());
      const [payload, isNew] = onSave.mock.calls[0];
      expect(isNew).toBe(false);
      expect(payload.chip_label).toBe("新称");
      expect(payload.is_published).toBe(true);
      expect(payload.default_weight).toBe(0.42);
      expect(payload.shape).toEqual(editing.shape);
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
      expect(screen.getByRole("radio", { name: /なめらか評価/ })).toBeChecked();
      await clickNext(user);

      expect(screen.getByRole("spinbutton", { name: "係数" })).toHaveValue(3);
      const inputValueInputs = screen.getAllByRole("spinbutton", { name: "入力値" }) as HTMLInputElement[];
      const scoreInputs = screen.getAllByRole("spinbutton", { name: "スコア" }) as HTMLInputElement[];
      expect(inputValueInputs.map((el) => el.valueAsNumber)).toEqual([0, 5]);
      expect(scoreInputs.map((el) => el.valueAsNumber)).toEqual([10, 90]);
    });

    it("他軸参照のterms(recipe_then_breakpoint_linear相当)を編集で開くと、上級者向けカードが選択済みになる", async () => {
      // 改善計画T396: 保存済みkindは常にbreakpoint_linearへ統合済みのため、材料一覧に
      // 存在しない参照（wind、材料カタログには無くaxis_idの想定）を使い、構造判定
      // （draftFromExisting）が「他軸参照termsのみ」からこのカードを推定することを確認する。
      const editing = baseDefinition({
        shape: {
          kind: "breakpoint_linear",
          terms: [{ material: "wind", weight: 1.0, required: true }],
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
      expect(screen.getByRole("radio", { name: /かけあわせ評価/ })).toBeChecked();
      expect(screen.getByRole("radio", { name: /なめらか評価/ })).not.toBeChecked();
    });

    it("categorical(boolean材料)軸を編集で開くと、true/falseスコアが反映される", async () => {
      const editing = baseDefinition({
        shape: categoricalShape("no_lit", { true: -30, false: 5 }),
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      expect(screen.getByRole("radio", { name: /ぴったり評価/ })).toBeChecked();
      await clickNext(user);

      expect(screen.getByRole("spinbutton", { name: "該当時(true)のスコア" })).toHaveValue(-30);
      expect(screen.getByRole("spinbutton", { name: "非該当時(false)のスコア" })).toHaveValue(5);
    });

    it("categorical(多値材料)軸を編集で開くと、材料選択と値ごとのスコア行が反映される", async () => {
      const editing = baseDefinition({
        shape: categoricalShape("tracktype", { separated: 80, none: -10 }),
      });
      const user = userEvent.setup();
      render(<AxisComposer editing={editing} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await clickNext(user);
      await clickNext(user);

      expect(screen.getByRole("combobox", { name: "材料(material)" })).toHaveValue("tracktype");
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

    // 改善計画T397: 旧flag_sum軸（boolean材料のみのterms）は、backend側では既にただの
    // breakpoint_linearとして保存されているため、編集で開くと（4カード化前と違い専用の
    // 判別は行わず）「なめらか評価」カードで開き、termsがそのまま反映される。
    it("boolean材料のみのterms（旧flag_sum相当）を編集で開くと、なめらか評価カードで係数が反映される", async () => {
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
      expect(screen.getByRole("radio", { name: /なめらか評価/ })).toBeChecked();
      await clickNext(user);

      const weightInputs = screen.getAllByRole("spinbutton", { name: "係数" });
      expect(weightInputs.map((el) => (el as HTMLInputElement).valueAsNumber)).toEqual([-30, -20]);
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
      await user.click(screen.getByRole("radio", { name: /ぴったり評価/ }));
      await clickNext(user);
      await user.selectOptions(screen.getByRole("combobox", { name: "材料(material)" }), "tracktype");

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
  // 実機不具合の回帰テスト: ウィザードの最終ステップ(4/4)へ「次へ」で遷移すると
  // 未変更のまま暗黙に保存されて（ユーザーの目には）モーダルが勝手に閉じる不具合
  // （本番環境で再現、原因はAxisComposer.tsx 1017行目付近参照）。
  // ============================================================
  describe("ウィザードのステップ遷移", () => {
    it("「次へ」で最終ステップ(4/4)へ着いても、明示的に保存ボタンを押すまでonSaveは呼ばれない", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={onSave} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸K");
      await clickNext(user); // basic -> shape_kind
      await clickNext(user); // shape_kind -> shape_params
      await clickNext(user); // shape_params -> display_publish（実機ではここで暗黙に保存されていた）

      expect(screen.getByText("ステップ 4/4: 地図表示・公開")).toBeInTheDocument();
      expect(onSave).not.toHaveBeenCalled();
    });

    // Reactが「次へ」ボタンと保存ボタンを同じ<button>要素の使い回し（type属性の
    // その場書き換え）として扱うと、クリックされた直後にtype="button"→"submit"へ
    // 同期的に変わり、ブラウザ側のクリックのデフォルト動作判定（type="submit"なら
    // フォーム送信）がこの書き換え後のtypeを見てしまい、「次へ」を押しただけで
    // フォームが暗黙に送信される（実機で確認、jsdomではこのブラウザ側の判定タイミングの
    // 差が再現できないため、React側の対策[key指定による強制的な要素の作り直し]が
    // 効いていることを、DOM要素の参照が別物になっているかで直接確認する）。
    it("「次へ」ボタンと保存ボタンは同じDOM要素を使い回さない（type属性の書き換えのみだとブラウザのクリック判定に混入し暗黙送信を招く）", async () => {
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸L");
      await clickNext(user);
      await clickNext(user);

      const nextButton = screen.getByRole("button", { name: "次へ" });
      await user.click(nextButton);

      const createButton = screen.getByRole("button", { name: "作成する" });
      expect(createButton).not.toBe(nextButton);
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

  // ============================================================
  // 改善計画T345: 材料説明の情報アイコン・既定重みの相対比較・必須チェックボックスの説明
  // ============================================================
  describe("材料の説明アイコン(情報アイコン)", () => {
    it("breakpoint_linearの材料(terms)欄で情報アイコンを押すと、選択中の材料の説明文が表示される", async () => {
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸H");
      await clickNext(user); // 既定でbreakpoint_linear選択済み
      await clickNext(user);
      // 既定材料はgradient_percent（emptyDraftのmaterialOptions[0]）。
      // 改善計画T345さらなるフォローアップ2: 材料labelは「論理名 - 物理名」形式。
      await user.click(screen.getByRole("button", { name: "勾配%（符号付き） - gradient_percentの説明を表示" }));

      expect(screen.getByText(/国土地理院の標高データ/)).toBeInTheDocument();
    });

    it("材料セレクトで別の材料を選ぶと、情報アイコンの説明文もその材料のものに切り替わる", async () => {
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸I");
      await clickNext(user);
      await clickNext(user);

      const materialSelect = screen.getAllByRole("combobox")[0];
      await user.selectOptions(materialSelect, "surface_good");

      await user.click(screen.getByRole("button", { name: "舗装良否 - surface_goodの説明を表示" }));
      expect(screen.getByText(/OSMの路面タグ\(surface\)/)).toBeInTheDocument();
    });

    it("「必須」チェックボックスの隣の情報アイコンに、欠損時の扱いを説明する文言がある", async () => {
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸J");
      await clickNext(user);
      await clickNext(user);

      await user.click(screen.getByRole("button", { name: "「必須」の説明を表示" }));
      expect(screen.getByText(/軸全体を「評価不能」として扱います/)).toBeInTheDocument();
    });
  });

  describe("既定重みの相対比較（otherAxes）", () => {
    it("otherAxesを渡すと、公開軸全体の重み合計に対する割合が参考表示される", async () => {
      const user = userEvent.setup();
      const otherAxes = [
        baseDefinition({ axis_id: "gradient", is_published: true, default_weight: 0.3 }),
        baseDefinition({ axis_id: "wind", label: "風", is_published: true, default_weight: 0.1 }),
      ];
      render(
        <AxisComposer editing={null} duplicateFrom={null} otherAxes={otherAxes} onCancelEdit={vi.fn()} onSave={vi.fn()} />,
      );

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸K");
      const weightInput = screen.getByRole("spinbutton", { name: "既定重み(default_weight)" });
      await user.clear(weightInput);
      await user.type(weightInput, "0.2");

      // 割合表示は公開する場合のみ意味を持つ（非公開の軸の重みはdefault_axis_weightsから
      // 除外され合成に加わらないため）。「公開する」チェックボックスは最終ステップにある。
      await clickNext(user);
      await clickNext(user);
      await clickNext(user);
      await user.click(screen.getByRole("checkbox", { name: "公開する" }));
      await user.click(screen.getByRole("button", { name: "戻る" }));
      await user.click(screen.getByRole("button", { name: "戻る" }));
      await user.click(screen.getByRole("button", { name: "戻る" }));

      // 新規作成軸(0.2) / (0.3+0.1+0.2) = 33.3%
      expect(screen.getByText(/約33\.3%/)).toBeInTheDocument();
    });

    it("非公開のままの軸では、重みが直接使われない旨の注記が出る", async () => {
      const user = userEvent.setup();
      render(
        <AxisComposer editing={null} duplicateFrom={null} otherAxes={[]} onCancelEdit={vi.fn()} onSave={vi.fn()} />,
      );

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸L");

      expect(screen.getByText(/現在非公開のため、重みはルート探索へ直接使われません/)).toBeInTheDocument();
    });

    it("otherAxesを渡さない場合は参考表示自体を出さない", async () => {
      const user = userEvent.setup();
      render(<AxisComposer editing={null} duplicateFrom={null} onCancelEdit={vi.fn()} onSave={vi.fn()} />);

      await user.type(screen.getByRole("textbox", { name: "表示名(label)" }), "軸M");

      expect(screen.queryByText(/重みはルート探索へ直接使われません/)).not.toBeInTheDocument();
      expect(screen.queryByText(/の重み合計に対して約/)).not.toBeInTheDocument();
    });
  });
});
