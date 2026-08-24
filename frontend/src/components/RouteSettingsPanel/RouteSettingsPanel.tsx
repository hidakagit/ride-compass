"use client";

import { useState } from "react";
import LayerChip from "@/components/Map/LayerChip";
import { FieldLabel, withAutoEnable } from "@/components/Map/recipeControls";
import { AXIS_CATEGORIES, PREFERENCE_AXES, axisCategory } from "@/lib/evaluationAxes";
import type { HardFilterOverride, RoutePreferenceWeights } from "@/types/route";
import axisCatalog from "@/types/generated/axis-catalog.json";
import styles from "./RouteSettingsPanel.module.css";

// 一般ユーザー向けルート設定画面（改善計画T267、目論見書4章「①一般ユーザ向け
// ルーティング設定」）。研究モード（WeightPanel）とは別の導線で、常に表示される
// メインの操作面に置く。0次(除外)→軸選択+重み(観測/推定/動的別)→重み配分の可視化→
// プリセット、という並びは提示済みのモックアップをそのまま実装したもの。

// backend/app/domain/evaluation.py: DEFAULT_HARD_FILTERSと同じ3種（改善計画T266）。
const HARD_FILTER_CHIPS: { key: string; label: string }[] = [
  { key: "no_bicycle", label: "自転車通行禁止" },
  { key: "motorway", label: "高速道路" },
  { key: "trunk", label: "幹線道路(trunk)" },
];

export const DEFAULT_HARD_FILTERS: HardFilterOverride = { no_bicycle: true, motorway: true, trunk: true };

// backend/app/domain/axis_definitions.py: AXIS_DEFINITIONSのdefault_weight（axis-catalog.json
// 経由、WeightPanel.tsx: DEFAULT_ROUTE_PREFERENCEと同じ単一ソース）。
export const DEFAULT_ROUTE_PREFERENCE: RoutePreferenceWeights = axisCatalog.preference_defaults;

interface Preset {
  label: string;
  weights: RoutePreferenceWeights;
}

// 重みは叩き台（目論見書8章「要判断事項」、実走検証を経て確定する）。
const PRESETS: readonly Preset[] = [
  { label: "バランス", weights: DEFAULT_ROUTE_PREFERENCE },
  {
    label: "自転車専用道を優先",
    weights: {
      gradient: 0.1, surface_q: 0.12, stop_density: 0.22, night: 0.0,
      car_stress: 0.45, accident: 0.08, wind: 0.03,
    },
  },
  {
    label: "最短時間重視",
    weights: {
      gradient: 0.05, surface_q: 0.05, stop_density: 0.05, night: 0.0,
      car_stress: 0.05, accident: 0.0, wind: 0.1,
    },
  },
  {
    label: "安全重視",
    weights: {
      gradient: 0.05, surface_q: 0.05, stop_density: 0.2, night: 0.1,
      car_stress: 0.3, accident: 0.3, wind: 0.0,
    },
  },
];

function totalWeight(weights: RoutePreferenceWeights): number {
  return Object.values(weights).reduce((sum, w) => sum + (w > 0 ? w : 0), 0);
}

interface RouteSettingsPanelProps {
  hardFilters: HardFilterOverride;
  onHardFiltersChange: (next: HardFilterOverride) => void;
  routePreference: RoutePreferenceWeights;
  onRoutePreferenceChange: (next: RoutePreferenceWeights) => void;
  /** route_preference上書き（研究モードのWeightPanelと共有する同じ状態、page.tsx参照）の
   * 有効フラグ。既定値のまま操作しなければ無効のままでよく（DEFAULT_ROUTE_PREFERENCE＝
   * backend YAML既定値のため挙動は変わらない）、値を変えると自動でONになる
   * （withAutoEnable、WeightPanel.tsxと同じパターン）。一般ユーザーはこのフラグの存在自体を
   * 意識しない（トグルUIをこのパネルには出さない）。 */
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
}

