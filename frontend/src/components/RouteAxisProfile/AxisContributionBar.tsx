"use client";

import type { ReactNode } from "react";
import InfoPopover from "@/components/Map/InfoPopover";
import { axisIconFor } from "@/components/Map/axisIconPalette";
import { InfoIcon } from "@/components/Map/icons";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
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
  /** 凡例に並べる軸。省略すると帯グラフに出る軸だけになる。公開軸すべてを渡せば、
   * 寄与が出ない軸（評価に使っていない・値が無い）も薄いチップとして残る。 */
  legendAxes?: readonly PreferenceAxisDef[];
  /** 凡例チップを押したときに開く、その軸の詳細。nullを返した軸のチップは押せない
   * （結果パネルでは「評価に使っていない軸」がこれにあたる）。prop自体を省略すると
   * どのチップも押せない静的な凡例のまま（区間クリック詳細のように、軸ごとの詳細を
   * 持たない呼び出し側がある）。 */
  renderDetail?: (axis: PreferenceAxisDef) => ReactNode | null;
}

const FALLBACK_COLOR = "#94a3b8";

/** 「重み付き寄与度」の内訳を積み上げ1本バー＋下の凡例（色ドット＋ラベル＋数値）で表示する
 * 共有部品。ルート結果タブ全体の内訳（RouteAxisProfile）と、区間クリック詳細
 * （ボトムシート側）の両方が同じこのコンポーネントを使う——値の出どころごとに別の
 * 表現は持たない。contributionsが1件も無ければ何も描画しない（呼び出し側の空状態
 * 文言に委ねる）。 */
export default function AxisContributionBar({
  axes,
  contributions,
  axisColors,
  legendAxes,
  renderDetail,
}: AxisContributionBarProps) {
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
      <div className={styles.stackBar}>
        {rows.map((axis) => {
          const value = Math.min(100, Math.max(0, contributions[axis.axisId]));
          const color = axisColors[axis.axisId] ?? FALLBACK_COLOR;
          return (
            <div
              key={axis.axisId}
              className={styles.stackSegment}
              style={{ width: `${value}%`, background: color }}
              title={`${axis.label} ${value.toFixed(1)}`}
            />
          );
        })}
      </div>
      <ul className={styles.legend}>
        {(legendAxes ?? rows)
          .filter((axis) => renderDetail == null || renderDetail(axis) !== null)
          .map((axis) => {
          const color = axisColors[axis.axisId] ?? FALLBACK_COLOR;
          const value = contributions[axis.axisId];
          const detail = renderDetail?.(axis) ?? null;
          // 軸の名前は出さず、地図チップと同じアイコンと寄与の値だけを並べる——狭い幅では
          // 名前がそのまま行数になり、10軸で内訳が画面の大半を占めてしまう。名前は押して
          // 開く説明（InfoPopover）が持ち、押せない軸はaria-labelとtitleで補う。
          const Icon = axisIconFor(axis.iconId);
          const body = (
            <>
              <span aria-hidden="true" className={styles.legendIcon} style={{ color }}>
                <Icon size={14} />
              </span>
              {value != null && value !== 0 && <span className={styles.legendValue}>{value.toFixed(1)}</span>}
            </>
          );
          return (
            <li key={axis.axisId} className={styles.legendChip} data-checked={detail !== null}>
              {detail === null ? (
                <span className={styles.legendChipBody} title={axis.label} aria-label={axis.label} role="img">
                  {body}
                </span>
              ) : (
                <InfoPopover
                  triggerClassName={styles.legendTrigger}
                  triggerAriaLabel={`${axis.label}の詳細`}
                  contentClassName={styles.legendPopover}
                  // チップ全体が押せることを、このアプリで「押すと説明が出る」を表している
                  // (i)で示す（押せる／押せないの差が輪郭の濃さだけでは伝わらない）。
                  triggerContent={
                    <>
                      {body}
                      <InfoIcon size={12} />
                    </>
                  }
                >
                  {detail}
                </InfoPopover>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
