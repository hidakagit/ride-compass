// 折れ点(breakpoints)編集の省力化（自動生成・効き目プレビュー・エディタの補助計算）を
// AxisComposer.tsxから切り出した純粋関数群。DOM/Reactに依存しない（BreakpointCurveEditor.
// test.tsxが単体で検証できるようにする、他のlib/*.ts純粋関数と同じ方針）。

export type BreakpointShape = "flat" | "back_loaded" | "front_loaded" | "s_curve";

export const BREAKPOINT_SHAPE_OPTIONS: readonly { id: BreakpointShape; label: string }[] = [
  { id: "flat", label: "一定" },
  { id: "back_loaded", label: "後半で急" },
  { id: "front_loaded", label: "前半で急" },
  { id: "s_curve", label: "S字" },
];

// t(0〜1)→スコア(0〜100)の形。いずれもt=0で0・t=1で100になる（範囲の両端は必ず折れ点の
// 両端と一致する）。
function shapeScoreAt(shape: BreakpointShape, t: number): number {
  switch (shape) {
    case "flat":
      return 100 * t;
    case "back_loaded":
      // 後半（tの大きい側）ほど傾きが急＝前半はゆるやかに増える下に凸の曲線。
      return 100 * t * t;
    case "front_loaded":
      // 前半ほど傾きが急＝後半はゆるやかに増える上に凸の曲線。
      return 100 * (1 - (1 - t) * (1 - t));
    case "s_curve":
      // smoothstep（3t^2-2t^3）。両端付近はゆるやか、中央付近が最も急。
      return 100 * (3 * t * t - 2 * t * t * t);
  }
}

const GENERATED_POINT_COUNT = 6;

/** 「0点にする値」「100点にする値」「形」の3入力から折れ点を生成する。0点=zeroValue・
 * 100点=hundredValueの間をGENERATED_POINT_COUNT点（5〜7点の範囲内）で均等分割し、
 * 各点のスコアをshapeの形に従って決める。zeroValue > hundredValue（値が大きいほど
 * 走りやすい軸、例: 制限速度は高いほど易しい）も入力として許容するため、生成後に必ず
 * x昇順へ並べ替える（backend: evaluate_breakpoint_linearが前提とする不変条件）。 */
export function generateBreakpoints(zeroValue: number, hundredValue: number, shape: BreakpointShape): [number, number][] {
  const points: [number, number][] = [];
  for (let i = 0; i < GENERATED_POINT_COUNT; i++) {
    const t = i / (GENERATED_POINT_COUNT - 1);
    const x = zeroValue + t * (hundredValue - zeroValue);
    const y = shapeScoreAt(shape, t);
    points.push([Math.round(x * 100) / 100, Math.round(y)]);
  }
  return sortBreakpoints(points);
}

/** 折れ点をx昇順へ並べ替える（ドラッグ・数値入力・自動生成のいずれの後も呼ぶ）。 */
export function sortBreakpoints(breakpoints: readonly [number, number][]): [number, number][] {
  return [...breakpoints].sort((a, b) => a[0] - b[0]);
}

/** 区分線形補間（backend: domain/axis_templates.py: evaluate_breakpoint_linearと同じ
 * np.interpの仕様——両端でクランプ、xは昇順前提）をfrontendで再現する。効き目プレビュー表が
 * 実際にbackendが返す値と一致するようにするため、丸め（小数1桁）も含めて揃える。 */
export function interpolateBreakpointScore(breakpoints: readonly [number, number][], x: number): number {
  const sorted = sortBreakpoints(breakpoints);
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  if (x <= first[0]) return first[1];
  if (x >= last[0]) return last[1];
  for (let i = 0; i < sorted.length - 1; i++) {
    const [x0, y0] = sorted[i];
    const [x1, y1] = sorted[i + 1];
    if (x >= x0 && x <= x1) {
      if (x1 === x0) return Math.round(y0 * 10) / 10;
      const t = (x - x0) / (x1 - x0);
      return Math.round((y0 + t * (y1 - y0)) * 10) / 10;
    }
  }
  return Math.round(last[1] * 10) / 10;
}

/** 「+ 折れ点を追加」の挿入位置。隣接点どうしのx方向の間隔が最も広い区間の中間へ挿入する
 * （末尾へ既定値[0,0]を足すだけの旧実装は、既存の折れ点より横軸が小さい点を足してしまい
 * 昇順制約に即座に違反していた）。点が1つ以下では追加できないため呼び出し側で
 * length>=2を保証すること。 */
export function insertBreakpointAtLargestGap(breakpoints: readonly [number, number][]): [number, number][] {
  const sorted = sortBreakpoints(breakpoints);
  let gapIndex = 0;
  let widestGap = -Infinity;
  for (let i = 0; i < sorted.length - 1; i++) {
    const gap = sorted[i + 1][0] - sorted[i][0];
    if (gap > widestGap) {
      widestGap = gap;
      gapIndex = i;
    }
  }
  const [x0, y0] = sorted[gapIndex];
  const [x1, y1] = sorted[gapIndex + 1];
  const midpoint: [number, number] = [Math.round(((x0 + x1) / 2) * 100) / 100, Math.round((y0 + y1) / 2)];
  const next = [...sorted];
  next.splice(gapIndex + 1, 0, midpoint);
  return next;
}

/** ドラッグ中のx方向のスナップ刻み幅。軸の表示レンジ（span）に対して「きりのいい」
 * 1/2/5×10^nの中から、span/snapDivisions個の目盛りに最も近いものを選ぶ（グラフの目盛り
 * 間隔でよく使われる手法）。 */
export function niceStep(span: number, snapDivisions = 20): number {
  if (!Number.isFinite(span) || span <= 0) return 1;
  const roughStep = span / snapDivisions;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const normalized = roughStep / magnitude;
  const niceNormalized = normalized < 1.5 ? 1 : normalized < 3.5 ? 2 : normalized < 7.5 ? 5 : 10;
  return niceNormalized * magnitude;
}

/** valueをstep刻みへ丸める。 */
export function snapToStep(value: number, step: number): number {
  if (step <= 0) return value;
  return Math.round(value / step) * step;
}
