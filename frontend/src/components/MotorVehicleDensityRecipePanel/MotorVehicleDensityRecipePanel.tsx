"use client";

import {
  ScalarInput,
  ThresholdAdjustmentRow,
  RecipePanelSection,
  adjustmentEndpointColors,
  withAutoEnable,
  type ScalarFieldDescriptor,
  type ThresholdAdjustmentFieldDescriptor,
} from "@/components/Map/recipeControls";
import { CAR_STRESS_COLORS } from "@/components/Map/staticAttributeLayers";
import {
  DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
  type MotorVehicleDensityRecipe,
} from "@/components/Map/carStressExpression";
import Disclosure from "@/components/Disclosure/Disclosure";
import styles from "./MotorVehicleDensityRecipePanel.module.css";

// 「自動車密度」（制限速度・車線数[多い方]・指定路線該当）の研究モード上書きUI（改善計画:
// 車との近さ材料の共有元化）。CarStressRecipePanel.tsxから該当フィールドを移設した
// 独立パネル。RoadSuitabilityRecipePanel.tsxと合わせて「車との近さ」(N2)を構成する、
// 車ストレス・安全度が共有するもう1つの材料。このパネル自体は独自の地図レイヤーを
// 持たないため、配色はCAR_STRESS_COLORSを流用する（RoadSuitabilityRecipePanel.tsxと
// 同じ理由）。

interface MotorVehicleDensityRecipePanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  recipe: MotorVehicleDensityRecipe;
  onRecipeChange: (recipe: MotorVehicleDensityRecipe) => void;
}

type ScalarKey = keyof MotorVehicleDensityRecipe;

const { negativeColor: ADJUSTMENT_NEGATIVE_COLOR, positiveColor: ADJUSTMENT_POSITIVE_COLOR } = adjustmentEndpointColors(
  CAR_STRESS_COLORS,
  1,
  5,
);

const MAXSPEED_PAIRS: ThresholdAdjustmentFieldDescriptor<MotorVehicleDensityRecipe, ScalarKey, ScalarKey>[] = [
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

const LANES_PAIRS: ThresholdAdjustmentFieldDescriptor<MotorVehicleDensityRecipe, ScalarKey, ScalarKey>[] = [
  {
    thresholdKey: "lanes_high_threshold",
    adjustmentKey: "lanes_high_adjustment",
    label: "多車線道路",
    thresholdSuffix: "車線以上",
    description: "車線数がこの値以上の道路を「多車線道路」とみなし、補正値を車との近さへ加える",
  },
];

const DESIGNATION_FIELDS: ScalarFieldDescriptor<MotorVehicleDensityRecipe, ScalarKey>[] = [
  {
    key: "designation_adjustment",
    label: "指定路線への補正",
    description: "緊急輸送道路（N10）・重要物流道路（N12）のいずれかに該当する道路に加える補正値",
  },
];

export default function MotorVehicleDensityRecipePanel({
  overrideEnabled,
  onOverrideEnabledChange,
  recipe,
  onRecipeChange,
}: MotorVehicleDensityRecipePanelProps) {
  const handleRecipeChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRecipeChange);

  return (
    <RecipePanelSection
      title="自動車密度[地図の色分けに即時反映]"
      overrideAriaLabel="自動車密度のレシピを上書き"
      overrideEnabled={overrideEnabled}
      onOverrideEnabledChange={onOverrideEnabledChange}
    >
      <div className={styles.groups}>
        <Disclosure
          className={styles.group}
          triggerClassName={styles.groupHeader}
          bodyClassName={styles.groupBody}
          summary={
            <>
              <span aria-hidden="true" className={styles.groupChevron} />
              制限速度補正[maxspeed]
            </>
          }
        >
          {MAXSPEED_PAIRS.map((field) => (
            <ThresholdAdjustmentRow
              key={field.thresholdKey}
              field={field}
              recipe={recipe}
              onChange={handleRecipeChange}
              negativeColor={ADJUSTMENT_NEGATIVE_COLOR}
              positiveColor={ADJUSTMENT_POSITIVE_COLOR}
            />
          ))}
        </Disclosure>

        <Disclosure
          className={styles.group}
          triggerClassName={styles.groupHeader}
          bodyClassName={styles.groupBody}
          summary={
            <>
              <span aria-hidden="true" className={styles.groupChevron} />
              車線数補正[lanes]
            </>
          }
        >
          {LANES_PAIRS.map((field) => (
            <ThresholdAdjustmentRow
              key={field.thresholdKey}
              field={field}
              recipe={recipe}
              onChange={handleRecipeChange}
              negativeColor={ADJUSTMENT_NEGATIVE_COLOR}
              positiveColor={ADJUSTMENT_POSITIVE_COLOR}
            />
          ))}
        </Disclosure>

        <Disclosure
          className={styles.group}
          triggerClassName={styles.groupHeader}
          bodyClassName={styles.groupBody}
          summary={
            <>
              <span aria-hidden="true" className={styles.groupChevron} />
              指定路線補正
            </>
          }
        >
          {DESIGNATION_FIELDS.map((field) => (
            <ScalarInput
              key={field.key}
              field={field}
              recipe={recipe}
              onChange={handleRecipeChange}
              negativeColor={ADJUSTMENT_NEGATIVE_COLOR}
              positiveColor={ADJUSTMENT_POSITIVE_COLOR}
            />
          ))}
        </Disclosure>

        <button
          type="button"
          className={styles.resetButton}
          onClick={() => onRecipeChange(DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE)}
        >
          既定値に戻す
        </button>
      </div>
    </RecipePanelSection>
  );
}
