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
 * - しきい値のまとめ入力の区切りの種類ごと（全角の「，」「、」等）と、小数・負の数 → 区切りは書かれた並び
 *   （`/[,，、\s]+/`）の値ごとで宣言の書き写し、小数・負は`Number.isFinite`の真の側で、どちらも残した行と同じ側
 *   （testing.md「そのテストは要るか」の表の行の決まり）
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
  return { id, label: id, description: "", dtype, unit: "" };
}

const NUM = material("num_a", "numeric");
const BOOL = material("bool_a", "boolean");
const CAT = material("cat_a", "categorical");
const MATERIALS = [NUM, BOOL, CAT];
/** 軸の一覧にある軸id。 */
const AXES: ReadonlySet<string> = new Set(["axis_p", "axis_q"]);

function axis(overrides: Partial<AxisDefinitionResponse> = {}): AxisDefinitionResponse {
  return {
    axis_id: "axis_x",
    label: "",
    description: "",
    weight_share_when_published: null,
    priority_overrides: [],
    icon_id: null,
    display_thresholds_override: null,
    display_band_labels_override: null,
    category: "推定",
    default_weight: 0,
    is_published: false,
    time_scope: "always",
    dedicated_way_value_layer: false,
    shape: { kind: "breakpoint_linear", terms: [], preprocess: "identity", breakpoints: [] },
    display: { kind: "none", tile_inputs: [], thresholds: [] },
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

  it.each([
    [[NUM, CAT, BOOL], NUM.id, BOOL.id],
    [[CAT, NUM], CAT.id, CAT.id],
    [[], "", ""],
  ])(
    "材料は一覧の先頭を、はい/いいえの点数の材料は最初の真偽の材料（無ければ一覧の先頭、それも無ければ空）を選ぶ: %#",
    (materials, term, categorical) => {
      const draft = emptyDraft(materials);
      expect(draft.terms.map((t) => t.material)).toEqual([term]);
      expect(draft.categoricalMaterial).toBe(categorical);
    },
  );
});

describe("draftFromExisting", () => {
  it.each([
    [
      "未設定（null）なら、文字の項目は空欄、上書きの項目はnull",
      {},
      { iconId: "", displayThresholdsOverride: null, displayBandLabelsOverride: null },
    ],
    [
      "設定済みなら、そのまま",
      {
        icon_id: "icon_a",
        display_thresholds_override: [1, 2],
        display_band_labels_override: ["低", "中", "高"],
      },
      {
        iconId: "icon_a",
        displayThresholdsOverride: [1, 2],
        displayBandLabelsOverride: ["低", "中", "高"],
      },
    ],
  ])("表示の項目は、%s", (_case, fields, expected) => {
    expect(draftFromExisting(axis(fields), MATERIALS, AXES)).toMatchObject(expected);
  });

  it("点数の形が種類の材料なら、値ごとの点数の行にする", () => {
    const draft = draftFromExisting(
      axis({ shape: { kind: "categorical", material: CAT.id, mapping: { primary: 10, residential: 70 } } }),
      MATERIALS,
      AXES,
    );
    expect(draft.shapeKind).toBe("categorical");
    expect(draft.categoricalMaterial).toBe(CAT.id);
    expect(draft.categoricalRows).toEqual([
      { value: "primary", score: 10 },
      { value: "residential", score: 70 },
    ]);
  });

  it.each([
    [BOOL.id, { true: 25 }, 25, 0],
    [BOOL.id, { false: 40 }, 0, 40],
    ["unknown", { true: 1, false: 2 }, 1, 2],
  ])(
    "点数の形が真偽の材料（材料の一覧に無い材料も）なら、該当時・非該当時の点数にする（無い側は0点）: %s %j",
    (material, mapping, trueScore, falseScore) => {
      const draft = draftFromExisting(axis({ shape: { kind: "categorical", material, mapping } }), MATERIALS, AXES);
      expect(draft).toMatchObject({ shapeKind: "categorical", categoricalMaterial: material, trueScore, falseScore });
    },
  );

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

  it("折れ線の項がすべて軸の一覧の軸を指すなら、ほかの軸を組み合わせる形として開く", () => {
    const draft = draftFromExisting(linear(terms("axis_p", "axis_q")), MATERIALS, AXES);
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
    ["項が無い", terms()],
  ])("折れ線の項が%sなら、材料を直接使う形として開く", (_case, termList) => {
    const draft = draftFromExisting(linear(termList), MATERIALS, AXES);
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
    const draft = draftFromDuplicate(source, MATERIALS, AXES);

    expect(draft.axisId).not.toBe("axis_source");
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
    expect(buildShape(draftFromExisting(def, MATERIALS, AXES), MATERIALS)).toEqual(def.shape);
  });
});

describe("parseThresholdList", () => {
  it("区切りが続いても前後にあっても、数だけを読む", () => {
    expect(parseThresholdList(" 1,,  2 ,3 ")).toEqual({ values: [1, 2, 3], error: null });
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
  it.each([
    [
      [0, 2, 5],
      ["低", "高", ""],
    ],
    [null, ["低", "中", "高"]],
  ])(
    "地図の段の判定 %j では、各段に当たる入力の段の番号でラベルを引き直し、無い番号は空欄、判定が無ければ入力どおり",
    (bandsOnMap, expected) => {
      expect(bandLabelsOnMap(["低", "中", "高"], bandsOnMap)).toEqual(expected);
    },
  );
});

describe("resizeBandLabels", () => {
  it("段が増えれば、末尾に空欄を足す", () => {
    expect(resizeBandLabels(["a", "b"], 4)).toEqual(["a", "b", "", ""]);
  });
});
