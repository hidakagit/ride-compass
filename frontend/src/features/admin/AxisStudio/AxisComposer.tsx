"use client";

// 軸コンポーザー。1画面のフォームで軸を組み立てる中核機能。節ごとの中身は
// AxisScoringSection（点数の決め方）・AxisMapDisplaySection（地図の色分け・公開）が持ち、
// ここは状態・検証・保存と、その組み立てだけを担う。

import { useState } from "react";
import { FieldLabel } from "@/components/ui/FieldLabel/FieldLabel";
import { useMapBandsOfThresholds } from "@/features/admin/useMapBandsOfThresholds";
import type { AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";
import { MATERIAL_CATALOG, type AxisMaterialOption } from "@/lib/axisMaterialsCatalog";

import { AxisMapDisplaySection } from "./AxisMapDisplaySection";
import { AxisScoringSection } from "./AxisScoringSection";
import { buildShape, draftFromDuplicate, draftFromExisting, emptyDraft, type Draft } from "./axisDraft";
import { Button } from "@/components/ui/Button/Button";
import { NumberInput } from "@/components/ui/NumberInput/NumberInput";
import { Input, Textarea } from "@/components/ui/Input/Input";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { cardVariants } from "@/components/ui/Card/Card";
import { fieldClass } from "@/components/ui/Input/Input";

interface AxisComposerProps {
  /** 編集対象。nullなら新規作成（下記duplicateFromが無ければ空欄から）。公開済み軸も
   * 渡りうる——その場合は材料・計算式・重み等の編集UIを一切出さず、**評価に影響しない
   * 表示専用フィールドだけ**を編集する制限モードへ自動的に切り替わる（どのフィールドが
   * それに当たるかは下記`restrictedDisplayOnly`の分岐が決める。ここへ並べると、backendが
   * 1つ足したときにこの注釈だけが古くなる）。 */
  editing: AxisDefinitionResponse | null;
  /** 複製元。editingがnullのとき、この軸の内容（axis_id/is_published除く）で新規作成
   * フォームを初期化する。 */
  duplicateFrom: AxisDefinitionResponse | null;
  /** 編集中の軸を地図が塗るときの段階色（しきい値の配列→段階数ぶんの色）。段階プレビューを
   * 実際の地図と同じ色で描くために親が渡す。地図に出る経路がまだ決まっていない軸
   * （下書き・ramp表示も専用配信も持たない軸）ではundefinedで、プレビューは色を持たない。 */
  mapBandColors?: (boundaries: readonly number[]) => readonly string[];
  /** 段階プレビューのレンジに添える単位（軸カタログのmap_value_unit、無ければ空）。 */
  mapValueUnit?: string;
  /** 既定重み(default_weight)欄に「他の公開軸の重みに対して何%か」を参考表示するための、
   * この軸以外を含む全軸一覧（AxisStudio.tsxが一覧取得済みのものをそのまま渡す）。
   * 省略時（テスト等）は参考表示自体を出さない。 */
  otherAxes?: readonly AxisDefinitionResponse[];
  /** 「調整する」で一時的に下書きへ戻した軸を編集中か。**保存すると必ず公開へ戻る**ため、
   * 公開の切り替えを操作させない（操作させると、チェックを外して保存しても公開へ戻り、
   * 画面の操作結果が無言で反転する）。 */
  republishing?: boolean;
  onCancelEdit: () => void;
  onSave: (payload: AxisDefinitionPayload, isNew: boolean) => Promise<void>;
}

// 節の識別子。画面は1枚のため順番を持たず、「どの節の検証か」を指すだけに使う。
const SECTIONS = ["basic", "shape_params", "display_publish"] as const;
type Section = (typeof SECTIONS)[number];

export default function AxisComposer({
  editing,
  duplicateFrom,
  otherAxes,
  mapBandColors,
  mapValueUnit = "",
  republishing = false,
  onCancelEdit,
  onSave,
}: AxisComposerProps) {
  const [draft, setDraft] = useState<Draft>(() => {
    const axisIds = new Set((otherAxes ?? []).map((axis) => axis.axis_id));
    if (editing) return draftFromExisting(editing, MATERIAL_CATALOG, axisIds);
    if (duplicateFrom) return draftFromDuplicate(duplicateFrom, MATERIAL_CATALOG, axisIds);
    return emptyDraft(MATERIAL_CATALOG);
  });
  // 公開済み軸は、backendが表示専用フィールドの差分しか受け付けない
  // （`domain/axis_definitions.py: _COSMETIC_ONLY_FIELDS`）。編集できない節は
  // 描画そのものを省き、いま何が変えられるかを画面の形で示す。
  const restrictedDisplayOnly = editing !== null && editing.is_published;
  // 地図の色分けしきい値のまとめ入力が読めない間は保存させない（節から受け取る）。
  const [thresholdError, setThresholdError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isNew = editing === null;
  const thresholds = draft.displayThresholdsOverride;
  const mapBands = useMapBandsOfThresholds(
    thresholds && thresholds.length > 0
      ? {
          axis_id: draft.axisId,
          shape: buildShape(draft, MATERIAL_CATALOG),
          priority_overrides: draft.passthrough.priority_overrides,
          thresholds,
        }
      : null,
  );

  // backend側は元々MaterialTerm.materialへ他の軸のaxis_idを指定できる設計
  // （domain/axis_definitions.py: AxisDefinition docstring「軸の階層」）。「他の軸の
  // 計算結果をもとに点数を変える」テンプレートでは、この軸候補一覧（otherAxes）を
  // 材料の一覧（MATERIAL_CATALOG）とは別に用意する。編集中の軸自身は
  // 自己参照になるため候補から除く。軸のスコアは常に0〜100（difficultyの規約）のため
  // dtype="numeric"として扱う。
  const axisTermOptions: readonly AxisMaterialOption[] = (otherAxes ?? [])
    .filter((a) => a.axis_id !== draft.axisId)
    .map((a) => ({
      id: a.axis_id,
      label: a.label,
      name: a.label,
      description: a.description,
      dtype: "numeric" as const,
      unit: "",
    }));

  // 一覧から別の軸の編集を選び直した場合の切り替えは、呼び出し側（AxisStudio）が
  // <AxisComposer key={editing?.axis_id ?? "new"}> のようにkeyを変えてコンポーネント自体を
  // 再マウントする方式に委ねる（このコンポーネント内でeditingの変化を検知しない）。

  // 保存前の検証。軸の不変条件（表示名・折れ点の昇順・値の行の件数・略称・しきい値の件数と昇順等）はbackendが検証し、保存の
  // 誤りとして日本語の文を返す（`axis_definitions.py: axis_error`）。ここで写さない——写すと、backendの条件を
  // 変えたとき画面だけが古い条件で止める。ここに残すのは、入力の読み取りの誤りだけ。
  function validateSection(target: Section): string | null {
    if (target === "display_publish" && draft.displayThresholdsOverride !== null && thresholdError) {
      return thresholdError;
    }
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    // 画面は1枚なので、検証は保存の直前にまとめて行う。制限モード（公開済み軸）は
    // 表示専用フィールドしか描画しないため、それ以外の節を検証すると「入力欄が無いのに
    // そこへ誘導される」行き止まりになる（公開済み軸は削除もできず、複製して作り直す
    // 以外に手が無くなる）。編集できない値はそもそも書き換えようがないので、編集できる
    // 節だけを検証する（不正な既存軸はbackend側の検証が最終的に弾く）。
    const sectionsToValidate: readonly Section[] = restrictedDisplayOnly ? ["display_publish"] : SECTIONS;
    for (const target of sectionsToValidate) {
      const err = validateSection(target);
      if (err) {
        setError(err);
        return;
      }
    }
    const payload: AxisDefinitionPayload = {
      // 編集欄を持たないフィールドは既存値をそのまま送り返す（`PASSTHROUGH_PAYLOAD_KEYS`）。
      // 編集値を後から重ねるため、ここでの展開順を入れ替えないこと。
      ...draft.passthrough,
      axis_id: draft.axisId,
      label: draft.label.trim(),
      description: draft.description,
      default_weight: draft.defaultWeight,
      shape: buildShape(draft, MATERIAL_CATALOG),
      is_published: draft.isPublished,
      // 空文字列は「未設定」の意味でnullへ変換する（trim()の理由はlabelと同じ、
      // 空白のみの入力を未設定扱いにする）。
      icon_id: draft.iconId.trim() === "" ? null : draft.iconId,
      chip_label: draft.chipLabel.trim() === "" ? null : draft.chipLabel.trim(),
      panel_hint: draft.panelHint.trim() === "" ? null : draft.panelHint.trim(),
      // 地図上にアイコンを表示するかどうかのON/OFF（既定true）。
      show_map_icon: draft.showMapIcon,
      display_thresholds_override: draft.displayThresholdsOverride,
      display_band_labels_override: draft.displayBandLabelsOverride,
    };
    setSaving(true);
    try {
      // 保存成功後は呼び出し側（AxisStudio）がモーダルごと閉じるため、ここでフォームを
      // リセットして開いたままにする必要はない。
      await onSave(payload, isNew);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  /** 既定重みの絶対値だけでは効果が分からない。
   * backend側の合成（domain/difficulty.py: composite_difficulty）は重み付き"平均"
   * （重みの合計で正規化）で、かつ対象は公開軸のみ（domain/axis_definitions.py:
   * default_axis_weights）のため、「他の公開軸の重み合計に対して何%か」を参考表示する。
   * 非公開の軸はそもそもこの合成に加わらないため、公開してから意味を持つ旨を案内する。
   * otherAxes未指定（テスト等）・公開軸が1つも無い場合は表示しない。 */
  function renderWeightShare() {
    if (!otherAxes) return null;
    if (!draft.isPublished) {
      return (
        <p className={textVariants({ variant: "hint" })}>
          この軸は現在非公開のため、重みはルート探索へ直接使われません（公開すると、他の公開軸との比率で効くようになります）。
        </p>
      );
    }
    // 公開したときの割合はbackendが総合難易度と同じ分母で返す（保存した重みで計算するため、編集中の値は
    // 保存してから変わる）。保存前の新しい軸は割合を持たない。
    const share = otherAxes.find((a) => a.axis_id === draft.axisId)?.weight_share_when_published;
    if (share == null) return null;
    const publishedCount = otherAxes.filter((a) => a.is_published && a.axis_id !== draft.axisId).length + 1;
    return (
      <p className={textVariants({ variant: "hint" })}>
        参考: 現在の公開軸全体（{publishedCount}軸）の重み合計に対して約{(share * 100).toFixed(1)}
        %です（保存した重みで計算）。
      </p>
    );
  }

  function renderBasicFields() {
    return (
      <>
        <div className={fieldClass}>
          <FieldLabel
            label="表示名"
            description="一般ユーザー向けのルート設定画面・地図の凡例に表示される名前です。（API: label）"
          />
          <Input
            type="text"
            value={draft.label}
            aria-label="表示名"
            onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))}
            placeholder="例: 未舗装回避"
          />
        </div>

        <label className={fieldClass}>
          説明
          <Textarea
            value={draft.description}
            onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
            rows={2}
          />
        </label>

        <div className={fieldClass}>
          <FieldLabel
            label="既定重み"
            description="この軸を誰も上書きしていないときに使われる重みです。他の公開軸の重みとの比率だけがルートの選ばれ方を左右します（数値そのものに意味はありません。例: 全軸の重みを一律2倍にしても結果は変わりません）。大きくするほど、他の軸に対して相対的にこの軸を重視します。0にすると計算から除外されます。（API: default_weight）"
          />
          <NumberInput
            commitOn="input"
            min="0"
            step="any"
            aria-label="既定重み"
            value={draft.defaultWeight}
            onValueChange={(next) => setDraft((d) => ({ ...d, defaultWeight: next }))}
          />
          {renderWeightShare()}
        </div>
      </>
    );
  }

  return (
    // noValidate: 検証はvalidateSectionが行い、原因を文章で出す。ブラウザ側の制約検証
    // （step・min/max）へ任せると、小数の刻みが浮動小数の誤差で不一致と判定されたとき、
    // 何の表示も無いまま送信だけが止まる——1画面になって全ての欄が同時に検証対象へ入った
    // ぶん、この止まり方は起きやすい。
    //
    // このフォームの中で**ボタンの役割を切り替えるときは、同じ要素の`type`を書き換えない**。
    // ブラウザは押された後の`type`で既定動作を判定するため、`"button"`→`"submit"`へ同期的に
    // 変わるとフォームが暗黙に送信される。役割が変わるなら`key`を変えて別の要素として
    // 作り直すこと（happy-domはこの判定のタイミング差を再現しないため、テストでは捕まらない）。
    <form
      onSubmit={handleSubmit}
      className={cn(cardVariants({ variant: "outline" }), "flex flex-col gap-3 border-[var(--color-border-strong)]")}
      noValidate
    >
      {restrictedDisplayOnly && (
        <p className={textVariants({ variant: "hint" })}>
          公開済みの軸のため、地図表示に関わる項目のみ編集できます（材料・計算式・重みを変えたい場合は「複製して新規作成」してください）。
        </p>
      )}

      {!restrictedDisplayOnly && renderBasicFields()}
      {!restrictedDisplayOnly && (
        <AxisScoringSection
          draft={draft}
          setDraft={setDraft}
          materialOptions={MATERIAL_CATALOG}
          axisTermOptions={axisTermOptions}
        />
      )}
      <AxisMapDisplaySection
        draft={draft}
        setDraft={setDraft}
        editing={editing}
        restrictedDisplayOnly={restrictedDisplayOnly}
        republishing={republishing}
        mapBandColors={mapBandColors}
        mapValueUnit={mapValueUnit}
        mapBands={mapBands}
        onThresholdErrorChange={setThresholdError}
      />

      {error && <p className={textVariants({ variant: "error" })}>{error}</p>}

      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" size="sm" type="submit" disabled={saving}>
          {saving ? "保存中..." : isNew ? "作成する" : "更新する"}
        </Button>
        {!isNew && (
          <Button size="sm" onClick={onCancelEdit} disabled={saving}>
            編集をやめる
          </Button>
        )}
      </div>
    </form>
  );
}
