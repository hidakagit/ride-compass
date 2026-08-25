"use client";

import { useState } from "react";
import { FieldLabel } from "@/components/Map/recipeControls";
import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import { useMaterialCatalog } from "@/hooks/useMaterialCatalog";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import type { AxisDefinitionPayload, AxisDefinitionResponse, AxisShape } from "@/types/route";
import { AXIS_ICON_PALETTE, axisIconFor } from "@/components/Map/axisIconPalette";
import styles from "./AxisStudio.module.css";

// 軸コンポーザー（改善計画T270、T221 Stage E）。表示名→点数のつけ方を選ぶ→点数の詳細→
// 地図表示・公開、という4ステップのウィザードで軸を組み立てる中核機能。既存の
// `AxisDefinition.shape`（判別union、backend/app/domain/axis_definitions.py）をそのまま
// GUIの入力欄群へ写す構造は変えず、専門知識のないユーザーにも辿れる導線へ再構成した
// （改善計画T332、UIレビュー2026-08-25のF-2「変換テンプレート4択が数式的な語彙のまま」
// への対応。カード選択の文言化でF-2の元ネタT324、地図チップ折れ点のスコア向き説明で
// T327、旧ドロップダウンの「真偽2値→定数」という食い違った文言の撤去でT326も併せて解消）。
//
// 内部で保持する4種の変換テンプレート(shape kind)自体は変えない（ADR「新しい計算
// テンプレートの追加は引き続きコード変更が必要、際限のない汎用化は目指さない」という
// 承認済み方針）。材料はuseMaterialCatalog()（改善計画T277、GET /api/material-catalog）が
// 返す候補から選ぶ（目論見書7章・歯止め4「材料の天井」。API取得失敗時はlib/
// axisMaterialsCatalog.tsの静的フォールバックへ自動的に切り替わる）。

type ShapeKind = "breakpoint_linear" | "recipe_then_breakpoint_linear" | "categorical" | "flag_sum";

// 改善計画T332: 「変換テンプレート(shape)」という技術名のドロップダウンを、
// 「どうやって点数をつけたいか」という利用者視点の質問＋カード選択へ置き換える
// （旧SHAPE_KIND_DESCRIPTIONSは「用語が何か」の説明だったが、こちらは「どんな時に選ぶか」
// を主役にする）。recipe_then_breakpoint_linearのみ、内部軸参照という上級者向けの用途の
// ため`advanced: true`を付け、他3枚より控えめに表示する。
interface ShapeKindOption {
  kind: ShapeKind;
  title: string;
  description: string;
  advanced?: boolean;
}

const SHAPE_KIND_OPTIONS: ShapeKindOption[] = [
  {
    kind: "categorical",
    title: "はい/いいえ、または種類ごとに点数を決める",
    description: "例: 一方通行かどうか、自転車専用道かどうか、道路の種類ごとに点数を変える。",
  },
  {
    kind: "breakpoint_linear",
    title: "数値の大きさに応じて点数を変える",
    description: "例: 勾配(%)が急なほど点数を下げる、停止回数が多いほど点数を下げる。",
  },
  {
    kind: "flag_sum",
    title: "複数の要素の有無を数えて減点・加点する",
    description: "例: 街灯なし・トンネルなど、危険要素が当てはまるほど点数を下げる。",
  },
  {
    kind: "recipe_then_breakpoint_linear",
    title: "他の軸の計算結果をもとに点数を変える",
    description: "内部軸（下書きのまま公開しない軸）の計算結果を材料として使う場合に選びます。仕組み自体は「数値の大きさに応じて点数を変える」と同じです。",
    advanced: true,
  },
];

function shapeKindOption(kind: ShapeKind): ShapeKindOption {
  return SHAPE_KIND_OPTIONS.find((o) => o.kind === kind) ?? SHAPE_KIND_OPTIONS[0];
}

