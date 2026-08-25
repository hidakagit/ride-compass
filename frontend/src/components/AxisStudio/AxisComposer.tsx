"use client";

import { useState } from "react";
import { FieldLabel } from "@/components/Map/recipeControls";
import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import { useMaterialCatalog } from "@/hooks/useMaterialCatalog";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import type { AxisDefinitionPayload, AxisDefinitionResponse, AxisShape } from "@/types/route";
import styles from "./AxisStudio.module.css";

// 軸コンポーザー（改善計画T270、T221 Stage E）。材料選択→4テンプレート選択→パラメータ
// 調整→保存、という軸スタジオの中核機能。既存の`AxisDefinition.shape`（判別union、
// backend/app/domain/axis_definitions.py）をそのままGUIの入力欄群へ写す。
//
// テンプレートは4種に限定する（ADR「新しい計算テンプレートの追加は引き続きコード変更が
// 必要、際限のない汎用化は目指さない」という承認済み方針）。材料は
// useMaterialCatalog()（改善計画T277、GET /api/material-catalog）が返す候補から選ぶ
// （目論見書7章・歯止め4「材料の天井」。API取得失敗時はlib/axisMaterialsCatalog.tsの
// 静的フォールバックへ自動的に切り替わる）。

type ShapeKind = "breakpoint_linear" | "recipe_then_breakpoint_linear" | "categorical" | "flag_sum";
type Category = "観測" | "推定" | "動的";

// 各変換テンプレート(shape)の説明（改善計画T304、「軸スタジオの使い方が分かりにくい」
// という実機フィードバックへの対応）。選択肢のラベルだけでは何が起きるか分からない
// という指摘のため、選んだ時点でその意味と具体例を1文で示す。
const SHAPE_KIND_DESCRIPTIONS: Record<ShapeKind, string> = {
  breakpoint_linear:
    "1つ以上の材料を重み付きで足し合わせ、折れ点（入力値→スコア）でなめらかに0〜100点へ変換します。例: 勾配(%)が急なほど点数を下げる。",
  recipe_then_breakpoint_linear:
    "他の軸（is_published=falseの内部軸）の計算結果を材料として使う場合に選びます。変換の仕組み自体はひとつ上の区分線形補間と同じです。",
  categorical: "真偽値1つを見て、該当する/しないの2パターンにそれぞれ固定スコアを割り当てます。例: 一方通行かどうか。",
  flag_sum: "複数の真偽フラグそれぞれに加点し合計します（上限[cap]を設定可）。例: 危険要因が多いほど減点する。",
};

interface TermDraft {
  material: string;
  weight: number;
  required: boolean;
}

interface FlagDraft {
  material: string;
  points: number;
}

interface Draft {
  axisId: string;
  label: string;
  description: string;
  category: Category;
  defaultWeight: number;
  shapeKind: ShapeKind;
  terms: TermDraft[];
  preprocess: "identity" | "abs";
  breakpoints: [number, number][];
  categoricalMaterial: string;
  trueScore: number;
  falseScore: number;
  flags: FlagDraft[];
  cap: number | null;
  /** 改善計画T271: 公開状態。trueにすると一般向けGET /api/axis-catalogへ現れ、以後
   * backend側で更新・削除が拒否される（不変制約）ため、確定前によく確認してからONにする。 */
  isPublished: boolean;
}

