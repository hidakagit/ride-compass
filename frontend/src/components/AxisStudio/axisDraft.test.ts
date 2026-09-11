// @vitest-environment node
//
// Draft⇔payloadの往復をコンポーネントを起動せずに直接検証する。
//
// 同じ性質はAxisComposer.test.tsx（フォームを描画してウィザードを操作し、onSaveへ渡る
// payloadを見る）でも押さえているが、そちらは「フォームの導線が壊れていないこと」も
// 同時に見ているため、変換だけの誤りが導線の変更に紛れて読みにくい。
import { describe, expect, it } from "vitest";

import { AXIS_MATERIAL_OPTIONS } from "@/lib/axisMaterialsCatalog";
import { baseAxisDefinition } from "@/testing/axisDefinitionFixtures";
import {
  buildShape,
  draftFromDuplicate,
  draftFromExisting,
  emptyDraft,
  generateAxisId,
  pickPassthroughFields,
  PASSTHROUGH_PAYLOAD_KEYS,
} from "./axisDraft";

const OPTIONS = AXIS_MATERIAL_OPTIONS;

describe("buildShape", () => {
  it("recipe_then_breakpoint_linearはbreakpoint_linearへ正規化する", () => {
    // backendのshape.kindは2種しかない。3種目はGUIの入り口としてだけ存在する。
    const draft = { ...emptyDraft(OPTIONS), shapeKind: "recipe_then_breakpoint_linear" as const };

    expect(buildShape(draft, OPTIONS).kind).toBe("breakpoint_linear");
  });

  it("categorical材料なら値→スコアの対応表を、真偽値材料ならtrue/falseの2値を作る", () => {
    const categorical = OPTIONS.find((m) => m.dtype === "categorical");
    const boolean = OPTIONS.find((m) => m.dtype === "boolean");
    if (!categorical || !boolean) throw new Error("テスト前提の材料が静的カタログに無い");

    const base = { ...emptyDraft(OPTIONS), shapeKind: "categorical" as const };
    const asCategorical = buildShape(
      {
        ...base,
        categoricalMaterial: categorical.id,
        categoricalRows: [
          { value: "a", score: 10 },
          { value: "b", score: 20 },
        ],
      },
      OPTIONS,
    );
    const asBoolean = buildShape(
      { ...base, categoricalMaterial: boolean.id, trueScore: 80, falseScore: 0 },
      OPTIONS,
    );

    expect(asCategorical).toEqual({ kind: "categorical", material: categorical.id, mapping: { a: 10, b: 20 } });
    expect(asBoolean).toEqual({ kind: "categorical", material: boolean.id, mapping: { true: 80, false: 0 } });
  });

  it("値が空欄のままの行は対応表へ入れない", () => {
    const categorical = OPTIONS.find((m) => m.dtype === "categorical");
    if (!categorical) throw new Error("テスト前提の材料が静的カタログに無い");

    const shape = buildShape(
      {
        ...emptyDraft(OPTIONS),
        shapeKind: "categorical",
        categoricalMaterial: categorical.id,
        categoricalRows: [
          { value: "a", score: 10 },
          { value: "   ", score: 99 },
        ],
      },
      OPTIONS,
    );

    expect(shape).toEqual({ kind: "categorical", material: categorical.id, mapping: { a: 10 } });
  });
});

describe("draftFromExisting → buildShape の往復", () => {
  it("breakpoint_linearのterms・preprocess・折れ点がそのまま戻る", () => {
    const shape = {
      kind: "breakpoint_linear" as const,
      terms: [
        { material: "gradient_percent", weight: 1.0, required: true },
        { material: "curvature_deg_per_km", weight: 0.3, required: false },
      ],
      preprocess: "abs" as const,
      breakpoints: [
        [0, 0],
        [15, 100],
      ] as [number, number][],
    };

    const draft = draftFromExisting(baseAxisDefinition({ shape }), OPTIONS);

    expect(buildShape(draft, OPTIONS)).toEqual(shape);
  });

  it("categoricalの対応表がそのまま戻る", () => {
    const categorical = OPTIONS.find((m) => m.dtype === "categorical");
    if (!categorical) throw new Error("テスト前提の材料が静的カタログに無い");
    const shape = {
      kind: "categorical" as const,
      material: categorical.id,
      mapping: { residential: 20, secondary: 60 },
    };

    const draft = draftFromExisting(baseAxisDefinition({ shape }), OPTIONS);

    expect(buildShape(draft, OPTIONS)).toEqual(shape);
  });
});

describe("編集欄を持たないフィールドの素通し", () => {
  it("既存値をそのまま拾う（拾わないとサーバー側の既定値で上書きされる）", () => {
    const values = {
      priority_overrides: [{ material: "motor_vehicle_no", equals: "true", value: 100 }],
      time_scope: "night_only" as const,
      dedicated_way_value_layer: true,
      dynamic_way_value_needs_time: true,
      dynamic_way_value_needs_bearing: true,
      dynamic_way_value_needs_speed: true,
    };
    // 素通し対象が増えたらこの入力も増やす（増やさないと既定値同士の比較になり検出力が落ちる）。
    expect([...PASSTHROUGH_PAYLOAD_KEYS].sort()).toEqual(Object.keys(values).sort());

    const picked = pickPassthroughFields(baseAxisDefinition(values));

    expect(picked).toEqual(values);
  });
});

describe("draftFromDuplicate", () => {
  it("複製元と同じ形のまま、id・公開状態・表示上書きだけを新規扱いへ落とす", () => {
    const source = baseAxisDefinition({
      axis_id: "source_axis",
      is_published: true,
      display_thresholds_override: [1, 2, 3],
      display_band_labels_override: ["a", "b", "c", "d"],
    });

    const duplicate = draftFromDuplicate(source, OPTIONS);
    const original = draftFromExisting(source, OPTIONS);

    expect(duplicate.axisId).not.toBe(source.axis_id);
    expect(duplicate.isPublished).toBe(false);
    expect(duplicate.displayThresholdsOverride).toBeNull();
    expect(duplicate.displayBandLabelsOverride).toBeNull();
    // それ以外は複製元のまま。
    expect(buildShape(duplicate, OPTIONS)).toEqual(buildShape(original, OPTIONS));
    expect(duplicate.label).toBe(original.label);
    expect(duplicate.passthrough).toEqual(original.passthrough);
  });
});

describe("generateAxisId", () => {
  it("crypto.randomUUIDが無い環境でもidを作れる（平文HTTPの/adminで落ちない）", () => {
    const original = globalThis.crypto;
    // セキュアコンテキストでない環境ではrandomUUIDが未定義になる。
    Object.defineProperty(globalThis, "crypto", { value: {}, configurable: true });
    try {
      expect(generateAxisId()).toMatch(/^axis_[0-9a-f]{12}$/);
    } finally {
      Object.defineProperty(globalThis, "crypto", { value: original, configurable: true });
    }
  });

  it("毎回違うidを返す", () => {
    expect(generateAxisId()).not.toBe(generateAxisId());
  });
});
