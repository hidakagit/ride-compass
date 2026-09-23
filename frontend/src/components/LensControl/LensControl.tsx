"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { useState } from "react";
import LegendCheckboxList from "@/components/Map/LegendCheckboxList";
import type { LegendEntry } from "@/components/Map/legendFilter";
import { LAYER_DATA_STATUS_LABELS, type LayerDataStatus } from "@/components/Map/mapLayers";
import {
  FIXED_LENS_LABELS,
  LENS_DIFFICULTY_ID,
  LENS_NEUTRAL_COLOR,
  LENS_NONE_ID,
  type LensId,
} from "@/components/Map/routeStyleModes";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { Button } from "@/components/ui/Button/Button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup/ToggleGroup";
import { Dot } from "@/components/ui/Dot/Dot";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { badgeVariants } from "@/components/ui/Badge/Badge";

export interface LensOption {
  id: LensId;
  label: string;
  color: string;
  description?: string;
  /** 生成条件の重みが0（評価に使っていない）。選べるが「未使用」バッジを付ける。 */
  unused: boolean;
  /** ルート未確定時に塗る手段（ramp・専用配信）を持たない軸。選べるがルート前は塗らない。 */
  routeOnly: boolean;
}

interface LensControlProps {
  lens: LensId;
  onLensChange: (id: LensId) => void;
  /** 軸カタログ順の公開軸（総合難易度・なしはこのコンポーネントが固定で足す）。 */
  axisOptions: readonly LensOption[];
  /** 現在のレンズの凡例（キー付き）。ルート未確定時の全道路の凡例・ルート後のルート線の凡例の
   * いずれも呼び出し側が組み立てる。 */
  legend: readonly LegendEntry[];
  /** 凡例で非表示にしている段階のキー。ルート確定の前後を問わず絞り込める
   * （ルート前は全道路の塗り、ルート後はルート線。同じ段階キーを共有する）。 */
  hiddenLegendKeys: readonly string[];
  onToggleLegendKey: (key: string) => void;
  /** 全段階の表示/非表示をまとめて置き換える（見出しのチェックから呼ぶ）。段階の細かい軸で
   * 「1つだけ見たい」を1つずつ外させないため。 */
  onSetHiddenLegendKeys: (hiddenKeys: string[]) => void;
  keepAfterRoute: boolean;
  onKeepAfterRouteChange: (keep: boolean) => void;
  /** ルート確定済みか（ルート前は「ルート後のみ」バッジを出す）。 */
  hasDetail: boolean;
  /** 現在のレンズのデータ取得状態（専用way値配信軸がレンズの間のみ意味を
   * 持つ。それ以外のレンズはこの失敗モードを持たないためundefined）。ピルへ小さな状態ドットを
   * 添える——道路の色分け自体は「取得失敗」と「本当にその範囲にデータが無い」のどちらも
   * 同じ無彩色になり見分けが付かないため。 */
  dataStatus?: LayerDataStatus;
}

