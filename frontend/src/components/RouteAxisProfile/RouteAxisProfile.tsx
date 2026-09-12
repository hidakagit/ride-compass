"use client";

import { useState } from "react";

import InfoPopover from "@/components/Map/InfoPopover";
import { InfoIcon } from "@/components/Map/icons";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights } from "@/types/route";
import AxisContributionBar from "./AxisContributionBar";
import {
  formatAxisRawValue,
  formatCategoryBreakdown,
  formatMaterialBreakdown,
} from "./axisRawValue";
import styles from "./RouteAxisProfile.module.css";

interface RouteAxisProfileProps {
  /** 公開軸すべて（軸カタログの順序・ラベルの正本）。重みによる絞り込みは行わない。 */
  axes: readonly PreferenceAxisDef[];
  /** この候補を実際に評価した重み（生成時点のroute_preference）。0の軸は畳んだ1行へまとめる。 */
  weights: RoutePreferenceWeights;
  /** RouteCandidate.axis_difficulties（axis_id→距離加重平均の難易度0-100）。評価できなかった
   * 軸はキー自体を持たない。 */
  axisDifficulties: Record<string, number>;
  /** RouteCandidate.axis_contributions（axis_id→重み付き寄与度0-100、合計はoverallDifficultyと
   * 一致する）。backendは公開軸すべてにキーを返す（重み0の軸は値0.0）ため、値0の軸は
   * AxisContributionBar側で表示から除く（本コンポーネント側での絞り込みは行わない）。 */
  axisContributions: Record<string, number>;
  /** RouteCandidate.axis_raw_values（axis_id→折れ点を通す前の生値）。単位が定まる軸だけが
   * 値を持つ。得点は目盛りの引き方に依存する相対評価のため、軸単体で経路を判断するには
   * この絶対値が要る。 */
  axisRawValues: Record<string, number>;
  /** RouteCandidate.material_values（材料id→距離加重平均の値）。生値の単位が定まらない軸は、
   * 軸の内訳（PreferenceAxisDef.materialBreakdown）が挙げる材料の値をここから引いて出す。
   * 真偽値材料は0/1で運ばれるため、平均がそのまま該当区間の延長割合になる。 */
  materialValues: Record<string, number>;
  /** RouteCandidate.material_category_shares（categorical材料id→{値: 延長割合}）。
   * 数値として平均できない材料の内訳はここから引く。 */
  materialCategoryShares: Record<string, Record<string, number>>;
  /** 経路の走行距離（km）。単位が「◯◯/km」の軸で、生値から経路全体の実数を出すのに使う。 */
  distanceKm: number | null;
  /** RouteCandidate.overall_difficulty（内訳の合計、絶対基準0-100）。 */
  overallDifficulty: number | null;
  /** RouteCandidate.difficulty_load（総合難易度×距離km）。総合難易度が距離で正規化
   * されるのに対し、こちらは距離が伸びればそのまま増えるため「遠回りした分だけ増える
   * しんどさ」を表す。候補間の相対比較に使う値で単位を持たない。 */
  difficultyLoad: number | null;
  /** 軸id→色ドットの色（ルート設定パネルの凡例チップと同じ色）。 */
  axisColors: Record<string, string>;
}

const FALLBACK_DOT_COLOR = "#64748b";

