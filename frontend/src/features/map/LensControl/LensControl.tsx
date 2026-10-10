"use client";

import { Popover, PopoverContent, PopoverTrigger, POPOVER_COLLISION_PADDING_PX } from "@/components/ui/Popover/Popover";
import { useState } from "react";
import LegendCheckboxList from "@/features/map/LegendCheckboxList/LegendCheckboxList";
import { hiddenAfterToggleAll } from "@/features/map/view/legendFilters";
import { LEGEND_SWATCH_RING_CLASS, legendSwatchBackground, type LegendEntry } from "@/lib/mapDisplay/legendFilter";
import { LAYER_DATA_STATUS_LABELS, layerDataStatusNotice, type LayerDataStatus } from "@/features/map/layers/mapLayers";
import {
  FIXED_LENS_LABELS,
  LENS_DIFFICULTY_ID,
  LENS_NEUTRAL_COLOR,
  LENS_NONE_ID,
  type LensId,
} from "@/lib/mapDisplay/routeStyleModes";
import { Checkbox } from "@/components/ui/Checkbox/Checkbox";
import { Button } from "@/components/ui/Button/Button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/ToggleGroup/ToggleGroup";
import { Dot } from "@/components/ui/Dot/Dot";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";
import { Badge } from "@/components/ui/Badge/Badge";

export interface LensOption {
  id: LensId;
  label: string;
  color: string;
  /** 重みが0（評価に使っていない）。選べるが「未使用」の見出しの下に並ぶ。 */
  unused: boolean;
  /** ルート未確定時に塗る手段（ramp・専用配信）を持たない軸。選べるがルート前は塗らない。 */
  routeOnly: boolean;
}

interface LensControlProps {
  lens: LensId;
  onLensChange: (id: LensId) => void;
  /** 軸カタログ順の公開軸（総合難易度・なしはこのコンポーネントが固定で足す）。 */
  axisOptions: readonly LensOption[];
  /** 今のレンズの凡例（ルートの前は道路、後はルートの線。どちらも呼ぶ側が組む）。 */
  legend: readonly LegendEntry[];
  /** 凡例で隠している段（ルートの前後で共有する）。 */
  hiddenLegendKeys: readonly string[];
  onToggleLegendKey: (key: string) => void;
  /** 全部の段をまとめて置き換える（段の細かい軸で「1つだけ見たい」を1つずつ外させない）。 */
  onSetHiddenLegendKeys: (hiddenKeys: string[]) => void;
  keepAfterRoute: boolean;
  onKeepAfterRouteChange: (keep: boolean) => void;
  /** ルート確定済みか（ルート前は「ルート後のみ」バッジを出す）。 */
  hasDetail: boolean;
  /** ルートの線を地図に出しているか。 */
  routeShown: boolean;
  /** 候補を選んでいるか。選ぶまでルートの線は無いので、出し入れを押せない。 */
  routeSelectable: boolean;
  onRouteShownChange: (shown: boolean) => void;
  /** 周りの道の色が拠る走る条件の文（`view/lens.ts: lensConditionsLabel`）。条件を使わない色分けではnull。 */
  conditions: string | null;
  /** 今のレンズの取得の状態（専用配信の軸のときだけ）。塗りは失敗でもデータ無しでも同じ無彩色なので、印で見分ける。 */
  dataStatus?: LayerDataStatus;
}

/** 画面の名前。コードの「レンズ」は画面には出さない（利用者が見る名前はこれだけ）。 */
const LENS_SCREEN_NAME = "地図の色分け";

/** ルートを作る前は道に何も塗らない色分けに付ける札。 */
const ROUTE_ONLY_BADGE = "ルート後のみ";

/** 凡例の段の見本（ピルの帯と開いた先の一覧で同じ形）。 */
const LEGEND_BAR_CLASS = "inline-block h-1.5 w-2.5 flex-shrink-0 rounded-[1px]";

/** 軸の外に固定で並べる色分け。総合難易度はルートの線にだけ色を付ける（周りの道を塗る値を持たない）。 */
const FIXED_LENS_OPTIONS: readonly LensOption[] = [
  {
    id: LENS_NONE_ID,
    label: FIXED_LENS_LABELS[LENS_NONE_ID],
    color: LENS_NEUTRAL_COLOR,
    unused: false,
    routeOnly: false,
  },
  {
    id: LENS_DIFFICULTY_ID,
    label: FIXED_LENS_LABELS[LENS_DIFFICULTY_ID],
    color: LENS_NEUTRAL_COLOR,
    unused: false,
    routeOnly: true,
  },
];

const GROUP_HEADING_CLASS = cn(textVariants({ variant: "note" }), "basis-full pt-0.5 tracking-wide");

function LensSwatch({ color }: { color: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("size-2.5 flex-shrink-0 rounded-full", LEGEND_SWATCH_RING_CLASS)}
      style={{ background: color }}
    />
  );
}

