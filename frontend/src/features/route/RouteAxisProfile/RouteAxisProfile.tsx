"use client";

import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { formatDurationShort } from "@/features/route/formatDuration";
import type { RoutePreferenceWeights } from "@/types/route";
import AxisContributionBar, { hasContribution } from "@/components/AxisContributionBar/AxisContributionBar";
import { formatAxisRawValue, formatCategoryBreakdown, formatMaterialBreakdown } from "./axisRawValue";
import { textVariants } from "@/components/ui/Text/Text";

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
  /** 内訳バーの高さの倍率（`features/route/difficultyLoadBar.ts: loadBarHeightRatio`、一覧の中で
   * 最も短い候補を1.0とする距離の比）。バーの長さが総合難易度を表すため、高さへ距離を
   * 与えると塗られた面積がdifficultyLoadになる。 */
  loadBarHeightRatio: number;
  /** RouteCandidate.estimated_duration_seconds（走行＋停止＋ターンの見積もり）。 */
  estimatedDurationSeconds: number | null;
  /** 軸id→色ドットの色（ルート設定パネルの凡例チップと同じ色）。 */
  axisColors: Record<string, string>;
}

/** ルート結果の総合難易度と、重み付きの寄与の積み上げの帯（読むだけ）。軸ごとの詳細は一覧を作らず、帯の凡例の
 * チップを押して開く。レンズはここでは選ばない（入口は地図の上のピルだけ）。 */
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
  loadBarHeightRatio,
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
    const rawText = formatAxisRawValue(
      axisRawValues[axis.axisId],
      axis.rawValueUnit,
      axis.rawValueTotalUnit,
      distanceKm,
    );
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
        <span className="block font-medium">{axis.label}</span>
        <span className="mt-1 block tabular-nums">
          {/* 重みを掛ける前の、この軸単体の難易度。チップの数字（重み付き寄与度）とは別物。 */}
          {difficulty == null ? "データなし" : `軸別難易度 ${Math.round(difficulty)}/100`}
        </span>
        {rawText && <span className="block text-[var(--color-muted-strong)] tabular-nums">{rawText}</span>}
        {breakdownTexts.length > 0 && (
          <span className="block text-[var(--color-muted-strong)] tabular-nums">{`この軸の内訳: ${breakdownTexts.join("・")}`}</span>
        )}
        <span className="mt-2 block text-[var(--color-muted)]">{axis.description}</span>
      </>
    );
  };

  return (
    <div className="flex flex-col">
      {overallDifficulty != null && (
        <div className="mx-0.5 mt-0.5 mb-1 flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <span className="inline-flex flex-shrink-0 items-baseline gap-0.5">
            <span className={textVariants({ variant: "hint" })}>総合難易度</span>
            <span className="text-[1.05rem] font-semibold">{Math.round(overallDifficulty)}</span>
            <span className={textVariants({ variant: "hint" })}>/100</span>
            <InfoPopover triggerAriaLabel="総合難易度の説明">
              <p>
                区間ごとの難しさを距離で重みづけて平均した値です。長く走っても難しさが同じなら増えません。
                軸の重み配分を反映していて、下の内訳の合計とほぼ一致します。候補タブはこの値が小さい順に並びます。
              </p>
            </InfoPopover>
          </span>
          {estimatedDurationSeconds != null && (
            <span className="inline-flex flex-shrink-0 items-baseline gap-0.5">
              <span className={textVariants({ variant: "hint" })}>所要</span>
              <span className="text-[1.05rem] font-semibold">{formatDurationShort(estimatedDurationSeconds)}</span>
              <InfoPopover triggerAriaLabel="所要時間の説明">
                <p>
                  走行時間（勾配・風・想定した巡航速度から区間ごとに計算）に、信号などで止まる
                  待ちと、交差点で曲がる待ちを足した見積もりです。実際の信号のタイミングや 走り方で変わります。
                </p>
              </InfoPopover>
            </span>
          )}
          {difficultyLoad != null && (
            <span className="inline-flex flex-shrink-0 items-baseline gap-0.5">
              {/* 「難易度×距離」という中身は説明（ⓘ）が持つ。狭い右カラムで折り返す
                  ぶんだけ縦を食うため、見出しは短い語に留める。 */}
              <span className={textVariants({ variant: "hint" })}>負荷</span>
              <span className="text-[1.05rem] font-semibold">{Math.round(difficultyLoad)}</span>
              <InfoPopover triggerAriaLabel="負荷の説明">
                <p>
                  総合難易度に距離を掛けた総量で、走り切るまでのしんどさの目安です。
                  平均は遠回りして難所を避けるほど下がりますが、負荷は走った分だけ増えます。
                  難所を通っても短いルートと、遠回りで易しいルートを見比べるときに使ってください。
                </p>
                <p>
                  下のバーは長さが総合難易度、高さが距離で、塗られた面積がこの負荷にあたります
                  （色ごとの面積がその軸の負荷）。候補一覧の行のバーも同じ見方です。距離の差が
                  大きいときは高さに上限をかけるため、面積の比は負荷の比と完全には一致しません。
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
              heightRatio={loadBarHeightRatio}
              renderDetail={renderAxisDetail}
            />
          ) : (
            <p className={textVariants({ variant: "hint" })}>このルートで表示できる評価軸データがありません</p>
          )}
        </div>
      )}
    </div>
  );
}
