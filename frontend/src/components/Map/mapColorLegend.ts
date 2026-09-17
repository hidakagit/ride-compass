// 地図上の色分け凡例の共通型・ラベル生成。
//
// 色分けを実際に塗る側（axisLayers.ts: buildAxisRampColorExpression・
// dedicatedWayValueLayer.ts: buildDedicatedWayValueColorExpression）とは別に、段階の
// ラベル・色・安定キーだけを持つ軽量な型。ramp軸の凡例（axisLayers.ts:
// buildAxisRampLegend）は▶パネル・MapOverlayControlsの絞り込み機構と共有する
// LegendEntry（MapLibreのfilter述語が必須）を返すが、専用way値配信軸の値は
// feature-state経由で入るためfilterでは絞り込めない（MapLibreのfilterはfeature-stateを
// 読めない）。段階の表示ON/OFFは色式側で透明にして実現する（valueScale.ts:
// buildSteppedColorExpression）ため、ここでは述語を持たないこの型を使う。

export interface MapColorLegendBand {
  /** 段階の安定識別子（表示ON/OFFの保存キー）。`legendBandKey`が唯一の出どころ。 */
  key: string;
  label: string;
  color: string;
  /** 「データなし」の受け皿段階（数値レンジを持たない）。 */
  isFallback?: boolean;
}

/** 段階の安定キー。**ルート確定前の全道路の塗りとルート確定後のルート線が同じ段階を同じ
 * キーで指す**ため、片方で非表示にした段階はもう片方でも非表示のまま引き継がれる
 * （どちらも同じ`map_value_thresholds`で同じ順に段階を並べる）。 */
export function legendBandKey(index: number): string {
  return `step-${index}`;
}

/** 値が無い地物（取得済みだが値が無い）の段階キー。数値段階と同じ仕組みで非表示にできる。 */
export const LEGEND_NO_DATA_KEY = "nodata";

/** 段階の体感ラベル（軸スタジオの`display_band_labels_override`）を、その段階数へ添えて
 * よいかの判定。ルート前（`dedicatedWayValueLegend`）とルート後（`routeStyleModes.ts`）が
 * 同じ規則で使うため1箇所に置く。
 *
 * 件数が段階数と合わないラベルは**添えずに捨てる**。合わない軸は実在し（地図が塗る値の
 * スケールへ境界を写すと、軸の折れ線が飽和する範囲に置かれた境界が同じ値へ潰れて段階が
 * 減る。backend `domain/dynamic_way_values.py: map_value_thresholds`）、ずらして添えると
 * 「最上位の段階のラベル」が実際にはそれより広い範囲を指す嘘になる。数値レンジだけの方が
 * 読み手を誤らせない。 */
export function bandLabelsForBandCount(
  labels: readonly string[] | null | undefined,
  bandCount: number,
): readonly string[] | undefined {
  if (!labels || labels.length !== bandCount) return undefined;
  return labels;
}

/** 段階ラベル（例: 「-2%未満」「-2〜2%」「10%以上」）。axisLayers.ts: axisRampBandLabelと
 * 同じ表記規則（未満/以上/〜）を、RampAxis型に依存せずunit文字列を直接受け取る形で
 * 共有する。 */
function rangeStepLabel(lower: number | null, upper: number | null, unit: string): string {
  if (lower === null) return `${upper}${unit}未満`;
  if (upper === null) return `${lower}${unit}以上`;
  return `${lower}〜${upper}${unit}`;
}

/** boundaries（昇順のしきい値配列、要素数=段階数-1）とcolors（段階数ぶん）から、
 * rangeStepLabelでラベル付けした凡例段階を組み立てる共通ロジック。dedicatedWayValueLayer.ts（風・勾配共通）が同じ「しきい値配列→段階ラベル+色」変換を必要とするため
 * ここへ集約する（定数・変換ロジックの片側import）。
 *
 * `labels`（省略可、colors.length件）を渡すと、数値レンジ表記の前に体感ラベルを添える
 * （例:「強い向かい風（2〜6m/s）」）。渡さない場合は数値レンジ表記のみ。
 * `windLayer.ts: WIND_SPEED_LEGEND_LEVELS`・`precipitationNowcast.ts:
 * PRECIPITATION_INTENSITY_LEVELS`と違い色は手打ちにしない（呼び出し側が既存の
 * rampColorForBand自動生成をそのまま使う。色指定機能は持たない設計）。 */
export function buildRangeLegendBands(
  boundaries: readonly number[],
  colors: readonly string[],
  unit: string,
  labels?: readonly string[],
): MapColorLegendBand[] {
  return colors.map((color, index) => {
    const lower = index === 0 ? null : boundaries[index - 1];
    const upper = index === boundaries.length ? null : boundaries[index];
    const rangeLabel = rangeStepLabel(lower, upper, unit);
    const label = labels ? `${labels[index]}（${rangeLabel}）` : rangeLabel;
    return { key: legendBandKey(index), label, color };
  });
}
