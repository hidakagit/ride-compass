"use client";

import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
// 改善計画T550: RouteSettingsPanelの「重み配分」帯グラフ（.stackBar/.stackSegment）と
// 同じ表現・同じCSS classをそのまま流用する（ユーザー指定「積み上げ1本バーへ統一」）。
import stackBarStyles from "@/components/RouteSettingsPanel/RouteSettingsPanel.module.css";
import styles from "./AxisContributionBar.module.css";

interface AxisContributionBarProps {
  /** 表示対象の軸一覧（順序・ラベルの正本）。contributionsにキーが無い軸は自動的に
   * 除外されるため、呼び出し側で事前に絞り込む必要はない。 */
  axes: readonly PreferenceAxisDef[];
  /** axis_id→重み付き寄与度（0-100スケール、合計が「総合難易度」と一致する値）。
   * ルート全体はRouteCandidate.axis_contributions、区間はRouteSegmentDetail.
   * axis_contributionsをそのまま渡す——frontendでの独自再計算は行わない
   * （backend: domain/evaluation.py: compose_costs_from_axis_matrix参照）。 */
  contributions: Record<string, number>;
  /** 軸id→色ドットの色（呼び出し側のRouteAxisProfile/RouteSettingsPanelと共通の
   * 配色から渡す。同じ軸は常に同じ色になるようにするため）。 */
  axisColors: Record<string, string>;
}

const FALLBACK_COLOR = "#94a3b8";

/** 「重み付き寄与度」の内訳を積み上げ1本バー＋下の凡例（色ドット＋ラベル＋数値）で表示する
 * 共有部品（改善計画T550）。ルート結果タブ全体の内訳（RouteAxisProfile）と、区間クリック
 * 詳細（ボトムシート側）の両方が同じこのコンポーネントを使う——区間ごとに専用のレーダー
 * チャートを持っていた旧実装（routeSegmentChartPopup.ts）を撤去し、表示部品を一元化した。
 * contributionsが1件も無ければ何も描画しない（呼び出し側の空状態文言に委ねる）。 */
export default function AxisContributionBar({ axes, contributions, axisColors }: AxisContributionBarProps) {
  const rows = axes.filter((axis) => contributions[axis.axisId] != null);
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
