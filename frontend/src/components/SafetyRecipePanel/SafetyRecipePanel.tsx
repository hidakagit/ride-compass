"use client";

import { useState } from "react";
import { AdjustmentStepper, FieldLabel, LevelPicker } from "@/components/Map/recipeControls";
import { SAFETY_COLORS } from "@/components/Map/staticAttributeLayers";
import { DEFAULT_SAFETY_RECIPE, type SafetyRecipe } from "@/components/Map/safetyExpression";
import styles from "./SafetyRecipePanel.module.css";

// TrafficStressRecipePanel.tsxと完全に同じ構造（基準値レベルピッカー・補正値ステッパー・
// 情報アイコン開閉ボタンはrecipeControls.tsxを共有、それ以外の骨格もミラー）。改善計画:
// 安全度レシピ。フィールド集合だけが異なる: 安全度はlanes_low（少車線）を採用せず
// （domain/safety.py: SafetyRecipeのdocstring参照）、代わりにshoulder/lit/tunnel
// （路肩・街灯・トンネル）の3補正を持つ。

interface SafetyRecipePanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  recipe: SafetyRecipe;
  onRecipeChange: (recipe: SafetyRecipe) => void;
}

type ScalarKey = Exclude<keyof SafetyRecipe, "base_by_highway">;

interface ScalarField {
  key: ScalarKey;
  label: string;
  description: string;
}

interface ThresholdAdjustmentField {
  thresholdKey: ScalarKey;
  adjustmentKey: ScalarKey;
  label: string;
  description: string;
  thresholdSuffix: string;
}

// 基準値ピッカーの段階。staticAttributeLayers.ts: SAFETY_COLORSと単一ソースにし、
// 段階数を増やす場合もそちらへキーを追加するだけで両方に反映される。
const SAFETY_LEVELS = Object.keys(SAFETY_COLORS)
  .map(Number)
  .sort((a, b) => a - b);

// backend/app/domain/safety.py: safety_breakdownの適用順序に合わせてグループ化する。
const CYCLEWAY_FIELDS: ScalarField[] = [
  {
    key: "cycleway_track_adjustment",
    label: "専用レーンの補正",
    description: "cycleway=track（車道と分離された自転車専用レーン）に該当する道路への補正値",
  },
  {
    key: "cycleway_lane_adjustment",
    label: "自転車レーンの補正",
    description: "cycleway=lane（車道内に区画された自転車レーン）に該当する道路への補正値",
  },
  {
    key: "cycleway_shared_adjustment",
    label: "共有レーンの補正",
    description: "cycleway=shared_lane / share_busway（自動車・バスと車線を共有する通行帯）に該当する道路への補正値",
  },
];

const MAXSPEED_PAIRS: ThresholdAdjustmentField[] = [
  {
    thresholdKey: "maxspeed_low_threshold",
    adjustmentKey: "maxspeed_low_adjustment",
    label: "低速道路",
    thresholdSuffix: "km/h以下",
    description: "制限速度がこの値[km/h]以下の道路を「低速道路」とみなし、補正値を安全度へ加える",
  },
  {
    thresholdKey: "maxspeed_high_threshold",
    adjustmentKey: "maxspeed_high_adjustment",
    label: "高速道路",
    thresholdSuffix: "km/h以上",
    description: "制限速度がこの値[km/h]以上の道路を「高速道路」とみなし、補正値を安全度へ加える",
  },
];

// 安全度はlanes_high（多車線＝リスク増）のみ採用する（少車線が安全側かは研究上見解が
// 分かれるため見送り、domain/safety.py: SafetyRecipeのdocstring参照）。
const LANES_PAIRS: ThresholdAdjustmentField[] = [
  {
    thresholdKey: "lanes_high_threshold",
    adjustmentKey: "lanes_high_adjustment",
    label: "多車線道路",
    thresholdSuffix: "車線以上",
    description: "車線数がこの値以上の道路を「多車線道路」とみなし、補正値を安全度へ加える",
  },
];

// 路肩・街灯・トンネル（安全度のみ採用、交通ストレスには無い補正）。
const ROAD_ENVIRONMENT_FIELDS: ScalarField[] = [
  { key: "shoulder_adjustment", label: "路肩ありの補正", description: "shoulder=yes（路肩あり）に該当する道路への補正値" },
  { key: "lit_adjustment", label: "街灯ありの補正", description: "lit=yes（街灯あり）に該当する道路への補正値" },
  { key: "tunnel_adjustment", label: "トンネルの補正", description: "tunnel=yes（トンネル区間）に該当する道路への補正値" },
];

const DESIGNATION_FIELDS: ScalarField[] = [
  {
    key: "designation_adjustment",
    label: "指定路線への補正",
    description: "緊急輸送道路（N10）・重要物流道路（N12）のいずれかに該当する道路に加える補正値",
  },
];

interface HighwayLabel {
  label: string;
  description: string;
}

