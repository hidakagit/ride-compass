"use client";

import InfoPopover from "@/components/Map/InfoPopover";
import LayerChip from "@/components/Map/LayerChip";
import type { HardFilterOverride } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import styles from "./RouteSettingsPanel.module.css";

// 「ルート設定」区分の「除外」タブ。ここでONにした種類は重みづけの対象ですらなく、
// 探索グラフから外れる（通らない）。将来の除外条件（未舗装路等）もこのタブへ足す。

// 0次ハードフィルタ。**キーと既定値はbackendが正**で、生成物
// （route-generate-config.json、domain/evaluation.py由来）から受け取る——backendは
// キー集合の完全一致を要求するため、手書きで複製すると4つ目を足した瞬間に
// すべてのルート生成が422になる。表示ラベルはUIの語彙なのでここが持つ。
const HARD_FILTER_LABELS: Record<string, string> = {
  no_bicycle: "自転車通行禁止",
  motorway: "高速道路",
  trunk: "幹線道路(trunk)",
};

const HARD_FILTER_CHIPS: { key: string; label: string }[] = routeGenerateConfig.hard_filters.keys.map(
  (key) => ({ key, label: HARD_FILTER_LABELS[key] ?? key }),
);

export const DEFAULT_HARD_FILTERS: HardFilterOverride = Object.fromEntries(
  routeGenerateConfig.hard_filters.keys.map((key) => [
    key,
    routeGenerateConfig.hard_filters.defaults.includes(key),
  ]),
);

interface HardFilterPanelProps {
  hardFilters: HardFilterOverride;
  onHardFiltersChange: (next: HardFilterOverride) => void;
}

export default function HardFilterPanel({ hardFilters, onHardFiltersChange }: HardFilterPanelProps) {
  // 未設定キーの既定値はDEFAULT_HARD_FILTERS（生成物由来）から引く。`?? true`で埋めると、
  // backendが既定OFFのフィルタを足した瞬間、何も操作していないのに「変更あり」になり、
  // チップも押していないのにONで表示される。
  const customized = HARD_FILTER_CHIPS.some(
    ({ key }) => (hardFilters[key] ?? DEFAULT_HARD_FILTERS[key]) !== DEFAULT_HARD_FILTERS[key],
  );

  return (
    <div className="flex flex-col gap-3">
      <div className={styles.sectionHeader}>
        <p className={styles.sectionLabel}>除外する道路</p>
        <InfoPopover
          triggerClassName={styles.sectionInfoButton}
          triggerAriaLabel="除外する道路の説明"
          contentClassName={styles.legendInfoPopover}
        >
          ONにした種類は経路から完全に外れます（重みづけと違い、多少コストが高くても通る、ということが無くなります）。
        </InfoPopover>
      </div>
      <div className={styles.chipRow}>
        {HARD_FILTER_CHIPS.map(({ key, label }) => (
          <LayerChip
            key={key}
            label={label}
            on={hardFilters[key] ?? DEFAULT_HARD_FILTERS[key]}
            ariaLabel={`${label}を除外`}
            onClick={() =>
              onHardFiltersChange({
                ...hardFilters,
                [key]: !(hardFilters[key] ?? DEFAULT_HARD_FILTERS[key]),
              })
            }
          />
        ))}
      </div>
      {customized && (
        <button
          type="button"
          className={styles.resetButton}
          onClick={() => onHardFiltersChange(DEFAULT_HARD_FILTERS)}
        >
          除外を既定値に戻す
        </button>
      )}
    </div>
  );
}