export default function RouteSettingsPanel({
  hardFilters,
  onHardFiltersChange,
  routePreference,
  onRoutePreferenceChange,
  overrideEnabled,
  onOverrideEnabledChange,
}: RouteSettingsPanelProps) {
  const handlePreferenceChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRoutePreferenceChange);

  // チェックを外した軸の重みを覚えておき、再度チェックしたときに元へ戻す
  // （routePreference自体は常に0を含む「実際に送る値」のため、ここでしか保持できない）。
  const [lastWeights, setLastWeights] = useState<Record<string, number>>(() => ({
    ...DEFAULT_ROUTE_PREFERENCE,
  }));

  function handleToggle(axisId: string, checked: boolean) {
    const restored = checked ? lastWeights[axisId] || DEFAULT_ROUTE_PREFERENCE[axisId] || 0.1 : 0;
    handlePreferenceChange({ ...routePreference, [axisId]: restored });
  }

  function handleWeightChange(axisId: string, value: number) {
    setLastWeights((prev) => ({ ...prev, [axisId]: value }));
    handlePreferenceChange({ ...routePreference, [axisId]: value });
  }

  function applyPreset(preset: Preset) {
    setLastWeights((prev) => {
      const next = { ...prev };
      for (const [axisId, weight] of Object.entries(preset.weights)) {
        if (weight > 0) next[axisId] = weight;
      }
      return next;
    });
    handlePreferenceChange(preset.weights);
  }

  const total = totalWeight(routePreference);

  return (
    <div className={styles.panel}>
      <div className={styles.presets}>
        {PRESETS.map((preset) => (
          <button
            key={preset.label}
            type="button"
            className={styles.presetButton}
            onClick={() => applyPreset(preset)}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className={styles.hardFilters}>
        <p className={styles.sectionLabel}>除外する道路</p>
        <div className={styles.chipRow}>
          {HARD_FILTER_CHIPS.map(({ key, label }) => (
            <LayerChip
              key={key}
              label={label}
              on={hardFilters[key] ?? true}
              ariaLabel={`${label}を除外`}
              onClick={() => onHardFiltersChange({ ...hardFilters, [key]: !(hardFilters[key] ?? true) })}
            />
          ))}
        </div>
      </div>

      <div className={styles.stackBarWrap}>
        <p className={styles.sectionLabel}>重み配分</p>
        <div className={styles.stackBar}>
          {PREFERENCE_AXES.map(({ axisId, label }) => {
            const weight = routePreference[axisId] ?? 0;
            if (weight <= 0 || total <= 0) return null;
            const pct = (weight / total) * 100;
            return (
              <div
                key={axisId}
                className={styles.stackSegment}
                data-axis={axisId}
                style={{ width: `${pct}%` }}
                title={`${label} ${Math.round(pct)}%`}
              />
            );
          })}
        </div>
      </div>

      {AXIS_CATEGORIES.map((category) => {
        const axesInCategory = PREFERENCE_AXES.filter((axis) => axisCategory(axis.axisId) === category);
        return (
          <div key={category} className={styles.group}>
            <p className={styles.groupHeader}>{category}</p>
            {axesInCategory.map((axis) => {
              const weight = routePreference[axis.axisId] ?? 0;
              const checked = weight > 0;
              return (
                <div key={axis.axisId} className={styles.row}>
                  {/* FieldLabelは説明ポップオーバーのボタンを内包するため、<label>で
                      checkboxと一緒に包まない（ネイティブlabelのクリック委譲でinfoボタン
                      押下時にもcheckboxがトグルされてしまう、WeightPanel.tsxのWeightInputと
                      同じ理由で兄弟要素として配置しaria-labelで関連付ける）。 */}
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => handleToggle(axis.axisId, e.target.checked)}
                    aria-label={axis.label}
                    className={styles.checkbox}
                  />
                  <span className={styles.rowLabel}>
                    <FieldLabel label={axis.label} description={axis.description} />
                  </span>
                  <input
                    type="range"
                    min="0"
                    max="0.6"
                    step="0.01"
                    value={weight}
                    disabled={!checked}
                    aria-label={`${axis.label}の重み`}
                    onChange={(e) => handleWeightChange(axis.axisId, Number(e.target.value))}
                    className={styles.slider}
                  />
                  <span className={styles.weightValue}>{weight.toFixed(2)}</span>
                </div>
              );
            })}
          </div>
        );
      })}

      <button
        type="button"
        className={styles.resetButton}
        onClick={() => {
          setLastWeights({ ...DEFAULT_ROUTE_PREFERENCE });
          handlePreferenceChange(DEFAULT_ROUTE_PREFERENCE);
          onHardFiltersChange(DEFAULT_HARD_FILTERS);
        }}
      >
        既定値に戻す
      </button>
    </div>
  );
}