function emptyDraft(materialOptions: readonly AxisMaterialOption[]): Draft {
  const firstBoolean = materialOptions.find((m) => m.dtype === "boolean")?.id ?? materialOptions[0].id;
  return {
    axisId: "",
    label: "",
    description: "",
    category: "推定",
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
    flags: [{ material: firstBoolean, points: 50 }],
    cap: 100,
    isPublished: false,
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
    category: def.category,
    defaultWeight: def.default_weight,
    isPublished: def.is_published,
  };
  // "kind"の判別子で分岐する（AxisShapeは3種のPydantic discriminated unionの構造をそのまま
  // 写した型のため、"terms"/"material"/"flags"というフィールド有無による判別も可能だが、
  // backend側の判別子(kind)に合わせてこちらを単一の判定基準にする）。
  if (shape.kind === "categorical") {
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
 * axis_idは空にして必ず新しいidの入力を求め、is_publishedは常にfalse（下書き）から
 * 始める——複製元が公開済みでも複製先まで公開扱いを引き継がない。 */
function draftFromDuplicate(def: AxisDefinitionResponse, materialOptions: readonly AxisMaterialOption[]): Draft {
  return { ...draftFromExisting(def, materialOptions), axisId: "", isPublished: false };
}

function buildShape(draft: Draft): AxisShape {
  if (draft.shapeKind === "breakpoint_linear" || draft.shapeKind === "recipe_then_breakpoint_linear") {
    return {
      kind: draft.shapeKind,
      terms: draft.terms.map((t) => ({ material: t.material, weight: t.weight, required: t.required })),
      preprocess: draft.preprocess,
      breakpoints: draft.breakpoints,
    };
  }
  if (draft.shapeKind === "categorical") {
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

export default function AxisComposer({ editing, duplicateFrom, onCancelEdit, onSave }: AxisComposerProps) {
  const materialOptions = useMaterialCatalog();
  const [draft, setDraft] = useState<Draft>(() => {
    if (editing) return draftFromExisting(editing, materialOptions);
    if (duplicateFrom) return draftFromDuplicate(duplicateFrom, materialOptions);
    return emptyDraft(materialOptions);
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isNew = editing === null;

  // 一覧から別の軸の編集を選び直した場合の切り替えは、呼び出し側（AxisStudio）が
  // <AxisComposer key={editing?.axis_id ?? "new"}> のようにkeyを変えてコンポーネント自体を
  // 再マウントする方式に委ねる（このコンポーネント内でeditingの変化を検知しない）。

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (draft.axisId.trim() === "") {
      setError("axis_idを入力してください。");
      return;
    }
    if (draft.label.trim() === "") {
      setError("表示名(label)を入力してください。");
      return;
    }
    const payload: AxisDefinitionPayload = {
      axis_id: draft.axisId.trim(),
      label: draft.label.trim(),
      description: draft.description,
      category: draft.category,
      default_weight: draft.defaultWeight,
      shape: buildShape(draft),
      is_published: draft.isPublished,
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

  return (
    <form onSubmit={handleSubmit} className={styles.composer}>
      <div className={styles.row}>
        <div className={styles.field}>
          <FieldLabel
            label="axis_id"
            description="軸の内部識別子（半角英数字とアンダースコア）。ルート設定・APIのキーとして使われ、作成後は変更できません。"
          />
          <input
            type="text"
            value={draft.axisId}
            disabled={!isNew}
            aria-label="axis_id"
            onChange={(e) => setDraft((d) => ({ ...d, axisId: e.target.value }))}
            placeholder="例: unpaved_avoidance"
          />
        </div>
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
      </div>

      <label className={styles.fieldFull}>
        説明(description)
        <textarea
          value={draft.description}
          onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
          rows={2}
        />
      </label>

      <div className={styles.row}>
        <div className={styles.field}>
          <FieldLabel
            label="分類(category)"
            description="観測=タグ・POIをそのまま読む軸／推定=複数の材料を判定式で合成する軸／動的=気象等、時々刻々変わる外部データ由来の軸。一般向けルート設定画面のグループ分けに使われます。"
          />
          <select
            value={draft.category}
            aria-label="分類(category)"
            onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value as Category }))}
          >
            <option value="観測">観測</option>
            <option value="推定">推定</option>
            <option value="動的">動的</option>
          </select>
        </div>
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
      </div>

      <label className={styles.fieldFull}>
        変換テンプレート(shape)
        <select
          value={draft.shapeKind}
          onChange={(e) => setDraft((d) => ({ ...d, shapeKind: e.target.value as ShapeKind }))}
        >
          <option value="breakpoint_linear">区分線形補間（複数材料の線形結合→折れ線）</option>
          <option value="recipe_then_breakpoint_linear">区分線形補間（レシピ判定済み材料向け）</option>
          <option value="categorical">カテゴリ値（真偽2値→定数）</option>
          <option value="flag_sum">フラグ加算（複数の真偽フラグ→加点合計）</option>
        </select>
      </label>
      <p className={styles.hint}>{SHAPE_KIND_DESCRIPTIONS[draft.shapeKind]}</p>

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

      {draft.shapeKind === "categorical" && (
        <div className={styles.shapeGroup}>
          <label className={styles.field}>
            材料(material)
            <select
              value={draft.categoricalMaterial}
              onChange={(e) => setDraft((d) => ({ ...d, categoricalMaterial: e.target.value }))}
            >
              {materialOptions.filter((m) => m.dtype === "boolean").map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
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
        </div>
      )}

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

      <label className={styles.inlineCheckbox}>
        <Checkbox
          checked={draft.isPublished}
          onCheckedChange={(next) => setDraft((d) => ({ ...d, isPublished: next }))}
          aria-label="公開する"
        />
        公開する（一般向けルート設定画面に表示。公開後は更新・削除ができなくなります——改良は複製から）
      </label>

      {error && <p className={styles.errorText}>{error}</p>}

      <div className={styles.row}>
        <button type="submit" disabled={saving} className={styles.saveButton}>
          {saving ? "保存中..." : isNew ? "作成する" : "更新する"}
        </button>
        {!isNew && (
          <button type="button" onClick={onCancelEdit} disabled={saving}>
            編集をやめる
          </button>
        )}
      </div>
    </form>
  );
}
