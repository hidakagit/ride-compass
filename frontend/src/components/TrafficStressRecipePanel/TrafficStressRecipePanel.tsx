"use client";

import { DEFAULT_TRAFFIC_STRESS_RECIPE, type TrafficStressRecipe } from "@/components/Map/trafficStressExpression";
import styles from "./TrafficStressRecipePanel.module.css";

interface TrafficStressRecipePanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  recipe: TrafficStressRecipe;
  onRecipeChange: (recipe: TrafficStressRecipe) => void;
}

type ScalarKey = Exclude<keyof TrafficStressRecipe, "base_by_highway">;

interface ScalarField {
  key: ScalarKey;
  label: string;
}

// WeightPanel.tsxのWeightField/WeightInputと同じ発想の一覧駆動だが、
// TrafficStressRecipeOverrideはevaluationAxes.tsのWeights系ユニオン型に含まれないため
// （軸間の重みではなく軸の中身のレシピのため）、フィールド一覧はこのファイル内に持つ。
// backend/app/domain/traffic.py: traffic_stress_breakdownの適用順序に合わせて4グループに束ねる。
const CYCLEWAY_FIELDS: ScalarField[] = [
  { key: "cycleway_track_adjustment", label: "track[専用レーン]の補正" },
  { key: "cycleway_lane_adjustment", label: "lane[レーン]の補正" },
  { key: "cycleway_shared_adjustment", label: "shared_lane/share_busway[共有]の補正" },
];
const MAXSPEED_FIELDS: ScalarField[] = [
  { key: "maxspeed_low_threshold", label: "低速の閾値[km/h以下]" },
  { key: "maxspeed_low_adjustment", label: "低速の補正" },
  { key: "maxspeed_high_threshold", label: "高速の閾値[km/h以上]" },
  { key: "maxspeed_high_adjustment", label: "高速の補正" },
];
const LANES_FIELDS: ScalarField[] = [
  { key: "lanes_high_threshold", label: "多車線の閾値[車線以上]" },
  { key: "lanes_high_adjustment", label: "多車線の補正" },
  { key: "lanes_low_threshold", label: "少車線の閾値[車線以下]" },
  { key: "lanes_low_adjustment", label: "少車線の補正" },
];
const DESIGNATION_FIELDS: ScalarField[] = [
  { key: "designation_adjustment", label: "指定路線[N10・N12]該当の補正" },
];

// highway別基準値の表示順はDEFAULT_TRAFFIC_STRESS_RECIPE.base_by_highwayの定義順
// （domain/traffic.py: TRAFFIC_STRESS_BASE_BY_HIGHWAYと同じ、単一ソースからの導出）。
// ラベルはOSMのhighway=タグ値をそのまま出す（この項目を編集する時点で利用者は
// OSMタグ語彙を前提にしているため、独自の日本語訳を新設しない）。
const HIGHWAY_ORDER = Object.keys(DEFAULT_TRAFFIC_STRESS_RECIPE.base_by_highway);

function ScalarInput({
  field,
  recipe,
  onChange,
}: {
  field: ScalarField;
  recipe: TrafficStressRecipe;
  onChange: (recipe: TrafficStressRecipe) => void;
}) {
  return (
    <label className={styles.field}>
      {field.label}
      <input
        type="number"
        step="1"
        value={recipe[field.key]}
        onChange={(e) => {
          const next = Number(e.target.value);
          if (Number.isNaN(next)) return;
          onChange({ ...recipe, [field.key]: next });
        }}
        className={styles.input}
      />
    </label>
  );
}

// 研究モードでの交通ストレスレシピ上書きUI（改善計画: 交通ストレスレシピ調整UIパネル、
// T107の次ラウンド）。WeightPanel（評価重みの上書き）とは独立したトグルにしている
// （ユーザー承認済み: レシピは有効化すると地図の色分けへ即座に反映されるが、重みは
// 次回のルート生成まで反映されないという挙動差があるため）。上書き中は地図の色分け・
// 凡例による絞り込み（MapView.tsx）・区間クリックの内訳ポップアップ・次回のルート生成
// （page.tsx経由で/api/routes/generateへ）すべてがこのレシピに従う。
export default function TrafficStressRecipePanel({
  overrideEnabled,
  onOverrideEnabledChange,
  recipe,
  onRecipeChange,
}: TrafficStressRecipePanelProps) {
  return (
    <div className={styles.panel}>
      <label className={styles.toggleLabel}>
        <input
          type="checkbox"
          checked={overrideEnabled}
          onChange={(e) => onOverrideEnabledChange(e.target.checked)}
        />
        交通ストレスのレシピを上書きする[地図の色分けに即時反映]
      </label>

      {overrideEnabled && (
        <div className={styles.groups}>
          <fieldset className={styles.group}>
            <legend>道路種別ごとの基準値[1-4]</legend>
            <table className={styles.table}>
              <tbody>
                {HIGHWAY_ORDER.map((highway) => (
                  <tr key={highway}>
                    <td className={styles.tableLabel}>{highway}</td>
                    <td>
                      <input
                        type="number"
                        min="1"
                        max="4"
                        step="1"
                        value={recipe.base_by_highway[highway] ?? ""}
                        onChange={(e) => {
                          const next = Number(e.target.value);
                          if (Number.isNaN(next)) return;
                          onRecipeChange({
                            ...recipe,
                            base_by_highway: { ...recipe.base_by_highway, [highway]: next },
                          });
                        }}
                        className={styles.input}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </fieldset>

          <fieldset className={styles.group}>
            <legend>自転車インフラ補正[cycleway]</legend>
            {CYCLEWAY_FIELDS.map((field) => (
              <ScalarInput key={field.key} field={field} recipe={recipe} onChange={onRecipeChange} />
            ))}
          </fieldset>

          <fieldset className={styles.group}>
            <legend>制限速度補正[maxspeed]</legend>
            {MAXSPEED_FIELDS.map((field) => (
              <ScalarInput key={field.key} field={field} recipe={recipe} onChange={onRecipeChange} />
            ))}
          </fieldset>

          <fieldset className={styles.group}>
            <legend>車線数補正[lanes]</legend>
            {LANES_FIELDS.map((field) => (
              <ScalarInput key={field.key} field={field} recipe={recipe} onChange={onRecipeChange} />
            ))}
          </fieldset>

          <fieldset className={styles.group}>
            <legend>指定路線補正</legend>
            {DESIGNATION_FIELDS.map((field) => (
              <ScalarInput key={field.key} field={field} recipe={recipe} onChange={onRecipeChange} />
            ))}
          </fieldset>

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
