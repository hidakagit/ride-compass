"use client";

import InfoPopover from "@/components/Map/InfoPopover";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights } from "@/types/route";
import AxisContributionBar from "./AxisContributionBar";
import legendStyles from "@/components/RouteSettingsPanel/RouteSettingsPanel.module.css";
import styles from "./RouteAxisProfile.module.css";

interface RouteAxisProfileProps {
  /** 公開軸すべて（軸カタログの順序・ラベルの正本）。重みによる絞り込みは行わない。 */
  axes: readonly PreferenceAxisDef[];
  /** この候補を実際に評価した重み（生成時点のroute_preference）。0の軸は「未使用」として残す。 */
  weights: RoutePreferenceWeights;
  /** RouteCandidate.axis_difficulties（axis_id→距離加重平均の難易度0-100）。評価できなかった
   * 軸はキー自体を持たない。 */
  axisDifficulties: Record<string, number>;
  /** RouteCandidate.axis_contributions（axis_id→重み付き寄与度0-100、合計はoverallDifficultyと
   * 一致する）。重み0の軸は寄与を持たない。 */
  axisContributions: Record<string, number>;
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

// ルート結果の「総合難易度＋重み付き寄与度の積み上げバー」と「軸別難易度の一覧」を表示する
// 読み取り専用の部品。地図の色分け（レンズ）の選択はここでは行わない（入口は地図上の凡例
// ピル`LensControl`だけ）。評価に使っていない軸（重み0）も「未使用」として一覧に残す
// （消さずに薄くする）。
export default function RouteAxisProfile({
  axes,
  weights,
  axisDifficulties,
  axisContributions,
  overallDifficulty,
  difficultyLoad,
  axisColors,
}: RouteAxisProfileProps) {
  const contributionRows = axes.filter((axis) => axisContributions[axis.axisId] != null);

  return (
    <div className={styles.wrap}>
      {overallDifficulty != null && (
        <div className={styles.scores}>
          <span className={styles.scoreItem}>
            <span className={styles.scoreValue}>{Math.round(overallDifficulty)}</span>
            <span className={styles.scoreLabel}>/100 総合難易度</span>
          </span>
          {difficultyLoad != null && (
            <span className={styles.scoreItem}>
              <span className={styles.scoreValue}>{Math.round(difficultyLoad)}</span>
              <span className={styles.scoreLabel}>負荷（難易度×距離）</span>
              <InfoPopover
                triggerClassName={legendStyles.legendInfoButton}
                triggerAriaLabel="負荷の説明を表示"
                contentClassName={legendStyles.legendInfoPopover}
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
            <AxisContributionBar axes={contributionRows} contributions={axisContributions} axisColors={axisColors} />
          ) : (
            <p className={styles.empty}>このルートで表示できる評価軸データがありません</p>
          )}
        </div>
      )}
      <ul className={styles.axisList} aria-label="軸別難易度">
        {axes.map((axis) => {
          const unused = (weights[axis.axisId] ?? 0) <= 0;
          const difficulty = axisDifficulties[axis.axisId];
          return (
            <li key={axis.axisId} className={styles.axisRow} data-unused={unused}>
              <span aria-hidden="true" className={legendStyles.legendDot} style={{ background: axisColors[axis.axisId] ?? FALLBACK_DOT_COLOR }} />
              <span className={styles.axisLabel}>{axis.label}</span>
              {unused && <span className={styles.badge}>未使用</span>}
              {difficulty == null && <span className={styles.badge}>データなし</span>}
              <InfoPopover
                triggerClassName={legendStyles.legendInfoButton}
                triggerAriaLabel={`${axis.label}の説明を表示`}
                contentClassName={legendStyles.legendInfoPopover}
              >
                {axis.description}
              </InfoPopover>
              <span className={styles.axisValue}>{difficulty == null ? "—" : Math.round(difficulty)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
