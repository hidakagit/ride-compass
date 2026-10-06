/**
 * `AxisScoringSection.tsx`——「点数の決め方」の節: 選んだもの（数値・真偽・種類の材料、ほかの軸）の型で下書きの形を
 * 組み替え、その形の入力欄だけを出すこと。取れた分布・点数・材料の分位・値の候補を、どの欄へどう出すか。
 *
 * 材料・軸は性質だけを持つ架空のもの。子の部品（分布の表示・曲線エディタ・材料の分位の1行）と取得のフックは本物を通し、
 * backendの応答（網の層）だけを与える。点数の応答は、送られた参考点の値と分布の階級の代表値から決まる値を返す。
 *
 * ここで見ないもの:
 * - 折れ点の生成・補間・追加位置の計算 → `breakpointTools.test.ts`（期待値はそこの関数から引く）
 * - 下書きから送る形の組み立て → `axisDraft.test.ts`
 * - 保存前の検証 → `AxisComposer.test.tsx`
 * - 子の部品の表示の決め方・取得の待ち方 → 子の部品とフックのテスト
 * - 読むだけの問い合わせへ送ったか・何を送ったか（応答を与えるだけにする）
 */
import { useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import type { getMaterialValues, ScoresPreviewRequest } from "@/features/admin/adminApi";
import { heldReplies, onSameOrigin } from "@/testing/backendServer";
import type { AxisShape } from "@/types/route";

import { emptyDraft, type Draft } from "./axisDraft";
import { generateBreakpoints, insertBreakpointAtLargestGap } from "./breakpointTools";
import { AxisScoringSection } from "./AxisScoringSection";
import { scoreBands, type ValueDistribution } from "./scoreDistribution";

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

const PREVIEW_DISTRIBUTION = "/admin/api/axis-definitions/preview-distribution";
const PREVIEW_SCORES = "/admin/api/axis-definitions/preview-scores";

/** 送られた形の分布。1階級だけを持ち、抽選の本数で下ごしらえを見分けられるようにする。 */
function distributionOf(shape: AxisShape): ValueDistribution {
  const sampleWays = "preprocess" in shape && shape.preprocess === "abs" ? 222 : 111;
  return { sample_ways: sampleWays, total_km: 1, quantiles: {}, bins: [[0, 2, 1]] };
}

/** 参考点の値ごとにbackendが返す横軸の値と点数。 */
const pointOf = (value: number) => ({ x: value * 2, score: value + 0.5 });
/** 分布の階級の代表値ごとにbackendが返す点数。 */
const binScoreOf = (x: number) => x * 40;

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
const effectRegion = () => screen.getByRole("region", { name: "折れ点の効き方" });

type MaterialValuesResponse = Awaited<ReturnType<typeof getMaterialValues>>;

function valuesResponse(values: string[], available = true): MaterialValuesResponse {
  return { available, values: values.map((value) => ({ value, label: `${value}のラベル` })) };
}

/** 材料`materialId`の値の候補の取得に`response`を返す（ほかの材料には候補0件）。 */
function serveValues(materialId: string, response: MaterialValuesResponse) {
  onSameOrigin("GET", "/admin/api/material-catalog/:materialId/values", ({ path }) =>
    Response.json(path.endsWith(`/${materialId}/values`) ? response : valuesResponse([])),
  );
}

/** 取得の応答が届くだけの間をおく（出ないことを確かめるため。届いた値を確かめるときは、その値が出るまで待つ。届くまでの
 * 時間は CI の負荷で変わる）。 */
const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 50)));

/** 点数は、分布が届いて階級の代表値が決まると、入力が落ち着くのを待って取り直す。その答えが届くまで待つ。 */
const LATER = { timeout: 2000 };
const scoresArrived = () => within(effectRegion()).findByText("100.0%", undefined, LATER);

beforeEach(() => {
  serveValues("", valuesResponse([]));
  onSameOrigin("POST", PREVIEW_DISTRIBUTION, ({ body }) =>
    Response.json(distributionOf((body as { shape: AxisShape }).shape)),
  );
  onSameOrigin("POST", PREVIEW_SCORES, ({ body }) => {
    const { xs, material_values } = body as Required<ScoresPreviewRequest>;
    return Response.json({ scores: xs.map(binScoreOf), material_points: material_values.map(pointOf) });
  });
  // 材料の分位の中央値に、材料の並びの番号を返す（どの材料の分位かを画面で見分けるため）。
  onSameOrigin("GET", "/admin/api/material-catalog/:materialId/distribution", ({ path }) =>
    Response.json({
      available: true,
      quantiles: { p50: MATERIALS.findIndex((m) => path.includes(`/${m.id}/`)) },
      zero_share: 0,
    }),
  );
});

