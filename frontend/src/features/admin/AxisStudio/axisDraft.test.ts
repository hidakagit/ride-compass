// @vitest-environment node
/**
 * `axisDraft.ts`——下書き（フォームの内部状態）とbackendの軸定義の相互変換と、しきい値のまとめ入力の
 * 読み書き、地図の段への引き直し。
 *
 * 材料と軸は性質だけを持つ架空のもの（数値・真偽・種類）を与える。フォームの既定値（新規の既定重み等）は
 * 宣言なので書き写さない。
 *
 * ここで見ないもの:
 * - 下書きからpayloadを組み立てて送ること（素通しの項目を含む往復） → `AxisComposer.test.tsx`
 * - しきい値の入力欄と段階プレビュー → `AxisMapDisplaySection.test.tsx`
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import type { AxisDefinitionResponse } from "@/types/route";

import {
  bandLabelsOnMap,
  buildShape,
  draftFromDuplicate,
  draftFromExisting,
  emptyDraft,
  formatThresholdList,
  parseThresholdList,
  resizeBandLabels,
  thresholdsKeptOnMap,
} from "./axisDraft";

function material(id: string, dtype: AxisMaterialOption["dtype"]): AxisMaterialOption {
  return { id, label: id, name: id, description: "", dtype, unit: "" };
}

const NUM = material("num_a", "numeric");
const BOOL = material("bool_a", "boolean");
const CAT = material("cat_a", "categorical");
const MATERIALS = [NUM, BOOL, CAT];

function axis(overrides: Partial<AxisDefinitionResponse> = {}): AxisDefinitionResponse {
  return {
    axis_id: "axis_x",
    label: "",
    description: "",
    weight_share_when_published: null,
    category: "推定",
    default_weight: 0,
    is_published: false,
    show_map_icon: false,
    time_scope: "always",
    dedicated_way_value_layer: false,
    dynamic_way_value_needs_time: false,
    dynamic_way_value_needs_bearing: false,
    dynamic_way_value_needs_speed: false,
    shape: { kind: "breakpoint_linear", terms: [], preprocess: "identity", breakpoints: [] },
    display: { kind: "none", label: "", category: "" },
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("emptyDraft", () => {
  it("新規の軸には、毎回ちがう axis_ で始まる識別子を振る", () => {
    const ids = new Set([emptyDraft(MATERIALS).axisId, emptyDraft(MATERIALS).axisId]);
    expect(ids.size).toBe(2);
    for (const id of ids) expect(id).toMatch(/^axis_[0-9a-f]{12}$/);
  });

  it("安全な文脈でない（crypto.randomUUID が無い）ページでも、同じ形の識別子を振る", () => {
    vi.stubGlobal("crypto", {});
    expect(emptyDraft(MATERIALS).axisId).toMatch(/^axis_[0-9a-f]{12}$/);
  });

  it("材料は一覧の先頭を選び、はい/いいえの点数の材料には最初の真偽の材料を選ぶ", () => {
    const draft = emptyDraft([NUM, CAT, BOOL]);
    expect(draft.terms.map((term) => term.material)).toEqual([NUM.id]);
    expect(draft.categoricalMaterial).toBe(BOOL.id);
  });

  it("真偽の材料が無ければ、はい/いいえの点数の材料にも一覧の先頭を選ぶ", () => {
    expect(emptyDraft([CAT, NUM]).categoricalMaterial).toBe(CAT.id);
  });

  it("材料が1つも無くても作れる（材料の欄は空）", () => {
    const draft = emptyDraft([]);
    expect(draft.terms.map((term) => term.material)).toEqual([""]);
    expect(draft.categoricalMaterial).toBe("");
  });
});

describe("draftFromExisting", () => {
  it("表示の項目を写し、未設定（null）の文字の項目は空欄、上書きの項目はnullにする", () => {
    const draft = draftFromExisting(
      axis({
        axis_id: "axis_keep",
        label: "表示名",
        description: "説明",
        default_weight: 0.4,
        is_published: true,
        show_map_icon: true,
        icon_id: null,
        chip_label: null,
        panel_hint: null,
        display_thresholds_override: undefined,
        display_band_labels_override: null,
      }),
      MATERIALS,
    );
    expect(draft).toMatchObject({
      axisId: "axis_keep",
      label: "表示名",
      description: "説明",
      defaultWeight: 0.4,
      isPublished: true,
      showMapIcon: true,
      iconId: "",
      chipLabel: "",
      panelHint: "",
      displayThresholdsOverride: null,
      displayBandLabelsOverride: null,
    });
  });

  it("設定済みの表示の項目・しきい値とラベルの上書きはそのまま写す", () => {
    const draft = draftFromExisting(
      axis({
        icon_id: "icon_a",
        chip_label: "略",
        panel_hint: "補足",
        display_thresholds_override: [1, 2],
        display_band_labels_override: ["低", "中", "高"],
      }),
      MATERIALS,
    );
    expect(draft).toMatchObject({
      iconId: "icon_a",
      chipLabel: "略",
      panelHint: "補足",
      displayThresholdsOverride: [1, 2],
      displayBandLabelsOverride: ["低", "中", "高"],
    });
  });

  it("点数の形が種類の材料なら、値ごとの点数の行にする", () => {
    const draft = draftFromExisting(
      axis({ shape: { kind: "categorical", material: CAT.id, mapping: { primary: 10, residential: 70 } } }),
      MATERIALS,
    );
    expect(draft.shapeKind).toBe("categorical");
    expect(draft.categoricalMaterial).toBe(CAT.id);
    expect(draft.categoricalRows).toEqual([
      { value: "primary", score: 10 },
      { value: "residential", score: 70 },
    ]);
  });

  it.each([
    [{ true: 25 }, 25, 0],
    [{ false: 40 }, 0, 40],
  ])("点数の形が真偽の材料なら、該当時・非該当時の点数にする（無い側は0点）: %j", (mapping, trueScore, falseScore) => {
    const draft = draftFromExisting(axis({ shape: { kind: "categorical", material: BOOL.id, mapping } }), MATERIALS);
    expect(draft).toMatchObject({ shapeKind: "categorical", categoricalMaterial: BOOL.id, trueScore, falseScore });
  });

  it("材料の一覧に無い材料の形は、種類ではなく真偽として開く", () => {
    const draft = draftFromExisting(
      axis({ shape: { kind: "categorical", material: "unknown", mapping: { true: 1, false: 2 } } }),
      MATERIALS,
    );
    expect(draft).toMatchObject({ trueScore: 1, falseScore: 2, categoricalRows: [] });
  });

  const terms = (...materials: string[]) => materials.map((m) => ({ material: m, weight: 2, required: false }));
  const linear = (termList: ReturnType<typeof terms>) =>
    axis({
      shape: {
        kind: "breakpoint_linear",
        terms: termList,
        preprocess: "abs",
        breakpoints: [
          [1, 5],
          [9, 95],
        ],
      },
    });

  it("折れ線の項がすべて材料の一覧に無い（ほかの軸を指す）なら、ほかの軸を組み合わせる形として開く", () => {
    const draft = draftFromExisting(linear(terms("axis_p", "axis_q")), MATERIALS);
    expect(draft.shapeKind).toBe("recipe_then_breakpoint_linear");
    expect(draft).toMatchObject({
      terms: terms("axis_p", "axis_q"),
      preprocess: "abs",
      breakpoints: [
        [1, 5],
        [9, 95],
      ],
    });
  });

  it.each([
    ["すべて材料", terms(NUM.id)],
    ["材料とほかの軸が混ざる", terms(NUM.id, "axis_p")],
    ["項が無い", terms()],
  ])("折れ線の項が%sなら、材料を直接使う形として開く", (_case, termList) => {
    const draft = draftFromExisting(linear(termList), MATERIALS);
    expect(draft.shapeKind).toBe("breakpoint_linear");
    expect(draft.terms).toEqual(termList);
  });
});

describe("draftFromDuplicate", () => {
  it("中身を写し、識別子は新しく振り、公開せず、しきい値とラベルの上書きは外す", () => {
    const source = axis({
      axis_id: "axis_source",
      label: "元",
      is_published: true,
      display_thresholds_override: [1, 2],
      display_band_labels_override: ["a", "b", "c"],
    });
    const draft = draftFromDuplicate(source, MATERIALS);

    expect(draft.axisId).not.toBe("axis_source");
    expect(draft.axisId).toMatch(/^axis_/);
    expect(draft).toMatchObject({
      label: "元",
      isPublished: false,
      displayThresholdsOverride: null,
      displayBandLabelsOverride: null,
    });
  });
});

function terms2(...materials: string[]) {
  return materials.map((m) => ({ material: m, weight: 1.5, required: true }));
}

describe("buildShape", () => {
  it.each([
    ["材料を直接使う", "breakpoint_linear"],
    ["ほかの軸を組み合わせる", "recipe_then_breakpoint_linear"],
  ] as const)("%s形は、backendの折れ線1種として送る", (_case, shapeKind) => {
    const draft = {
      ...emptyDraft(MATERIALS),
      shapeKind,
      terms: [{ material: "m", weight: 3, required: false }],
      preprocess: "abs" as const,
      breakpoints: [[2, 20]] as [number, number][],
    };
    expect(buildShape(draft, MATERIALS)).toEqual({
      kind: "breakpoint_linear",
      terms: [{ material: "m", weight: 3, required: false }],
      preprocess: "abs",
      breakpoints: [[2, 20]],
    });
  });

  it("種類の材料は、値の前後の空白を落とし、値が空の行は送らない", () => {
    const draft = {
      ...emptyDraft(MATERIALS),
      shapeKind: "categorical" as const,
      categoricalMaterial: CAT.id,
      categoricalRows: [
        { value: " primary ", score: 10 },
        { value: "  ", score: 99 },
        { value: "track", score: 60 },
      ],
    };
    expect(buildShape(draft, MATERIALS)).toEqual({
      kind: "categorical",
      material: CAT.id,
      mapping: { primary: 10, track: 60 },
    });
  });

  it("真偽の材料は、該当時・非該当時の2つの点数として送る", () => {
    const draft = {
      ...emptyDraft(MATERIALS),
      shapeKind: "categorical" as const,
      categoricalMaterial: BOOL.id,
      trueScore: 5,
      falseScore: 90,
    };
    expect(buildShape(draft, MATERIALS)).toEqual({
      kind: "categorical",
      material: BOOL.id,
      mapping: { true: 5, false: 90 },
    });
  });

  it.each([
    [
      "数値の折れ線",
      axis({
        shape: {
          kind: "breakpoint_linear",
          terms: terms2(NUM.id),
          preprocess: "abs",
          breakpoints: [
            [0, 0],
            [4, 100],
          ],
        },
      }),
    ],
    [
      "ほかの軸の折れ線",
      axis({
        shape: { kind: "breakpoint_linear", terms: terms2("axis_p"), preprocess: "identity", breakpoints: [[1, 9]] },
      }),
    ],
    ["種類の点数", axis({ shape: { kind: "categorical", material: CAT.id, mapping: { a: 1, b: 2 } } })],
    ["真偽の点数", axis({ shape: { kind: "categorical", material: BOOL.id, mapping: { true: 3, false: 4 } } })],
  ])("%s: 開いてそのまま送ると、保存済みの形に戻る", (_case, def) => {
    expect(buildShape(draftFromExisting(def, MATERIALS), MATERIALS)).toEqual(def.shape);
  });
});

describe("parseThresholdList", () => {
  it.each([["1, 2, 3"], ["1，2，3"], ["1、2、3"], ["1 2\n3"], [" 1,,  2 ,3 "]])(
    "区切りの種類を問わず読む: %j",
    (text) => {
      expect(parseThresholdList(text)).toEqual({ values: [1, 2, 3], error: null });
    },
  );

  it("小数・負の数も読む", () => {
    expect(parseThresholdList("-1.5, 0, 2.25")).toEqual({ values: [-1.5, 0, 2.25], error: null });
  });

  it("空（空白だけ）は、エラーにせず1件も無いとして返す", () => {
    expect(parseThresholdList("   ")).toEqual({ values: [], error: null });
  });

  it("数として読めない値があれば、その値を名指しして値を返さない", () => {
    const result = parseThresholdList("1, abc, 3");
    expect(result.values).toEqual([]);
    expect(result.error).toContain("abc");
  });
});

describe("formatThresholdList", () => {
  it("読み直すと同じ並びに戻る形で書く", () => {
    const values = [-1, 0.5, 12];
    expect(parseThresholdList(formatThresholdList(values)).values).toEqual(values);
  });
});

describe("thresholdsKeptOnMap", () => {
  it("地図で段にならない境界を除き、並びは保つ", () => {
    expect(thresholdsKeptOnMap([1, 2, 3, 4], [2, 4])).toEqual([1, 3]);
  });
});

describe("bandLabelsOnMap", () => {
  it("地図の各段に当たる入力の段の番号でラベルを引き直し、無い番号は空欄にする", () => {
    expect(bandLabelsOnMap(["低", "中", "高"], [0, 2, 5])).toEqual(["低", "高", ""]);
  });

  it("地図の段の判定が無い間は、入力どおりのラベルを出す", () => {
    const labels = ["低", "中"];
    expect(bandLabelsOnMap(labels, null)).toBe(labels);
  });
});

describe("resizeBandLabels", () => {
  it("段が増えれば末尾に空欄を足し、減れば末尾から落とす", () => {
    expect(resizeBandLabels(["a", "b"], 4)).toEqual(["a", "b", "", ""]);
    expect(resizeBandLabels(["a", "b", "c"], 2)).toEqual(["a", "b"]);
  });
});
