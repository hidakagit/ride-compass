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

import type { components } from "@/types/generated/api";
import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import type { AxisDefinitionPayload, AxisDefinitionResponse, AxisShape } from "@/types/route";

// axis_idはユーザー入力欄から撤去してある——内部識別子であって人間が読む必要はなく、
// 実際に画面上で意味を持つのは表示名(label)の方だけのため。新規作成・複製時にここで
// 自動生成し、編集時は既存のaxis_idをそのまま使う（axis_id自体はbackend側で形式制約が
// 無い[str]ため、半角英数字で読みやすいprefix+乱数のみで十分）。
/** 点数の形。backendが持つ形は契約から引く——写すと、形が増えたとき片側だけ知っている
 * 状態になる。`recipe_then_breakpoint_linear`だけは**編集画面の区別**で、backendの
 * `breakpoint_linear`1種を「材料を直接使う」「他の軸を組み合わせる」の2つの編集モードへ
 * 割ったもの（送信時は1種へ畳む。下の`buildShape`参照）。 */
type BackendShapeKind =
  | NonNullable<components["schemas"]["BreakpointLinearShape"]["kind"]>
  | NonNullable<components["schemas"]["CategoricalShape"]["kind"]>;
type ShapeKind = BackendShapeKind | "recipe_then_breakpoint_linear";

function generateAxisId(): string {
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
const PASSTHROUGH_PAYLOAD_KEYS = [
  "category",
  "priority_overrides",
  "time_scope",
  "dedicated_way_value_layer",
  "dynamic_way_value_needs_time",
  "dynamic_way_value_needs_bearing",
  "dynamic_way_value_needs_speed",
] as const satisfies readonly (keyof AxisDefinitionPayload)[];

type PassthroughPayloadKey = (typeof PASSTHROUGH_PAYLOAD_KEYS)[number];
type PassthroughFields = Pick<AxisDefinitionPayload, PassthroughPayloadKey>;

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
  // 軸スタジオが作る軸は常に「推定」（複数材料を判定式で合成する軸）。「観測」
  // （タグ・POIをそのまま読む）「動的」（気象等、時々刻々変わる外部データ由来）は
  // どちらも材料そのものの性質で、材料を組み合わせて判定式を作る仕組みからは生み出せない。
  // 既存軸を編集するときは既存の値を素通しする——この画面が編集欄を持たない以上、
  // 定数で上書きしてよい理由が無い（「観測」の公開済み軸は、表示専用の編集でも
  // categoryが書き換わるぶん見た目だけの更新と見なされずbackendに拒否される）。
  category: "推定",
  priority_overrides: [],
  time_scope: "always",
  dedicated_way_value_layer: false,
  dynamic_way_value_needs_time: false,
  dynamic_way_value_needs_bearing: false,
  dynamic_way_value_needs_speed: false,
};

function pickPassthroughFields(def: AxisDefinitionResponse): PassthroughFields {
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
  /** この軸のアイコンを地図上チップに表示するかどうか。
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
  // "kind"の判別子で分岐する（AxisShapeはPydantic discriminated unionの構造をそのまま
  // 写した型のため、フィールドの有無による判別も可能だが、backend側の判別子(kind)に
  // 合わせてこちらを単一の判定基準にする）。
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
 * 複製元のしきい値をそのまま持ち越すと自動計算(breakpointsのx値から導出)が働かなくなる。
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

/** 地図の色分けしきい値のまとめ入力を解釈する。区切りはカンマ（全角含む）・空白・改行・
 * 読点のいずれでもよい——利用者は他所からコピーした並びをそのまま貼るため、区切りの
 * 種類を当てさせない。
 *
 * 昇順・重複の検査はbackendの保存時検証（`axis_definitions.py:
 * AxisDefinition._thresholds_must_be_strictly_ascending`）と同じ条件で、入力した場で返す。
 * 空文字は「1件も無い」（`values: []`）として返し、エラーにはしない——入力欄を空にする
 * 途中の状態を打ち消さないため、その判断は呼び出し側が行う。 */
export function parseThresholdList(text: string): { values: number[]; error: string | null } {
  const tokens = text
    .split(/[,、\s]+/)
    .map((token) => token.trim())
    .filter((token) => token !== "");
  const values: number[] = [];
  for (const token of tokens) {
    const value = Number(token);
    if (!Number.isFinite(value)) {
      return { values: [], error: `数値として読めない値があります: ${token}` };
    }
    values.push(value);
  }
  for (let i = 1; i < values.length; i++) {
    if (values[i] <= values[i - 1]) {
      return { values: [], error: "しきい値は小さい順に並べてください（同じ値は使えません）。" };
    }
  }
  return { values, error: null };
}

/** 解釈済みのしきい値を、まとめ入力欄へ表示する文字列へ戻す。 */
export function formatThresholdList(values: readonly number[]): string {
  return values.join(", ");
}

/** 段階ラベルを段階数（しきい値の件数+1）へ合わせる。増えた分は空欄、減った分は末尾から
 * 落とす。しきい値をまとめて入れ替えると段階数が何段階も動くため、1件ずつの増減では
 * 追従しきれない。 */
export function resizeBandLabels(labels: readonly string[], bandCount: number): string[] {
  return Array.from({ length: bandCount }, (_, index) => labels[index] ?? "");
}
