"use client";

import palette from "@/types/generated/palette.json";
import type React from "react";
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
   * **寄与が0・欠損でも詳細を持つ軸は凡例に残る**——効くはずの軸が効かなかったことも
   * 判断材料のため。 */
  legendAxes?: readonly PreferenceAxisDef[];
  /** 帯の高さの倍率（`lib/difficultyLoadBar.ts: loadBarHeightRatio`）。帯は長さが
   * 総合難易度を表すため、高さへ距離を与えると塗られた面積が負荷、色ごとの面積が軸別の
   * 負荷になる。省略時は1.0——区間の内訳のように、比べる相手が無く距離を与えない
   * 呼び出し側は長さだけの帯のままにする。 */
  heightRatio?: number;
  /** 凡例チップを押したときに開く、その軸の詳細。**nullを返した軸は凡例から落ちる**
   * （結果パネルは重み0の軸でnullを返し、評価に使っていない軸を並べない）。prop自体を
   * 省略するとどのチップも押せない静的な凡例のまま（区間クリック詳細のように、軸ごとの
   * 詳細を持たない呼び出し側がある）。 */
  renderDetail?: (axis: PreferenceAxisDef) => ReactNode | null;
}

const FALLBACK_COLOR = palette.semantic.neutral;

/** その軸に「表示すべき寄与」があるか。
 *
 * 値0（重み0の軸は常にちょうど0.0になる、backend: compose_costs_from_axis_matrix参照）は、
 * キーが無い（欠損データ）場合と同じく無しとして扱う。負の値（クランプ前）は0ではないため
 * 残す——0-100範囲外のクランプは表示側のstyle計算で行う。
 *
 * **空状態の案内文を出す側とバーを描く側で同じ判定を使う**（別々に書くとずれ、
 * 「案内文も出ないしバーも無い」状態が生まれる）。 */
export function hasContribution(contributions: Record<string, number>, axisId: string): boolean {
  const value = contributions[axisId];
  return value != null && value !== 0;
}

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
  heightRatio,
  renderDetail,
}: AxisContributionBarProps) {
  const rows = axes.filter((axis) => hasContribution(contributions, axis.axisId));
  if (rows.length === 0) return null;

  const barStyle: React.CSSProperties & { "--load-bar-height-ratio"?: string } = {
    "--load-bar-height-ratio": String(heightRatio ?? 1),
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.stackBar} style={barStyle}>
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
          // renderDetailは軸あたり1回だけ呼ぶ（絞り込みと本体で別々に呼ぶと、片方で
          // 組み立てたJSXがそのまま捨てられる）。
          .map((axis) => ({ axis, detail: renderDetail?.(axis) ?? null }))
          .filter(({ detail }) => renderDetail == null || detail !== null)
          .map(({ axis, detail }) => {
            const color = axisColors[axis.axisId] ?? FALLBACK_COLOR;
            const value = contributions[axis.axisId];
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
              // 押せる／押せないの区別は、詳細を出す契約（renderDetail）がある呼び出しに
              // だけある。契約が無い呼び出しで全チップを「押せない」印にすると、凡例全体が
              // 薄く描かれて理由の無い弱め方になる。
              <li
                key={axis.axisId}
                className={styles.legendChip}
                data-checked={renderDetail == null ? undefined : detail !== null}
              >
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
