"use client";

import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import type { HardFilterOverride } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import { Button } from "@/components/ui/Button/Button";
import { ResetDefaultsIcon } from "@/components/ui/icons/icons";
import { Toggle } from "@/components/ui/Toggle/Toggle";

// 「ルート設定」区分の「除外」タブ。ここでONにした種類は重みづけの対象ですらなく、
// 探索グラフから外れる（通らない）。将来の除外条件（未舗装路等）もこのタブへ足す。

// 0次ハードフィルタ。**キー・画面に出す名前・既定値はbackendが正**で、生成物
// （route-generate-config.json、domain/hard_filters.py由来）から受け取る——backendは
// キー集合の完全一致を要求するため、手書きで複製すると1つ足した瞬間にすべての
// ルート生成が422になる。名前もキーと同じ行で届くので、名前の無いキーは無い。
const HARD_FILTER_CHIPS: readonly { key: string; label: string }[] = routeGenerateConfig.hard_filters.filters;

export const DEFAULT_HARD_FILTERS: HardFilterOverride = Object.fromEntries(
  HARD_FILTER_CHIPS.map(({ key }) => [key, routeGenerateConfig.hard_filters.defaults.includes(key)]),
);

interface HardFilterPanelProps {
  /** 今の項目を全部持つ値（保存値は`features/route/useGenerationConditions.ts`が読むときに今の項目へ揃える）。 */
  hardFilters: HardFilterOverride;
  onHardFiltersChange: (next: HardFilterOverride) => void;
}

export default function HardFilterPanel({ hardFilters, onHardFiltersChange }: HardFilterPanelProps) {
  const customized = HARD_FILTER_CHIPS.some(({ key }) => hardFilters[key] !== DEFAULT_HARD_FILTERS[key]);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {HARD_FILTER_CHIPS.map(({ key, label }) => (
        <Toggle
          key={key}
          pressed={hardFilters[key]}
          aria-label={`${label}を除外`}
          usage="ONにした種類の道路を通らないルートを作ります。"
          onClick={() =>
            onHardFiltersChange({
              ...hardFilters,
              [key]: !hardFilters[key],
            })
          }
        >
          {label}
        </Toggle>
      ))}
      <InfoPopover triggerAriaLabel="除外する道路の説明">
        ONにした種類は経路から完全に外れます[重みづけと違い、多少難易度が高くても通る、ということが無くなります]。
      </InfoPopover>
      <Button
        size="panelIcon"
        className="ml-auto"
        aria-label="除外を既定値に戻す"
        disabled={!customized}
        onClick={() => onHardFiltersChange(DEFAULT_HARD_FILTERS)}
        usage="除外のON/OFFを既定に戻します。"
      >
        <ResetDefaultsIcon />
      </Button>
    </div>
  );
}
