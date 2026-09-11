// 軸コンポーザーのDraft（フォームの内部状態）とbackendのpayloadの相互変換。
//
// このファイルの変更理由は**backendのpayloadスキーマ**（`AxisDefinitionPayload`）で、
// フォームUIの増減とは独立している。同じディレクトリの`breakpointTools.ts`・
// `scoreDistribution.ts`と同じくDOM非依存の純ロジックで、コンポーネントを起動せず
// 直接テストできる。
//
// Draftはbackendの`shape`（判別union）をそのままGUIの入力欄群へ写した形で、
// 「今は選ばれていないkindの入力値」も保持する（kindを切り替えて戻したときに
// 打ち直しにならないようにするため）。保存時に`buildShape`が選択中のkindぶんだけを
// 取り出してpayloadへ組み立てる。

import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import type { AxisDefinitionPayload, AxisDefinitionResponse, AxisShape } from "@/types/route";

// axis_idはユーザー入力欄から撤去してある——内部識別子であって人間が読む必要はなく、
// 実際に画面上で意味を持つのは表示名(label)の方だけのため。新規作成・複製時にここで
// 自動生成し、編集時は既存のaxis_idをそのまま使う（axis_id自体はbackend側で形式制約が
// 無い[str]ため、半角英数字で読みやすいprefix+乱数のみで十分）。
/** フォーム上の変換テンプレート3種。backendのshape.kindは2種
 * （`breakpoint_linear`・`categorical`）で、`recipe_then_breakpoint_linear`は
 * ユーザー向けの入り口としてだけ存在し、保存時に`breakpoint_linear`へ正規化する
 * （`buildShape`）。 */
export type ShapeKind = "breakpoint_linear" | "recipe_then_breakpoint_linear" | "categorical";