// 改善計画T305: axis_idはユーザー入力欄から撤去した。ユーザーからの指摘「axis_idは
// システムが勝手に一意な何かを自動採番してくれればよい。設定画面に不要では？画面上は
// 表示名があればよい」への対応——内部識別子であって人間が読む必要はなく、実際に画面上で
// 意味を持つのは表示名(label)の方だけだったため。新規作成・複製時にここで自動生成し、
// 編集時は既存のaxis_idをそのまま使う（axis_id自体はbackend側で形式制約が無い[str]ため、
// 半角英数字で読みやすいprefix+乱数のみで十分）。
function generateAxisId(): string {
  // コードレビュー指摘の修正: crypto.randomUUIDはセキュアコンテキスト（HTTPS/localhost）
  // でのみ定義される。/adminが平文HTTPの非localhostオリジン（TLS終端がNext.jsの手前に
  // 無いオンプレ運用時の内部LAN IP等）から配信されると、この関数がuseState初期化子内で
  // TypeErrorを送出し、AxisComposerのマウント自体が失敗する（エラー表示すら出ない）。
  // Math.randomベースのフォールバックを用意する（axis_idは内部識別子で暗号学的な
  // 一意性は不要、衝突時はbackend側のPRIMARY KEY制約で409になるだけで安全）。
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `axis_${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
  }
  return `axis_${Math.random().toString(16).slice(2, 14).padEnd(12, "0")}`;
}

interface TermDraft {
  material: string;
  weight: number;
  required: boolean;
}

interface FlagDraft {
  material: string;
  points: number;
}

/** 改善計画T322: categorical材料（highway/bicycle_infra等、真偽値ではなく文字列多値）を
 * 「はい/いいえ、または種類ごとに点数を決める」で使うための(値, スコア)行。値は自由入力
 * （既知の値一覧を返すAPIを持たないため）で、mapping未登録の値は評価対象外(欠損)として
 * 扱われる。 */
interface CategoricalRowDraft {
  value: string;
  score: number;
}

interface Draft {
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
  /** 改善計画T322: categoricalMaterialのdtypeが"categorical"のときのみ使う行群。
   * dtype="boolean"の材料を選んでいる間はtrueScore/falseScoreの方を使う。 */
  categoricalRows: CategoricalRowDraft[];
  flags: FlagDraft[];
  cap: number | null;
  /** 改善計画T271: 公開状態。trueにすると一般向けGET /api/axis-catalogへ現れ、以後
   * backend側で更新・削除が拒否される（不変制約）ため、確定前によく確認してからONにする。 */
  isPublished: boolean;
  /** 改善計画T310: 地図チップ表示要素（未設定は空文字列で表し、送信時にnullへ変換する）。
   * display_override（地図rampの閾値上書き）はTileInputSpecの構造が複雑なため、
   * このフォームには編集欄を持たない（domain/axis_definitions.py: AxisDefinition.
   * display_overrideのdocstring参照。管理API経由の直接編集のみ対応）。 */
  iconId: string;
  chipLabel: string;
  panelHint: string;
  /** 改善計画T318: この軸のアイコンを地図上チップ・地図の見え方パネルに表示するか
   * どうか。既定true（表示する）。旧proxyHint（専用地図レイヤーを持たない軸向けの
   * 代役案内文）はこのON/OFFに置き換わり撤去した。 */
  showMapIcon: boolean;
  /** コードレビュー指摘の修正: priority_overrides（改善計画T292、0次条件）・
   * display_override（改善計画T310、地図ramp閾値の手書き上書き）はどちらもこの
   * フォームに編集欄を持たないが、既存軸の値をpayloadへ素通しして保持する
   * （以前はpayloadに含めておらず、公開済み軸を非公開へ戻して軽微な編集をしただけで
   * これらが黙って失われていた——エラーも警告も出ない静かなデータ破壊だったため）。 */
  priorityOverrides: AxisDefinitionResponse["priority_overrides"];
  displayOverride: AxisDefinitionResponse["display_override"];
}

function emptyDraft(materialOptions: readonly AxisMaterialOption[]): Draft {
  const firstBoolean = materialOptions.find((m) => m.dtype === "boolean")?.id ?? materialOptions[0].id;
  return {
    axisId: generateAxisId(),
    label: "",
    description: "",
    defaultWeight: 0.1,
    shapeKind: "breakpoint_linear",
    terms: [{ material: materialOptions[0].id, weight: 1.0, required: true }],
    preprocess: "identity",
    breakpoints: [
      [0, 0],
      [10, 100],
    ],
    categoricalMaterial: firstBoolean,
    trueScore: 0,
    falseScore: 80,
    categoricalRows: [],
    flags: [{ material: firstBoolean, points: 50 }],
    cap: 100,
    isPublished: false,
    iconId: "",
    chipLabel: "",
    panelHint: "",
    showMapIcon: true,
    priorityOverrides: [],
    displayOverride: null,
  };
}

function draftFromExisting(def: AxisDefinitionResponse, materialOptions: readonly AxisMaterialOption[]): Draft {
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
    priorityOverrides: def.priority_overrides,
    displayOverride: def.display_override,
  };
  // "kind"の判別子で分岐する（AxisShapeは3種のPydantic discriminated unionの構造をそのまま
  // 写した型のため、"terms"/"material"/"flags"というフィールド有無による判別も可能だが、
  // backend側の判別子(kind)に合わせてこちらを単一の判定基準にする）。
  if (shape.kind === "categorical") {
    // 改善計画T322: 材料のdtypeで真偽値2択/カテゴリ値複数行のどちらの編集UIを
    // 初期表示するか決める（保存済みmapping自体のキー型からは判別しない。JSON化された
    // mappingのキーは常に文字列で、bool材料でも"true"/"false"という文字列キーになるため）。
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
  if (shape.kind === "flag_sum") {
    return {
      ...common,
      shapeKind: "flag_sum",
      flags: shape.flags.map(([material, points]) => ({ material, points })),
      cap: shape.cap ?? null,
    };
  }
  return {
    ...common,
    shapeKind: shape.kind,
    terms: shape.terms.map((t) => ({ material: t.material, weight: t.weight, required: t.required })),
    preprocess: shape.preprocess,
    breakpoints: shape.breakpoints,
  };
}

/** 複製（改善計画T271、公開済み軸を「改良」する唯一の経路）。既存の内容を丸ごと写すが、
 * axis_idは新規に自動採番し（改善計画T305）、is_publishedは常にfalse（下書き）から
 * 始める——複製元が公開済みでも複製先まで公開扱いを引き継がない。 */
function draftFromDuplicate(def: AxisDefinitionResponse, materialOptions: readonly AxisMaterialOption[]): Draft {
  return { ...draftFromExisting(def, materialOptions), axisId: generateAxisId(), isPublished: false };
}

function buildShape(draft: Draft, materialOptions: readonly AxisMaterialOption[]): AxisShape {
  if (draft.shapeKind === "breakpoint_linear" || draft.shapeKind === "recipe_then_breakpoint_linear") {
    return {
      kind: draft.shapeKind,
      terms: draft.terms.map((t) => ({ material: t.material, weight: t.weight, required: t.required })),
      preprocess: draft.preprocess,
      breakpoints: draft.breakpoints,
    };
  }
  if (draft.shapeKind === "categorical") {
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
  return {
    kind: "flag_sum",
    flags: draft.flags.map((f) => [f.material, f.points] as [string, number]),
    cap: draft.cap,
  };
}

interface AxisComposerProps {
  /** 編集対象。nullなら新規作成（下記duplicateFromが無ければ空欄から）。公開済み軸は
   * 呼び出し側（AxisStudio）が編集ボタン自体を無効化するため、ここへは渡らない想定。 */
  editing: AxisDefinitionResponse | null;
  /** 複製元（改善計画T271）。editingがnullのとき、この軸の内容（axis_id/is_published除く）
   * で新規作成フォームを初期化する。 */
  duplicateFrom: AxisDefinitionResponse | null;
  onCancelEdit: () => void;
  onSave: (payload: AxisDefinitionPayload, isNew: boolean) => Promise<void>;
}

// 改善計画T332: 4ステップのウィザード。ステップ自体の追加・削除はコード変更を要する
// （4テンプレート限定の方針と同様、際限のない動的ステップ化は目指さない）。
const STEPS = ["basic", "shape_kind", "shape_params", "display_publish"] as const;
type Step = (typeof STEPS)[number];
const STEP_TITLES: Record<Step, string> = {
  basic: "基本情報",
  shape_kind: "点数のつけ方を選ぶ",
  shape_params: "点数の詳細を設定",
  display_publish: "地図表示・公開",
};

export default function AxisComposer({ editing, duplicateFrom, onCancelEdit, onSave }: AxisComposerProps) {
  const materialOptions = useMaterialCatalog();
  const [draft, setDraft] = useState<Draft>(() => {
    if (editing) return draftFromExisting(editing, materialOptions);
    if (duplicateFrom) return draftFromDuplicate(duplicateFrom, materialOptions);
    return emptyDraft(materialOptions);
  });
  const [stepIndex, setStepIndex] = useState(0);
  const step = STEPS[stepIndex];
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isNew = editing === null;

  // 一覧から別の軸の編集を選び直した場合の切り替えは、呼び出し側（AxisStudio）が
  // <AxisComposer key={editing?.axis_id ?? "new"}> のようにkeyを変えてコンポーネント自体を
  // 再マウントする方式に委ねる（このコンポーネント内でeditingの変化を検知しない）。

  // 改善計画T332: ステップを進める前の検証。「表示名が無いまま次へ進んで、最後の保存時に
  // 初めてエラーが出る」という手戻りを避け、該当ステップに留まったまま原因を示す。
  function validateStep(target: Step): string | null {
    if (target === "basic") {
      if (draft.label.trim() === "") return "表示名(label)を入力してください。";
    }
    if (target === "shape_params" && draft.shapeKind === "categorical") {
      // 改善計画T322: categorical材料選択時、値の行が1つも入力されていないと
      // mapping={}のまま保存されてしまい（全区間で評価不能=欠損になるだけで保存自体は
      // 通ってしまう）、設定し忘れに気づきにくいため事前に弾く。
      const dtype = materialOptions.find((m) => m.id === draft.categoricalMaterial)?.dtype;
      if (dtype === "categorical" && draft.categoricalRows.every((r) => r.value.trim() === "")) {
        return "値ごとのスコアを少なくとも1件設定してください。";
      }
    }
    if (target === "display_publish") {
      // コードレビュー指摘の修正: backend側の検証（axis_admin.py:
      // _check_label_length_or_chip_label）と同じ条件をここでも先回りしてチェックし、
      // 保存時まで待たせない。地図チップの略称(chip_label)欄はこのステップにあるため、
      // ここでチェックする（「基本情報」ステップでチェックすると、まだ入力欄が無い
      // 「地図表示・公開」ステップへ誘導するだけで先へ進めない詰みを生む——実機確認で
      // 発覚したT332実装時の不具合、修正済み）。
      if (draft.chipLabel.trim() === "" && draft.label.trim().length > 4) {
        return "表示名(label)が4文字を超えています。地図チップの略称(chip_label)を設定してください。";
      }
    }
    return null;
  }

  function goNext() {
    const err = validateStep(step);
    if (err) {
      setError(err);
      return;
    }
    setError(null);
    setStepIndex((i) => Math.min(i + 1, STEPS.length - 1));
  }

  function goBack() {
    setError(null);
    setStepIndex((i) => Math.max(i - 1, 0));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    // 改善計画T332: 最終ステップ以外でのEnterキー送信は「次へ」として扱う
    // （このコンポーネントは単一の<form>のまま、表示するステップだけを切り替える設計の
    // ため、type="submit"ボタンが常にDOM上に無くても暗黙のフォーム送信は起こりうる）。
    if (step !== "display_publish") {
      goNext();
      return;
    }
    setError(null);
    // basic・shape_paramsステップの検証を保存直前にも通す（ステップを戻って値を空へ
    // 書き換えてから、戻らずに保存を試みた場合の安全網）。
    for (const target of STEPS) {
      const err = validateStep(target);
      if (err) {
        setError(err);
        setStepIndex(STEPS.indexOf(target));
        return;
      }
    }
    const payload: AxisDefinitionPayload = {
      axis_id: draft.axisId,
      label: draft.label.trim(),
      description: draft.description,
      // 改善計画T305: 軸スタジオが作る軸は常に「推定」（複数材料を判定式で合成する軸）。
      // 「観測」（タグ・POIをそのまま読む）「動的」（気象等、時々刻々変わる外部データ由来）は
      // どちらもそれ自体が材料の性質であり、材料を組み合わせて判定式を作る軸スタジオの
      // 仕組みからこれらを生み出すのは概念上おかしい、というユーザー指摘を受けて固定した。
      category: "推定",
      default_weight: draft.defaultWeight,
      shape: buildShape(draft, materialOptions),
      is_published: draft.isPublished,
      // 改善計画T310: 空文字列は「未設定」の意味でnullへ変換する（trim()の理由はlabelと同じ、
      // 空白のみの入力を未設定扱いにする）。
      icon_id: draft.iconId.trim() === "" ? null : draft.iconId,
      chip_label: draft.chipLabel.trim() === "" ? null : draft.chipLabel.trim(),
      panel_hint: draft.panelHint.trim() === "" ? null : draft.panelHint.trim(),
      // 改善計画T318: 地図上にアイコンを表示するかどうかのON/OFF（既定true）。
      show_map_icon: draft.showMapIcon,
      // コードレビュー指摘の修正: このフォームに編集欄を持たないフィールドも、既存値を
      // 素通しして送る（未送信＝サーバー側の既定値[空リスト/null]で上書きされ、既存軸の
      // 値が消えるのを防ぐ）。
      priority_overrides: draft.priorityOverrides,
      display_override: draft.displayOverride,
    };
    setSaving(true);
    try {
      // 改善計画T304: 保存成功後は呼び出し側（AxisStudio）がモーダルごと閉じるため、
      // ここでフォームをリセットして開いたままにする必要はない（以前の「新規作成時は
      // 続けて次の1件を入力できるようフォームを空へ戻す」挙動は撤去した）。
      await onSave(payload, isNew);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  function updateTerm(index: number, patch: Partial<TermDraft>) {
    setDraft((d) => ({ ...d, terms: d.terms.map((t, i) => (i === index ? { ...t, ...patch } : t)) }));
  }

  function updateBreakpoint(index: number, pos: 0 | 1, value: number) {
    setDraft((d) => ({
      ...d,
      breakpoints: d.breakpoints.map((bp, i) => (i === index ? ([pos === 0 ? value : bp[0], pos === 1 ? value : bp[1]] as [number, number]) : bp)),
    }));
  }

  function updateFlag(index: number, patch: Partial<FlagDraft>) {
    setDraft((d) => ({ ...d, flags: d.flags.map((f, i) => (i === index ? { ...f, ...patch } : f)) }));
  }

  function updateCategoricalRow(index: number, patch: Partial<CategoricalRowDraft>) {
    setDraft((d) => ({
      ...d,
      categoricalRows: d.categoricalRows.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    }));
  }

  function addCategoricalRow() {
    setDraft((d) => ({ ...d, categoricalRows: [...d.categoricalRows, { value: "", score: 0 }] }));
  }

  function removeCategoricalRow(index: number) {
    setDraft((d) => ({ ...d, categoricalRows: d.categoricalRows.filter((_, i) => i !== index) }));
  }

  // 選択中iconIdのプレビュー表示用。axisIconFor自体はaxisIconPalette.tsxの固定辞書を
  // 引くだけの純関数だが、react-hooks/static-componentsのeslintルールはコンポーネント
  // 本体直下で`const X = fn(); <X/>`という形を「レンダー毎にコンポーネントを新規生成
  // している」と静的に誤検知する（MapOverlayControls.tsxのrenderAxisTile等、ネストした
  // 関数内では同じ形でも誤検知しないため、ここも小さな関数に包んで回避する）。
  function renderIconPreview() {
    const PreviewIcon = axisIconFor(draft.iconId || null);
    return <PreviewIcon size={20} />;
  }

  function renderBasicStep() {
    return (
      <>
        <div className={styles.field}>
          <FieldLabel
            label="表示名(label)"
            description="一般ユーザー向けのルート設定画面・地図の凡例に表示される名前です。"
          />
          <input
            type="text"
            value={draft.label}
            aria-label="表示名(label)"
            onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))}
            placeholder="例: 未舗装回避"
          />
        </div>

        <label className={styles.fieldFull}>
          説明(description)
          <textarea
            value={draft.description}
            onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
            rows={2}
          />
        </label>

        <div className={styles.field}>
          <FieldLabel
            label="既定重み(default_weight)"
            description="この軸を誰も上書きしていないときに使われる重みです。0にするとおすすめ度の計算から実質除外されます。"
          />
          <input
            type="number"
            min="0"
            step="0.01"
            aria-label="既定重み(default_weight)"
            value={draft.defaultWeight}
            onChange={(e) => setDraft((d) => ({ ...d, defaultWeight: Number(e.target.value) }))}
          />
        </div>
      </>
    );
  }

  function renderShapeKindStep() {
    return (
      <>
        <p className={styles.groupLabel}>この軸はどうやって点数をつけますか？</p>
        <div className={styles.shapeKindOptions}>
          {SHAPE_KIND_OPTIONS.map((option) => (
            <label
              key={option.kind}
              className={
                option.kind === draft.shapeKind
                  ? `${styles.shapeKindOption} ${styles.shapeKindOptionSelected}`
                  : styles.shapeKindOption
              }
            >
              <input
                type="radio"
                name="shapeKind"
                value={option.kind}
                checked={draft.shapeKind === option.kind}
                onChange={() => setDraft((d) => ({ ...d, shapeKind: option.kind }))}
              />
              <span className={styles.shapeKindOptionBody}>
                <strong>
                  {option.title}
                  {option.advanced && <span className={styles.hint}>（上級者向け）</span>}
                </strong>
                <span className={styles.hint}>{option.description}</span>
              </span>
            </label>
          ))}
        </div>
      </>
    );
  }

  function renderShapeParamsStep() {
    return (
      <>
        <p className={styles.groupLabel}>選択中: {shapeKindOption(draft.shapeKind).title}</p>

        {(draft.shapeKind === "breakpoint_linear" || draft.shapeKind === "recipe_then_breakpoint_linear") && (
          <div className={styles.shapeGroup}>
            <p className={styles.groupLabel}>材料(terms)</p>
            {draft.terms.map((term, i) => (
              <div key={i} className={styles.termRow}>
                <select value={term.material} onChange={(e) => updateTerm(i, { material: e.target.value })}>
                  {materialOptions.filter((m) => m.dtype === "numeric").map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
                <input
                  type="number"
                  step="0.1"
                  value={term.weight}
                  aria-label="係数"
                  onChange={(e) => updateTerm(i, { weight: Number(e.target.value) })}
                />
                <label className={styles.inlineCheckbox}>
                  <Checkbox checked={term.required} onCheckedChange={(next) => updateTerm(i, { required: next })} aria-label="必須" />
                  必須
                </label>
                <button
                  type="button"
                  onClick={() => setDraft((d) => ({ ...d, terms: d.terms.filter((_, j) => j !== i) }))}
                  disabled={draft.terms.length <= 1}
                >
                  削除
                </button>
              </div>
            ))}
            <button
              type="button"
              className={styles.addButton}
              onClick={() =>
                setDraft((d) => ({
                  ...d,
                  terms: [...d.terms, { material: materialOptions[0].id, weight: 1.0, required: false }],
                }))
              }
            >
              + 材料を追加
            </button>

            <label className={styles.field}>
              前処理(preprocess)
              <select value={draft.preprocess} onChange={(e) => setDraft((d) => ({ ...d, preprocess: e.target.value as "identity" | "abs" }))}>
                <option value="identity">そのまま</option>
                <option value="abs">絶対値</option>
              </select>
            </label>

            <p className={styles.groupLabel}>折れ点(breakpoints) [入力値, スコア0-100]</p>
            {/* 改善計画T327（UIレビュー2026-08-25 F-5）: スコア0〜100が「走りやすさ」か
                「難しさ」かを明示しないまま数値ペアだけを並べていた。既存軸の実データ
                （例: gradient軸は勾配0%→0点・15%→100点ではなく、実際は逆で勾配が急なほど
                スコアが下がる設計）から「スコアは高いほど走りやすい」という規約を明文化する。 */}
            <p className={styles.hint}>
              スコアは0(最も走りにくい)〜100(最も走りやすい)で入力します。入力値が大きくなるほどスコアを上げれば「値が大きいほど走りやすい」、下げれば「値が大きいほど走りにくい」という軸になります。
            </p>
            {draft.breakpoints.map((bp, i) => (
              <div key={i} className={styles.breakpointRow}>
                <input type="number" step="0.1" value={bp[0]} aria-label="入力値" onChange={(e) => updateBreakpoint(i, 0, Number(e.target.value))} />
                <span>→</span>
                <input type="number" step="1" value={bp[1]} aria-label="スコア" onChange={(e) => updateBreakpoint(i, 1, Number(e.target.value))} />
                <button
                  type="button"
                  onClick={() => setDraft((d) => ({ ...d, breakpoints: d.breakpoints.filter((_, j) => j !== i) }))}
                  disabled={draft.breakpoints.length <= 2}
                >
                  削除
                </button>
              </div>
            ))}
            <button
              type="button"
              className={styles.addButton}
              onClick={() => setDraft((d) => ({ ...d, breakpoints: [...d.breakpoints, [0, 0]] }))}
            >
              + 折れ点を追加
            </button>
          </div>
        )}

        {draft.shapeKind === "categorical" && (() => {
          // 改善計画T322: 選んだ材料のdtypeで表示を切り替える（boolean→従来の2択、
          // categorical→値ごとのスコア行）。
          const selectedDtype = materialOptions.find((m) => m.id === draft.categoricalMaterial)?.dtype;
          return (
            <div className={styles.shapeGroup}>
              <label className={styles.field}>
                材料(material)
                <select
                  value={draft.categoricalMaterial}
                  onChange={(e) => {
                    const nextMaterial = e.target.value;
                    const nextDtype = materialOptions.find((m) => m.id === nextMaterial)?.dtype;
                    setDraft((d) => ({
                      ...d,
                      categoricalMaterial: nextMaterial,
                      categoricalRows:
                        nextDtype === "categorical" && d.categoricalRows.length === 0
                          ? [{ value: "", score: 0 }]
                          : d.categoricalRows,
                    }));
                  }}
                >
                  {materialOptions
                    .filter((m) => m.dtype === "boolean" || m.dtype === "categorical")
                    .map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                      </option>
                    ))}
                </select>
              </label>
              {selectedDtype === "categorical" ? (
                <>
                  <p className={styles.hint}>
                    値は元データのタグ値と完全に一致する文字列で入力します。ここに設定していない値の区間は、この軸では評価対象外（データなし扱い）になります。
                  </p>
                  <p className={styles.groupLabel}>値ごとのスコア</p>
                  {draft.categoricalRows.map((row, i) => (
                    <div key={i} className={styles.termRow}>
                      <input
                        type="text"
                        value={row.value}
                        aria-label="値"
                        placeholder="例: separated"
                        onChange={(e) => updateCategoricalRow(i, { value: e.target.value })}
                      />
                      <input
                        type="number"
                        step="1"
                        value={row.score}
                        aria-label="スコア"
                        onChange={(e) => updateCategoricalRow(i, { score: Number(e.target.value) })}
                      />
                      <button
                        type="button"
                        onClick={() => removeCategoricalRow(i)}
                        disabled={draft.categoricalRows.length <= 1}
                      >
                        削除
                      </button>
                    </div>
                  ))}
                  <button type="button" className={styles.addButton} onClick={addCategoricalRow}>
                    + 値を追加
                  </button>
                </>
              ) : (
                <div className={styles.row}>
                  <label className={styles.field}>
                    該当時(true)のスコア
                    <input type="number" step="1" value={draft.trueScore} onChange={(e) => setDraft((d) => ({ ...d, trueScore: Number(e.target.value) }))} />
                  </label>
                  <label className={styles.field}>
                    非該当時(false)のスコア
                    <input type="number" step="1" value={draft.falseScore} onChange={(e) => setDraft((d) => ({ ...d, falseScore: Number(e.target.value) }))} />
                  </label>
                </div>
              )}
            </div>
          );
        })()}

        {draft.shapeKind === "flag_sum" && (
          <div className={styles.shapeGroup}>
            <p className={styles.groupLabel}>フラグ(flags)</p>
            {draft.flags.map((flag, i) => (
              <div key={i} className={styles.termRow}>
                <select value={flag.material} onChange={(e) => updateFlag(i, { material: e.target.value })}>
                  {materialOptions.filter((m) => m.dtype === "boolean").map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
                <input type="number" step="1" value={flag.points} aria-label="加点" onChange={(e) => updateFlag(i, { points: Number(e.target.value) })} />
                <button
                  type="button"
                  onClick={() => setDraft((d) => ({ ...d, flags: d.flags.filter((_, j) => j !== i) }))}
                  disabled={draft.flags.length <= 1}
                >
                  削除
                </button>
              </div>
            ))}
            <button
              type="button"
              className={styles.addButton}
              onClick={() =>
                setDraft((d) => ({
                  ...d,
                  flags: [...d.flags, { material: materialOptions.find((m) => m.dtype === "boolean")?.id ?? "", points: 10 }],
                }))
              }
            >
              + フラグを追加
            </button>
            <label className={styles.field}>
              上限(cap、任意)
              <input
                type="number"
                step="1"
                value={draft.cap ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, cap: e.target.value === "" ? null : Number(e.target.value) }))}
              />
            </label>
          </div>
        )}
      </>
    );
  }

  function renderDisplayPublishStep() {
    return (
      <>
        <div className={styles.shapeGroup}>
          <p className={styles.groupLabel}>地図チップ表示要素(任意)</p>
          <p className={styles.hint}>
            いずれも未設定のままでよい（アイコンは汎用アイコン、略称は表示名(label)、地図の見え方パネルの説明は
            説明(description)がそれぞれ代わりに使われる）。
          </p>
          <label className={styles.inlineCheckbox}>
            <Checkbox
              checked={draft.showMapIcon}
              onCheckedChange={(next) => setDraft((d) => ({ ...d, showMapIcon: next }))}
              aria-label="地図上にアイコンを表示する(show_map_icon)"
            />
            地図上にアイコンを表示する(show_map_icon)（オフにすると地図上チップ・地図の見え方パネルのどちらにもこの軸が現れなくなります）
          </label>
          <div className={styles.field}>
            <FieldLabel label="アイコン(icon_id)" description="地図チップに表示するアイコン。既存の意匠から選ぶ（新しい形状の追加はコード変更が必要）。" />
            <div className={styles.row}>
              <select
                value={draft.iconId}
                aria-label="アイコン(icon_id)"
                onChange={(e) => setDraft((d) => ({ ...d, iconId: e.target.value }))}
              >
                <option value="">（未設定、汎用アイコン）</option>
                {Object.entries(AXIS_ICON_PALETTE).map(([iconId, entry]) => (
                  <option key={iconId} value={iconId}>
                    {entry.label}
                  </option>
                ))}
              </select>
              {renderIconPreview()}
            </div>
          </div>

          <div className={styles.field}>
            <FieldLabel
              label="地図チップの略称(chip_label)"
              description="4文字以内（地図チップは固定サイズのタイルのため必須の上限。未設定時は表示名(label)がそのまま使われるが、正式名が4文字を超える場合はここで略称を設定すること）。"
            />
            <input
              type="text"
              value={draft.chipLabel}
              aria-label="地図チップの略称(chip_label)"
              onChange={(e) => setDraft((d) => ({ ...d, chipLabel: e.target.value }))}
              maxLength={4}
              placeholder="例: 未舗装"
            />
          </div>

          <label className={styles.fieldFull}>
            地図の見え方パネル向け説明文(panel_hint)
            <textarea
              value={draft.panelHint}
              onChange={(e) => setDraft((d) => ({ ...d, panelHint: e.target.value }))}
              rows={2}
              placeholder="一般ユーザー向けに噛み砕いた説明文（未設定時は説明(description)がそのまま使われる）"
            />
          </label>
        </div>

        <label className={styles.inlineCheckbox}>
          <Checkbox
            checked={draft.isPublished}
            onCheckedChange={(next) => setDraft((d) => ({ ...d, isPublished: next }))}
            aria-label="公開する"
          />
          公開する（一般向けルート設定画面に表示。公開後は更新・削除ができなくなります——改良は複製から）
        </label>
      </>
    );
  }

  return (
    <form onSubmit={handleSubmit} className={styles.composer}>
      <p className={styles.stepIndicator}>
        ステップ {stepIndex + 1}/{STEPS.length}: {STEP_TITLES[step]}
      </p>

      {step === "basic" && renderBasicStep()}
      {step === "shape_kind" && renderShapeKindStep()}
      {step === "shape_params" && renderShapeParamsStep()}
      {step === "display_publish" && renderDisplayPublishStep()}

      {error && <p className={styles.errorText}>{error}</p>}

      <div className={styles.row}>
        {stepIndex > 0 && (
          <button type="button" onClick={goBack} disabled={saving}>
            戻る
          </button>
        )}
        {step !== "display_publish" ? (
          <button type="button" onClick={goNext} className={styles.saveButton}>
            次へ
          </button>
        ) : (
          <button type="submit" disabled={saving} className={styles.saveButton}>
            {saving ? "保存中..." : isNew ? "作成する" : "更新する"}
          </button>
        )}
        {!isNew && (
          <button type="button" onClick={onCancelEdit} disabled={saving}>
            編集をやめる
          </button>
        )}
      </div>
    </form>
  );
}
