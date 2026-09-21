"use client";

// 軸コンポーザー。1画面のフォームで軸を組み立てる中核機能。節ごとの中身は
// AxisScoringSection（点数の決め方）・AxisMapDisplaySection（地図の色分け・公開）が持ち、
// ここは状態・検証・保存と、その組み立てだけを担う。

import { useCallback, useState } from "react";
import { FieldLabel } from "@/components/Map/recipeControls";
import { useMaterialCatalog } from "@/hooks/useMaterialCatalog";
import type { AxisDefinitionPayload, AxisDefinitionResponse } from "@/types/route";
import type { AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import styles from "./AxisStudio.module.css";
import { NumberField } from "./AxisFormFields";
import { AxisMapDisplaySection } from "./AxisMapDisplaySection";
import { AxisScoringSection } from "./AxisScoringSection";
import { buildShape, draftFromDuplicate, draftFromExisting, emptyDraft, type Draft } from "./axisDraft";

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
  const { materials: materialOptions, loaded: catalogLoaded } = useMaterialCatalog();
  const deriveDraft = useCallback((): Draft => {
    if (editing) return draftFromExisting(editing, materialOptions);
    if (duplicateFrom) return draftFromDuplicate(duplicateFrom, materialOptions);
    return emptyDraft(materialOptions);
  }, [editing, duplicateFrom, materialOptions]);
  // 材料カタログは実行時フェッチで後から入れ替わる。**入れ替わったら下書きを作り直す**
  // ——`useState`の初期化はマウント時に1度しか走らないため、ビルド時フォールバックの
  // 材料で固定されたままになる。backendをデプロイしてからfrontendをデプロイするまでの
  // 窓では、新しい材料を使う軸の編集画面が「組み合わせる軸」の画面として開く
  // （`axisDraft.ts: draftFromExisting`が材料として引けない項目を軸参照とみなすため）。
  //
  // 作り直すのは**利用者がまだ触っていないとき**だけ（触った後に入れ替えると入力が消える）。
  // 触ったかどうかは、いまの下書きが最後に導出したものと同じ実体かで判定する。
  const [derived, setDerived] = useState(() => deriveDraft());
  const [draft, setDraft] = useState<Draft>(derived);
  const [derivedFrom, setDerivedFrom] = useState(() => deriveDraft);
  if (derivedFrom !== deriveDraft) {
    const next = deriveDraft();
    setDerivedFrom(() => deriveDraft);
    setDerived(next);
    if (draft === derived) setDraft(next);
  }
  // categorical材料の値入力欄に候補選択を添えるための実データ値一覧。
  // dtype="categorical"の材料を選んでいる間だけ取得する（boolean材料選択中・
  // categorical材料でも動的値一覧に対応していない場合[bicycle_infra等]は空配列が返り、
  // 呼び出し先の入力欄は自由テキストのままになる）。
  // 公開済み軸は、backendが表示専用フィールドの差分しか受け付けない
  // （`domain/axis_definitions.py: _COSMETIC_ONLY_FIELDS`）。編集できない節は
  // 描画そのものを省き、いま何が変えられるかを画面の形で示す。
  const restrictedDisplayOnly = editing !== null && editing.is_published;
  // 地図の色分けしきい値のまとめ入力が読めない間は保存させない（節から受け取る）。
  const [thresholdError, setThresholdError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isNew = editing === null;

  // 材料が1件も無ければどの入力欄も選択肢を作れず、保存できない軸しか組めない。
  // フォームの代わりに状態を出して、開かせない。**読み込み中と0件は分けて出す**
  // ——同じ文言にすると、通信が遅いだけのときに利用者がbackendの異常を疑う。
  // フックの呼び出しはすべてこのガードより前で終えているためRules of Hooksには反しない。
  if (!catalogLoaded) {
    return <div className={styles.composer}>材料カタログを読み込んでいます…</div>;
  }
  if (materialOptions.length === 0) {
    return (
      <div className={styles.composer}>
        <p className={styles.errorText}>
          材料カタログを取得できませんでした（0件の応答）。時間をおいて再度開くか、backend側の材料カタログ（material_catalog.py）の状態を確認してください。
        </p>
        <div className={styles.row}>
          <button type="button" onClick={onCancelEdit}>
            閉じる
          </button>
        </div>
      </div>
    );
  }

  // backend側は元々MaterialTerm.materialへ他の軸のaxis_idを指定できる設計
  // （domain/axis_definitions.py: AxisDefinition docstring「軸の階層」）。「他の軸の
  // 計算結果をもとに点数を変える」テンプレートでは、この軸候補一覧（otherAxes）を
  // materialOptions（MATERIAL_CATALOGの材料）とは別に用意する。編集中の軸自身は
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

  // 保存前の検証。backend側の検証を先回りし、どの入力欄が原因かを文章で示す。
  function validateSection(target: Section): string | null {
    if (target === "basic") {
      if (draft.label.trim() === "") return "表示名を入力してください。";
    }
    if (target === "shape_params" && draft.shapeKind === "breakpoint_linear") {
      // display_thresholds_override
      // （色分け表示用）と同じ昇順チェックを、評価に使うdraft.breakpoints
      // （backend: shape.breakpoints）にも先回りして適用する。backend側の対応する
      // 検証（axis_admin.py: _check_materials_are_known内）は保存時の最終防衛のため、
      // ここでは保存する前にユーザーへ知らせる。
      const xs = draft.breakpoints.map((bp) => bp[0]);
      if (xs.some((x, i) => i > 0 && x <= xs[i - 1])) {
        return "折れ点は横軸（左の入力欄）の値が小さい順になるようにしてください（同じ値は使えません）。";
      }
    }
    if (target === "shape_params" && draft.shapeKind === "categorical") {
      // categorical材料選択時、値の行が1つも入力されていないと
      // mapping={}のまま保存されてしまい（全区間で評価不能=欠損になるだけで保存自体は
      // 通ってしまう）、設定し忘れに気づきにくいため事前に弾く。
      const dtype = materialOptions.find((m) => m.id === draft.categoricalMaterial)?.dtype;
      if (dtype === "categorical" && draft.categoricalRows.every((r) => r.value.trim() === "")) {
        return "値ごとのスコアを少なくとも1件設定してください。";
      }
    }
    if (target === "display_publish") {
      // backend側の検証（axis_admin.py: _check_label_length_or_chip_label）と同じ条件を
      // ここでも先回りしてチェックし、保存時まで待たせない。
      if (draft.chipLabel.trim() === "" && draft.label.trim().length > 4) {
        return "表示名が4文字を超えています。チップの略称を設定してください。";
      }
      // backend側の検証（axis_admin.py: AxisDefinitionPayload._check_
      // display_thresholds_override_is_ascending）と同じ条件を先回りしてチェックする。
      if (draft.displayThresholdsOverride !== null) {
        if (thresholdError) return thresholdError;
        if (draft.displayThresholdsOverride.length === 0) {
          return "色分けのしきい値を1件以上入力するか、上書きをオフにしてください。";
        }
      }
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
      shape: buildShape(draft, materialOptions),
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
        <p className={styles.hint}>
          この軸は現在非公開のため、重みはルート探索へ直接使われません（公開すると、他の公開軸との比率で効くようになります）。
        </p>
      );
    }
    const publishedOthers = otherAxes.filter((a) => a.is_published && a.axis_id !== draft.axisId);
    const total = publishedOthers.reduce((sum, a) => sum + a.default_weight, 0) + draft.defaultWeight;
    if (total <= 0) return null;
    const sharePercent = (draft.defaultWeight / total) * 100;
    return (
      <p className={styles.hint}>
        参考: 現在の公開軸全体（{publishedOthers.length + 1}軸）の重み合計に対して約{sharePercent.toFixed(1)}%です。
      </p>
    );
  }

  function renderBasicFields() {
    return (
      <>
        <div className={styles.field}>
          <FieldLabel
            label="表示名"
            description="一般ユーザー向けのルート設定画面・地図の凡例に表示される名前です。（API: label）"
          />
          <input
            type="text"
            value={draft.label}
            aria-label="表示名"
            onChange={(e) => setDraft((d) => ({ ...d, label: e.target.value }))}
            placeholder="例: 未舗装回避"
          />
        </div>

        <label className={styles.fieldFull}>
          説明
          <textarea
            value={draft.description}
            onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
            rows={2}
          />
        </label>

        <div className={styles.field}>
          <FieldLabel
            label="既定重み"
            description="この軸を誰も上書きしていないときに使われる重みです。他の公開軸の重みとの比率だけがルートの選ばれ方を左右します（数値そのものに意味はありません。例: 全軸の重みを一律2倍にしても結果は変わりません）。大きくするほど、他の軸に対して相対的にこの軸を重視します。0にすると計算から除外されます。（API: default_weight）"
          />
          <NumberField
            min="0"
            step="any"
            aria-label="既定重み"
            value={draft.defaultWeight}
            onChange={(next) => setDraft((d) => ({ ...d, defaultWeight: next }))}
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
    <form onSubmit={handleSubmit} className={styles.composer} noValidate>
      {restrictedDisplayOnly && (
        <p className={styles.hint}>
          公開済みの軸のため、地図表示に関わる項目のみ編集できます（材料・計算式・重みを変えたい場合は「複製して新規作成」してください）。
        </p>
      )}

      {!restrictedDisplayOnly && renderBasicFields()}
      {!restrictedDisplayOnly && (
        <AxisScoringSection
          draft={draft}
          setDraft={setDraft}
          materialOptions={materialOptions}
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
        onThresholdErrorChange={setThresholdError}
      />

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