export function generateAxisId(): string {
  // crypto.randomUUIDはセキュアコンテキスト（HTTPS/localhost）でのみ定義される。/admin
  // が平文HTTPの非localhostオリジン（TLS終端がNext.jsの手前に無いオンプレ運用時の
  // 内部LAN IP等）から配信されると、この関数がuseState初期化子内でTypeErrorを送出し、
  // AxisComposerのマウント自体が失敗する（エラー表示すら出ない）。Math.randomベースの
  // フォールバックを用意する（axis_idは内部識別子で暗号学的な一意性は不要、衝突時は
  // backend側のPRIMARY KEY制約で409になるだけで安全）。
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `axis_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
  }
  return `axis_${Math.random().toString(16).slice(2, 14).padEnd(12, "0")}`;
}

export interface TermDraft {
  material: string;
  weight: number;
  required: boolean;
}

/** categorical材料（highway/bicycle_infra等、真偽値ではなく文字列多値）を
 * 「はい/いいえ、または種類ごとに点数を決める」で使うための(値, スコア)行。値は自由入力
 * テキストで持つ（mapping未登録の値は評価対象外[欠損]として扱われる）。
 * highway/surface/smoothnessのようにGET /api/admin/material-catalog/{material_id}/valuesが
 * 実データの値一覧を返せる材料では、入力欄の隣に候補選択セレクトを添えてタグ生値の
 * 暗記・手入力の負担を減らす（値の保存先はこのvalueフィールドのまま変わらない）。 */
export interface CategoricalRowDraft {
  value: string;
  score: number;
}

/** このフォームが値を組み立てるpayloadフィールド（実行時には使わないため型で持つ）。 */
type EditedPayloadKey =
  | "axis_id"
  | "label"
  | "description"
  | "category"
  | "default_weight"
  | "shape"
  | "is_published"
  | "icon_id"
  | "chip_label"
  | "panel_hint"
  | "show_map_icon"
  | "display_thresholds_override"
  | "display_band_labels_override";

/** このフォームが編集欄を持たないpayloadフィールド。既存軸の値をそのまま送り返す
 * （送らないとサーバー側の既定値で上書きされ、公開済み軸を非公開へ戻して軽微な編集を
 * しただけでこの値が黙って失われる——エラーも警告も出ない静かなデータ破壊になる）。 */
export const PASSTHROUGH_PAYLOAD_KEYS = [
  "priority_overrides",
  "time_scope",
  "dedicated_way_value_layer",
  "dynamic_way_value_needs_time",
  "dynamic_way_value_needs_bearing",
  "dynamic_way_value_needs_speed",
] as const satisfies readonly (keyof AxisDefinitionPayload)[];

type PassthroughPayloadKey = (typeof PASSTHROUGH_PAYLOAD_KEYS)[number];
export type PassthroughFields = Pick<AxisDefinitionPayload, PassthroughPayloadKey>;

type AssertNever<T extends never> = T;

/** payloadの全フィールドが`EditedPayloadKey`と`PASSTHROUGH_PAYLOAD_KEYS`のどちらかに
 * 属し、かつ前者に実在しないキーが混じっていないことの静的検査。backendがフィールドを
 * 足してどちらへも入れなければ、ここがneverでなくなり型エラーになる（payload側は
 * 全フィールドが既定値付きのため、追加漏れは実行時には「既定値による静かな上書き」と
 * してしか現れず、backendの検証もtscの必須プロパティ検査も素通りする）。 */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
type _PayloadKeyCoverage = [
  AssertNever<Exclude<keyof AxisDefinitionPayload, EditedPayloadKey | PassthroughPayloadKey>>,
  AssertNever<Exclude<EditedPayloadKey, keyof AxisDefinitionPayload>>,
];

/** 新規軸の素通しフィールド初期値（既存軸は`pickPassthroughFields`が実値で置き換える）。 */
const DEFAULT_PASSTHROUGH_FIELDS: PassthroughFields = {
  priority_overrides: [],
  time_scope: "always",
  dedicated_way_value_layer: false,
  dynamic_way_value_needs_time: false,
  dynamic_way_value_needs_bearing: false,
  dynamic_way_value_needs_speed: false,
};

export function pickPassthroughFields(def: AxisDefinitionResponse): PassthroughFields {
  const picked: Record<string, unknown> = { ...DEFAULT_PASSTHROUGH_FIELDS };
  for (const key of PASSTHROUGH_PAYLOAD_KEYS) {
    const value = def[key];
    if (value !== undefined) picked[key] = value;
  }
  return picked as PassthroughFields;
}

export interface Draft {
  axisId: string;
  label: string;
  description: string;
  defaultWeight: number;
  shapeKind: ShapeKind;
  terms: TermDraft[];
  preprocess: "identity" | "abs";
  breakpoints: [number, number][];
  categoricalMaterial: string;
  trueScore: number;
  falseScore: number;
  /** categoricalMaterialのdtypeが"categorical"のときのみ使う行群。
   * dtype="boolean"の材料を選んでいる間はtrueScore/falseScoreの方を使う。 */
  categoricalRows: CategoricalRowDraft[];
  /** 公開状態。trueにすると一般向けGET /api/axis-catalogへ現れ、以後
   * backend側で更新・削除が拒否される（不変制約）ため、確定前によく確認してからONにする。 */
  isPublished: boolean;
  /** 地図チップ表示要素（未設定は空文字列で表し、送信時にnullへ変換する）。 */
  iconId: string;
  chipLabel: string;
  panelHint: string;
  /** この軸のアイコンを地図上チップ・地図の見え方パネルに表示するかどうか。
   * 既定true（表示する）。 */
  showMapIcon: boolean;
  /** 地図の色分けしきい値だけを差し替える軽量な上書き。未設定(null)は自動導出した
   * しきい値をそのまま使う。数値の配列を直接編集するシンプルなUIでこのフォームで
   * 直接編集できる（domain/axis_definitions.py:
   * AxisDefinition.display_thresholds_overrideのdocstring参照）。 */
  displayThresholdsOverride: number[] | null;
  /** displayThresholdsOverrideと対になる、段階ごとの体感ラベルの軽量な
   * 上書き。displayThresholdsOverrideがnullの間は編集欄自体を出さない（段階数が
   * 決まらないと対応が取れないため、backend側のバリデーションと同じ制約をGUIでも
   * 先回りする）。要素数はdisplayThresholdsOverride.length+1と常に一致させる。 */
  displayBandLabelsOverride: string[] | null;
  /** 編集欄を持たないpayloadフィールド（`PASSTHROUGH_PAYLOAD_KEYS`）の値。 */
  passthrough: PassthroughFields;
}

export function emptyDraft(materialOptions: readonly AxisMaterialOption[]): Draft {
  // materialOptionsが空配列（useMaterialCatalogが取得成功したがmaterials0件の場合）の
  // とき、`materialOptions[0].id`を無条件参照するとマウント直後にTypeErrorでクラッシュ
  // する。空文字列(""へ)フォールバックし、呼び出し元(AxisComposer本体)が
  // materialOptions.length === 0 のとき早期にエラー状態UIへ切り替えてこの空文字列の
  // draftをそもそも画面に出さないようにする。
  const firstBoolean = materialOptions.find((m) => m.dtype === "boolean")?.id ?? materialOptions[0]?.id ?? "";
  return {
    axisId: generateAxisId(),
    label: "",
    description: "",
    defaultWeight: 0.1,
    shapeKind: "breakpoint_linear",
    terms: [{ material: materialOptions[0]?.id ?? "", weight: 1.0, required: true }],
    preprocess: "identity",
    breakpoints: [
      [0, 0],
      [10, 100],
    ],
    categoricalMaterial: firstBoolean,
    trueScore: 0,
    falseScore: 80,
    categoricalRows: [],
    isPublished: false,
    iconId: "",
    chipLabel: "",
    panelHint: "",
    showMapIcon: true,
    displayThresholdsOverride: null,
    displayBandLabelsOverride: null,
    passthrough: { ...DEFAULT_PASSTHROUGH_FIELDS },
  };
}

export function draftFromExisting(def: AxisDefinitionResponse, materialOptions: readonly AxisMaterialOption[]): Draft {
  const base = emptyDraft(materialOptions);
  const shape = def.shape;
  const common = {
    ...base,
    axisId: def.axis_id,
    label: def.label,
    description: def.description,
    defaultWeight: def.default_weight,
    isPublished: def.is_published,
    iconId: def.icon_id ?? "",
    chipLabel: def.chip_label ?? "",
    panelHint: def.panel_hint ?? "",
    showMapIcon: def.show_map_icon,
    displayThresholdsOverride: def.display_thresholds_override ?? null,
    displayBandLabelsOverride: def.display_band_labels_override ?? null,
    passthrough: pickPassthroughFields(def),
  };
  // "kind"の判別子で分岐する（AxisShapeは3種のPydantic discriminated unionの構造をそのまま
  // 写した型のため、"terms"/"material"/"flags"というフィールド有無による判別も可能だが、
  // backend側の判別子(kind)に合わせてこちらを単一の判定基準にする）。
  if (shape.kind === "categorical") {
    // 材料のdtypeで真偽値2択/カテゴリ値複数行のどちらの編集UIを初期表示するか決める
    // （保存済みmapping自体のキー型からは判別しない。JSON化されたmappingのキーは
    // 常に文字列で、bool材料でも"true"/"false"という文字列キーになるため）。
    const dtype = materialOptions.find((m) => m.id === shape.material)?.dtype;
    if (dtype === "categorical") {
      return {
        ...common,
        shapeKind: "categorical",
        categoricalMaterial: shape.material,
        categoricalRows: Object.entries(shape.mapping).map(([value, score]) => ({ value, score })),
      };
    }
    return {
      ...common,
      shapeKind: "categorical",
      categoricalMaterial: shape.material,
      trueScore: shape.mapping["true"] ?? 0,
      falseScore: shape.mapping["false"] ?? 0,
    };
  }
  // backendはbreakpoint_linear/recipe_then_breakpoint_linearを"breakpoint_linear"1種へ
  // 統合しているため、保存済みのkindだけでは元々どのカードで作られた軸かを判別できない。
  // termsの構造（材料か他軸か）から表示するカードを推定し直す（domain/axis_display.pyの
  // 構造判定と同じ考え方）。
  const isAxisReference = (material: string) => !materialOptions.some((m) => m.id === material);
  if (shape.terms.length > 0 && shape.terms.every((t) => isAxisReference(t.material))) {
    return {
      ...common,
      shapeKind: "recipe_then_breakpoint_linear",
      terms: shape.terms.map((t) => ({ material: t.material, weight: t.weight, required: t.required })),
      preprocess: shape.preprocess,
      breakpoints: shape.breakpoints,
    };
  }
  return {
    ...common,
    shapeKind: "breakpoint_linear",
    terms: shape.terms.map((t) => ({ material: t.material, weight: t.weight, required: t.required })),
    preprocess: shape.preprocess,
    breakpoints: shape.breakpoints,
  };
}

/** 複製（公開済み軸を「改良」する唯一の経路）。既存の内容を丸ごと写すが、axis_idは
 * 新規に自動採番し、is_publishedは常にfalse（下書き）から始める——複製元が公開済みでも
 * 複製先まで公開扱いを引き継がない。displayThresholdsOverrideも複製元の手動設定値を
 * 引き継がずnullへリセットする——複製先は変化点(breakpoints)を独自に調整しうるため、
 * 複製元のしきい値をそのまま持ち越すと自動計算(breakpointsのx値から導出、backend
 * domain/axis_display.py: derive_ramp_inputs参照)が働かなくなる。
 * displayBandLabelsOverrideも同じ理由でnullへリセットする——displayThresholdsOverrideが
 * 無いままでは段階数が決まらず対応が取れない。 */
export function draftFromDuplicate(def: AxisDefinitionResponse, materialOptions: readonly AxisMaterialOption[]): Draft {
  return {
    ...draftFromExisting(def, materialOptions),
    axisId: generateAxisId(),
    isPublished: false,
    displayThresholdsOverride: null,
    displayBandLabelsOverride: null,
  };
}

export function buildShape(draft: Draft, materialOptions: readonly AxisMaterialOption[]): AxisShape {
  // backend側はbreakpoint_linear/recipe_then_breakpoint_linearを「連続演算」1種
  // （kind="breakpoint_linear"）へ統合している。draft.shapeKindはユーザー向けカード選択
  // （UIの入り口）としては引き続き3種を保つが、保存するshape.kindは常に
  // "breakpoint_linear"へ正規化する。
  if (draft.shapeKind === "breakpoint_linear" || draft.shapeKind === "recipe_then_breakpoint_linear") {
    return {
      kind: "breakpoint_linear",
      terms: draft.terms.map((t) => ({ material: t.material, weight: t.weight, required: t.required })),
      preprocess: draft.preprocess,
      breakpoints: draft.breakpoints,
    };
  }
  const dtype = materialOptions.find((m) => m.id === draft.categoricalMaterial)?.dtype;
  if (dtype === "categorical") {
    return {
      kind: "categorical",
      material: draft.categoricalMaterial,
      mapping: Object.fromEntries(
        draft.categoricalRows.filter((r) => r.value.trim() !== "").map((r) => [r.value.trim(), r.score]),
      ),
    };
  }
  return {
    kind: "categorical",
    material: draft.categoricalMaterial,
    mapping: { true: draft.trueScore, false: draft.falseScore },
  };
}
