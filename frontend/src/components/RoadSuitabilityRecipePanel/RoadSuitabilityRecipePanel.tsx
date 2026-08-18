"use client";

import { useState } from "react";
import {
  ScalarInput,
  FieldLabel,
  LevelPicker,
  RecipePanelSection,
  adjustmentEndpointColors,
  withAutoEnable,
  type ScalarFieldDescriptor,
} from "@/components/Map/recipeControls";
import { TRAFFIC_STRESS_COLORS } from "@/components/Map/staticAttributeLayers";
import { DEFAULT_ROAD_SUITABILITY_RECIPE, type RoadSuitabilityRecipe } from "@/components/Map/trafficStressExpression";
import styles from "./RoadSuitabilityRecipePanel.module.css";

// 「道路適正」（highway別基準値＋cycleway補正）の研究モード上書きUI（改善計画: 車との近さ
// 材料の共有元化）。TrafficStressRecipePanel.tsxから該当2セクション（道路種別ごとの基準値・
// 自転車インフラ補正）をそのまま移設した独立パネル。交通ストレス・安全度の両方が
// domain/recipe.py: car_closeness()経由でこのレシピを参照するため、ここを上書きすると
// 両軸の地図色・区間クリックの内訳ポップアップ・次回のルート生成すべてへ同時に反映される
// （軸ごとに別の値へ上書きする自由度は無い、意図した設計）。

interface RoadSuitabilityRecipePanelProps {
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  recipe: RoadSuitabilityRecipe;
  onRecipeChange: (recipe: RoadSuitabilityRecipe) => void;
}

type ScalarKey = Exclude<keyof RoadSuitabilityRecipe, "base_by_highway">;

// このパネルは独自の地図レイヤーを持たないため（道路適正は交通ストレス・安全度の材料に
// とどまる）、配色はTRAFFIC_STRESS_COLORSを流用する（TrafficStressRecipePanel.tsxと
// 同じ配色にすることで「元は交通ストレスパネルの一部だった」という連続性も保つ）。
// ROAD_SUITABILITY_BASE_BY_HIGHWAYの値域は1〜4のため、5段階目は使わない。
const ROAD_SUITABILITY_LEVELS = [1, 2, 3, 4];

const CYCLEWAY_FIELDS: ScalarFieldDescriptor<RoadSuitabilityRecipe, ScalarKey>[] = [
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

interface HighwayLabel {
  label: string;
  description: string;
}

// TrafficStressRecipePanel.tsx（改名前）: HIGHWAY_LABELSと同じ対訳表。道路適正は交通ストレス・
// 安全度が共有する唯一の出どころのため、この対訳表もここ1箇所へ集約する
// （改善計画: 車との近さ材料の共有元化。以前は交通ストレス・安全度パネルの双方に
// 同じ対訳表が重複していた）。
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

const HIGHWAY_ORDER = Object.keys(DEFAULT_ROAD_SUITABILITY_RECIPE.base_by_highway);

const { negativeColor: ADJUSTMENT_NEGATIVE_COLOR, positiveColor: ADJUSTMENT_POSITIVE_COLOR } = adjustmentEndpointColors(
  TRAFFIC_STRESS_COLORS,
  ROAD_SUITABILITY_LEVELS[0],
  ROAD_SUITABILITY_LEVELS[ROAD_SUITABILITY_LEVELS.length - 1],
);

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
  const resolvedValue = value ?? ROAD_SUITABILITY_LEVELS[0];
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
            levels={ROAD_SUITABILITY_LEVELS}
            colors={TRAFFIC_STRESS_COLORS}
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

export default function RoadSuitabilityRecipePanel({
  overrideEnabled,
  onOverrideEnabledChange,
  recipe,
  onRecipeChange,
}: RoadSuitabilityRecipePanelProps) {
  const handleRecipeChange = withAutoEnable(overrideEnabled, onOverrideEnabledChange, onRecipeChange);

  return (
    <RecipePanelSection
      title="道路適正[地図の色分けに即時反映]"
      overrideAriaLabel="道路適正のレシピを上書き"
      overrideEnabled={overrideEnabled}
      onOverrideEnabledChange={onOverrideEnabledChange}
    >
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
                      handleRecipeChange({
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
          onClick={() => onRecipeChange(DEFAULT_ROAD_SUITABILITY_RECIPE)}
        >
          既定値に戻す
        </button>
      </div>
    </RecipePanelSection>
  );
}
