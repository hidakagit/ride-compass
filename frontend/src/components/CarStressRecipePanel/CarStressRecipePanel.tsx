"use client";

import {
  CarClosenessReferenceSection,
  RecipePanelSection,
  ThresholdAdjustmentRow,
  adjustmentEndpointColors,
  withAutoEnable,
  type ThresholdAdjustmentFieldDescriptor,
} from "@/components/Map/recipeControls";
import { CAR_STRESS_COLORS } from "@/components/Map/staticAttributeLayers";
import {
  DEFAULT_CAR_STRESS_RECIPE,
  type MotorVehicleDensityRecipe,
  type RoadSuitabilityRecipe,
  type CarStressRecipe,
} from "@/components/Map/carStressExpression";
import Disclosure from "@/components/Disclosure/Disclosure";
import styles from "./CarStressRecipePanel.module.css";

// 車ストレス軸だけが持つ判定レシピ（対面通行の少車線道路への緩和）の研究モード上書きUI
// （改善計画: 車ストレスレシピ調整UIパネル、T107の次ラウンド。車との近さ材料の
// 共有元化以降はこの軸固有の1グループのみを持つ薄いパネルになった）。highway別基準値・
// cycleway補正・制限速度補正・車線数[多い方]補正・指定路線補正は車ストレス・安全度が
// 共有する「車との近さ」(N2)の材料としてRoadSuitabilityRecipePanel/
// MotorVehicleDensityRecipePanelへ切り出し済み。このパネルの先頭には、その2つの現在値を
// 読み取り専用で確認できる参照セクション（CarClosenessReferenceSection）を表示する。

interface CarStressRecipePanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  recipe: CarStressRecipe;
  onRecipeChange: (recipe: CarStressRecipe) => void;
  /** 参照表示用（読み取り専用）。研究モードでroad_suitability/motor_vehicle_densityの
   * 上書きが無効なら既定レシピが渡る。CarClosenessReferenceSection参照。 */
  roadSuitabilityRecipe: RoadSuitabilityRecipe;
  motorVehicleDensityRecipe: MotorVehicleDensityRecipe;
}

type ScalarKey = keyof CarStressRecipe;

// WeightPanel.tsxのWeightField/WeightInputと同じ発想の一覧駆動だが、
// CarStressRecipeOverrideはevaluationAxes.tsのWeights系ユニオン型に含まれないため
// （軸間の重みではなく軸の中身のレシピのため）、フィールド一覧はこのファイル内に持つ。
const LANES_PAIRS: ThresholdAdjustmentFieldDescriptor<CarStressRecipe, ScalarKey, ScalarKey>[] = [
  {
    thresholdKey: "lanes_low_threshold",
    adjustmentKey: "lanes_low_adjustment",
    label: "少車線道路",
    thresholdSuffix: "車線以下",
    description: "車線数がこの値以下の道路を「少車線道路」とみなし、補正値を車の圧迫感へ加える(分離自転車道がある区間は対象外)",
  },
];

// 補正値ステッパーの色（負値=ストレス軽減は最も低い段階の色、正値=ストレス増加は最も高い
// 段階の色）。CAR_STRESS_COLORSと連動させることで「0中心に変動する」という感覚を
// 色だけで確実に伝える（recipeControls.tsx: AdjustmentStepperへ渡す）。
const { negativeColor: ADJUSTMENT_NEGATIVE_COLOR, positiveColor: ADJUSTMENT_POSITIVE_COLOR } = adjustmentEndpointColors(
  CAR_STRESS_COLORS,
  1,
  5,
);

// 研究モードでの車ストレスレシピ上書きUI（改善計画: 車ストレスレシピ調整UIパネル、
// T107の次ラウンド。入力欄の見た目は改善計画: レシピ入力フォームの改善で刷新）。
// WeightPanel（評価重みの上書き）とは独立したトグルにしている（ユーザー承認済み: レシピは
// 有効化すると地図の色分けへ即座に反映されるが、重みは次回のルート生成まで反映されない
// という挙動差があるため）。上書き中は地図の色分け・凡例による絞り込み（MapView.tsx）・
// 区間クリックの内訳ポップアップ・次回のルート生成（page.tsx経由で/api/routes/generateへ）
// すべてがこのレシピに従う。
export default function CarStressRecipePanel({
  overrideEnabled,
  onOverrideEnabledChange,
  recipe,
  onRecipeChange,
  roadSuitabilityRecipe,
  motorVehicleDensityRecipe,
}: CarStressRecipePanelProps) {
  const handleRecipeChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRecipeChange);

  return (
    <RecipePanelSection
      title="車の圧迫感[地図の色分けに即時反映]"
      overrideAriaLabel="車の圧迫感のレシピを上書き"
      overrideEnabled={overrideEnabled}
      onOverrideEnabledChange={onOverrideEnabledChange}
    >
      <div className={styles.groups}>
        <CarClosenessReferenceSection
          roadSuitabilityRecipe={roadSuitabilityRecipe}
          motorVehicleDensityRecipe={motorVehicleDensityRecipe}
        />

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

        <button
          type="button"
          className={styles.resetButton}
          onClick={() => onRecipeChange(DEFAULT_CAR_STRESS_RECIPE)}
        >
          既定値に戻す
        </button>
      </div>
    </RecipePanelSection>
  );
}