describe("点数のもとになるもの", () => {
  it.each([
    ["ほかの軸があれば、その群も置く", [AXIS], [[NUM.id, NUM_PLAIN.id], [BOOL.id, CAT.id], [AXIS.id]]],
    [
      "ほかの軸が無ければ、その群を置かない",
      [],
      [
        [NUM.id, NUM_PLAIN.id],
        [BOOL.id, CAT.id],
      ],
    ],
  ])("材料を数値と、はい/いいえ・種類に分け、%s", (_case, axes, groups) => {
    renderSection(linearDraft(), axes);
    const options = Array.from(primarySelect().querySelectorAll("optgroup")).map((group) =>
      Array.from(group.querySelectorAll("option")).map((o) => o.value),
    );
    expect(options).toEqual(groups);
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

  it.each([
    ["真偽の材料を選ぶと、値ごとの行には触れない", BOOL, [], []],
    ["種類の材料を選ぶと、値ごとの行が無ければ空の行を1つ用意する", CAT, [], [{ value: "", score: 0 }]],
    ["種類の材料を選んだとき、値ごとの行が既にあれば残す", CAT, [{ value: "a", score: 5 }], [{ value: "a", score: 5 }]],
  ])("%s", async (_case, material, rows, expected) => {
    const user = renderSection(linearDraft({ categoricalRows: rows }));
    await user.selectOptions(primarySelect(), material.id);
    expect(draft()).toMatchObject({
      shapeKind: "categorical",
      categoricalMaterial: material.id,
      categoricalRows: expected,
    });
  });

  it("折れ線のまま別の数値材料を選ぶと、先頭の項の材料だけを入れ替え、係数と折れ点は保つ", async () => {
    const terms = [
      { material: NUM.id, weight: 2, required: false },
      { material: BOOL.id, weight: 3, required: false },
    ];
    const breakpoints: [number, number][] = [
      [3, 10],
      [7, 90],
    ];
    const user = renderSection(linearDraft({ terms, breakpoints }));
    await user.selectOptions(primarySelect(), NUM_PLAIN.id);
    expect(draft().terms).toEqual([{ ...terms[0], material: NUM_PLAIN.id }, terms[1]]);
    expect(draft().breakpoints).toEqual(breakpoints);
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

  it.each([
    ["単一の数値材料・係数1なら出さない（係数は0点・100点の値へ吸収される）", [{ material: NUM.id, weight: 1 }], []],
    ["係数が1でなければ出す", [{ material: NUM.id, weight: 2 }], ["p50=0 (km/h)"]],
    ["真偽の材料を足し合わせるなら出す", [{ material: BOOL.id, weight: 1 }], ["p50=2"]],
    [
      "項が2つ以上あれば出す",
      [
        { material: NUM.id, weight: 1 },
        { material: NUM_PLAIN.id, weight: 1 },
      ],
      ["p50=0 (km/h)", "p50=1"],
    ],
  ])("項ごとの行（材料・係数・必須・削除・材料の分位）は、%s", async (_case, terms, ranges) => {
    renderSection(linearDraft({ terms: terms.map((term) => ({ ...term, required: true })) }));
    await settle();
    expect(screen.queryAllByRole("slider", { name: "係数(スライダー)" })).toHaveLength(ranges.length);
    await waitFor(() =>
      expect(screen.queryAllByText(/^実データ/).map((hint) => hint.textContent)).toEqual(
        ranges.map((range) => `実データ: ${range}`),
      ),
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
    await settle();
    expect(screen.queryByText(/^実データ/)).not.toBeInTheDocument();
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
    // 入れると折れ点が変わり、点数を取り直す間は参考点のボタンが消えるので、押すたびに探す。
    const referenceButton = async (name: string) =>
      within(await screen.findByRole("group", { name: "参考点から値を選ぶ" }, LATER)).getByRole("button", { name });
    expect(await referenceButton("下り")).toHaveAttribute("title", "下り: -5km/h");

    await user.click(await referenceButton("平坦"));
    expect(screen.getByRole("spinbutton", { name: "0点にする値" })).toHaveValue(pointOf(30).x);

    fireEvent.doubleClick(await referenceButton("下り"));
    expect(screen.getByRole("spinbutton", { name: "100点にする値" })).toHaveValue(pointOf(-5).x);
  });

  it("参考点のボタンと効き目の表は、点数が届くまで出さず、届くと参考点ごとに値と、backendが返した点数を出す", async () => {
    const held = heldReplies();
    onSameOrigin("POST", PREVIEW_SCORES, held.reply);
    renderSection(linearDraft());
    await within(effectRegion()).findByText(/111本/);
    expect(screen.queryByRole("group", { name: "参考点から値を選ぶ" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    // 分布が届いて階級の代表値が決まった後の問い合わせに応える。
    await held.answer(1, Response.json({ scores: [binScoreOf(1)], material_points: [-5, 30].map(pointOf) }));
    const rows = within(await screen.findByRole("table"))
      .getAllByRole("row")
      .slice(1);
    expect(
      rows.map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      ),
    ).toEqual(NUM.referencePoints!.map((p) => [p.label, `${p.value}km/h`, String(pointOf(p.value).score)]));
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
  ])("%sなら、参考点のボタンと効き目の表を出さない", async (_case, initial) => {
    renderSection(initial);
    await scoresArrived();
    expect(screen.queryByRole("group", { name: "参考点から値を選ぶ" })).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("分布と折れ点の直接編集", () => {
  it("分布の表示は、取れるまで集計中で、取れたら分布と、backendが返した階級ごとの点数の帯を出す", async () => {
    const held = heldReplies();
    onSameOrigin("POST", PREVIEW_DISTRIBUTION, held.reply);
    renderSection(linearDraft());
    expect(effectRegion()).toHaveTextContent("実データを集計中");

    const distribution = distributionOf({
      kind: "breakpoint_linear",
      terms: [],
      preprocess: "identity",
      breakpoints: [],
    });
    await held.answer(0, Response.json(distribution));
    const full = scoreBands(distribution, [binScoreOf(1)])!.find((band) => band.share === 1)!;
    expect((await scoresArrived()).parentElement).toHaveTextContent(full.label);
    expect(effectRegion()).toHaveTextContent("111本");
  });

  it("下ごしらえを変えると、分布をそのときの形で取り直す", async () => {
    const user = renderSection(linearDraft());
    expect(await within(effectRegion()).findByText(/111本/)).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "マイナス側も同じ強さとして扱う" }));
    expect(await within(effectRegion()).findByText(/222本/, undefined, LATER)).toBeInTheDocument();
  });

  it.each([
    ["分布", PREVIEW_DISTRIBUTION, "分布の取得: 500"],
    ["点数", PREVIEW_SCORES, "この折れ点での点数を取得できませんでした。"],
  ])("%sを取れなかったら、分布の表示にそう出す", async (_case, path, message) => {
    onSameOrigin("POST", path, () => Response.json({ detail: "分布の取得: 500" }, { status: 500 }));
    renderSection(linearDraft());
    expect(await within(effectRegion()).findByText(message, undefined, LATER)).toBeInTheDocument();
  });

  it.each([
    ["参考点のある材料なら、横軸をbackendが返した参考点の横軸の値の範囲で固定する", NUM, true],
    ["参考点の無い材料なら、横軸を固定しない", NUM_PLAIN, false],
  ])("曲線エディタは、%s", async (_case, material, fixed) => {
    const user = renderSection(linearDraft({ terms: [{ material: material.id, weight: 1, required: true }] }));
    await scoresArrived();
    await user.click(screen.getByText("折れ点を直接いじる"));
    const ticks = Array.from(screen.getByRole("img").querySelectorAll("g > text")).map((text) => text.textContent);
    expect(ticks.includes(String(pointOf(30).x))).toBe(fixed);
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

  it("真偽の材料は、該当時・非該当時の点数を入れる", () => {
    renderSection(categoricalDraft(BOOL.id, { trueScore: 0, falseScore: 0 }));
    fireEvent.change(screen.getByRole("slider", { name: "はいのときのスコア(スライダー)" }), {
      target: { value: "30" },
    });
    fireEvent.change(screen.getByRole("slider", { name: "いいえのときのスコア(スライダー)" }), {
      target: { value: "-20" },
    });
    expect(draft()).toMatchObject({ trueScore: 30, falseScore: -20 });
  });

  it("種類の材料で値の候補が取れたら、値は候補からだけ選べ、値はラベルで出す（候補に無い値はそのまま）。選んだときは生の値を入れる", async () => {
    serveValues(CAT.id, valuesResponse(["primary", "track"]));
    const user = renderSection(
      categoricalDraft(CAT.id, {
        categoricalRows: [
          { value: "track", score: 10 },
          { value: "legacy", score: 20 },
        ],
      }),
    );

    const candidates = await screen.findAllByRole("combobox", { name: "値の候補" });
    const values = screen.getAllByRole("textbox", { name: "値" });
    expect(values.map((input) => (input as HTMLInputElement).value)).toEqual(["trackのラベル", "legacy"]);
    expect(values.every((input) => input.hasAttribute("readonly"))).toBe(true);

    await user.selectOptions(candidates[1], "primary");
    expect(draft().categoricalRows[1].value).toBe("primary");
  });

  it.each([
    ["候補が0件", valuesResponse([]), false],
    ["候補を出せなかった", valuesResponse([], false), true],
  ])(
    "種類の材料で%sなら、値を自由に打て、出せなかったときだけ説明にその理由を出す",
    async (_case, response, reason) => {
      serveValues(CAT.id, response);
      const user = renderSection(categoricalDraft(CAT.id, { categoricalRows: [{ value: "", score: 0 }] }));
      await settle();

      await user.type(screen.getByRole("textbox", { name: "値" }), "separated");
      expect(draft().categoricalRows[0].value).toBe("separated");
      expect(screen.queryByRole("combobox", { name: "値の候補" })).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: /値ごとのスコアの説明/ }));
      expect(await screen.findByText(/タグ値と完全に一致する文字列/)).toBeInTheDocument();
      await waitFor(() => expect(screen.queryByText(/候補を取得できませんでした/) !== null).toBe(reason));
    },
  );

  it("値ごとの行の点数を変えられ、行を足せ、1行のときは削除できない", async () => {
    const user = renderSection(categoricalDraft(CAT.id, { categoricalRows: [{ value: "a", score: 0 }] }));
    await settle();

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