// レンズ（地図を何で塗るか）の唯一の入口。地図上部中央のピルが「今のレンズ」の表示と
// 切替を兼ね、タップでポップオーバー（単一選択の一覧＋ルート後の扱い）を開く。
// サイドバーにはレンズの項目を置かない（入口はここ1つ、T590「UI設計の基準」2）。
export default function LensControl({
  lens,
  onLensChange,
  axisOptions,
  legend,
  hiddenLegendKeys,
  onToggleLegendKey,
  onSetHiddenLegendKeys,
  keepAfterRoute,
  onKeepAfterRouteChange,
  hasDetail,
  dataStatus,
}: LensControlProps) {
  const [open, setOpen] = useState(false);
  const statusLabel = dataStatus ? LAYER_DATA_STATUS_LABELS[dataStatus] : undefined;
  const current =
    FIXED_LENS_LABELS[lens] !== undefined
      ? { label: FIXED_LENS_LABELS[lens], color: LENS_NEUTRAL_COLOR }
      : (axisOptions.find((option) => option.id === lens) ?? { label: lens, color: LENS_NEUTRAL_COLOR });
  const used = axisOptions.filter((option) => !option.unused);
  const unused = axisOptions.filter((option) => option.unused);

  const select = (id: LensId) => {
    onLensChange(id);
    setOpen(false);
  };

  function renderOption(id: LensId, label: string, color: string, badges: string[] = []) {
    return (
      <ToggleGroupItem key={id} value={id}>
        <span aria-hidden="true" className="size-2.5 flex-shrink-0 rounded-full" style={{ background: color }} />
        <span className="flex-auto">{label}</span>
        {badges.map((badge) => (
          <span key={badge} className={badgeVariants({ variant: "warning" })}>
            {badge}
          </span>
        ))}
      </ToggleGroupItem>
    );
  }

  function renderAxis(option: LensOption) {
    const badges: string[] = [];
    if (option.unused) badges.push("未使用");
    if (option.routeOnly && !hasDetail) badges.push("ルート後のみ");
    return renderOption(option.id, option.label, option.color, badges);
  }

  return (
    <div className="absolute top-3 left-1/2 z-[var(--z-map-control)] max-w-[min(14rem,calc(100%-7rem))] -translate-x-1/2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="float"
            size="bare"
            shape="pill"
            className="flex-col items-stretch gap-1 border-0 px-2.5 py-1 text-[length:var(--font-size-sm)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent-strong)]"
            aria-label={`レンズ: ${current.label}（タップで変更）`}
            title={statusLabel}
          >
            <span className="flex items-center justify-center gap-1.5 whitespace-nowrap">
              <span
                aria-hidden="true"
                className="size-2.5 flex-shrink-0 rounded-full"
                style={{ background: current.color }}
              />
              <span className="font-semibold">{current.label}</span>
              {dataStatus && <Dot aria-hidden="true" tone={dataStatus} />}
              <span aria-hidden="true" className="text-[0.7rem] text-[var(--color-muted)]">
                ▾
              </span>
            </span>
            {legend.length > 0 && (
              <span className="flex flex-wrap justify-center gap-0.5" aria-hidden="true">
                {legend
                  .filter((entry) => !hiddenLegendKeys.includes(entry.key))
                  .map((entry) => (
                    <span
                      key={entry.key}
                      className="inline-block h-1.5 w-2.5 flex-shrink-0 rounded-[1px]"
                      style={{ background: entry.color }}
                      title={entry.label}
                    />
                  ))}
              </span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent
          className="max-h-[70vh] w-[min(24rem,calc(100vw-1.5rem))] overflow-y-auto rounded-sm px-3 py-2.5"
          side="bottom"
          align="center"
          sideOffset={6}
          collisionPadding={8}
        >
          <p className="mb-1.5 font-semibold">レンズ</p>
          {/* ピルの状態ドットの意味。titleはスマホでは出ないため、開いた先で文として読ませる。 */}
          {statusLabel && (
            <p className="mb-1.5 text-[length:var(--font-size-sm)]" role="status">
              {statusLabel}
            </p>
          )}
          <ToggleGroup
            variant="list"
            className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-x-1 p-0"
            value={lens}
            onValueChange={(id) => select(id as LensId)}
            aria-label="レンズ"
          >
            {renderOption(LENS_NONE_ID, FIXED_LENS_LABELS[LENS_NONE_ID], LENS_NEUTRAL_COLOR)}
            {renderOption(LENS_DIFFICULTY_ID, FIXED_LENS_LABELS[LENS_DIFFICULTY_ID], LENS_NEUTRAL_COLOR)}
            {used.length > 0 && (
              <span className={cn(textVariants({ variant: "note" }), "col-span-full mt-1.5 py-0.5 tracking-wide")}>
                評価に使用中
              </span>
            )}
            {used.map(renderAxis)}
            {unused.length > 0 && (
              <span className={cn(textVariants({ variant: "note" }), "col-span-full mt-1.5 py-0.5 tracking-wide")}>
                未使用
              </span>
            )}
            {unused.map(renderAxis)}
          </ToggleGroup>
          <label className="mt-2 flex items-center gap-1.5 border-t border-dashed border-[var(--color-border)] pt-2">
            <Checkbox
              checked={keepAfterRoute}
              onCheckedChange={onKeepAfterRouteChange}
              aria-label="ルート後も周囲の道路を薄く塗る"
            />
            ルート後も周囲の道路を薄く塗る
          </label>
          {legend.length > 0 && (
            <div className="mt-2 border-t border-[var(--color-border)] pt-2">
              <label className="mb-1 flex cursor-pointer items-center gap-1.5 font-semibold text-[var(--color-muted)]">
                <Checkbox
                  checked={hiddenLegendKeys.length === 0}
                  onCheckedChange={() =>
                    onSetHiddenLegendKeys(hiddenLegendKeys.length === 0 ? legend.map((entry) => entry.key) : [])
                  }
                  aria-label="凡例の全段階をまとめて表示/非表示"
                />
                凡例
              </label>
              <LegendCheckboxList
                legend={legend}
                hiddenKeys={hiddenLegendKeys}
                onToggle={onToggleLegendKey}
                listClassName={
                  "m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-x-2 gap-y-0.5 p-0"
                }
                rowClassName={"flex items-center gap-1 tabular-nums [overflow-wrap:anywhere]"}
                swatchClassName={"inline-block h-1.5 w-2.5 flex-shrink-0 rounded-[1px]"}
              />
            </div>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}
