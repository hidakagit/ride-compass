// 地図上の色分け凡例の共通型・ラベル生成。
//
// 色分けを実際に塗る側（axisLayers.ts: buildAxisRampColorExpression・
// dedicatedWayValueLayer.ts: buildDedicatedWayValueColorExpression）とは別に、この凡例は「今どう塗られているか」を
// 読み手（LegendEntryのfilter述語によるカテゴリ絞り込み）ではなく見せるためだけの
// 軽量な型を持つ。ramp軸の凡例（axisLayers.ts: buildAxisRampLegend）はMapLayersPanel・
// MapOverlayControlsの絞り込み機構と共有するLegendEntry（filter必須）を返すが、
// 専用way値配信軸にはそのような絞り込み機構自体が無いため、意味の無いfilterを
// 捏造せずに済むこの専用の軽量型を使う。

export interface MapColorLegendBand {
  label: string;
  color: string;
}

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
  bandCount: number
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
  labels?: readonly string[]
): MapColorLegendBand[] {
  return colors.map((color, index) => {
    const lower = index === 0 ? null : boundaries[index - 1];
    const upper = index === boundaries.length ? null : boundaries[index];
    const rangeLabel = rangeStepLabel(lower, upper, unit);
    const label = labels ? `${labels[index]}（${rangeLabel}）` : rangeLabel;
    return { label, color };
  });
}
