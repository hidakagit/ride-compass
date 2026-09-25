// 地図の色分けの凡例の段（ラベル・色・安定キーだけ）と、段の範囲の書き方。専用配信の軸の値はfeature-stateで入り、
// MapLibreのfilterはfeature-stateを読めないため、段の表示ON/OFFは色の式の側で透明にする——そのため述語を持たない。

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

/** 段の体感ラベルを、その段の数へ添えてよいか。地図の段に合わせてラベルを引き直すのはbackendで、件数が合わない
 * ラベルは**添えずに捨てる**（ずらして添えると、ラベルが実際より広い範囲を指す嘘になる）。 */
export function bandLabelsForBandCount(
  labels: readonly string[] | null | undefined,
  bandCount: number,
): readonly string[] | undefined {
  if (!labels || labels.length !== bandCount) return undefined;
  return labels;
}

/** 段の範囲の文字（例: 「-2%未満」「-2〜2%」「10%以上」）。**段の範囲を文字にするのはここだけ**。語は述語に合わせる
 * （境界の判定は`>= lower`・`< upper`なので、最上位は「超」ではなく「以上」）。境界が無ければ空文字。 */
export function rangeStepLabel(lower: number | null, upper: number | null, unit: string): string {
  if (lower === null && upper === null) return "";
  if (lower === null) return `${upper}${unit}未満`;
  if (upper === null) return `${lower}${unit}以上`;
  return `${lower}〜${upper}${unit}`;
}

/** 境界（昇順、段の数−1件）と色（段の数ぶん）から凡例の段を組む。`labels`（段の数ぶん）を渡すと、範囲の前に体感ラベル
 * を添える（例:「強い向かい風（2〜6m/s）」）。 */
export function buildRangeLegendBands(
  boundaries: readonly number[],
  colors: readonly string[],
  unit: string,
  labels?: readonly string[],
): MapColorLegendBand[] {
  return colors.map((color, index) => {
    // 境界が段の数に足りなくても、無い端は「無い」として扱う（「undefined〜」を出さない）。
    const lower = index === 0 ? null : (boundaries[index - 1] ?? null);
    const upper = index >= boundaries.length ? null : (boundaries[index] ?? null);
    const rangeLabel = rangeStepLabel(lower, upper, unit);
    const label = labels ? `${labels[index]}（${rangeLabel}）` : rangeLabel;
    return { key: legendBandKey(index), label, color };
  });
}
