// 地図が軸について塗る値のスケール（種類ごとの既定しきい値・配色）と、段階分けの色式を
// 組み立てる共通ロジック。ルート確定前の専用way値レイヤー（dedicatedWayValueLayer.ts）と
// ルート確定後のルート線色分け（routeStyleModes.ts）が同じ関数を使うことで、同じ軸の
// 色分けがルートの有無でスケール・配色を変えないことをコード上で保証する。
// MapLibre・DOMに依存しない純粋関数のみ。

/** backend `GET /api/axis-catalog` の `map_value_kind`（domain/dynamic_way_values.py:
 * map_value_kind）と同じ語彙。`difficulty`は軸スタジオのbreakpointsで評価済みの0〜100、
 * `signed_material`は単一材料の符号付き生値（勾配のように向きの符号が意味を持つ軸）。 */
export type MapValueKind = "difficulty" | "signed_material";

export const COLOR_EASY = "#16a34a";
export const COLOR_HARD = "#dc2626";
export const COLOR_NO_DATA = "#9ca3af";
/** フェッチ進行中で、まだそのwayの値を一度も受け取っていない状態の色（改善計画T607）。
 * COLOR_NO_DATAより明るくし、「取得中」と「取得済みだが値が無い」を見分けられるようにする。 */
export const COLOR_LOADING = "#d1d5db";
/** 符号付き材料の負側（下り坂等、走行が楽になる側）の色。 */
export const COLOR_SIGNED_LOW = "#0284c7";

/** 軸スタジオのdisplay_thresholds_overrideが未設定のときの既定の段階境界。値そのものは
 * 色分けロジックの前提にならず、境界値の個数がそのまま段階数を決める。 */
export const DEFAULT_DIFFICULTY_BOUNDARIES: readonly number[] = [33, 66];
export const SIGNED_MATERIAL_BOUNDARIES: readonly number[] = [-2, 2, 6, 10];

export interface ValueScale {
  defaultBoundaries: readonly number[];
  colorLow: string;
  colorHigh: string;
}

export function valueScaleFor(kind: MapValueKind): ValueScale {
  if (kind === "signed_material") {
    return { defaultBoundaries: SIGNED_MATERIAL_BOUNDARIES, colorLow: COLOR_SIGNED_LOW, colorHigh: COLOR_HARD };
  }
  return { defaultBoundaries: DEFAULT_DIFFICULTY_BOUNDARIES, colorLow: COLOR_EASY, colorHigh: COLOR_HARD };
}

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHsl([r8, g8, b8]: readonly [number, number, number]): [number, number, number] {
  const r = r8 / 255;
  const g = g8 / 255;
  const b = b8 / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return [h * 60, s, l];
}

function hue2rgb(p: number, q: number, tIn: number): number {
  let t = tIn;
  if (t < 0) t += 1;
  if (t > 1) t -= 1;
  if (t < 1 / 6) return p + (q - p) * 6 * t;
  if (t < 1 / 2) return q;
  if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
  return p;
}

function hslToRgb(hDeg: number, s: number, l: number): [number, number, number] {
  const h = (((hDeg % 360) + 360) % 360) / 360;
  if (s === 0) {
    const v = Math.round(l * 255);
    return [v, v, v];
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  return [
    Math.round(hue2rgb(p, q, h + 1 / 3) * 255),
    Math.round(hue2rgb(p, q, h) * 255),
    Math.round(hue2rgb(p, q, h - 1 / 3) * 255),
  ];
}

function rgbToHex([r, g, b]: readonly [number, number, number]): string {
  return (
    "#" +
    [r, g, b]
      .map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0"))
      .join("")
  );
}

/** 2色（colorLow/colorHigh）の間をHSL色空間でcount色に均等補間する。境界値の個数
 * （＝段階数）は軸スタジオが決めるため任意のcountに対応する。RGB直接補間だと中間色が
 * 濁るため（緑↔赤の中間が茶色がかる）、色相を短い経路で回るHSL補間にしている。 */
export function interpolateColors(colorLow: string, colorHigh: string, count: number): string[] {
  if (count <= 1) return [colorLow];
  const [h1, s1, l1] = rgbToHsl(hexToRgb(colorLow));
  const [h2, s2, l2] = rgbToHsl(hexToRgb(colorHigh));
  let dh = h2 - h1;
  if (dh > 180) dh -= 360;
  if (dh < -180) dh += 360;
  return Array.from({ length: count }, (_, i) => {
    const t = i / (count - 1);
    return rgbToHex(hslToRgb(h1 + dh * t, s1 + (s2 - s1) * t, l1 + (l2 - l1) * t));
  });
}

/** 種類とboundaries（未指定なら種類の既定値）から段階ごとの色配列を求める。 */
export function bandColorsFor(kind: MapValueKind, boundaries?: readonly number[] | null): string[] {
  const scale = valueScaleFor(kind);
  const resolved = boundaries ?? scale.defaultBoundaries;
  return interpolateColors(scale.colorLow, scale.colorHigh, resolved.length + 1);
}

/** 値取得式を段階分けの色へ変換するMapLibre expression。値がnull（データ欠落・未取得）なら
 * `loading`に応じてCOLOR_LOADING（フェッチ進行中）またはCOLOR_NO_DATA（取得済みだが値が
 * 無い、改善計画T607）、それ以外は`["step", value, color0, boundary1, color1, ...]`。
 * `numericExpression`はstep式に渡す数値化済みの式（geojsonプロパティは`["to-number", ...]`で
 * 包む必要があり、feature-stateはそのままでよい）。null判定は数値化前の式で行う
 * （to-numberがnull→0へ変換してしまう前に判定するため）。 */
export function buildSteppedColorExpression(
  valueExpression: unknown[],
  kind: MapValueKind,
  boundaries?: readonly number[] | null,
  numericExpression: unknown[] = valueExpression,
  loading = false
): unknown[] {
  const resolved = boundaries ?? valueScaleFor(kind).defaultBoundaries;
  const colors = bandColorsFor(kind, resolved);
  const stepExpression: unknown[] = ["step", numericExpression, colors[0]];
  resolved.forEach((boundary, index) => {
    stepExpression.push(boundary, colors[index + 1]);
  });
  return ["case", ["==", valueExpression, null], loading ? COLOR_LOADING : COLOR_NO_DATA, stepExpression];
}
