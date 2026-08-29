"use client";

import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { rampColorForBand } from "@/components/Map/axisLayers";
import styles from "./RouteAxisProfile.module.css";

interface RouteAxisProfileProps {
  /** 表示対象の軸一覧（順序・ラベルの正本）。呼び出し側がuseAxisCatalog().axesを渡す
   * ことで、軸スタジオでの軸増減に自動追従する（ハードコードした軸id→ラベル辞書を
   * 新設しない、改善計画T402）。 */
  axes: readonly PreferenceAxisDef[];
  /** RouteCandidate.axis_difficulties（axis_id→difficulty 0-100の距離加重平均、
   * 改善計画T402）。評価できなかった軸はキー自体を持たない。 */
  axisDifficulties: Record<string, number>;
}

// difficulty(0-100)をaxisLayers.tsの共有ランプ配色（緑→黄→橙→赤、RAMP_COLOR_ANCHORS）へ
// 写像する。rampColorForBand(index, bandCount)はbandCount段階中index番目の色を
// t=index/(bandCount-1)でRAMP_COLOR_ANCHORS上を線形補間して返す設計のため、
// bandCount=101・index=Math.round(value)とすればt=value/100に一致し、地図の段階配色と
// 完全に同じ配色系統のまま0-100の連続値をそのまま色へ変換できる（新しい配色ロジックを
// 増やさない）。
function colorForDifficulty(value: number): string {
  const clamped = Math.min(100, Math.max(0, value));
  return rampColorForBand(Math.round(clamped), 101);
}

// ルート全体のaxis_difficultiesを軸ごとの横棒グラフ一覧として表示する（改善計画T400節4・
// T402、ユーザー確定済みの可視化形式）。レーダーチャートは採用しない
// （区間クリックの小型チャート[別途T400節3で実装予定]と役割を分ける）。
export default function RouteAxisProfile({ axes, axisDifficulties }: RouteAxisProfileProps) {
  // 軸カタログの並び順のうち、このルートで実際に評価できた軸だけを表示する
  // （axis_difficultiesにキーが無い＝データ無しで評価不能、という規約はRouteSegmentDetail
  // と共通。domain/route.py: RouteCandidate docstring参照）。
  const rows = axes.filter((axis) => axisDifficulties[axis.axisId] != null);

  if (rows.length === 0) {
    return <p className={styles.empty}>このルートで表示できる評価軸データがありません</p>;
  }

  return (
    <div>
      <p className={styles.hint}>各軸の難易度[0-100、絶対基準・軸スタジオの重みで自動追従]</p>
      <ul className={styles.list}>
        {rows.map((axis) => {
          const value = axisDifficulties[axis.axisId];
          return (
            <li key={axis.axisId} className={styles.row}>
              <span className={styles.label} title={axis.label}>
                {axis.label}
              </span>
              <span className={styles.track}>
                <span
                  className={styles.bar}
                  style={{ width: `${Math.min(100, Math.max(0, value))}%`, background: colorForDifficulty(value) }}
                />
              </span>
              <span className={styles.value}>{Math.round(value)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
