// AxisComposer.tsx（軸スタジオの中核フォーム、T270で新設・T332で4ステップウィザードへ
// 再構成）自体には今までテストが無かった（AxisStudio.test.tsxはAxisStudio経由の統合的な
// 導線確認が主で、buildShape()の4テンプレート・priority_overridesの素通し保持・
// draftFromExisting往復までは踏み込んでいない）。ここではAxisComposerを
// 単体でレンダリングし（Dialog等の呼び出し元の関心事を持ち込まない）、ウィザードを
// userEventで実際に操作してonSaveへ渡るpayloadを検証する。
//
// 最優先の観点: このフォームが編集欄を持たないフィールド（AxisComposer.tsxの
// PASSTHROUGH_PAYLOAD_KEYS、priority_overrides等）は、編集フォームを経由しても元の値の
// ままpayloadへ素通しされる必要がある。送り返さないとサーバー側の既定値で上書きされ、
// 公開済み軸を非公開へ戻して軽微な編集をしただけで値が黙って失われる。
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { AxisDefinitionResponse, AxisShape } from "@/types/route";
import AxisComposer from "./AxisComposer";
import { PASSTHROUGH_PAYLOAD_KEYS } from "./axisDraft";
import { baseAxisDefinition } from "@/testing/axisDefinitionFixtures";

