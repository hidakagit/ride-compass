// 地図上の色分け凡例の共通型・ラベル生成。
//
// 色分けを実際に塗る側（`features/map/scene/groups/axisLines.ts`）とは別に、段階の
// ラベル・色・安定キーだけを持つ軽量な型。ramp軸の凡例（axisLayers.ts:
// buildAxisRampLegend）は▶パネル・MapOverlayControlsの絞り込み機構と共有する
// LegendEntry（MapLibreのfilter述語が必須）を返すが、専用way値配信軸の値は
// feature-state経由で入るためfilterでは絞り込めない（MapLibreのfilterはfeature-stateを
// 読めない）。段階の表示ON/OFFは色式側で透明にして実現するため、ここでは述語を持たない
// この型を使う。

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

/** 段階ラベル（例: 「-2%未満」「-2〜2%」「10%以上」）。**段階の範囲を文字にするのは
 * ここだけ**——同じ表記規則を各所で書き直すと、片方だけが述語とずれる（実際、ルート線側
 * だけが最上位帯を「超」と書き、ちょうど境界値の区間がその行で数えられていた）。
 *
 * 語は述語に合わせる。境界の判定は`>= lower`・`< upper`のため、最上位帯は「以上」で
 * あって「超」ではない。
 *
 * 段階が1つしか無い（境界が無い）軸は範囲を言えないため空文字を返す。 */
export function rangeStepLabel(lower: number | null, upper: number | null, unit: string): string {
  if (lower === null && upper === null) return "";
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
    // 境界が段階数に足りない組み合わせでも、無い端は「無い」として扱う（`??`）。
    // 添字で引いた`undefined`をそのまま文字にすると「undefined〜undefined%」という
    // 読めないラベルが凡例に出る——範囲を言えないなら、言わない方が読み手を誤らせない。
    const lower = index === 0 ? null : (boundaries[index - 1] ?? null);
    const upper = index >= boundaries.length ? null : (boundaries[index] ?? null);
    const rangeLabel = rangeStepLabel(lower, upper, unit);
    const label = labels ? `${labels[index]}（${rangeLabel}）` : rangeLabel;
    return { key: legendBandKey(index), label, color };
  });
}
