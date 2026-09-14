"use client";

import InfoPopover from "@/components/Map/InfoPopover";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { formatDurationShort } from "@/lib/formatDuration";
import type { RoutePreferenceWeights } from "@/types/route";
import AxisContributionBar, { hasContribution } from "./AxisContributionBar";
import { formatAxisRawValue, formatCategoryBreakdown, formatMaterialBreakdown } from "./axisRawValue";
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
  /** RouteCandidate.estimated_duration_seconds（走行＋停止＋ターンの見積もり）。 */
  estimatedDurationSeconds: number | null;
  /** 軸id→色ドットの色（ルート設定パネルの凡例チップと同じ色）。 */
  axisColors: Record<string, string>;
}

// ルート結果の「総合難易度＋重み付き寄与度の積み上げバー」を表示する読み取り専用の部品。
// 軸ごとの詳細（軸別難易度・生値・材料内訳・説明）は一覧を作らず、バーの凡例チップを
// 押して開く。地図の色分け（レンズ）の選択はここでは行わない（入口は地図上の凡例ピル
// `LensControl`だけ）。チップはルート設定パネルの「重み配分」と同じ形で、評価に使って
// いない軸（重み0）は押せない薄いチップとして残す（消さずに薄くする）。
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
  estimatedDurationSeconds,
  axisColors,
}: RouteAxisProfileProps) {
  const contributionRows = axes.filter((axis) => hasContribution(axisContributions, axis.axisId));

  // 評価に使っていない軸（重み0）はnullを返し、AxisContributionBarの凡例から落とす。
  // 内訳は候補ごとに縦へ伸びるため、使っていない軸まで並べると狭い幅で「このルートで
  // 何が効いたか」が読めなくなる（設計原則「消さずに薄くする」の例外）。
  const renderAxisDetail = (axis: PreferenceAxisDef) => {
    if ((weights[axis.axisId] ?? 0) <= 0) return null;
    const difficulty = axisDifficulties[axis.axisId];
    // 折れ点を通す前の生値。単位が定まらない軸（合成軸等）はbackendがrawValueUnitを
    // 返さないため何も出ない。
    const rawText = formatAxisRawValue(axisRawValues[axis.axisId], axis.rawValueUnit, distanceKm);
    // backendがmaterialBreakdownで並び順ごと返すため、ここでは並べ替えない。
    const breakdownTexts = (axis.materialBreakdown ?? [])
      .map((entry) =>
        entry.dtype === "categorical"
          ? formatCategoryBreakdown(entry, materialCategoryShares[entry.materialId])
          : formatMaterialBreakdown(entry, materialValues[entry.materialId]),
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

  return (
    <div className={styles.wrap}>
      {overallDifficulty != null && (
        <div className={styles.scores}>
          <span className={styles.scoreItem}>
            <span className={styles.scoreLabel}>総合難易度</span>
            <span className={styles.scoreValue}>{Math.round(overallDifficulty)}</span>
            <span className={styles.scoreLabel}>/100</span>
            <InfoPopover
              triggerClassName={styles.infoButton}
              triggerAriaLabel="総合難易度の説明"
              contentClassName={styles.infoPopover}
            >
              <p>
                距離・軸重みを反映した絶対値（各候補の内訳の合計に近い値）です。候補タブはこの値が小さい順に並びます。
              </p>
            </InfoPopover>
          </span>
          {estimatedDurationSeconds != null && (
            <span className={styles.scoreItem}>
              <span className={styles.scoreLabel}>所要</span>
              <span className={styles.scoreValue}>{formatDurationShort(estimatedDurationSeconds)}</span>
              <InfoPopover
                triggerClassName={styles.infoButton}
                triggerAriaLabel="所要時間の説明"
                contentClassName={styles.infoPopover}
              >
                <p>
                  走行時間（勾配・風・想定した巡航速度から区間ごとに計算）に、信号などで止まる
                  待ちと、交差点で曲がる待ちを足した見積もりです。実際の信号のタイミングや 走り方で変わります。
                </p>
              </InfoPopover>
            </span>
          )}
          {difficultyLoad != null && (
            <span className={styles.scoreItem}>
              {/* 「難易度×距離」という中身は説明（ⓘ）が持つ。狭い右カラムで折り返す
                  ぶんだけ縦を食うため、見出しは短い語に留める。 */}
              <span className={styles.scoreLabel}>負荷</span>
              <span className={styles.scoreValue}>{Math.round(difficultyLoad)}</span>
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
              legendAxes={axes}
              contributions={axisContributions}
              axisColors={axisColors}
              renderDetail={renderAxisDetail}
            />
          ) : (
            <p className={styles.empty}>このルートで表示できる評価軸データがありません</p>
          )}
        </div>
      )}
    </div>
  );
}
