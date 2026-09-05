"use client";

import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
// RouteSettingsPanelの「重み配分」帯グラフ（.stackBar/.stackSegment）と同じ表現・
// 同じCSS classをそのまま流用する。
import stackBarStyles from "@/components/RouteSettingsPanel/RouteSettingsPanel.module.css";
import styles from "./AxisContributionBar.module.css";

interface AxisContributionBarProps {
  /** 表示対象の軸一覧（順序・ラベルの正本）。contributionsにキーが無い軸・値が0の軸は
   * 自動的に除外されるため、呼び出し側で事前に絞り込む必要はない。 */
  axes: readonly PreferenceAxisDef[];
  /** axis_id→重み付き寄与度（0-100スケール、合計が「総合難易度」と一致する値）。
   * ルート全体はRouteCandidate.axis_contributions、区間はRouteSegmentDetail.
   * axis_contributionsをそのまま渡す——frontendでの独自再計算は行わない
   * （backend: domain/evaluation.py: compose_costs_from_axis_matrix参照）。backendは
   * 公開軸すべてにキーを返す（重み0の軸も値0.0で含まれ、キーが省略されるのはその区間で
   * データ欠損の軸のみ）ため、値0（重み0の軸に限らず、寄与が実質無かった軸も含む）は
   * このコンポーネント側で表示から除く。 */
  contributions: Record<string, number>;
  /** 軸id→色ドットの色（呼び出し側のRouteAxisProfile/RouteSettingsPanelと共通の
   * 配色から渡す。同じ軸は常に同じ色になるようにするため）。 */
  axisColors: Record<string, string>;
}

const FALLBACK_COLOR = "#94a3b8";

/** 「重み付き寄与度」の内訳を積み上げ1本バー＋下の凡例（色ドット＋ラベル＋数値）で表示する
 * 共有部品。ルート結果タブ全体の内訳（RouteAxisProfile）と、区間クリック詳細
 * （ボトムシート側）の両方が同じこのコンポーネントを使う——値の出どころごとに別の
 * 表現は持たない。contributionsが1件も無ければ何も描画しない（呼び出し側の空状態
 * 文言に委ねる）。 */
export default function AxisContributionBar({ axes, contributions, axisColors }: AxisContributionBarProps) {
  // 値0（重み0の軸は常にちょうど0.0になる、backend: compose_costs_from_axis_matrix参照）は
  // 除外する。キーが無い（欠損データ）場合と同じ「表示すべき寄与が無い」として扱うが、
  // 負の値（クランプ前）は0ではないため除外しない——0-100範囲外のクランプ自体は
  // 下のstyle計算で行う。
  const rows = axes.filter((axis) => {
    const value = contributions[axis.axisId];
    return value != null && value !== 0;
  });
  if (rows.length === 0) return null;

  return (
    <div className={styles.wrap}>
      <div className={stackBarStyles.stackBar}>
        {rows.map((axis) => {
          const value = Math.min(100, Math.max(0, contributions[axis.axisId]));
          const color = axisColors[axis.axisId] ?? FALLBACK_COLOR;
          return (
            <div
              key={axis.axisId}
              className={stackBarStyles.stackSegment}
              style={{ width: `${value}%`, background: color }}
              title={`${axis.label} ${value.toFixed(1)}`}
            />
          );
        })}
      </div>
      <ul className={styles.legend}>
        {rows.map((axis) => {
          const color = axisColors[axis.axisId] ?? FALLBACK_COLOR;
          return (
            <li key={axis.axisId} className={styles.legendItem}>
              <span aria-hidden="true" className={styles.legendDot} style={{ background: color }} />
              <span className={styles.legendLabel}>{axis.label}</span>
              <span className={styles.legendValue}>{contributions[axis.axisId].toFixed(1)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