// ルート結果の「総合難易度＋重み付き寄与度の積み上げバー」を表示する読み取り専用の部品。
// 軸ごとの詳細（軸別難易度・生値・材料内訳・説明）は一覧を作らず、バーの凡例チップを
// 押して開く。地図の色分け（レンズ）の選択はここでは行わない（入口は地図上の凡例ピル
// `LensControl`だけ）。寄与が出ない軸は、重み0なら畳んだ1行へまとめて本数を残し、
// 値が無いだけの軸はチップのまま残す（消さずに薄くする）。
export default function RouteAxisProfile({
  axes,
  weights,
  axisRawValues,
  materialValues,
  materialCategoryShares,
  distanceKm,
  axisDifficulties,
  axisContributions,
  overallDifficulty,
  difficultyLoad,
  axisColors,
}: RouteAxisProfileProps) {
  // 値0（重み0の軸は常に0.0、AxisContributionBar.tsx参照）は表示すべき寄与が無いものとして
  // 除外する。ここでの絞り込みはAxisContributionBar自身が行う絞り込みと同じ条件にし、
  // 「空状態の案内文」と「バーの中身が無い」の判定がずれないようにする。
  const contributionRows = axes.filter((axis) => {
    const value = axisContributions[axis.axisId];
    return value != null && value !== 0;
  });

  // 寄与のバーに出ない軸の行き先を2つに分ける。重み0（ユーザー自身が使わないと決めた軸）は
  // 畳んで本数だけを残し、値が無いだけの軸は畳まずチップのまま残す——後者はユーザーの
  // 選択ではないため、読みたい軸が黙って隠れないようにする（設計原則「消さずに薄くする」）。
  const leftoverAxes = axes.filter((axis) => !contributionRows.includes(axis));
  const unusedAxes = leftoverAxes.filter((axis) => (weights[axis.axisId] ?? 0) <= 0);
  const valuelessAxes = leftoverAxes.filter((axis) => (weights[axis.axisId] ?? 0) > 0);
  const [unusedOpen, setUnusedOpen] = useState(false);

  // 凡例チップ・残りチップのどちらから開いても同じ中身にする（軸の詳細の出どころは1つ）。
  const renderAxisDetail = (axis: PreferenceAxisDef) => {
    const difficulty = axisDifficulties[axis.axisId];
    // 折れ点を通す前の生値。単位が定まらない軸（合成軸等）はbackendがrawValueUnitを
    // 返さないため何も出ない。
    const rawText = formatAxisRawValue(axisRawValues[axis.axisId], axis.rawValueUnit, distanceKm);
    // backendがmaterialBreakdownで並び順ごと返すため、ここでは並べ替えない。
    const breakdownTexts = (axis.materialBreakdown ?? [])
      .map((entry) =>
        entry.dtype === "categorical"
          ? formatCategoryBreakdown(entry, materialCategoryShares[entry.materialId])
          : formatMaterialBreakdown(entry, materialValues[entry.materialId])
      )
      .filter((text): text is string => text !== null);
    return (
      <>
        <span className={styles.detailHeading}>{axis.label}</span>
        <span className={styles.detailScore}>
          {/* 重みを掛ける前の、この軸単体の難易度。チップの数字（重み付き寄与度）とは別物。 */}
          {difficulty == null ? "データなし" : `軸別難易度 ${Math.round(difficulty)}/100`}
        </span>
        {rawText && <span className={styles.detailValue}>{rawText}</span>}
        {breakdownTexts.length > 0 && (
          <span className={styles.detailValue}>{`この軸の内訳: ${breakdownTexts.join("・")}`}</span>
        )}
        <span className={styles.detailDescription}>{axis.description}</span>
      </>
    );
  };

  const renderLeftoverChip = (axis: PreferenceAxisDef, showNoData: boolean) => (
    <li key={axis.axisId} className={styles.leftoverItem} data-unused={!showNoData}>
      <InfoPopover
        triggerClassName={styles.leftoverTrigger}
        triggerAriaLabel={`${axis.label}の詳細`}
        contentClassName={styles.infoPopover}
        triggerContent={
          <>
            <span aria-hidden="true" className={styles.legendDot} style={{ background: axisColors[axis.axisId] ?? FALLBACK_DOT_COLOR }} />
            <span>{axis.label}</span>
            {showNoData && <span className={styles.badge}>データなし</span>}
            <InfoIcon size={12} />
          </>
        }
      >
        {renderAxisDetail(axis)}
      </InfoPopover>
    </li>
  );

  return (
    <div className={styles.wrap}>
      {overallDifficulty != null && (
        <div className={styles.scores}>
          <span className={styles.scoreItem}>
            <span className={styles.scoreValue}>{Math.round(overallDifficulty)}</span>
            <span className={styles.scoreLabel}>/100 総合難易度</span>
            <InfoPopover
              triggerClassName={styles.infoButton}
              triggerAriaLabel="総合難易度の説明"
              contentClassName={styles.infoPopover}
            >
              <p>距離・軸重みを反映した絶対値（各候補の内訳の合計に近い値）です。候補タブはこの値が小さい順に並びます。</p>
            </InfoPopover>
          </span>
          {difficultyLoad != null && (
            <span className={styles.scoreItem}>
              <span className={styles.scoreValue}>{Math.round(difficultyLoad)}</span>
              <span className={styles.scoreLabel}>負荷（難易度×距離）</span>
              <InfoPopover
                triggerClassName={styles.infoButton}
                triggerAriaLabel="負荷の説明"
                contentClassName={styles.infoPopover}
              >
                <p>
                  総合難易度は距離で割った平均のため、遠回りして難所を避けるほど下がります。
                  負荷は距離を掛けた総量で、走り切るまでのしんどさの目安です。難所を通っても
                  短いルートと、遠回りで易しいルートを見比べるときに使ってください。
                </p>
              </InfoPopover>
            </span>
          )}
          {contributionRows.length > 0 ? (
            <AxisContributionBar
              axes={contributionRows}
              contributions={axisContributions}
              axisColors={axisColors}
              renderDetail={renderAxisDetail}
            />
          ) : (
            <p className={styles.empty}>このルートで表示できる評価軸データがありません</p>
          )}
        </div>
      )}
      {(valuelessAxes.length > 0 || unusedAxes.length > 0) && (
        <ul className={styles.leftovers} aria-label="寄与が出ていない軸">
          {valuelessAxes.map((axis) => renderLeftoverChip(axis, true))}
          {unusedAxes.length > 0 && (
            <li className={styles.leftoverItem}>
              <button
                type="button"
                className={styles.unusedToggle}
                aria-expanded={unusedOpen}
                onClick={() => setUnusedOpen((open) => !open)}
              >
                <span aria-hidden="true" className={styles.unusedChevron} data-open={unusedOpen} />
                {`未使用の軸 ${unusedAxes.length}本`}
              </button>
            </li>
          )}
          {unusedOpen && unusedAxes.map((axis) => renderLeftoverChip(axis, false))}
        </ul>
      )}
    </div>
  );
}
