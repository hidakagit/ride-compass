"use client";

import InfoPopover from "@/components/Map/InfoPopover";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import type { RoutePreferenceWeights } from "@/types/route";
import AxisContributionBar from "./AxisContributionBar";
import {
  DEFAULT_BREAKDOWN_VISIBLE,
  formatAxisRawValue,
  formatMaterialBreakdown,
} from "./axisRawValue";
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

// ルート結果の「総合難易度＋重み付き寄与度の積み上げバー」と「軸別難易度の一覧」を表示する
// 読み取り専用の部品。地図の色分け（レンズ）の選択はここでは行わない（入口は地図上の凡例
// ピル`LensControl`だけ）。評価に使っていない軸（重み0）も「未使用」として一覧に残す
// （消さずに薄くする）。
export default function RouteAxisProfile({
  axes,
  weights,
  axisRawValues,
  materialValues,
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
          // 得点の隣に、折れ点を通す前の生値を単位付きで添える。単位が定まらない軸
          // （合成軸等）はbackendがrawValueUnitを返さないため何も出ない。
          const rawText = formatAxisRawValue(axisRawValues[axis.axisId], axis.rawValueUnit, distanceKm);
          // 単位が定まらない軸は、材料まで分解した内訳を代わりに出す（backendが
          // materialBreakdownで並び順ごと返すため、ここでは並べ替えない）。行数を増やさない
          // よう既定は先頭2件までで、残りは軸の説明ポップオーバーへ回す。
          const breakdownTexts = (axis.materialBreakdown ?? [])
            .map((entry) => formatMaterialBreakdown(entry, materialValues[entry.materialId]))
            .filter((text): text is string => text !== null);
          const visibleBreakdown = breakdownTexts.slice(0, DEFAULT_BREAKDOWN_VISIBLE);
          const hiddenBreakdown = breakdownTexts.slice(DEFAULT_BREAKDOWN_VISIBLE);
          return (
            <li key={axis.axisId} className={styles.axisRow} data-unused={unused}>
              <span aria-hidden="true" className={styles.legendDot} style={{ background: axisColors[axis.axisId] ?? FALLBACK_DOT_COLOR }} />
              {/* ラベルとバッジは1つの列に入れる（列を軸をまたいで揃えるため、行ではなく
                  一覧側がグリッドになっている。RouteAxisProfile.module.css参照）。 */}
              <span className={styles.axisLabel}>
                <span className={styles.axisLabelText} title={axis.label}>
                  {axis.label}
                </span>
                {unused && <span className={styles.badge}>未使用</span>}
                {difficulty == null && <span className={styles.badge}>データなし</span>}
              </span>
              <InfoPopover
                triggerClassName={styles.infoButton}
                triggerAriaLabel={`${axis.label}の説明`}
                contentClassName={styles.infoPopover}
              >
                {axis.description}
                {hiddenBreakdown.length > 0 && (
                  <span className={styles.infoBreakdown}>{`この軸の内訳（続き）: ${hiddenBreakdown.join("・")}`}</span>
                )}
              </InfoPopover>
              <span className={styles.axisValue}>{difficulty == null ? "—" : Math.round(difficulty)}</span>
              {/* 生値は行の2段目（値のある軸だけ）。1段目の列を占めないため軸名が省略されず、
                  右端で揃うので軸をまたいで読み比べられる。 */}
              {rawText && <span className={styles.axisRawValue}>{rawText}</span>}
              {!rawText && visibleBreakdown.length > 0 && (
                <span className={styles.axisRawValue}>{visibleBreakdown.join("・")}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
