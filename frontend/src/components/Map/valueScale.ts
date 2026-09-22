// 地図が軸について塗る値のスケール（種類ごとの既定しきい値・配色）と、段階分けの色式を
// 組み立てる共通ロジック。ルート確定前の専用way値レイヤー（dedicatedWayValueLayer.ts）と
// ルート確定後のルート線色分け（routeStyleModes.ts）が同じ関数を使うことで、同じ軸の
// 色分けがルートの有無でスケール・配色を変えないことをコード上で保証する。
// MapLibre・DOMに依存しない純粋関数のみ。

import { mapDisplay } from "@/types/generated/mapDisplay";
import type { components } from "@/types/generated/api";
import palette from "@/types/generated/palette.json";
import { LEGEND_NO_DATA_KEY, legendBandKey } from "./mapColorLegend";

/** backend `GET /api/axis-catalog` の `map_value_kind`（domain/dynamic_way_values.py:
 * map_value_kind）と同じ語彙。`difficulty`は軸スタジオのbreakpointsで評価済みの0〜100、
 * `signed_material`は単一材料の符号付き生値（勾配のように向きの符号が意味を持つ軸）。 */
/** 地図がその軸について塗る値の種類。**正本はbackend**（`domain/dynamic_way_values.py`）。 */
export type MapValueKind = NonNullable<components["schemas"]["AxisCatalogEntry"]["map_value_kind"]>;

const COLOR_EASY = palette.semantic.evaluation_good;
const COLOR_HARD = palette.semantic.evaluation_bad;
export const COLOR_NO_DATA = palette.semantic.no_data;
/** フェッチ進行中で、まだそのwayの値を一度も受け取っていない状態の色。
 * COLOR_NO_DATAより明るくし、「取得中」と「取得済みだが値が無い」を見分けられるようにする。 */
export const COLOR_LOADING = palette.semantic.loading;
/** 凡例で非表示にした段階の色。線は描かれるが透明で、下の路面レイヤーがそのまま見える。 */
const COLOR_HIDDEN = palette.semantic.hidden;
/** 符号付き材料の負側（下り坂等、走行が楽になる側）の色。 */
const COLOR_SIGNED_LOW = palette.semantic.signed_descent;
/** 符号付き材料の0付近（平坦）の色。難易度スケールの「易しい」と同じ緑にして、
 * 「楽な区間」の色をスケールの種類をまたいで揃える。 */
const COLOR_SIGNED_FLAT = COLOR_EASY;
/** 符号付き材料の正側が赤へ向かう途中に置く色。段階数が増えても隣同士が見分けられるよう、
 * 色相だけでなく明度も動かす経路（緑→黄→赤→暗赤）にするための中継点。 */
const COLOR_SIGNED_CLIMB_MID = palette.semantic.signed_climb_mid;
const COLOR_SIGNED_CLIMB_EXTREME = palette.semantic.signed_climb_extreme;

/** 符号付き材料の配色は0（平坦）を境に2方向へ分ける。1つの2色補間で全段階を塗ると、
 * 0付近の段階が両端のどちらかの色に寄り（勾配では平坦帯が濃い青になる）、段階を細かく
 * するほど隣と見分けられなくなる。 */
const SIGNED_DESCENT_ANCHORS: readonly string[] = [COLOR_SIGNED_LOW, COLOR_SIGNED_FLAT];
const SIGNED_CLIMB_ANCHORS: readonly string[] = [
  COLOR_SIGNED_FLAT,
  COLOR_SIGNED_CLIMB_MID,
  COLOR_HARD,
  COLOR_SIGNED_CLIMB_EXTREME,
];

/** 軸カタログの`map_value_thresholds`が未設定のときの段の境界。**源泉が配る**
 * （`backend/app/domain/map_display.py`）——境界の個数がそのまま段の数になるので、
 * 画面側に写しを置くと段の数だけが古いまま描かれる。 */
export const DEFAULT_DIFFICULTY_BOUNDARIES: readonly number[] = mapDisplay.valueScale.difficultyBoundaries;
const SIGNED_MATERIAL_BOUNDARIES: readonly number[] = mapDisplay.valueScale.signedMaterialBoundaries;

interface ValueScale {
  defaultBoundaries: readonly number[];
}

export function valueScaleFor(kind: MapValueKind): ValueScale {
  if (kind === "signed_material") {
    return { defaultBoundaries: SIGNED_MATERIAL_BOUNDARIES };
  }
  return { defaultBoundaries: DEFAULT_DIFFICULTY_BOUNDARIES };
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
      .map((v) =>
        Math.max(0, Math.min(255, Math.round(v)))
          .toString(16)
          .padStart(2, "0"),
      )
      .join("")
  );
}

/** 2色の間をHSL色空間で位置t（0〜1）の1色へ混ぜる。RGB直接補間だと中間色が濁るため
 * （緑↔赤の中間が茶色がかる）、色相を短い経路で回る。 */
function mixColors(colorLow: string, colorHigh: string, t: number): string {
  const [h1, s1, l1] = rgbToHsl(hexToRgb(colorLow));
  const [h2, s2, l2] = rgbToHsl(hexToRgb(colorHigh));
  let dh = h2 - h1;
  if (dh > 180) dh -= 360;
  if (dh < -180) dh += 360;
  return rgbToHex(hslToRgb(h1 + dh * t, s1 + (s2 - s1) * t, l1 + (l2 - l1) * t));
}

/** 2色（colorLow/colorHigh）の間をHSL色空間でcount色に均等補間する。境界値の個数
 * （＝段階数）は軸スタジオが決めるため任意のcountに対応する。 */