/** レンズ（地図を何で塗るか）の唯一の入口。地図の上のピルが今のレンズを示し、押すと一覧を開く。置き場は呼び出し側が決める。 */
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
  routeShown,
  routeSelectable,
  onRouteShownChange,
  conditions,
  dataStatus,
}: LensControlProps) {
  const [open, setOpen] = useState(false);
  const statusLabel = dataStatus ? LAYER_DATA_STATUS_LABELS[dataStatus] : undefined;
  const statusNotice = layerDataStatusNotice(dataStatus);
  const current = [...FIXED_LENS_OPTIONS, ...axisOptions].find((option) => option.id === lens) ?? {
    label: lens,
    color: LENS_NEUTRAL_COLOR,
    routeOnly: false,
  };
  const used = axisOptions.filter((option) => !option.unused);
  const unused = axisOptions.filter((option) => option.unused);
  const routeOnlyBadge = (routeOnly: boolean) =>
    routeOnly && !hasDetail ? <Badge variant="warning">{ROUTE_ONLY_BADGE}</Badge> : null;
  const currentRouteOnly = !hasDetail && current.routeOnly;

  const select = (id: LensId) => {
    onLensChange(id);
    setOpen(false);
  };

  function renderOption(option: LensOption) {
    return (
      <ToggleGroupItem key={option.id} value={option.id}>
        <LensSwatch color={option.color} />
        {option.label}
        {routeOnlyBadge(option.routeOnly)}
      </ToggleGroupItem>
    );
  }

  return (
    <div className="pointer-events-auto min-w-0 max-w-56">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="float"
            size="bare"
            shape="pill"
            className="flex-col items-stretch gap-1 border-0 px-2.5 py-1 text-[length:var(--font-size-sm)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-accent-strong)]"
            aria-label={`${LENS_SCREEN_NAME}: ${[current.label, currentRouteOnly && ROUTE_ONLY_BADGE, conditions].filter(Boolean).join("・")}（タップで変更）`}
            title={statusLabel}
            usage="地図の道路（ルートを作った後はルートの線）を何で色分けするかを選びます。下の帯は今の色分けの凡例です。"
          >
            <span className="flex items-center justify-center gap-1.5 whitespace-nowrap">
              <LensSwatch color={current.color} />
              <span className="font-semibold">{current.label}</span>
              {routeOnlyBadge(currentRouteOnly)}
              {dataStatus && <Dot aria-hidden="true" tone={dataStatus} />}
              <span aria-hidden="true" className="text-[0.7rem] text-[var(--color-muted)]">
                ▾
              </span>
            </span>
            {conditions && (
              <span aria-hidden="true" className="text-center text-[0.7rem] text-[var(--color-muted)]">
                {conditions}
              </span>
            )}
            {legend.length > 0 && (
              <span className="flex flex-wrap justify-center gap-0.5" aria-hidden="true">
                {legend
                  .filter((entry) => !hiddenLegendKeys.includes(entry.key))
                  .map((entry) => (
                    <span
                      key={entry.key}
                      className={cn(LEGEND_BAR_CLASS, LEGEND_SWATCH_RING_CLASS)}
                      style={{ background: legendSwatchBackground(entry) }}
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
          align="start"
          collisionPadding={POPOVER_COLLISION_PADDING_PX}
        >
          <p className="mb-1.5 font-semibold">{LENS_SCREEN_NAME}</p>
          {conditions && (
            <p className="mb-1.5 text-[length:var(--font-size-sm)]">{`周りの道は「${conditions}」の条件で塗っています。`}</p>
          )}
          {/* ピルの状態ドットの意味。titleはスマホでは出ないため、開いた先で文として読ませる。 */}
          {statusNotice && (
            <p className="mb-1.5 text-[length:var(--font-size-sm)]" role="status">
              {statusNotice}
            </p>
          )}
          <ToggleGroup
            variant="chips"
            value={lens}
            onValueChange={(id) => select(id as LensId)}
            aria-label={LENS_SCREEN_NAME}
            usage="押した項目で、地図の道路（ルートを作った後はルートの線）を色分けします。"
          >
            {FIXED_LENS_OPTIONS.map(renderOption)}
            {used.length > 0 && <span className={GROUP_HEADING_CLASS}>評価軸に使用中</span>}
            {used.map(renderOption)}
            {unused.length > 0 && <span className={GROUP_HEADING_CLASS}>未使用</span>}
            {unused.map(renderOption)}
          </ToggleGroup>
          <label
            className={cn(
              "mt-2 flex items-center gap-1.5 border-t border-dashed border-[var(--color-border)] pt-2",
              routeSelectable ? "cursor-pointer" : "text-[var(--color-neutral)]",
            )}
            data-usage="選んだ候補のルートの線を、地図に出し入れします。"
          >
            <Checkbox
              checked={routeShown && routeSelectable}
              disabled={!routeSelectable}
              onCheckedChange={() => onRouteShownChange(!routeShown)}
              aria-label="ルートを地図に出す"
            />
            ルートを地図に出す
            {!routeSelectable && <span className={textVariants({ variant: "note" })}>（候補を選ぶと出せます）</span>}
          </label>
          <label
            className="mt-1 flex items-center gap-1.5"
            data-usage="ルートを作った後も、ルートの外の道路を薄く色分けしたまま残します。"
          >
            <Checkbox
              checked={keepAfterRoute}
              onCheckedChange={onKeepAfterRouteChange}
              aria-label="ルート後も周囲の道路を薄く塗る"
            />
            ルート後も周囲の道路を薄く塗る
          </label>
          {legend.length > 0 && (
            <div
              className="mt-2 border-t border-[var(--color-border)] pt-2"
              data-usage="チェックを外した段階は、地図の色分けから隠れます。「凡例」のチェックで全部をまとめて切り替えます。"
            >
              <label className="mb-1 flex cursor-pointer items-center gap-1.5 font-semibold text-[var(--color-muted)]">
                <Checkbox
                  checked={hiddenLegendKeys.length === 0}
                  onCheckedChange={() => onSetHiddenLegendKeys(hiddenAfterToggleAll(legend, hiddenLegendKeys))}
                  aria-label="凡例の全段階をまとめて表示/非表示"
                />
                凡例
              </label>
              <LegendCheckboxList
                legend={legend}
                hiddenKeys={hiddenLegendKeys}
                onToggle={onToggleLegendKey}
                listClassName="flex flex-wrap gap-x-3 gap-y-0.5"
                rowClassName="flex items-center gap-1 whitespace-nowrap tabular-nums"
                swatchClassName={LEGEND_BAR_CLASS}
              />
            </div>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}