// AxisComposerが使うuseMaterialCatalog/useMaterialValuesの取得先。AxisStudio.test.tsxと
// 同じ方針で、静的フォールバック（AXIS_MATERIAL_OPTIONS、lib/axisMaterialsCatalog.ts）で
// 十分なため失敗させておく（実HTTPは呼ばない）。getMaterialValues（改善計画T340）も
// 失敗させ、値入力欄が既定の自由テキストのままになることをこのファイルの既存テストが
// 引き続き検証する（候補選択セレクトのテストはAxisComposer.materialValues.test.tsx参照）。
// 分布プレビューの2フック（useAxisValueDistribution/useMaterialDistribution）は
// マウント直後にフェッチする。モックしないとテストが実HTTPを発火する
// （このファイル冒頭が掲げる「実HTTPは呼ばない」方針どおり、ここで塞ぐ）。
vi.mock("@/services/axisPreviewApi", () => ({
  fetchAxisValueDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  fetchMaterialDistribution: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

vi.mock("@/services/materialCatalogApi", () => ({
  getMaterialCatalog: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
  getMaterialValues: vi.fn().mockRejectedValue(new Error("network unavailable in test")),
}));

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

/** 表示名を入れ、必要なら「点数のもとになるもの」を選ぶ。画面は1枚なので、ここで
 * 入力欄が全て出そろう（形の種類を選ぶ手順はもう無い——材料の型が決める）。 */
async function fillBasics(user: ReturnType<typeof userEvent.setup>, label: string, material?: RegExp) {
  await user.type(screen.getByRole("textbox", { name: "表示名" }), label);
  if (material) {
    await user.selectOptions(
      screen.getByRole("combobox", { name: "点数のもとになるもの" }),
      screen.getByRole("option", { name: material }),
    );
  }
}

/** AxisComposerを1つ立ち上げる。`editing`/`duplicateFrom`を省くと新規作成になる。
 * 返る`onSave`は既定で解決するspyで、payloadの検証はこれを見る（保存の失敗を試すテストは
 * `onSave`を渡して差し替える）。 */
// `vi.fn()`が返すMockの型は書き下せないため、既定のspyを作る関数から引く。
// `ReturnType<typeof vi.fn>`と書くと呼び出し可能な形を失い、onSaveのpropへ渡せない。
function makeSaveSpy() {
  return vi.fn().mockResolvedValue(undefined);
}

function renderComposer(
  options: {
    editing?: AxisDefinitionResponse | null;
    duplicateFrom?: AxisDefinitionResponse | null;
    mapBandColors?: (boundaries: readonly number[]) => readonly string[];
    mapValueUnit?: string;
    onSave?: ReturnType<typeof makeSaveSpy>;
  } = {},
) {
  const onSave = options.onSave ?? makeSaveSpy();
  const user = userEvent.setup();
  render(
    <AxisComposer
      editing={options.editing ?? null}
      duplicateFrom={options.duplicateFrom ?? null}
      mapBandColors={options.mapBandColors}
      mapValueUnit={options.mapValueUnit}
      onCancelEdit={vi.fn()}
      onSave={onSave}
    />,
  );
  return { user, onSave };
}

/** 折れ点の直接編集は詳細設定の中にある（簡単な入力で表せない形のためだけに開く）。 */
async function openBreakpointDetails(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText("折れ点を直接いじる"));
}

describe("AxisComposer", () => {
  // ============================================================
  // buildShape(): 4テンプレート（+categoricalの2dtype）の変換結果検証
  // ============================================================
  describe("点数のつけ方(shape)テンプレートごとのpayload変換", () => {
    it("数値の材料(breakpoint_linear)で入力した係数・折れ点がそのままshapeになる", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸C");

      await openBreakpointDetails(user);
      await user.click(screen.getByRole("button", { name: "+ 折れ点を追加" }));
      const inputValueInputs = screen.getAllByRole("spinbutton", { name: "入力値" });
      const scoreInputs = screen.getAllByRole("spinbutton", { name: "スコア" });
      expect(inputValueInputs).toHaveLength(3);
      // 追加は最も間隔の広い区間（既定値[[0,0],[10,100]]では唯一の区間）の中間へ挿入される
      // ため、新しい点は真ん中の行（index 1）に[5, 50]で入る。
      expect(inputValueInputs[1]).toHaveValue(5);
      expect(scoreInputs[1]).toHaveValue(50);
      await user.clear(scoreInputs[1]);
      await user.type(scoreInputs[1], "60");

      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload, isNew] = onSave.mock.calls[0];
      expect(isNew).toBe(true);
      expect(payload.shape).toEqual({
        kind: "breakpoint_linear",
        terms: [{ material: "gradient_percent", weight: 1, required: true }],
        preprocess: "identity",
        breakpoints: [
          [0, 0],
          [5, 60],
          [10, 100],
        ],
      });
    });

    it("T598: 「+ 折れ点を追加」は最も間隔の広い区間の中間へ挿入するため、昇順のまま次へ進める（改善計画T425の不具合を解消）", async () => {
      const { user } = renderComposer();

      await fillBasics(user, "軸E");

      await openBreakpointDetails(user);
      await user.click(screen.getByRole("button", { name: "+ 折れ点を追加" }));

      expect(
        screen.queryByText("折れ点は横軸（左の入力欄）の値が小さい順になるようにしてください（同じ値は使えません）。"),
      ).not.toBeInTheDocument();
    });

    it("改善計画T425回帰テスト: 手入力で折れ点の横軸が昇順でなくなった状態で次へ進もうとすると、進まずエラーが出る", async () => {
      const { user } = renderComposer();

      await fillBasics(user, "軸E");

      // 既定値[[0,0],[10,100]]の最後の行を、最初の行より小さい値へ手入力で書き換えて
      // 非昇順にする（自動生成・追加はいずれも昇順を保つため、手入力だけがこの状態を
      // 作れる経路として残る）。
      await openBreakpointDetails(user);
      const inputValueInputs = screen.getAllByRole("spinbutton", { name: "入力値" });
      await user.clear(inputValueInputs[1]);
      await user.type(inputValueInputs[1], "-5");

      await user.click(screen.getByRole("button", { name: "作成する" }));

      expect(
        screen.getByText("折れ点は横軸（左の入力欄）の値が小さい順になるようにしてください（同じ値は使えません）。"),
      ).toBeInTheDocument();
    });

    it("改善計画T342回帰テスト: breakpoint_linearの材料(terms)にboolean材料も選べる（backend側のBreakpointLinearShapeは元々bool値を1/0として係数と掛け合わせて評価できていたが、GUIのセレクトがnumeric限定で選べなかった）", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸D");

      // はい/いいえの材料は既定では「値ごとのスコア」になる。複数の危険要素を足し合わせる
      // 軸（街灯なし＋トンネル等）は、そこから「材料を足して合計する」で合計の形へ移る。
      await user.selectOptions(screen.getByRole("combobox", { name: "点数のもとになるもの" }), "surface_good");
      await user.click(screen.getByRole("button", { name: "+ 材料を足して合計する" }));

      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape.terms[0].material).toBe("surface_good");
    });

    // ユーザー指摘（軸同士の線形結合nX+mYがGUIから組めない）への対応の回帰テスト。
    // 以前はこのテンプレートの材料セレクトがMATERIAL_CATALOGの材料しか出しておらず、
    // 「他の軸の計算結果を材料として使う」という説明どおりに他の軸を選ぶ手段がGUI上に
    // 存在しなかった（backend側は元々MaterialTerm.materialへ他axis_idを指定できる設計
    // だったが、GUIが対応していなかった実装漏れ）。改善計画T397: 他の軸を組み合わせる形は
    // 純粋な重み付き結合に絞ったため、下ごしらえ(preprocess)・折れ点の編集UIは出ない
    // （常にpreprocess="identity"・恒等クランプ[[0,0],[100,100]]のまま送信される）。
    it("他の軸(recipe_then_breakpoint_linear)を選ぶと材料セレクトが他の軸一覧になり、下ごしらえ・折れ点の編集UIは出ない", async () => {
      const onSave = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      const otherAxes = [baseAxisDefinition({ axis_id: "wind", label: "風" })];
      render(
        <AxisComposer
          editing={null}
          duplicateFrom={null}
          otherAxes={otherAxes}
          onCancelEdit={vi.fn()}
          onSave={onSave}
        />,
      );

      await fillBasics(user, "軸D", /^風$/);

      // 「ほかの軸」も材料の一覧に並ぶ（型が他の軸なら、係数を掛けた合計になる）。
      expect(screen.getByRole("option", { name: "風" })).toBeInTheDocument();
      // 純粋な重み付き結合に絞ったため、点数の変換まわりの編集UIは表示されない。
      expect(screen.queryByText("マイナス側も同じ強さとして扱う")).not.toBeInTheDocument();
      expect(screen.queryByText("何点にするか")).not.toBeInTheDocument();

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
        baseAxisDefinition({ axis_id: "gradient", label: "勾配" }),
        baseAxisDefinition({ axis_id: "wind", label: "風" }),
      ];
      render(
        <AxisComposer
          editing={null}
          duplicateFrom={null}
          otherAxes={otherAxes}
          onCancelEdit={vi.fn()}
          onSave={onSave}
        />,
      );

      await fillBasics(user, "複合軸", /^勾配$/);

      await user.click(screen.getByRole("button", { name: "+ 軸を足して合計する" }));
      const weightInputs = screen.getAllByRole("spinbutton", { name: "係数" });
      await user.clear(weightInputs[0]);
      await user.type(weightInputs[0], "2");
      // 材料セレクトの並びは［点数のもとになるもの, 1件目の行, 2件目の行］。
      await user.selectOptions(screen.getAllByRole("combobox")[2], "wind");

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
      const { user } = renderComposer();

      await fillBasics(user, "軸E");

      // 他の軸が1つも無ければ、材料の一覧に「ほかの軸」のまとまりごと現れない。
      expect(screen.queryByRole("group", { name: "ほかの軸" })).not.toBeInTheDocument();
    });

    it("はい/いいえの材料(categorical)でtrue/falseスコアがmappingになる", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸A", /surface_good/);

      const trueInput = screen.getByRole("spinbutton", { name: "はいのときのスコア" });
      const falseInput = screen.getByRole("spinbutton", { name: "いいえのときのスコア" });
      await user.clear(trueInput);
      await user.type(trueInput, "15");
      await user.clear(falseInput);
      await user.type(falseInput, "85");

      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape).toEqual(categoricalShape("surface_good", { true: 15, false: 85 }));
    });

    it("種類の材料(categorical)で値ごとのスコア行がmappingになり、空行は除外される", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸B");

      await user.selectOptions(screen.getByRole("combobox", { name: "点数のもとになるもの" }), "tracktype");
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

      await user.click(screen.getByRole("button", { name: "作成する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.shape).toEqual(categoricalShape("tracktype", { separated: 60, none: 10 }));
    });

    // 改善計画T397: 旧「複数の要素の有無を数えて減点・加点する」(flag_sum)カードは
    // 数値の材料と同じ形へ吸収された。boolean材料をterms(材料)に追加し、係数(旧points相当)を
    // 入力するだけで同じ結果（terms×breakpoints=[[0,0],[cap,cap]]の恒等クランプ）を
    // 組めることを確認する。
    it("はい/いいえの材料を足し合わせる形で係数をマイナスにできる（旧flag_sumの減点相当）", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸F");

      await user.selectOptions(screen.getByRole("combobox", { name: "点数のもとになるもの" }), "surface_good");
      // はい/いいえの材料は既定では値ごとのスコアになる。減点の配分（-20）を持たせるのは
      // 合計の形なので、そちらへ移ってから係数を入れる。
      await user.click(screen.getByRole("button", { name: "+ 材料を足して合計する" }));

      // 改善計画T547でNumberField化し、"-"のみ入力された中間状態でも消えず最後まで
      // 打ち切れるようになったため、実際のユーザー操作に近いuser.type（1文字ずつ）で
      // 検証する（以前はNumber("-")===NaNで消えるバグを避けfireEvent.changeで一括設定
      // する回避策を取っていた）。
      const weightInput = screen.getByRole("spinbutton", { name: "係数" });
      await user.clear(weightInput);
      await user.type(weightInput, "-20");

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
    it("編集欄を持たない素通しフィールドがすべて、他フィールドの変更だけを経て編集前の値のまま保存される", async () => {
      // すべての素通し対象へ既定値と異なる値を入れる。素通しが1件でも落ちれば、
      // その値はサーバー側の既定値相当（false/"always"/[]）へ静かに戻る。
      const nonDefaultPassthrough: Partial<AxisDefinitionResponse> = {
        priority_overrides: [{ material: "has_tunnel", equals: "true", value: -1000 }],
        time_scope: "night_only",
        dedicated_way_value_layer: true,
        dynamic_way_value_needs_time: true,
        dynamic_way_value_needs_bearing: true,
        dynamic_way_value_needs_speed: true,
      };
      // 素通し対象が増えたらこのテストの入力も増やす（増やさないと既定値同士の比較になり
      // 検出力が落ちるため、リストの網羅自体をここで固定する）。
      expect([...PASSTHROUGH_PAYLOAD_KEYS].sort()).toEqual(Object.keys(nonDefaultPassthrough).sort());

      const editing = baseAxisDefinition(nonDefaultPassthrough);
      const { user, onSave } = renderComposer({ editing });

      // 「基本情報」ステップでラベルと重みだけを変更する。shape・display系の欄には触れない。
      await user.type(screen.getByRole("textbox", { name: "表示名" }), "改");
      const weightInput = screen.getByRole("spinbutton", { name: "既定重み" });
      await user.clear(weightInput);
      await user.type(weightInput, "0.35");
      await user.click(screen.getByRole("button", { name: "更新する" }));

      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload, isNew] = onSave.mock.calls[0];
      // 触った欄はちゃんと変わる（素通しの確認が「何も変わっていないだけ」にならないように）。
      expect(isNew).toBe(false);
      expect(payload.label).toBe("勾配改");
      expect(payload.default_weight).toBeCloseTo(0.35);
      for (const key of PASSTHROUGH_PAYLOAD_KEYS) {
        expect(payload[key]).toEqual(editing[key]);
      }
    });

    it("priority_overridesが空配列の既存軸を編集しても、[]のまま保存され欠落しない", async () => {
      const editing = baseAxisDefinition({ priority_overrides: [] });
      const { user, onSave } = renderComposer({ editing });

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
    it("既定は上書きオフで、「+ しきい値を自分で設定する」を押すとまとめ入力欄が現れる", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸D");

      expect(screen.queryByLabelText("色分けのしきい値（まとめて入力）")).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "1");

      await user.click(screen.getByRole("button", { name: "作成する" }));
      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.display_thresholds_override).toEqual([1]);
    });

    it("境界値をまとめて貼り付けると、1件ずつ足さずに段階が決まる", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸D2");

      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "-10, -5, -1, 1, 2, 3");
      // 段階数（しきい値+1）とレンジが、入力した場で分かる。
      expect(screen.getByLabelText("色分けプレビュー（7段階）")).toBeInTheDocument();
      expect(screen.getByText("-10未満")).toBeInTheDocument();
      expect(screen.getByText("3以上")).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "作成する" }));
      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.display_thresholds_override).toEqual([-10, -5, -1, 1, 2, 3]);
    });

    it("プレビューは親から渡された配色と単位で描き、地図と同じ段階の並びになる", async () => {
      const { user } = renderComposer({
        mapBandColors: (boundaries) => boundaries.map(() => "#111111").concat("#222222"),
        mapValueUnit: "%",
      });

      await fillBasics(user, "軸D3");
      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "1, 4");

      // 単位付きのレンジ表記（地図の凡例と同じbuildRangeLegendBands由来）。
      expect(screen.getByText("1%未満")).toBeInTheDocument();
      expect(screen.getByText("1〜4%")).toBeInTheDocument();
      expect(screen.getByText("4%以上")).toBeInTheDocument();
      const preview = screen.getByLabelText("色分けプレビュー（3段階）");
      const swatchColors = [...preview.querySelectorAll("span[style]")].map((el) => el.getAttribute("style"));
      expect(swatchColors).toEqual(["background: #111111;", "background: #111111;", "background: #222222;"]);
      expect(screen.queryByText(/配色はまだ決まっていません/)).not.toBeInTheDocument();
    });

    it("しきい値を編集でき、「自動計算に戻す」でnullへ戻る", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸E");

      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "1, 4");

      await user.click(screen.getByRole("button", { name: "自動計算に戻す" }));
      expect(screen.queryByLabelText("色分けのしきい値（まとめて入力）")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "作成する" }));
      await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
      const [payload] = onSave.mock.calls[0];
      expect(payload.display_thresholds_override).toBeNull();
    });

    // 改善計画T513: 段階ごとの体感ラベル（display_band_labels_override）は
    // display_thresholds_overrideと対になる軸スタジオ設定可能なフィールド。しきい値の
    // 上書きが無効の間は編集欄自体を出さない（段階数が決まらないため）。
    it("しきい値の上書きが無効の間は体感ラベルの編集欄自体が出ない", async () => {
      renderComposer();

      expect(screen.queryByRole("button", { name: "+ 体感ラベルを設定する" })).not.toBeInTheDocument();
      expect(screen.queryByLabelText("体感ラベル1")).not.toBeInTheDocument();
    });

    it("しきい値の上書きを設定すると体感ラベルの編集欄が使え、段階数ぶんの入力欄が現れ保存される", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸G");

      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "1, 4");
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
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸H");

      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "1");
      await user.click(screen.getByRole("button", { name: "+ 体感ラベルを設定する" }));
      expect(screen.getByLabelText("体感ラベル1")).toBeInTheDocument();
      expect(screen.getByLabelText("体感ラベル2")).toBeInTheDocument();
      expect(screen.queryByLabelText("体感ラベル3")).not.toBeInTheDocument();

      // 段階数が動いたら体感ラベルの件数も追従する（まとめ入力では何段階も一度に動く）。
      await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), ", 4");
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
      const editing = baseAxisDefinition({
        display_thresholds_override: [2],
        display_band_labels_override: ["低い", "高い"],
      });
      renderComposer({ editing });

      expect(screen.getByLabelText("体感ラベル1")).toHaveValue("低い");
      expect(screen.getByLabelText("体感ラベル2")).toHaveValue("高い");
    });

    it("改善計画T513回帰テスト: 複製元のdisplay_band_labels_overrideは複製先へ引き継がずnullへリセットされる", async () => {
      const source = baseAxisDefinition({
        display_thresholds_override: [2],
        display_band_labels_override: ["低い", "高い"],
      });
      renderComposer({ duplicateFrom: source });

      // しきい値自体も複製時にリセットされる（既存の回帰テスト参照）ため、体感ラベルの
      // 編集欄はそもそも出ない（しきい値の上書きが無効のため）。
      expect(screen.queryByRole("button", { name: "+ 体感ラベルを設定する" })).not.toBeInTheDocument();
    });

    it("しきい値が降順・同値だと保存直前の検証でエラーになりステップが進まない", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸F");

      await user.click(screen.getByRole("button", { name: "+ しきい値を自分で設定する" }));
      await user.type(screen.getByLabelText("色分けのしきい値（まとめて入力）"), "4, 1");

      // 入力した場でエラーが出て、そのまま保存もできない（読めない並びで黙って
      // 直前の値を保存しない）。
      expect(screen.getAllByText(/小さい順に並べてください/).length).toBeGreaterThan(0);
      await user.click(screen.getByRole("button", { name: "作成する" }));
      expect(onSave).not.toHaveBeenCalled();
    });

    it("編集中の軸がkind=noneの場合、地図表示用のデータ取得経路が無い旨の注記が出る", async () => {
      const editing = baseAxisDefinition({
        display: {
          kind: "none",
          label: "勾配",
          category: "trafficSafety",
          tile_inputs: [],
          thresholds: [],
          unit: "",
          note: "",
        },
      });
      renderComposer({ editing });

      expect(
        screen.getByText(
          "この軸で使っている材料の一部は、まだ地図表示用のデータ取得経路が用意されていません（ルート探索のコストには反映されます）",
        ),
      ).toBeInTheDocument();
    });

    it("編集中の軸がkind=rampの場合、注記は出ない", async () => {
      const editing = baseAxisDefinition({
        display: {
          kind: "ramp",
          label: "勾配",
          category: "trafficSafety",
          tile_inputs: [
            {
              property: "dummy_per_km",
              weight: 1.0,
              boolean: false,
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
      renderComposer({ editing });

      expect(screen.queryByText(/まだ地図表示用のデータ取得経路が用意されていません/)).not.toBeInTheDocument();
    });

    it("新規作成中（editing=null）は注記を出さない", async () => {
      const { user } = renderComposer();

      await fillBasics(user, "軸G");

      expect(screen.queryByText(/まだ地図表示用のデータ取得経路が用意されていません/)).not.toBeInTheDocument();
    });

    it("既存軸のdisplay_thresholds_overrideがまとめ入力欄へ初期反映される", async () => {
      const editing = baseAxisDefinition({ display_thresholds_override: [1, 2, 4] });
      renderComposer({ editing });

      expect(screen.getByLabelText("色分けのしきい値（まとめて入力）")).toHaveValue("1, 2, 4");
    });

    it("改善計画T501回帰テスト: 複製元のdisplay_thresholds_overrideは複製先へ引き継がず自動計算(null)へリセットされる", async () => {
      const source = baseAxisDefinition({ axis_id: "gradient", display_thresholds_override: [-2, 2, 6, 10] });
      renderComposer({ duplicateFrom: source });

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
      const editing = baseAxisDefinition({ is_published: true });
      renderComposer({ editing });

      expect(screen.getByLabelText("チップの略称")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "次へ" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "戻る" })).not.toBeInTheDocument();
      expect(screen.queryByRole("checkbox", { name: "公開する" })).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "更新する" })).toBeInTheDocument();
    });

    it("表示専用フィールドだけを変更して保存すると、材料・計算式・重み・is_publishedは既存のまま送信される", async () => {
      const editing = baseAxisDefinition({
        is_published: true,
        default_weight: 0.42,
        icon_id: "old_icon",
      });
      const { user, onSave } = renderComposer({ editing });

      await user.type(screen.getByLabelText("チップの略称"), "新称");
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
    it("数値材料の軸を編集で開くと、材料・係数・折れ点が反映される", async () => {
      const editing = baseAxisDefinition({
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
      const { user } = renderComposer({ editing });

      expect(screen.getByRole("combobox", { name: "点数のもとになるもの" })).toHaveValue("gradient_percent");
      // 係数が1でない軸は、合計の形として材料の行が出る。
      expect(screen.getByRole("spinbutton", { name: "係数" })).toHaveValue(3);
      await openBreakpointDetails(user);
      const inputValueInputs = screen.getAllByRole("spinbutton", { name: "入力値" }) as HTMLInputElement[];
      const scoreInputs = screen.getAllByRole("spinbutton", { name: "スコア" }) as HTMLInputElement[];
      expect(inputValueInputs.map((el) => el.valueAsNumber)).toEqual([0, 5]);
      expect(scoreInputs.map((el) => el.valueAsNumber)).toEqual([10, 90]);
    });

    it("他の軸を材料にした軸を編集で開くと、材料の一覧がその軸を指す", async () => {
      // 改善計画T396: 保存済みkindは常にbreakpoint_linearへ統合済みのため、材料一覧に
      // 存在しない参照（wind、材料カタログには無くaxis_idの想定）を使い、構造判定
      // （draftFromExisting）が「他軸参照termsのみ」からこのカードを推定することを確認する。
      const editing = baseAxisDefinition({
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
      render(
        <AxisComposer
          editing={editing}
          duplicateFrom={null}
          otherAxes={[baseAxisDefinition({ axis_id: "wind", label: "風" })]}
          onCancelEdit={vi.fn()}
          onSave={vi.fn()}
        />,
      );

      expect(screen.getByRole("combobox", { name: "点数のもとになるもの" })).toHaveValue("wind");
    });

    it("categorical(boolean材料)軸を編集で開くと、true/falseスコアが反映される", async () => {
      const editing = baseAxisDefinition({
        shape: categoricalShape("has_tunnel", { true: -30, false: 5 }),
      });
      renderComposer({ editing });

      expect(screen.getByRole("combobox", { name: "点数のもとになるもの" })).toHaveValue("has_tunnel");
      expect(screen.getByRole("spinbutton", { name: "はいのときのスコア" })).toHaveValue(-30);
      expect(screen.getByRole("spinbutton", { name: "いいえのときのスコア" })).toHaveValue(5);
    });

    it("categorical(多値材料)軸を編集で開くと、材料選択と値ごとのスコア行が反映される", async () => {
      const editing = baseAxisDefinition({
        shape: categoricalShape("tracktype", { separated: 80, none: -10 }),
      });
      renderComposer({ editing });

      expect(screen.getByRole("combobox", { name: "点数のもとになるもの" })).toHaveValue("tracktype");
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
    // 判別は行わず）数値の材料と同じ形で開き、termsがそのまま反映される。
    it("boolean材料のみのterms（旧flag_sum相当）を編集で開くと、合計の形として係数が反映される", async () => {
      const editing = baseAxisDefinition({
        shape: flagSumShape(
          [
            ["lit", -30],
            ["has_tunnel", -20],
          ],
          50,
        ),
      });
      renderComposer({ editing });

      expect(screen.getByRole("combobox", { name: "点数のもとになるもの" })).toHaveValue("lit");
      const weightInputs = screen.getAllByRole("spinbutton", { name: "係数" });
      expect(weightInputs.map((el) => (el as HTMLInputElement).valueAsNumber)).toEqual([-30, -20]);
    });
  });

  // ============================================================
  // バリデーション
  // ============================================================
  describe("バリデーション", () => {
    it("表示名が空のまま保存しようとすると、保存されずエラーが出る", async () => {
      const { user, onSave } = renderComposer();

      await user.click(screen.getByRole("button", { name: "作成する" }));

      expect(screen.getByText("表示名を入力してください。")).toBeInTheDocument();
      expect(onSave).not.toHaveBeenCalled();
    });

    it("種類の材料で値ごとのスコアを1件も設定しないまま保存しようとすると、保存されずエラーが出る", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸E");
      await user.selectOptions(screen.getByRole("combobox", { name: "点数のもとになるもの" }), "tracktype");
      await user.click(screen.getByRole("button", { name: "作成する" }));

      expect(screen.getByText("値ごとのスコアを少なくとも1件設定してください。")).toBeInTheDocument();
      expect(onSave).not.toHaveBeenCalled();
    });

    it("表示名が4文字を超えchip_labelを未設定のまま保存しようとすると、エラーが出て保存されない", async () => {
      const onSave = vi.fn();
      const { user } = renderComposer({ onSave });

      await fillBasics(user, "とても長い表示名");
      await user.click(screen.getByRole("button", { name: "作成する" }));

      expect(screen.getByText("表示名が4文字を超えています。チップの略称を設定してください。")).toBeInTheDocument();
      expect(onSave).not.toHaveBeenCalled();
    });

    it("表示名が4文字を超えていてもchip_labelを設定すれば保存できる", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "とても長い表示名");
      await user.type(screen.getByRole("textbox", { name: "チップの略称" }), "長い");
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
  describe("画面の構成", () => {
    it("全ての節が1画面に並び、保存ボタンを押すまでonSaveは呼ばれない", async () => {
      const { user, onSave } = renderComposer();

      await fillBasics(user, "軸K");

      // 基本・点数・地図表示のいずれの入力欄も、順送りなしで同時に触れる。
      expect(screen.getByRole("textbox", { name: "表示名" })).toBeInTheDocument();
      expect(screen.getByRole("combobox", { name: "点数のもとになるもの" })).toBeInTheDocument();
      expect(screen.getByText("地図の色分けしきい値(任意)")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "次へ" })).not.toBeInTheDocument();
      expect(onSave).not.toHaveBeenCalled();
    });
  });

  // ============================================================
  // onSave失敗時のエラー表示
  // ============================================================
  describe("保存失敗時の挙動", () => {
    it("onSaveがreject(失敗)すると、そのエラーメッセージが表示され保存ボタンが再び押せる状態に戻る", async () => {
      const onSave = vi.fn().mockRejectedValue(new Error("サーバーで保存に失敗しました"));
      const { user } = renderComposer({ onSave });

      await fillBasics(user, "軸G");
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
      const { user } = renderComposer();

      await fillBasics(user, "軸H");
      // 既定材料はgradient_percent（emptyDraftのmaterialOptions[0]）。
      // 改善計画T345さらなるフォローアップ2: 材料labelは「論理名 - 物理名」形式。
      await user.click(screen.getByRole("button", { name: "勾配（符号付き） - gradient_percentの説明を表示" }));

      expect(screen.getByText(/国土地理院の標高データ/)).toBeInTheDocument();
    });

    it("材料セレクトで別の材料を選ぶと、情報アイコンの説明文もその材料のものに切り替わる", async () => {
      const { user } = renderComposer();

      await fillBasics(user, "軸I");

      const materialSelect = screen.getAllByRole("combobox")[0];
      await user.selectOptions(materialSelect, "surface_good");

      await user.click(screen.getByRole("button", { name: "舗装良否 - surface_goodの説明を表示" }));
      expect(screen.getByText(/OSMの路面タグ\(surface\)/)).toBeInTheDocument();
    });

    it("「必須」チェックボックスの隣の情報アイコンに、欠損時の扱いを説明する文言がある", async () => {
      const { user } = renderComposer();

      await fillBasics(user, "軸J");

      await user.click(screen.getByRole("button", { name: "「必須」の説明を表示" }));
      expect(screen.getByText(/軸全体を「評価不能」として扱います/)).toBeInTheDocument();
    });
  });

  describe("既定重みの相対比較（otherAxes）", () => {
    it("otherAxesを渡すと、公開軸全体の重み合計に対する割合が参考表示される", async () => {
      const user = userEvent.setup();
      const otherAxes = [
        baseAxisDefinition({ axis_id: "gradient", is_published: true, default_weight: 0.3 }),
        baseAxisDefinition({ axis_id: "wind", label: "風", is_published: true, default_weight: 0.1 }),
      ];
      render(
        <AxisComposer
          editing={null}
          duplicateFrom={null}
          otherAxes={otherAxes}
          onCancelEdit={vi.fn()}
          onSave={vi.fn()}
        />,
      );

      await user.type(screen.getByRole("textbox", { name: "表示名" }), "軸K");
      const weightInput = screen.getByRole("spinbutton", { name: "既定重み" });
      await user.clear(weightInput);
      await user.type(weightInput, "0.2");

      // 割合表示は公開する場合のみ意味を持つ（非公開の軸の重みはdefault_axis_weightsから
      // 除外され合成に加わらないため）。1画面なので、同じ画面のチェックを入れるだけでよい。
      await user.click(screen.getByRole("checkbox", { name: "公開する" }));

      // 新規作成軸(0.2) / (0.3+0.1+0.2) = 33.3%
      expect(screen.getByText(/約33\.3%/)).toBeInTheDocument();
    });

    it("非公開のままの軸では、重みが直接使われない旨の注記が出る", async () => {
      const user = userEvent.setup();
      render(
        <AxisComposer editing={null} duplicateFrom={null} otherAxes={[]} onCancelEdit={vi.fn()} onSave={vi.fn()} />,
      );

      await user.type(screen.getByRole("textbox", { name: "表示名" }), "軸L");

      expect(screen.getByText(/現在非公開のため、重みはルート探索へ直接使われません/)).toBeInTheDocument();
    });

    it("otherAxesを渡さない場合は参考表示自体を出さない", async () => {
      const { user } = renderComposer();

      await user.type(screen.getByRole("textbox", { name: "表示名" }), "軸M");

      expect(screen.queryByText(/重みはルート探索へ直接使われません/)).not.toBeInTheDocument();
      expect(screen.queryByText(/の重み合計に対して約/)).not.toBeInTheDocument();
    });
  });
});
