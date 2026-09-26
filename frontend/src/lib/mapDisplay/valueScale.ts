// 地図が軸について塗る値の段と配色。ルート前の道路の線（ramp軸・専用配信の軸）・ルートの線・凡例・管理画面の
// プレビューが同じ関数を通るので、同じ軸の同じ段はどこでも同じ色になる。

import { mapDisplay } from "@/types/generated/mapDisplay";
import type { components } from "@/types/generated/api";
import palette from "@/types/generated/palette.json";
import type { RampAxis } from "./axisLayers";
import type { DedicatedWayValueDisplay } from "./dedicatedWayValueLayer";
import { bandLabelsForBandCount, buildRangeLegendBands, type MapColorLegendBand } from "./mapColorLegend";

/** 地図がその軸について塗る値の種類（正本はbackend）。`difficulty`は評価済みの0〜100、`signed_material`は
 * 向きの符号が意味を持つ材料1つの生値（勾配等）。 */
export type MapValueKind = NonNullable<components["schemas"]["AxisCatalogEntry"]["map_value_kind"]>;

/** ramp軸（タイルへ焼いた材料の重み付き和で塗る軸）の値の種類。重み付き和は向きの符号を持たないので、
 * 難易度と同じ評価の配色で塗る。 */
export const RAMP_AXIS_VALUE_KIND: MapValueKind = "difficulty";

const COLOR_EASY = palette.semantic.evaluation_good;
export const COLOR_NO_DATA = palette.semantic.no_data;
/** 符号付き材料の負側（下り坂等、走行が楽になる側）の色。 */
const COLOR_SIGNED_LOW = palette.semantic.signed_descent;
/** 平坦の色は難易度の「易しい」と同じにして、楽な区間の色を種類をまたいで揃える。 */
const COLOR_SIGNED_FLAT = COLOR_EASY;

/** 評価の配色（易しい→難しい）。色相だけでなく明度も動かし（緑→黄→赤→暗赤）、段を増やしても隣が見分けられる
 * ようにする。難易度の段と、符号付き材料の上り側が同じものを使う。 */
const EVALUATION_ANCHORS: readonly string[] = [
  COLOR_EASY,
  palette.semantic.evaluation_mid,
  palette.semantic.evaluation_bad,
  palette.semantic.evaluation_extreme,
];

/** 符号付き材料は0（平坦）を境に2方向の配色へ分ける（2色の補間1本だと0付近の段が端の色に寄る）。 */
const SIGNED_DESCENT_ANCHORS: readonly string[] = [COLOR_SIGNED_LOW, COLOR_SIGNED_FLAT];

/** 難易度の段の境界の既定（軸が宣言していないとき）。backendが配る。符号付き材料の段はbackendが軸ごとに必ず
 * 返すので、ここに既定を持たない。 */
export const DEFAULT_DIFFICULTY_BOUNDARIES: readonly number[] = mapDisplay.valueScale.difficultyBoundaries;

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

/** 中継点を並べた配色の上をcount色に均等に補間する。 */
function interpolateColorStops(anchors: readonly string[], count: number): string[] {
  if (count <= 1) return [anchors[0]];
  const segments = anchors.length - 1;
  return Array.from({ length: count }, (_, index) => {
    const position = (index / (count - 1)) * segments;
    const segment = Math.min(Math.floor(position), segments - 1);
    return mixColors(anchors[segment], anchors[segment + 1], position - segment);
  });
}

/** 符号付き材料の段の色。0を含む段（境界にちょうど0があるときは0から始まる段）を平坦にし、その手前と先を
 * それぞれの配色で補間する。 */
function signedBandColors(boundaries: readonly number[]): string[] {
  const bandCount = boundaries.length + 1;
  const firstPositive = boundaries.findIndex((boundary) => boundary > 0);
  const flatIndex = firstPositive < 0 ? bandCount - 1 : firstPositive;
  const descent = interpolateColorStops(SIGNED_DESCENT_ANCHORS, flatIndex + 1).slice(0, flatIndex);
  const climb = interpolateColorStops(EVALUATION_ANCHORS, bandCount - flatIndex).slice(1);
  return [...descent, COLOR_SIGNED_FLAT, ...climb];
}

/** 値の種類と段の境界から、段ごとの色を求める。 */
export function bandColorsFor(kind: MapValueKind, boundaries: readonly number[]): string[] {
  if (kind === "signed_material") return signedBandColors(boundaries);
  return interpolateColorStops(EVALUATION_ANCHORS, boundaries.length + 1);
}

/** 段1つ。`lowerBound`は段の下限（最も低い段は-∞）で、判定は`>= 下限`・`< 次の下限`。 */
export interface ValueBand extends MapColorLegendBand {
  lowerBound: number;
}

/** 軸を塗る段の並び（低い段から）。鍵・範囲の文字・体感ラベル・色をここで一度に決める。体感ラベルは件数が段の数と
 * 合うときだけ添える（`bandLabelsForBandCount`）。 */
export function valueBands(
  kind: MapValueKind,
  boundaries: readonly number[],
  unit: string,
  bandLabels?: readonly string[] | null,
): ValueBand[] {
  const colors = bandColorsFor(kind, boundaries);
  const labels = bandLabelsForBandCount(bandLabels, colors.length);
  return buildRangeLegendBands(boundaries, colors, unit, labels).map((band, index) => ({
    ...band,
    lowerBound: index === 0 ? Number.NEGATIVE_INFINITY : (boundaries[index - 1] as number),
  }));
}

/** ramp軸の段。境界は軸の地図表示のしきい値（重み付き和の目盛り）。 */
export function rampAxisBands(axis: RampAxis): ValueBand[] {
  return valueBands(RAMP_AXIS_VALUE_KIND, axis.thresholds, axis.unit, axis.bandLabelsOverride);
}

/** 専用配信の軸の段。境界を宣言していない軸は難易度の既定の境界で切る。 */
export function dedicatedAxisBands(display: DedicatedWayValueDisplay): ValueBand[] {
  return valueBands(
    display.kind,
    display.boundaries ?? DEFAULT_DIFFICULTY_BOUNDARIES,
    display.unit,
    display.bandLabels,
  );
}
