"use client";

import {
  CarClosenessReferenceSection,
  RecipePanelSection,
  ScalarInput,
  adjustmentEndpointColors,
  withAutoEnable,
  type ScalarFieldDescriptor,
} from "@/components/Map/recipeControls";
import { TRAFFIC_STRESS_COLORS } from "@/components/Map/staticAttributeLayers";
import {
  type MotorVehicleDensityRecipe,
  type RoadSuitabilityRecipe,
} from "@/components/Map/trafficStressExpression";
import { DEFAULT_SAFETY_RECIPE, type SafetyRecipe } from "@/components/Map/safetyExpression";
import styles from "./SafetyRecipePanel.module.css";

// 安全度軸だけが持つ判定レシピ（街灯・トンネル補正）の研究モード上書きUI（改善計画:
// 安全度レシピ。車との近さ材料の共有元化以降はこの軸固有の1グループのみを持つ薄い
// パネルになった）。highway別基準値・cycleway補正・制限速度補正・車線数[多い方]補正・
// 指定路線補正は交通ストレスと共有する「車との近さ」(N2)の材料として
// RoadSuitabilityRecipePanel/MotorVehicleDensityRecipePanelへ切り出し済み。このパネルの
// 先頭には、その2つの現在値を読み取り専用で確認できる参照セクション
// （CarClosenessReferenceSection、TrafficStressRecipePanel.tsxと共有）を表示する。

interface SafetyRecipePanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  recipe: SafetyRecipe;
  onRecipeChange: (recipe: SafetyRecipe) => void;
  /** 参照表示用（読み取り専用）。TrafficStressRecipePanelと同じ扱い。 */
  roadSuitabilityRecipe: RoadSuitabilityRecipe;
  motorVehicleDensityRecipe: MotorVehicleDensityRecipe;
}

type ScalarKey = keyof SafetyRecipe;

// 街灯・トンネル（安全度のみ採用、交通ストレスには無い補正）。
const ROAD_ENVIRONMENT_FIELDS: ScalarFieldDescriptor<SafetyRecipe, ScalarKey>[] = [
  { key: "lit_adjustment", label: "街灯ありの補正", description: "lit=yes（街灯あり）に該当する道路への補正値" },
  { key: "tunnel_adjustment", label: "トンネルの補正", description: "tunnel=yes（トンネル区間）に該当する道路への補正値" },
];

// 補正値ステッパーの色。このパネル自体は独自の地図レイヤーを持たないため
// （街灯・トンネル補正だけでは段階を持たない）、TRAFFIC_STRESS_COLORSを流用する
// （RoadSuitabilityRecipePanel.tsxと同じ理由）。
const { negativeColor: ADJUSTMENT_NEGATIVE_COLOR, positiveColor: ADJUSTMENT_POSITIVE_COLOR } = adjustmentEndpointColors(
  TRAFFIC_STRESS_COLORS,
  1,
  5,
);

// 研究モードでの安全度レシピ上書きUI（改善計画: 安全度レシピ）。TrafficStressRecipePanel.tsxと
// 同じ構造・同じ独立トグルの理由（上書き中は地図の色分け即座反映、重みは次回生成まで反映
// されないという挙動差があるため）。
export default function SafetyRecipePanel({
  overrideEnabled,
  onOverrideEnabledChange,
  recipe,
  onRecipeChange,
  roadSuitabilityRecipe,
  motorVehicleDensityRecipe,
}: SafetyRecipePanelProps) {
  const handleRecipeChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRecipeChange);

  return (
    <RecipePanelSection
      title="安全度[地図の色分けに即時反映]"
      overrideAriaLabel="安全度のレシピを上書き"
      overrideEnabled={overrideEnabled}
      onOverrideEnabledChange={onOverrideEnabledChange}
    >
      <div className={styles.groups}>
        <CarClosenessReferenceSection
          roadSuitabilityRecipe={roadSuitabilityRecipe}
          motorVehicleDensityRecipe={motorVehicleDensityRecipe}
        />

        <details className={styles.group}>
          <summary className={styles.groupHeader}>
            <span aria-hidden="true" className={styles.groupChevron} />
            街灯・トンネル補正
          </summary>
          <div className={styles.groupBody}>
            {ROAD_ENVIRONMENT_FIELDS.map((field) => (
              <ScalarInput
                key={field.key}
                field={field}
                recipe={recipe}
                onChange={handleRecipeChange}
                negativeColor={ADJUSTMENT_NEGATIVE_COLOR}
                positiveColor={ADJUSTMENT_POSITIVE_COLOR}
              />
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
    </RecipePanelSection>
  );
}