export function interpolateColors(colorLow: string, colorHigh: string, count: number): string[] {
  return interpolateColorStops([colorLow, colorHigh], count);
}

/** 中継点を並べた配色（anchors）の上をcount色に均等補間する。2色補間では色相が一本道に
 * なり、段階数が増えるほど隣同士が近づく——中継点を置くと同じ段階数でも色差を稼げる。 */
export function interpolateColorStops(anchors: readonly string[], count: number): string[] {
  if (count <= 1) return [anchors[0]];
  const segments = anchors.length - 1;
  return Array.from({ length: count }, (_, index) => {
    const position = (index / (count - 1)) * segments;
    const segment = Math.min(Math.floor(position), segments - 1);
    return mixColors(anchors[segment], anchors[segment + 1], position - segment);
  });
}

/** 符号付き材料の段階色。0を含む段階（平坦）を境に、下り側・上り側それぞれ別の配色の上を
 * 補間する。0を含む段階が無い（境界に0がある）場合は、0から始まる段階を平坦側として扱う。 */
function signedBandColors(boundaries: readonly number[]): string[] {
  const bandCount = boundaries.length + 1;
  const firstPositive = boundaries.findIndex((boundary) => boundary > 0);
  const flatIndex = firstPositive < 0 ? bandCount - 1 : firstPositive;
  const descent = interpolateColorStops(SIGNED_DESCENT_ANCHORS, flatIndex + 1).slice(0, flatIndex);
  const climb = interpolateColorStops(SIGNED_CLIMB_ANCHORS, bandCount - flatIndex).slice(1);
  return [...descent, COLOR_SIGNED_FLAT, ...climb];
}

/** 種類とboundaries（未指定なら種類の既定値）から段階ごとの色配列を求める。ルート確定前の
 * 全道路の塗り・ルート確定後のルート線・凡例がいずれもこの1つの関数を通るため、同じ軸の
 * 同じ段階はどこでも同じ色になる。 */
export function bandColorsFor(kind: MapValueKind, boundaries?: readonly number[] | null): string[] {
  const resolved = boundaries ?? valueScaleFor(kind).defaultBoundaries;
  if (kind === "signed_material") return signedBandColors(resolved);
  return interpolateColors(COLOR_EASY, COLOR_HARD, resolved.length + 1);
}

/** 「帯の下限＋色」の並びを、そのままMapLibreのstep式へ組み立てる。
 *
 * **地図を連続補間（`interpolate`）で塗ると、凡例と一致しない**。凡例が並べられるのは帯ごとの
 * 色見本1つだけで、それは帯の端の色でしかない。帯の中ほどの値はどの見本とも違う色になり、
 * 「この色は凡例のどれか」が答えられなくなる。同じ配列が地図の帯と凡例の行の両方を決める形に
 * しておけば、そのずれ自体が生まれない。
 *
 * `bands`は下限の昇順で、先頭の`from`は使わない（それより小さい値も先頭の色になる）。 */
export function buildBandColorExpression(
  numericExpression: unknown[],
  bands: readonly { from: number; color: string }[],
): unknown[] {
  const expression: unknown[] = ["step", numericExpression, bands[0].color];
  for (const band of bands.slice(1)) {
    expression.push(band.from, band.color);
  }
  return expression;
}

/** 値取得式を段階分けの色へ変換するMapLibre expression。値がnull（データ欠落・未取得）なら
 * `loading`に応じてCOLOR_LOADING（フェッチ進行中）またはCOLOR_NO_DATA（取得済みだが値が
 * 無い）、それ以外は`["step", value, color0, boundary1, color1, ...]`。
 * `numericExpression`はstep式に渡す数値化済みの式（geojsonプロパティは`["to-number", ...]`で
 * 包む必要があり、feature-stateはそのままでよい）。null判定は数値化前の式で行う
 * （to-numberがnull→0へ変換してしまう前に判定するため）。
 *
 * `hiddenBandKeys`（凡例で非表示にした段階）の色はCOLOR_HIDDEN（透明）にする。**この値は
 * feature-state経由で入るため、MapLibreのfilterでは絞り込めない**——filterはfeature-stateを
 * 読めないので、線そのものを間引くのではなく色を透明にして下の路面レイヤーを見せる。
 * フェッチ進行中の色は非表示指定があっても残す（読込中であることの手がかりまで消えると、
 * 「まだ来ていない」と「隠した」が区別できなくなる）。 */
export function buildSteppedColorExpression(options: {
  valueExpression: unknown[];
  kind: MapValueKind;
  boundaries?: readonly number[] | null;
  numericExpression?: unknown[];
  loading?: boolean;
  hiddenBandKeys?: readonly string[];
}): unknown[] {
  const { valueExpression, kind, boundaries, loading = false, hiddenBandKeys = [] } = options;
  const numericExpression = options.numericExpression ?? valueExpression;
  const resolved = boundaries ?? valueScaleFor(kind).defaultBoundaries;
  const colors = bandColorsFor(kind, resolved).map((color, index) =>
    hiddenBandKeys.includes(legendBandKey(index)) ? COLOR_HIDDEN : color,
  );
  const noDataColor = hiddenBandKeys.includes(LEGEND_NO_DATA_KEY) ? COLOR_HIDDEN : COLOR_NO_DATA;
  const stepExpression: unknown[] = ["step", numericExpression, colors[0]];
  resolved.forEach((boundary, index) => {
    stepExpression.push(boundary, colors[index + 1]);
  });
  return ["case", ["==", valueExpression, null], loading ? COLOR_LOADING : noDataColor, stepExpression];
}