// TrafficStressRecipePanel.tsx: HIGHWAY_LABELSと同じ対訳表（highwayキー集合は交通ストレスと
// 共有だが、基準値の数値セット自体は別、domain/safety.py: SAFETY_BASE_BY_HIGHWAY参照）。
const HIGHWAY_LABELS: Record<string, HighwayLabel> = {
  cycleway: { label: "自転車専用道", description: "highway=cycleway。自転車のための専用道路" },
  living_street: {
    label: "生活道路(歩車共存)",
    description: "highway=living_street。歩行者優先で自動車もゆっくり走る道路",
  },
  residential: { label: "住宅地の道路", description: "highway=residential。住宅地内の一般道路" },
  unclassified: {
    label: "その他の一般道",
    description: "highway=unclassified。上記のどれにも当てはまらない格付けの低い一般道路",
  },
  track: { label: "農道・林道", description: "highway=track。農地・山林内の道（未舗装が多い）" },
  tertiary: { label: "地区の主要道路", description: "highway=tertiary。市区町村道クラスの主要な道路" },
  tertiary_link: {
    label: "地区の主要道路(連絡路)",
    description: "highway=tertiary_link。上記の合流・分岐路（ランプ）",
  },
  secondary: { label: "都道府県道クラスの道路", description: "highway=secondary。主要地方道クラスの道路" },
  secondary_link: {
    label: "都道府県道クラスの道路(連絡路)",
    description: "highway=secondary_link。上記の合流・分岐路（ランプ）",
  },
  primary: { label: "国道クラスの幹線道路", description: "highway=primary。国道クラスの幹線道路" },
  primary_link: { label: "幹線道路(連絡路)", description: "highway=primary_link。上記の合流・分岐路（ランプ）" },
  trunk: { label: "高規格の幹線道路", description: "highway=trunk。自動車専用道路に準ずる高規格の幹線道路" },
  trunk_link: {
    label: "高規格の幹線道路(連絡路)",
    description: "highway=trunk_link。上記の合流・分岐路（ランプ）",
  },
};

const HIGHWAY_ORDER = Object.keys(DEFAULT_SAFETY_RECIPE.base_by_highway);

// 補正値ステッパーの色（負値=安全側は最も安全な段階の色、正値=危険側は最も危険な段階の色）。
const ADJUSTMENT_NEGATIVE_COLOR = SAFETY_COLORS[SAFETY_LEVELS[0]];
const ADJUSTMENT_POSITIVE_COLOR = SAFETY_COLORS[SAFETY_LEVELS[SAFETY_LEVELS.length - 1]];

