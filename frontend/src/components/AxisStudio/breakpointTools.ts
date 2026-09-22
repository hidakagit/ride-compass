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
export function generateBreakpoints(
  zeroValue: number,
  hundredValue: number,
  shape: BreakpointShape,
): [number, number][] {
  const points: [number, number][] = [];
  for (let i = 0; i < GENERATED_POINT_COUNT; i++) {
    const t = i / (GENERATED_POINT_COUNT - 1);
    const x = zeroValue + t * (hundredValue - zeroValue);
    const y = shapeScoreAt(shape, t);
    points.push([Math.round(x * 100) / 100, Math.round(y)]);
  }
  return sortBreakpoints(points);
}

/** いまの折れ点から、自動生成フォームの3入力（0点・100点・効き方）を復元する。
 *
 * 生成フォームは**使い捨ての入力欄ではない**——`draft.breakpoints`と別に固定の初期値を
 * 持たせると、既存の軸を開いたときに入力欄がその軸と無関係な値（0と10）を表示し、
 * どれか1つに触れた瞬間にその値で折れ点が作り直される。較正済みの端点が黙って消えるため、
 * 入力欄は必ずいまの折れ点から導く。
 *
 * `matched`は「いまの折れ点が、この3入力から生成したものとぴったり一致するか」。
 * falseなら手で編集された（あるいは別の手順で作られた）折れ点で、効き方は復元できない
 * ——そのときも端点だけは正しく復元し、効き方は`flat`を初期値にする。 */
export function generatorSettingsFrom(breakpoints: readonly [number, number][]): {
  zeroValue: number;
  hundredValue: number;
  shape: BreakpointShape;
  matched: boolean;
} {
  const sorted = sortBreakpoints(breakpoints);
  if (sorted.length < 2) {
    return { zeroValue: 0, hundredValue: 10, shape: "flat", matched: false };
  }
  const lowX = sorted[0][0];
  const highX = sorted[sorted.length - 1][0];
  // 生成した折れ点と総当たりで突き合わせる。向きは2通り（値が大きいほど点数が高い軸と、
  // 低いほど高い軸）あり、どちらが0点側かは折れ点そのものからしか分からない。
  for (const { id } of BREAKPOINT_SHAPE_OPTIONS) {
    for (const [zeroValue, hundredValue] of [[lowX, highX], [highX, lowX]] as const) {
      const candidate = generateBreakpoints(zeroValue, hundredValue, id);
      if (candidate.length !== sorted.length) continue;
      if (candidate.every(([x, y], i) => x === sorted[i][0] && y === sorted[i][1])) {
        return { zeroValue, hundredValue, shape: id, matched: true };
      }
    }
  }
  // 一致しない＝手で編集された折れ点。端点は「点数が低い側が0点」として復元する。
  const zeroSide = sorted[0][1] <= sorted[sorted.length - 1][1] ? 0 : sorted.length - 1;
  return {
    zeroValue: sorted[zeroSide][0],
    hundredValue: sorted[zeroSide === 0 ? sorted.length - 1 : 0][0],
    shape: "flat",
    matched: false,
  };
}

/** 折れ点をx昇順へ並べ替える（ドラッグ・数値入力・自動生成のいずれの後も呼ぶ）。 */
function sortBreakpoints(breakpoints: readonly [number, number][]): [number, number][] {
  return [...breakpoints].sort((a, b) => a[0] - b[0]);
}

/** 区分線形補間（backend: domain/axis_templates.py: evaluate_breakpoint_linearと同じ
 * np.interpの仕様——両端でクランプ、xは昇順前提）。**丸めない**。
 *
 * 同じxを持つ折れ点が並んだときは後ろのyを返す（np.interpと同じ。前のyを返す実装が別に
 * あると、同じ折れ点を与えた画面どうしで値が食い違う）。 */
export function breakpointScore(breakpoints: readonly [number, number][], x: number): number {
  if (breakpoints.length === 0) return 0;
  const sorted = sortBreakpoints(breakpoints);
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  if (x <= first[0]) return first[1];
  if (x >= last[0]) return last[1];
  for (let i = 0; i < sorted.length - 1; i++) {
    const [x0, y0] = sorted[i];
    const [x1, y1] = sorted[i + 1];
    if (x >= x0 && x <= x1) {
      if (x1 === x0) return y1;
      return y0 + ((x - x0) / (x1 - x0)) * (y1 - y0);
    }
  }
  return last[1];
}

/** 効き目プレビュー表が出す得点。backendが返す値と見た目を揃えるため小数1桁へ丸める
 * （計算そのものは`breakpointScore`が持つ）。 */
export function interpolateBreakpointScore(breakpoints: readonly [number, number][], x: number): number {
  return Math.round(breakpointScore(breakpoints, x) * 10) / 10;
}

/** 「+ 折れ点を追加」の挿入位置。隣接点どうしのx方向の間隔が最も広い区間の中間へ挿入する
 * ——追加した点が常に昇順制約を満たすため。点が1つ以下では追加できないため呼び出し側で
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
