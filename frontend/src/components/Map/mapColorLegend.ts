// 地図上の色分け凡例（ユーザー要望2026-08-31、「地図上の色付の凡例が欲しい。例えば、勾配ON
// にした時に青くなる道路は何なのか、その度合いが分かればいい」）の共通型・ラベル生成。
//
// 色分けを実際に塗る側（axisLayers.ts: buildAxisRampColorExpression・
// windAxisLayer.ts: buildWindPenaltyColorExpression・gradientAxisLayer.ts:
// buildGradientColorExpression）とは別に、この凡例は「今どう塗られているか」を
// 読み手（LegendEntryのfilter述語によるカテゴリ絞り込み）ではなく見せるためだけの
// 軽量な型を持つ。ramp軸の凡例（axisLayers.ts: buildAxisRampLegend）はMapLayersPanel・
// MapOverlayControlsの絞り込み機構と共有するLegendEntry（filter必須）を返すが、
// windAxis/gradientAxisにはそのような絞り込み機構自体が無いため、意味の無いfilterを
// 捏造せずに済むこの専用の軽量型を使う。

export interface MapColorLegendBand {
  label: string;
  color: string;
}

/** 段階ラベル（例: 「-2%未満」「-2〜2%」「10%以上」）。axisLayers.ts: axisRampBandLabelと
 * 同じ表記規則（未満/以上/〜）を、RampAxis型に依存せずunit文字列を直接受け取る形で
 * 共有する。 */
export function rangeStepLabel(lower: number | null, upper: number | null, unit: string): string {
  if (lower === null) return `${upper}${unit}未満`;
  if (upper === null) return `${lower}${unit}以上`;
  return `${lower}〜${upper}${unit}`;
}

/** boundaries（昇順のしきい値配列、要素数=段階数-1）とcolors（段階数ぶん）から、
 * rangeStepLabelでラベル付けした凡例段階を組み立てる共通ロジック。gradientAxisLayer.ts・
 * windAxisLayer.tsの両方が同じ「しきい値配列→段階ラベル+色」変換を必要とするため
 * ここへ集約する（設計原則2: 定数・変換ロジックの片側import）。
 *
 * ユーザー要望（2026-08-31「降水のように体感で分かる凡例ラベルを付けたい（色の指定は不要）」）:
 * `labels`（省略可、colors.length件）を渡すと、数値レンジ表記の前に体感ラベルを添える
 * （例:「強い向かい風（2〜6m/s）」）。渡さない場合は従来どおり数値レンジ表記のみ。
 * `windLayer.ts: WIND_SPEED_LEGEND_LEVELS`・`precipitationNowcast.ts:
 * PRECIPITATION_INTENSITY_LEVELS`と違い色は手打ちにしない（呼び出し側が既存の
 * rampColorForBand自動生成をそのまま使う）——ユーザー指示により色指定機能は追加しない。 */
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