function ScalarInput({
  field,
  recipe,
  onChange,
}: {
  field: ScalarField;
  recipe: SafetyRecipe;
  onChange: (recipe: SafetyRecipe) => void;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const value = recipe[field.key];
  return (
    <>
      <div className={styles.field}>
        <FieldLabel label={field.label} open={infoOpen} onToggle={() => setInfoOpen((v) => !v)} />
        <AdjustmentStepper
          label={field.label}
          value={value}
          onChange={(next) => onChange({ ...recipe, [field.key]: next })}
          negativeColor={ADJUSTMENT_NEGATIVE_COLOR}
          positiveColor={ADJUSTMENT_POSITIVE_COLOR}
        />
      </div>
      {infoOpen && <p className={styles.infoTooltip}>{field.description}</p>}
    </>
  );
}

function ThresholdAdjustmentRow({
  field,
  recipe,
  onChange,
}: {
  field: ThresholdAdjustmentField;
  recipe: SafetyRecipe;
  onChange: (recipe: SafetyRecipe) => void;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const thresholdValue = recipe[field.thresholdKey];
  const adjustmentValue = recipe[field.adjustmentKey];
  return (
    <>
      <div className={styles.field}>
        <FieldLabel label={field.label} open={infoOpen} onToggle={() => setInfoOpen((v) => !v)} />
        <span className={styles.pairControls}>
          <AdjustmentStepper
            label={field.label}
            value={adjustmentValue}
            onChange={(next) => onChange({ ...recipe, [field.adjustmentKey]: next })}
            negativeColor={ADJUSTMENT_NEGATIVE_COLOR}
            positiveColor={ADJUSTMENT_POSITIVE_COLOR}
          />
          <span className={styles.thresholdInline}>
            <span className={styles.thresholdCaption}>条件</span>
            <input
              type="number"
              step="1"
              aria-label={`${field.label}の条件`}
              value={thresholdValue}
              onChange={(e) => {
                const next = Number(e.target.value);
                if (Number.isNaN(next)) return;
                onChange({ ...recipe, [field.thresholdKey]: next });
              }}
              className={styles.thresholdInput}
            />
            <span className={styles.thresholdSuffix}>{field.thresholdSuffix}</span>
          </span>
        </span>
      </div>
      {infoOpen && <p className={styles.infoTooltip}>{field.description}</p>}
    </>
  );
}

function HighwayRow({
  highway,
  value,
  onChange,
}: {
  highway: string;
  value: number | undefined;
  onChange: (highway: string, next: number) => void;
}) {
  const [infoOpen, setInfoOpen] = useState(false);
  const highwayLabel = HIGHWAY_LABELS[highway];
  const resolvedValue = value ?? SAFETY_LEVELS[0];
  return (
    <>
      <tr>
        <td className={styles.tableLabel}>
          {highwayLabel ? (
            <FieldLabel
              label={highwayLabel.label}
              open={infoOpen}
              onToggle={() => setInfoOpen((v) => !v)}
              className={styles.tableLabelFieldLabel}
            />
          ) : (
            highway
          )}
        </td>
        <td className={styles.tableValue}>
          <LevelPicker
            levels={SAFETY_LEVELS}
            colors={SAFETY_COLORS}
            value={resolvedValue}
            onChange={(next) => onChange(highway, next)}
            groupLabel={`${highwayLabel?.label ?? highway}の基準値`}
          />
        </td>
      </tr>
      {infoOpen && highwayLabel && (
        <tr>
          <td colSpan={2} className={styles.infoTooltipCell}>
            {highwayLabel.description}
          </td>
        </tr>
      )}
    </>
  );
}

// 研究モードでの安全度レシピ上書きUI（改善計画: 安全度レシピ）。TrafficStressRecipePanel.tsxと
// 同じ構造・同じ独立トグルの理由（上書き中は地図の色分け即座反映、重みは次回生成まで反映
// されないという挙動差があるため）。
export default function SafetyRecipePanel({
  overrideEnabled,
  onOverrideEnabledChange,
  recipe,
  onRecipeChange,
}: SafetyRecipePanelProps) {
  return (
    <div className={styles.panel}>
      <label className={styles.toggleLabel}>
        <input
          type="checkbox"
          checked={overrideEnabled}
          onChange={(e) => onOverrideEnabledChange(e.target.checked)}
        />
        安全度のレシピを上書きする[地図の色分けに即時反映]
      </label>

      {overrideEnabled && (
        <div className={styles.groups}>
          <details className={styles.group}>
            <summary className={styles.groupHeader}>
              <span aria-hidden="true" className={styles.groupChevron} />
              道路種別ごとの基準値[低→高]
            </summary>
            <div className={styles.groupBody}>
              <table className={styles.table}>
                <tbody>
                  {HIGHWAY_ORDER.map((highway) => (
                    <HighwayRow
                      key={highway}
                      highway={highway}
                      value={recipe.base_by_highway[highway]}
                      onChange={(hw, next) =>
                        onRecipeChange({
                          ...recipe,
                          base_by_highway: { ...recipe.base_by_highway, [hw]: next },
                        })
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </details>

          <details className={styles.group}>
            <summary className={styles.groupHeader}>
              <span aria-hidden="true" className={styles.groupChevron} />
              自転車インフラ補正[cycleway]
            </summary>
            <div className={styles.groupBody}>
              {CYCLEWAY_FIELDS.map((field) => (
                <ScalarInput key={field.key} field={field} recipe={recipe} onChange={onRecipeChange} />
              ))}
            </div>
          </details>

          <details className={styles.group}>
            <summary className={styles.groupHeader}>
              <span aria-hidden="true" className={styles.groupChevron} />
              制限速度補正[maxspeed]
            </summary>
            <div className={styles.groupBody}>
              {MAXSPEED_PAIRS.map((field) => (
                <ThresholdAdjustmentRow key={field.thresholdKey} field={field} recipe={recipe} onChange={onRecipeChange} />
              ))}
            </div>
          </details>

          <details className={styles.group}>
            <summary className={styles.groupHeader}>
              <span aria-hidden="true" className={styles.groupChevron} />
              車線数補正[lanes]
            </summary>
            <div className={styles.groupBody}>
              {LANES_PAIRS.map((field) => (
                <ThresholdAdjustmentRow key={field.thresholdKey} field={field} recipe={recipe} onChange={onRecipeChange} />
              ))}
            </div>
          </details>

          <details className={styles.group}>
            <summary className={styles.groupHeader}>
              <span aria-hidden="true" className={styles.groupChevron} />
              路肩・街灯・トンネル補正
            </summary>
            <div className={styles.groupBody}>
              {ROAD_ENVIRONMENT_FIELDS.map((field) => (
                <ScalarInput key={field.key} field={field} recipe={recipe} onChange={onRecipeChange} />
              ))}
            </div>
          </details>

          <details className={styles.group}>
            <summary className={styles.groupHeader}>
              <span aria-hidden="true" className={styles.groupChevron} />
              指定路線補正
            </summary>
            <div className={styles.groupBody}>
              {DESIGNATION_FIELDS.map((field) => (
                <ScalarInput key={field.key} field={field} recipe={recipe} onChange={onRecipeChange} />
              ))}
            </div>
          </details>

          <button
            type="button"
            className={styles.resetButton}
            onClick={() => onRecipeChange(DEFAULT_SAFETY_RECIPE)}
          >
            既定値に戻す
          </button>
        </div>
      )}
    </div>
  );
}
