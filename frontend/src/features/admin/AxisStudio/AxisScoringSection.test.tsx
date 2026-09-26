/**
 * `AxisScoringSection.tsx`——「点数の決め方」の節: 選んだもの（数値・真偽・種類の材料、ほかの軸）の型で下書きの形を
 * 組み替え、その形の入力欄だけを出すこと。
 *
 * 材料・軸は性質だけを持つ架空のもの。値の候補は取得の応答（`getMaterialValues`）を差し替えて与え、候補あり・
 * 空・出せなかったの3経路をこの節の中で見る。分布の取得（`useAxisValueDistribution`）は差し替えて、何を渡したかを見る。
 * 分布の表示・曲線エディタ・材料の分位の1行は子の部品で、ここでは何を渡したかだけを見る。
 *
 * ここで見ないもの:
 * - 折れ点の生成・補間・追加位置の計算 → `breakpointTools.test.ts`（期待値はそこの関数から引く）
 * - 下書きから送る形の組み立て → `axisDraft.test.ts`
 * - 保存前の検証 → `AxisComposer.test.tsx`
 */
import { useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import type { MaterialValuesResponse } from "@/types/route";

import { buildShape, emptyDraft, type Draft } from "./axisDraft";
import { generateBreakpoints, insertBreakpointAtLargestGap } from "./breakpointTools";

const api = vi.hoisted(() => ({ getMaterialValues: vi.fn() }));
vi.mock("@/features/admin/adminApi", () => ({ getMaterialValues: api.getMaterialValues }));

const captured = vi.hoisted(() => ({
  distributionArgs: [] as [boolean, string, () => unknown][],
  distributionResult: { distribution: null, loading: false, error: null } as {
    distribution: unknown;
    loading: boolean;
    error: string | null;
  },
  preview: null as Record<string, unknown> | null,
  curve: null as Record<string, unknown> | null,
  scoresRequest: null as unknown,
  scoresPreview: null as { scores: number[]; material_points: { x: number; score: number }[] } | null,
}));
// 点数と参考点の横軸の値はbackendが返す（`useScoresPreview`）。ここでは決まった値を返させ、画面がそれを
// そのまま使うことと、問い合わせに渡すものを見る。
vi.mock("@/features/admin/useScoresPreview", () => ({
  useScoresPreview: (request: unknown) => {
    captured.scoresRequest = request;
    return captured.scoresPreview;
  },
}));
vi.mock("@/features/admin/useAxisValueDistribution", () => ({
  useAxisValueDistribution: (enabled: boolean, key: string, shape: () => unknown) => {
    captured.distributionArgs.push([enabled, key, shape]);
    return captured.distributionResult;
  },
}));
vi.mock("./DistributionPreview", () => ({
  DistributionPreview: (props: Record<string, unknown>) => {
    captured.preview = props;
    return null;
  },
}));
vi.mock("./BreakpointCurveEditor", () => ({
  BreakpointCurveEditor: (props: Record<string, unknown>) => {
    captured.curve = props;
    return null;
  },
}));
vi.mock("./MaterialRangeHint", () => ({
  MaterialRangeHint: ({ materialId, unit }: { materialId: string; unit?: string }) => (
    <p data-testid="range-hint">{`${materialId}:${unit ?? ""}`}</p>
  ),
}));

import { AxisScoringSection } from "./AxisScoringSection";

function option(overrides: Partial<AxisMaterialOption> & Pick<AxisMaterialOption, "id" | "dtype">): AxisMaterialOption {
  return { label: overrides.id, name: overrides.id, description: `${overrides.id}の説明文`, unit: "", ...overrides };
}

const NUM = option({
  id: "num_a",
  dtype: "numeric",
  unit: "km/h",
  referencePoints: [
    { label: "下り", value: -5 },
    { label: "平坦", value: 30 },
  ],
});
const NUM_PLAIN = option({ id: "num_b", dtype: "numeric" });
const BOOL = option({ id: "bool_a", dtype: "boolean" });
const CAT = option({ id: "cat_a", dtype: "categorical" });
const MATERIALS = [NUM, NUM_PLAIN, BOOL, CAT];
const AXIS = option({ id: "axis_other", dtype: "numeric" });

/** 参考点ごとにbackendが返す横軸の値と点数（参考点の並びどおり）。 */
const REFERENCE_POINTS = [
  { x: 10, score: 12.5 },
  { x: 60, score: 87.5 },
];

beforeEach(() => {
  captured.scoresPreview = { scores: [], material_points: REFERENCE_POINTS };
});

function Harness({ initial, axes }: { initial: Draft; axes: readonly AxisMaterialOption[] }) {
  const [draft, setDraft] = useState(initial);
  return (
    <>
      <output data-testid="draft">{JSON.stringify(draft)}</output>
      <AxisScoringSection draft={draft} setDraft={setDraft} materialOptions={MATERIALS} axisTermOptions={axes} />
    </>
  );
}

function linearDraft(overrides: Partial<Draft> = {}): Draft {
  return {
    ...emptyDraft(MATERIALS),
    shapeKind: "breakpoint_linear",
    terms: [{ material: NUM.id, weight: 1, required: true }],
    ...overrides,
  };
}

function categoricalDraft(material: string, overrides: Partial<Draft> = {}): Draft {
  return { ...emptyDraft(MATERIALS), shapeKind: "categorical", categoricalMaterial: material, ...overrides };
}

function renderSection(initial: Draft, axes: readonly AxisMaterialOption[] = [AXIS]) {
  const user = userEvent.setup();
  render(<Harness initial={initial} axes={axes} />);
  return user;
}

function draft(): Draft {
  return JSON.parse(screen.getByTestId("draft").textContent!);
}

const primarySelect = () => screen.getByRole("combobox", { name: "点数のもとになるもの" });

function valuesResponse(values: string[], available = true): MaterialValuesResponse {
  return { available, values: values.map((value) => ({ value, label: `${value}のラベル` })) };
}

beforeEach(() => {
  api.getMaterialValues.mockReset();
  api.getMaterialValues.mockResolvedValue(valuesResponse([]));
  captured.distributionArgs = [];
  captured.distributionResult = { distribution: null, loading: false, error: null };
  captured.preview = null;
  captured.curve = null;
});

describe("点数のもとになるもの", () => {
  it("材料を数値と、はい/いいえ・種類に分け、ほかの軸があればその群も置く", () => {
    renderSection(linearDraft());
    const groups = Object.fromEntries(
      Array.from(primarySelect().querySelectorAll("optgroup")).map((group) => [
        group.label,
        Array.from(group.querySelectorAll("option")).map((o) => o.value),
      ]),
    );
    expect(Object.values(groups)).toEqual([[NUM.id, NUM_PLAIN.id], [BOOL.id, CAT.id], [AXIS.id]]);
  });

  it("ほかの軸が無ければ、その群を置かない", () => {
    renderSection(linearDraft(), []);
    expect(primarySelect().querySelectorAll("optgroup")).toHaveLength(2);
  });

  it("選んでいるものは、折れ線なら最初の項の材料、はい/いいえ・種類なら点数の材料", () => {
    renderSection(linearDraft({ terms: [{ material: NUM_PLAIN.id, weight: 1, required: true }] }));
    expect(primarySelect()).toHaveValue(NUM_PLAIN.id);
  });

  it("ほかの軸を選ぶと、その軸1つを係数1で足し合わせる形にし、下ごしらえと折れ点は既定へ戻す", async () => {
    const user = renderSection(linearDraft({ preprocess: "abs", breakpoints: [[1, 2]] }));
    await user.selectOptions(primarySelect(), AXIS.id);
    expect(draft()).toMatchObject({
      shapeKind: "recipe_then_breakpoint_linear",
      terms: [{ material: AXIS.id, weight: 1, required: true }],
      preprocess: "identity",
      breakpoints: [
        [0, 0],
        [100, 100],
      ],
    });
  });

  it("真偽の材料を選ぶと、はい/いいえの点数の形にし、値ごとの行には触れない", async () => {
    const user = renderSection(linearDraft());
    await user.selectOptions(primarySelect(), BOOL.id);
    expect(draft()).toMatchObject({ shapeKind: "categorical", categoricalMaterial: BOOL.id, categoricalRows: [] });
  });

  it("種類の材料を選ぶと、値ごとの行が無ければ空の行を1つ用意する", async () => {
    const user = renderSection(linearDraft());
    await user.selectOptions(primarySelect(), CAT.id);
    expect(draft()).toMatchObject({ shapeKind: "categorical", categoricalMaterial: CAT.id });
    expect(draft().categoricalRows).toEqual([{ value: "", score: 0 }]);
  });

  it("種類の材料を選んだとき、値ごとの行が既にあれば残す", async () => {
    const user = renderSection(linearDraft({ categoricalRows: [{ value: "a", score: 5 }] }));
    await user.selectOptions(primarySelect(), CAT.id);
    expect(draft().categoricalRows).toEqual([{ value: "a", score: 5 }]);
  });

  it("折れ線のまま別の数値材料を選ぶと、材料だけを入れ替え、係数と折れ点は保つ", async () => {
    const breakpoints: [number, number][] = [
      [3, 10],
      [7, 90],
    ];
    const user = renderSection(linearDraft({ terms: [{ material: NUM.id, weight: 2, required: false }], breakpoints }));
    await user.selectOptions(primarySelect(), NUM_PLAIN.id);
    expect(draft().terms).toEqual([{ material: NUM_PLAIN.id, weight: 2, required: false }]);
    expect(draft().breakpoints).toEqual(breakpoints);
  });

  it("項が2つある折れ線で数値材料を選ぶと、先頭の項の材料だけを入れ替える", async () => {
    const terms = [
      { material: NUM.id, weight: 1, required: true },
      { material: BOOL.id, weight: 3, required: false },
    ];
    const user = renderSection(linearDraft({ terms }));
    await user.selectOptions(primarySelect(), NUM_PLAIN.id);
    expect(draft().terms).toEqual([{ ...terms[0], material: NUM_PLAIN.id }, terms[1]]);
  });

  it("ほかの形から数値材料を選ぶと、その材料1つの折れ線にし、折れ点は既定へ戻す", async () => {
    const user = renderSection(categoricalDraft(BOOL.id));
    await user.selectOptions(primarySelect(), NUM_PLAIN.id);
    expect(draft()).toMatchObject({
      shapeKind: "breakpoint_linear",
      terms: [{ material: NUM_PLAIN.id, weight: 1, required: true }],
      breakpoints: [
        [0, 0],
        [10, 100],
      ],
    });
  });
});

describe("折れ線の形", () => {
  it("項が1つなら、その項の「必須」を材料の横で切り替えられる", async () => {
    const user = renderSection(linearDraft());
    await user.click(screen.getByRole("checkbox", { name: "必須" }));
    expect(draft().terms[0].required).toBe(false);
  });

  it("単一の数値材料・係数1なら、項の行を出さない（係数は0点・100点の値へ吸収される）", () => {
    renderSection(linearDraft());
    expect(screen.queryByRole("slider", { name: "係数(スライダー)" })).not.toBeInTheDocument();
  });

  it.each([
    ["係数が1でない", { terms: [{ material: NUM.id, weight: 2, required: true }] }],
    ["真偽の材料を足し合わせる", { terms: [{ material: BOOL.id, weight: 1, required: true }] }],
    [
      "項が2つ以上ある",
      {
        terms: [
          { material: NUM.id, weight: 1, required: true },
          { material: NUM_PLAIN.id, weight: 1, required: true },
        ],
      },
    ],
  ])("%sなら、項ごとの行（材料・係数・必須・削除・分位）を出す", (_case, overrides) => {
    renderSection(linearDraft(overrides as Partial<Draft>));
    const draftTerms = (overrides as Partial<Draft>).terms!;
    expect(screen.getAllByRole("slider", { name: "係数(スライダー)" })).toHaveLength(draftTerms.length);
    expect(screen.getAllByTestId("range-hint").map((hint) => hint.textContent)).toEqual(
      draftTerms.map((term) => `${term.material}:${MATERIALS.find((m) => m.id === term.material)!.unit}`),
    );
  });

  it("項の行の材料の候補は、数値と真偽の材料だけ（種類の材料は掛け算できない）", () => {
    renderSection(linearDraft({ terms: [{ material: NUM.id, weight: 2, required: true }] }));
    const rowSelect = screen.getAllByRole("combobox").find((select) => select !== primarySelect())!;
    const values = Array.from(rowSelect.querySelectorAll("option")).map((o) => o.value);
    expect(values).toEqual([NUM.id, NUM_PLAIN.id, BOOL.id]);
  });

  it("項の係数・必須・材料を変えられ、項が1つのときは削除できず、2つ以上なら削除できる", async () => {
    const user = renderSection(
      linearDraft({
        terms: [
          { material: NUM.id, weight: 1, required: true },
          { material: NUM_PLAIN.id, weight: 1, required: true },
        ],
      }),
    );
    fireEvent.change(screen.getAllByRole("slider", { name: "係数(スライダー)" })[1], { target: { value: "-2" } });
    await user.click(screen.getAllByRole("checkbox", { name: "必須" })[1]);
    const rowSelects = screen.getAllByRole("combobox").filter((select) => select !== primarySelect());
    await user.selectOptions(rowSelects[1], BOOL.id);
    expect(draft().terms[1]).toEqual({ material: BOOL.id, weight: -2, required: false });

    const termDeletes = () =>
      screen.getAllByRole("button", { name: "削除" }).filter((button) => button.closest("details") === null);
    await user.click(termDeletes()[0]);
    expect(draft().terms.map((t) => t.material)).toEqual([BOOL.id]);
    expect(termDeletes()).toHaveLength(1);
    expect(termDeletes()[0]).toBeDisabled();
  });

  it("材料を足すと、候補の先頭を必須でない係数1の項として足す", async () => {
    const user = renderSection(linearDraft());
    await user.click(screen.getByRole("button", { name: "+ 材料を足して合計する" }));
    expect(draft().terms.at(-1)).toEqual({ material: NUM.id, weight: 1, required: false });
  });

  it("ほかの軸を組み合わせる形では、軸を足す口を置き、候補の先頭の軸を足す。項の行に分位は出さない", async () => {
    const user = renderSection(
      linearDraft({
        shapeKind: "recipe_then_breakpoint_linear",
        terms: [{ material: AXIS.id, weight: 2, required: true }],
      }),
    );
    await user.click(screen.getByRole("button", { name: "+ 軸を足して合計する" }));
    expect(draft().terms.at(-1)).toEqual({ material: AXIS.id, weight: 1, required: false });
    expect(screen.queryByTestId("range-hint")).not.toBeInTheDocument();
  });

  it("組み合わせられる軸が無ければ、そう言い、軸を足す口を押せない", () => {
    renderSection(linearDraft({ shapeKind: "recipe_then_breakpoint_linear", terms: [] }), []);
    expect(screen.getByText(/組み合わせられる他の軸がまだありません/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ 軸を足して合計する" })).toBeDisabled();
  });

  it("ほかの軸を組み合わせる形では、下ごしらえ・0点100点・折れ点の入力欄を出さない", () => {
    renderSection(linearDraft({ shapeKind: "recipe_then_breakpoint_linear", terms: [] }));
    expect(screen.queryByRole("checkbox", { name: "マイナス側も同じ強さとして扱う" })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton", { name: "0点にする値" })).not.toBeInTheDocument();
    expect(screen.queryByText("折れ点を直接いじる")).not.toBeInTheDocument();
  });

  it("「マイナス側も同じ強さとして扱う」で、下ごしらえを絶対値と恒等で切り替える", async () => {
    const user = renderSection(linearDraft());
    const abs = screen.getByRole("checkbox", { name: "マイナス側も同じ強さとして扱う" });
    await user.click(abs);
    expect(draft().preprocess).toBe("abs");
    await user.click(abs);
    expect(draft().preprocess).toBe("identity");
  });
});

describe("0点・100点・効き方", () => {
  it("欄は、いまの折れ点から復元した値で始まる", () => {
    renderSection(linearDraft({ breakpoints: generateBreakpoints(40, 5, "front_loaded") }));
    expect(screen.getByRole("spinbutton", { name: "0点にする値" })).toHaveValue(40);
    expect(screen.getByRole("spinbutton", { name: "100点にする値" })).toHaveValue(5);
    expect(screen.getByRole("combobox", { name: "効き方" })).toHaveValue("front_loaded");
  });

  it("どれかを変えると、3つの値から折れ点を作り直す", async () => {
    const user = renderSection(linearDraft({ breakpoints: generateBreakpoints(0, 10, "flat") }));
    const zero = screen.getByRole("spinbutton", { name: "0点にする値" });
    await user.clear(zero);
    await user.type(zero, "4");
    expect(draft().breakpoints).toEqual(generateBreakpoints(4, 10, "flat"));

    await user.selectOptions(screen.getByRole("combobox", { name: "効き方" }), "s_curve");
    expect(draft().breakpoints).toEqual(generateBreakpoints(4, 10, "s_curve"));

    const hundred = screen.getByRole("spinbutton", { name: "100点にする値" });
    await user.clear(hundred);
    await user.type(hundred, "20");
    expect(draft().breakpoints).toEqual(generateBreakpoints(4, 20, "s_curve"));
  });

  it("0点と100点が同じ値になるときは、折れ点を作り直さない", async () => {
    const before = generateBreakpoints(0, 10, "flat");
    const user = renderSection(linearDraft({ breakpoints: before }));
    const zero = screen.getByRole("spinbutton", { name: "0点にする値" });
    await user.clear(zero);
    await user.type(zero, "10");
    expect(draft().breakpoints).toEqual(generateBreakpoints(1, 10, "flat"));
  });

  it("材料に参考点があれば、押すと0点・2回押すと100点へ、backendが返した横軸の値で入れる", async () => {
    const user = renderSection(linearDraft());
    const group = screen.getByRole("group", { name: "参考点から値を選ぶ" });
    const downhill = within(group).getByRole("button", { name: "下り" });
    expect(downhill).toHaveAttribute("title", "下り: -5km/h");

    await user.click(within(group).getByRole("button", { name: "平坦" }));
    expect(screen.getByRole("spinbutton", { name: "0点にする値" })).toHaveValue(REFERENCE_POINTS[1].x);

    await user.dblClick(downhill);
    expect(screen.getByRole("spinbutton", { name: "100点にする値" })).toHaveValue(REFERENCE_POINTS[0].x);
  });

  it("点数が届くまでは、参考点のボタンと効き目の表を出さない", () => {
    captured.scoresPreview = null;
    renderSection(linearDraft());
    expect(screen.queryByRole("group", { name: "参考点から値を選ぶ" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it.each([
    ["参考点の無い材料", linearDraft({ terms: [{ material: NUM_PLAIN.id, weight: 1, required: true }] })],
    [
      "項が2つある",
      linearDraft({
        terms: [
          { material: NUM.id, weight: 1, required: true },
          { material: NUM_PLAIN.id, weight: 1, required: true },
        ],
      }),
    ],
  ])("%sなら、参考点のボタンと効き目の表を出さない", (_case, initial) => {
    renderSection(initial);
    expect(screen.queryByRole("group", { name: "参考点から値を選ぶ" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("効き目の表は、参考点ごとに値と、backendが返した点数を出す", () => {
    renderSection(linearDraft());

    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(
      rows.map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      ),
    ).toEqual(NUM.referencePoints!.map((p, i) => [p.label, `${p.value}km/h`, String(REFERENCE_POINTS[i].score)]));
  });

  it("点数の問い合わせには、今の形・分布の階級の代表値・参考点の値を渡し、折れ線でなければ問い合わせない", () => {
    captured.distributionResult = {
      distribution: { sample_ways: 1, total_km: 1, quantiles: {}, bins: [[0, 2, 1]], zero_share: 0 },
      loading: false,
      error: null,
    };
    const { unmount } = render(<Harness initial={linearDraft()} axes={[]} />);
    expect(captured.scoresRequest).toEqual({
      shape: buildShape(draft(), MATERIALS),
      xs: [1],
      material_values: NUM.referencePoints!.map((p) => p.value),
    });
    unmount();
    captured.distributionResult = { distribution: null, loading: false, error: null };

    renderSection(categoricalDraft(BOOL.id));
    expect(captured.scoresRequest).toBeNull();
  });
});

describe("分布と折れ点の直接編集", () => {
  it("分布の取得には、折れ線のときだけ、材料・係数・必須・下ごしらえで決まる鍵を渡し、今の形を送る", async () => {
    const user = renderSection(linearDraft());
    const [enabled, key, shape] = captured.distributionArgs.at(-1)!;
    expect(enabled).toBe(true);
    expect(key).not.toBe("");
    expect(shape()).toEqual(buildShape(draft(), MATERIALS));

    await user.selectOptions(screen.getByRole("combobox", { name: "効き方" }), "s_curve");
    expect(captured.distributionArgs.at(-1)![1]).toBe(key);

    await user.click(screen.getByRole("checkbox", { name: "マイナス側も同じ強さとして扱う" }));
    expect(captured.distributionArgs.at(-1)![1]).not.toBe(key);
  });

  it.each([
    ["はい/いいえ", categoricalDraft(BOOL.id)],
    ["ほかの軸を組み合わせる", linearDraft({ shapeKind: "recipe_then_breakpoint_linear", terms: [] })],
  ])("%sの形では、分布を取りに行かない", (_case, initial) => {
    renderSection(initial);
    expect(captured.distributionArgs.at(-1)!.slice(0, 2)).toEqual([false, ""]);
  });

  it("分布の表示へ、取得の結果と、backendが返した階級ごとの点数を渡す", () => {
    captured.distributionResult = { distribution: { sample_ways: 1 }, loading: true, error: "e" };
    captured.scoresPreview = { scores: [40, 60], material_points: [] };
    renderSection(linearDraft());
    expect(captured.preview).toEqual({
      distribution: { sample_ways: 1 },
      loading: true,
      error: "e",
      binScores: [40, 60],
    });
  });

  it("曲線エディタの横軸は、backendが返した参考点の横軸の値の範囲で固定し、参考点が無ければ固定しない", () => {
    const { unmount } = render(<Harness initial={linearDraft()} axes={[]} />);
    expect(captured.curve!.referenceRange).toEqual({ min: REFERENCE_POINTS[0].x, max: REFERENCE_POINTS[1].x });
    unmount();

    render(
      <Harness initial={linearDraft({ terms: [{ material: NUM_PLAIN.id, weight: 1, required: true }] })} axes={[]} />,
    );
    expect(captured.curve!.referenceRange).toBeUndefined();
  });

  it("曲線エディタで動かした点を、その折れ点の横軸・スコアへ入れる", async () => {
    renderSection(
      linearDraft({
        breakpoints: [
          [0, 0],
          [10, 100],
        ],
      }),
    );
    type OnChangePoint = (index: number, pos: 0 | 1, value: number) => void;
    act(() => (captured.curve!.onChangePoint as OnChangePoint)(1, 0, 12));
    expect(draft().breakpoints).toEqual([
      [0, 0],
      [12, 100],
    ]);
    act(() => (captured.curve!.onChangePoint as OnChangePoint)(0, 1, 5));
    expect(draft().breakpoints[0]).toEqual([0, 5]);
  });

  it("折れ点の行で入力値・スコアを直せ、2点のときは削除できず、追加は最も広い間隔の中点へ入る", async () => {
    const user = renderSection(
      linearDraft({
        breakpoints: [
          [0, 0],
          [10, 100],
        ],
      }),
    );
    await user.click(screen.getByText("折れ点を直接いじる"));
    const inputs = screen.getAllByRole("spinbutton", { name: "入力値" });
    await user.clear(inputs[1]);
    await user.type(inputs[1], "20");
    const scores = screen.getAllByRole("spinbutton", { name: "スコア" });
    await user.clear(scores[0]);
    await user.type(scores[0], "5");
    expect(draft().breakpoints).toEqual([
      [0, 5],
      [20, 100],
    ]);

    const rowDeletes = () =>
      screen.getAllByRole("button", { name: "削除" }).filter((button) => button.closest("details") !== null);
    expect(rowDeletes()).not.toHaveLength(0);
    expect(rowDeletes().every((button) => button.hasAttribute("disabled"))).toBe(true);

    await user.click(screen.getByRole("button", { name: "+ 折れ点を追加" }));
    expect(draft().breakpoints).toEqual(
      insertBreakpointAtLargestGap([
        [0, 5],
        [20, 100],
      ]),
    );
    await user.click(rowDeletes()[1]);
    expect(draft().breakpoints).toEqual([
      [0, 5],
      [20, 100],
    ]);
  });
});

describe("はい/いいえ・種類の形", () => {
  it("「材料を足して合計する」で、点数の材料を係数1の項にした折れ線（0→0点・1→100点）へ移る", async () => {
    const user = renderSection(categoricalDraft(BOOL.id));
    await user.click(screen.getByRole("button", { name: "+ 材料を足して合計する" }));
    expect(draft()).toMatchObject({
      shapeKind: "breakpoint_linear",
      terms: [{ material: BOOL.id, weight: 1, required: true }],
      breakpoints: [
        [0, 0],
        [1, 100],
      ],
    });
  });

  it("真偽の材料は、該当時・非該当時の点数を入れる。値の候補は取りに行かない", () => {
    renderSection(categoricalDraft(BOOL.id, { trueScore: 0, falseScore: 0 }));
    fireEvent.change(screen.getByRole("slider", { name: "はいのときのスコア(スライダー)" }), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByRole("slider", { name: "いいえのときのスコア(スライダー)" }), {
      target: { value: "-20" },
    });
    expect(draft()).toMatchObject({ trueScore: 30, falseScore: -20 });
    expect(api.getMaterialValues).not.toHaveBeenCalled();
  });

  it("種類の材料で値の候補が取れたら、値は候補からだけ選べ、値はラベルで出す（候補に無い値はそのまま）。選んだときは生の値を入れる", async () => {
    api.getMaterialValues.mockResolvedValue(valuesResponse(["primary", "track"]));
    const user = renderSection(
      categoricalDraft(CAT.id, {
        categoricalRows: [
          { value: "track", score: 10 },
          { value: "legacy", score: 20 },
        ],
      }),
    );

    const candidates = await screen.findAllByRole("combobox", { name: "値の候補" });
    expect(api.getMaterialValues).toHaveBeenCalledWith(CAT.id);
    const values = screen.getAllByRole("textbox", { name: "値" });
    expect(values.map((input) => (input as HTMLInputElement).value)).toEqual(["trackのラベル", "legacy"]);
    expect(values.every((input) => input.hasAttribute("readonly"))).toBe(true);

    await user.selectOptions(candidates[1], "primary");
    expect(draft().categoricalRows[1].value).toBe("primary");
  });

  it("種類の材料で候補が0件なら、値を自由に打てる", async () => {
    api.getMaterialValues.mockResolvedValue(valuesResponse([]));
    const user = renderSection(categoricalDraft(CAT.id, { categoricalRows: [{ value: "", score: 0 }] }));
    await waitFor(() => expect(api.getMaterialValues).toHaveBeenCalled());

    const value = screen.getByRole("textbox", { name: "値" });
    expect(value).not.toHaveAttribute("readonly");
    await user.type(value, "separated");
    expect(draft().categoricalRows[0].value).toBe("separated");
    expect(screen.queryByRole("combobox", { name: "値の候補" })).not.toBeInTheDocument();
  });

  it("種類の材料で候補を出せなかったら、値を自由に打て、説明にその理由を出す", async () => {
    api.getMaterialValues.mockResolvedValue(valuesResponse([], false));
    const user = renderSection(categoricalDraft(CAT.id, { categoricalRows: [{ value: "", score: 0 }] }));
    await waitFor(() => expect(api.getMaterialValues).toHaveBeenCalled());

    await user.type(screen.getByRole("textbox", { name: "値" }), "x");
    expect(draft().categoricalRows[0].value).toBe("x");
    await user.click(screen.getByRole("button", { name: /値ごとのスコアの説明/ }));
    expect(await screen.findByText(/候補を取得できませんでした/)).toBeInTheDocument();
  });

  it("値ごとの行の点数を変えられ、行を足せ、1行のときは削除できない", async () => {
    const user = renderSection(categoricalDraft(CAT.id, { categoricalRows: [{ value: "a", score: 0 }] }));
    await waitFor(() => expect(api.getMaterialValues).toHaveBeenCalled());

    fireEvent.change(screen.getByRole("slider", { name: "スコア(スライダー)" }), { target: { value: "45" } });
    expect(draft().categoricalRows[0].score).toBe(45);
    expect(screen.getByRole("button", { name: "削除" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "+ 値を追加" }));
    expect(draft().categoricalRows).toEqual([
      { value: "a", score: 45 },
      { value: "", score: 0 },
    ]);
    await user.click(screen.getAllByRole("button", { name: "削除" })[0]);
    expect(draft().categoricalRows).toEqual([{ value: "", score: 0 }]);
  });
});
