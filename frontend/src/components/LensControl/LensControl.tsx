"use client";

import * as Popover from "@radix-ui/react-popover";
import { useState, type RefObject } from "react";
import LegendCheckboxList from "@/components/Map/LegendCheckboxList";
import type { LegendEntry } from "@/components/Map/legendFilter";
import { LENS_DIFFICULTY_ID, LENS_NONE_ID, type LensId } from "@/components/Map/routeStyleModes";
import styles from "./LensControl.module.css";

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

export interface LensControlProps {
  lens: LensId;
  onLensChange: (id: LensId) => void;
  /** 軸カタログ順の公開軸（総合難易度・なしはこのコンポーネントが固定で足す）。 */
  axisOptions: readonly LensOption[];
  /** 現在のレンズの凡例（キー付き）。ルート未確定時の全道路の凡例・ルート後のルート線の凡例の
   * いずれも呼び出し側が組み立てる。 */
  legend: readonly LegendEntry[];
  /** ルート後だけ凡例の段階を非表示にできる（undefinedなら読み取り専用の凡例）。 */
  hiddenLegendKeys?: readonly string[];
  onToggleLegendKey?: (key: string) => void;
  keepAfterRoute: boolean;
  onKeepAfterRouteChange: (keep: boolean) => void;
  /** ルート確定済みか（ルート前は「ルート後のみ」バッジを出す）。 */
  hasDetail: boolean;
  /** ルート条件バーを本コンポーネントの直下へ積む配置（page.tsx）が、実測高さを
   * useElementHeightCssVarへ渡すために使う。指定が無ければ通常どおり動作する。 */
  rootRef?: RefObject<HTMLDivElement | null>;
}

const DIFFICULTY_COLOR = "#64748b";

// レンズ（地図を何で塗るか）の唯一の入口。地図上部中央のピルが「今のレンズ」の表示と
// 切替を兼ね、タップでポップオーバー（単一選択の一覧＋ルート後の扱い）を開く。
// 「地図の見え方」パネルにはレンズの項目を置かない（入口はここ1つ、T590「UI設計の基準」2）。
export default function LensControl({
  lens,
  onLensChange,
  axisOptions,
  legend,
  hiddenLegendKeys,
  onToggleLegendKey,
  keepAfterRoute,
  onKeepAfterRouteChange,
  hasDetail,
  rootRef,
}: LensControlProps) {
  const [open, setOpen] = useState(false);
  const current =
    lens === LENS_NONE_ID
      ? { label: "なし", color: DIFFICULTY_COLOR }
      : lens === LENS_DIFFICULTY_ID
        ? { label: "総合難易度", color: DIFFICULTY_COLOR }
        : (axisOptions.find((option) => option.id === lens) ?? { label: lens, color: DIFFICULTY_COLOR });
  const used = axisOptions.filter((option) => !option.unused);
  const unused = axisOptions.filter((option) => option.unused);

  const select = (id: LensId) => {
    onLensChange(id);
    setOpen(false);
  };

  function renderOption(id: LensId, label: string, color: string, badges: string[] = []) {
    const checked = lens === id;
    return (
      <li key={id} className={styles.option}>
        <button
          type="button"
          role="radio"
          aria-checked={checked}
          className={styles.optionButton}
          data-checked={checked}
          onClick={() => select(id)}
        >
          <span aria-hidden="true" className={styles.dot} style={{ background: color }} />
          <span className={styles.optionLabel}>{label}</span>
          {badges.map((badge) => (
            <span key={badge} className={styles.badge}>
              {badge}
            </span>
          ))}
        </button>
      </li>
    );
  }

  function renderAxis(option: LensOption) {
    const badges: string[] = [];
    if (option.unused) badges.push("未使用");
    if (option.routeOnly && !hasDetail) badges.push("ルート後のみ");
    return renderOption(option.id, option.label, option.color, badges);
  }

  return (
    <div ref={rootRef} className={styles.wrap}>
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button type="button" className={styles.pill} aria-label={`レンズ: ${current.label}（タップで変更）`}>
            <span className={styles.pillHeader}>
              <span aria-hidden="true" className={styles.dot} style={{ background: current.color }} />
              <span className={styles.pillLabel}>{current.label}</span>
              <span aria-hidden="true" className={styles.chevron}>
                ▾
              </span>
            </span>
            {legend.length > 0 && (
              <span className={styles.swatchRow} aria-hidden="true">
                {legend
                  .filter((entry) => !hiddenLegendKeys?.includes(entry.key))
                  .map((entry) => (
                    <span key={entry.key} className={styles.swatch} style={{ background: entry.color }} title={entry.label} />
                  ))}
              </span>
            )}
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content className={styles.content} side="bottom" align="center" sideOffset={6} collisionPadding={8}>
            <p className={styles.heading}>レンズ（地図を何で塗るか）</p>
            <ul className={styles.list} role="radiogroup" aria-label="レンズ">
              {renderOption(LENS_NONE_ID, "なし", DIFFICULTY_COLOR)}
              {renderOption(LENS_DIFFICULTY_ID, "総合難易度", DIFFICULTY_COLOR)}
              {used.length > 0 && <li className={styles.groupLabel}>評価に使用中</li>}
              {used.map(renderAxis)}
              {unused.length > 0 && <li className={styles.groupLabel}>未使用</li>}
              {unused.map(renderAxis)}
            </ul>
            <label className={styles.keepRow}>
              <input
                type="checkbox"
                checked={keepAfterRoute}
                onChange={(event) => onKeepAfterRouteChange(event.target.checked)}
              />
              ルート後も周囲の道路を薄く塗る
            </label>
            {legend.length > 0 && (
              <div className={styles.legendBlock}>
                <p className={styles.heading}>凡例</p>
                {hiddenLegendKeys && onToggleLegendKey ? (
                  <LegendCheckboxList
                    legend={legend}
                    hiddenKeys={hiddenLegendKeys}
                    onToggle={onToggleLegendKey}
                    listClassName={styles.legendList}
                    rowClassName={styles.legendRow}
                    swatchClassName={styles.swatch}
                  />
                ) : (
                  <ul className={styles.legendList}>
                    {legend.map((entry) => (
                      <li key={entry.key} className={styles.legendRow}>
                        <span aria-hidden="true" className={styles.swatch} style={{ background: entry.color }} />
                        <span>{entry.label}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
