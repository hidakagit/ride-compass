"use client";

import { useState } from "react";
import { AdjustmentStepper, FieldLabel } from "@/components/Map/recipeControls";
import { TRAFFIC_STRESS_COLORS } from "@/components/Map/staticAttributeLayers";
import {
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  type MotorVehicleDensityRecipe,
} from "@/components/Map/trafficStressExpression";
import styles from "./MotorVehicleDensityRecipePanel.module.css";

// 「自動車密度」（制限速度・車線数[多い方]・指定路線該当）の研究モード上書きUI（改善計画:
// 車との近さ材料の共有元化）。TrafficStressRecipePanel.tsxから該当フィールドを移設した
// 独立パネル。RoadSuitabilityRecipePanel.tsxと合わせて「車との近さ」(N2)を構成する、
// 交通ストレス・安全度が共有するもう1つの材料。このパネル自体は独自の地図レイヤーを
// 持たないため、配色はTRAFFIC_STRESS_COLORSを流用する（RoadSuitabilityRecipePanel.tsxと
// 同じ理由）。

interface MotorVehicleDensityRecipePanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  recipe: MotorVehicleDensityRecipe;
  onRecipeChange: (recipe: MotorVehicleDensityRecipe) => void;
}

type ScalarKey = keyof MotorVehicleDensityRecipe;

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

const ADJUSTMENT_NEGATIVE_COLOR = TRAFFIC_STRESS_COLORS[1];
const ADJUSTMENT_POSITIVE_COLOR = TRAFFIC_STRESS_COLORS[5];

const MAXSPEED_PAIRS: ThresholdAdjustmentField[] = [
  {
    thresholdKey: "maxspeed_low_threshold",
    adjustmentKey: "maxspeed_low_adjustment",
    label: "低速道路",
    thresholdSuffix: "km/h以下",
    description: "制限速度がこの値[km/h]以下の道路を「低速道路」とみなし、補正値を車との近さへ加える",
  },
  {
    thresholdKey: "maxspeed_high_threshold",
    adjustmentKey: "maxspeed_high_adjustment",
    label: "高速道路",
    thresholdSuffix: "km/h以上",
    description: "制限速度がこの値[km/h]以上の道路を「高速道路」とみなし、補正値を車との近さへ加える",
  },
];

const LANES_PAIRS: ThresholdAdjustmentField[] = [
  {
    thresholdKey: "lanes_high_threshold",
    adjustmentKey: "lanes_high_adjustment",
    label: "多車線道路",
    thresholdSuffix: "車線以上",
    description: "車線数がこの値以上の道路を「多車線道路」とみなし、補正値を車との近さへ加える",
  },
];

const DESIGNATION_FIELDS: ScalarField[] = [
  {
    key: "designation_adjustment",
    label: "指定路線への補正",
    description: "緊急輸送道路（N10）・重要物流道路（N12）のいずれかに該当する道路に加える補正値",
  },
];

function ScalarInput({
  field,
  recipe,
  onChange,
}: {
  field: ScalarField;
  recipe: MotorVehicleDensityRecipe;
  onChange: (recipe: MotorVehicleDensityRecipe) => void;
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
  recipe: MotorVehicleDensityRecipe;
  onChange: (recipe: MotorVehicleDensityRecipe) => void;
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

export default function MotorVehicleDensityRecipePanel({
  overrideEnabled,
  onOverrideEnabledChange,
  recipe,
  onRecipeChange,
}: MotorVehicleDensityRecipePanelProps) {
  return (
    <div className={styles.panel}>
      <label className={styles.toggleLabel}>
        <input
          type="checkbox"
          checked={overrideEnabled}
          onChange={(e) => onOverrideEnabledChange(e.target.checked)}
        />
        自動車密度のレシピを上書きする[地図の色分けに即時反映]
      </label>

      {overrideEnabled && (
        <div className={styles.groups}>
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
            onClick={() => onRecipeChange(DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE)}
          >
            既定値に戻す
          </button>
        </div>
      )}
    </div>
  );
}
