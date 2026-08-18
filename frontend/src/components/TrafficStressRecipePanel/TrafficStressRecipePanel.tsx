"use client";

import { useState } from "react";
import { AdjustmentStepper, CarClosenessReferenceSection, FieldLabel } from "@/components/Map/recipeControls";
import { TRAFFIC_STRESS_COLORS } from "@/components/Map/staticAttributeLayers";
import {
  DEFAULT_TRAFFIC_STRESS_RECIPE,
  type MotorVehicleDensityRecipe,
  type RoadSuitabilityRecipe,
  type TrafficStressRecipe,
} from "@/components/Map/trafficStressExpression";
import styles from "./TrafficStressRecipePanel.module.css";

// 交通ストレス軸だけが持つ判定レシピ（対面通行の少車線道路への緩和）の研究モード上書きUI
// （改善計画: 交通ストレスレシピ調整UIパネル、T107の次ラウンド。車との近さ材料の
// 共有元化以降はこの軸固有の1グループのみを持つ薄いパネルになった）。highway別基準値・
// cycleway補正・制限速度補正・車線数[多い方]補正・指定路線補正は交通ストレス・安全度が
// 共有する「車との近さ」(N2)の材料としてRoadSuitabilityRecipePanel/
// MotorVehicleDensityRecipePanelへ切り出し済み。このパネルの先頭には、その2つの現在値を
// 読み取り専用で確認できる参照セクション（CarClosenessReferenceSection）を表示する。

interface TrafficStressRecipePanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  recipe: TrafficStressRecipe;
  onRecipeChange: (recipe: TrafficStressRecipe) => void;
  /** 参照表示用（読み取り専用）。研究モードでroad_suitability/motor_vehicle_densityの
   * 上書きが無効なら既定レシピが渡る。CarClosenessReferenceSection参照。 */
  roadSuitabilityRecipe: RoadSuitabilityRecipe;
  motorVehicleDensityRecipe: MotorVehicleDensityRecipe;
}

type ScalarKey = keyof TrafficStressRecipe;

interface ThresholdAdjustmentField {
  thresholdKey: ScalarKey;
  adjustmentKey: ScalarKey;
  label: string;
  description: string;
  thresholdSuffix: string;
}

// WeightPanel.tsxのWeightField/WeightInputと同じ発想の一覧駆動だが、
// TrafficStressRecipeOverrideはevaluationAxes.tsのWeights系ユニオン型に含まれないため
// （軸間の重みではなく軸の中身のレシピのため）、フィールド一覧はこのファイル内に持つ。
const LANES_PAIRS: ThresholdAdjustmentField[] = [
  {
    thresholdKey: "lanes_low_threshold",
    adjustmentKey: "lanes_low_adjustment",
    label: "少車線道路",
    thresholdSuffix: "車線以下",
    description: "車線数がこの値以下の道路を「少車線道路」とみなし、補正値を車の圧迫感へ加える(分離自転車道がある区間は対象外)",
  },
];

// 補正値ステッパーの色（負値=ストレス軽減は最も低い段階の色、正値=ストレス増加は最も高い
// 段階の色）。TRAFFIC_STRESS_COLORSと連動させることで「0中心に変動する」という感覚を
// 色だけで確実に伝える（recipeControls.tsx: AdjustmentStepperへ渡す）。
const ADJUSTMENT_NEGATIVE_COLOR = TRAFFIC_STRESS_COLORS[1];
const ADJUSTMENT_POSITIVE_COLOR = TRAFFIC_STRESS_COLORS[5];

// 閾値+補正値の対フィールド（少車線道路）。補正値のステッパーと変動条件（閾値）を
// 同じ行に横並びで置く。
function ThresholdAdjustmentRow({
  field,
  recipe,
  onChange,
}: {
  field: ThresholdAdjustmentField;
  recipe: TrafficStressRecipe;
  onChange: (recipe: TrafficStressRecipe) => void;
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

// 研究モードでの交通ストレスレシピ上書きUI（改善計画: 交通ストレスレシピ調整UIパネル、
// T107の次ラウンド。入力欄の見た目は改善計画: レシピ入力フォームの改善で刷新）。
// WeightPanel（評価重みの上書き）とは独立したトグルにしている（ユーザー承認済み: レシピは
// 有効化すると地図の色分けへ即座に反映されるが、重みは次回のルート生成まで反映されない
// という挙動差があるため）。上書き中は地図の色分け・凡例による絞り込み（MapView.tsx）・
// 区間クリックの内訳ポップアップ・次回のルート生成（page.tsx経由で/api/routes/generateへ）
// すべてがこのレシピに従う。
export default function TrafficStressRecipePanel({
  overrideEnabled,
  onOverrideEnabledChange,
  recipe,
  onRecipeChange,
  roadSuitabilityRecipe,
  motorVehicleDensityRecipe,
}: TrafficStressRecipePanelProps) {
  return (
    <div className={styles.panel}>
      <label className={styles.toggleLabel}>
        <input
          type="checkbox"
          checked={overrideEnabled}
          onChange={(e) => onOverrideEnabledChange(e.target.checked)}
        />
        車の圧迫感のレシピを上書きする[地図の色分けに即時反映]
      </label>

      {overrideEnabled && (
        <div className={styles.groups}>
          <CarClosenessReferenceSection
            roadSuitabilityRecipe={roadSuitabilityRecipe}
            motorVehicleDensityRecipe={motorVehicleDensityRecipe}
          />

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

          <button
            type="button"
            className={styles.resetButton}
            onClick={() => onRecipeChange(DEFAULT_TRAFFIC_STRESS_RECIPE)}
          >
            既定値に戻す
          </button>
        </div>
      )}
    </div>
  );
}
