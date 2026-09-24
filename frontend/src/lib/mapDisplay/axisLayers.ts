// 軸カタログ（`GET /api/axis-catalog`）の軸を、地図が読む形（ramp軸・専用配信軸）へ移す。
//
// 軸の地図表示は`domain/axis_display.py: axis_display_for()`が軸スタジオの公開状態から都度作り、
// **ビルド時の写しは持たない**——写しを持つと、API障害時に古い軸で地図が描かれ、伝播の失敗が
// 見えなくなる。取得できるまでは軸0件で描く（`hooks/useAxisCatalog.ts`）。軸は軸スタジオで公開すれば、
// 材料がタイルにある限り再デプロイなしに地図のレイヤーとして現れる。

import palette from "@/types/generated/palette.json";
import type { DedicatedWayValueDisplay } from "./dedicatedWayValueLayer";
import type { MapValueKind } from "./valueScale";
import type { AxisShape } from "@/types/route";

interface AxisTileInput {
  property: string;
  weight: number;
  /** true=真偽値材料。weightは無視し、trueValue/falseValueで寄与値を直接指定する。 */
  boolean?: boolean;
  trueValue?: number;
  falseValue?: number;
  /** true=タイルプロパティの欠損が「true/falseどちらでもない不明」を表す（例:
   * surface_good、未分類の路面）。欠損時はtrueValue/falseValueどちらにも倒さず、
   * 灰色「不明」表示にする（registry.py: TileInputSpec.has_unknown_fallback参照）。既定false（欠損=falseとみなしてよい材料、例:
   * lit・has_tunnel⟵tunnel）はtrueValue/falseValueへ通常どおり倒す。 */
  hasUnknownFallback?: boolean;
  /** N値文字列材料（例: highway）。タイルプロパティの
   * 文字列値をこの辞書で引いた点数×weightを寄与値とする。未登録値は0扱い
   * （registry.py: TileInputSpec.categories参照）。 */
  categories?: Record<string, number>;
  /** 自己変換材料（例: maxspeed_kmh/lanes_count）。材料自身が持つ
   * 区分線形breakpointsでタイルプロパティの生値をinterpolateした値×weightを
   * 寄与値とする（registry.py: TileInputSpec.breakpoints参照）。 */
  breakpoints?: readonly (readonly [number, number])[];
}

export interface RampAxis {
  axisId: string;
  label: string;
  category: string;
  tileInputs: readonly AxisTileInput[];
  /** 昇順の色段階境界値。値 < thresholds[0] が最も低い段階 */
  thresholds: readonly number[];
  /** 凡例の範囲に添える単位（軸カタログの`raw_value_unit`。定まらない軸は空）。 */
  unit: string;
  /** 地図上のレイヤー一覧向けの噛み砕いた説明文（軸自身のデータ）。 */
  panelHint?: string;
  /** 地図チップのアイコン（axisIconPalette.tsxのicon_id）。未設定は
   * 汎用フォールバック（AxisRampIcon）。 */
  iconId?: string;
  /** 地図チップの略名（4文字以下、CatalogAxis.chip_label由来）。未設定はlabel（正式名）へ
   * フォールバックする（mapLayers.ts参照）。 */
  chipLabel?: string;
  /** 段階ごとの体感ラベル（軸自身のデータ、display_band_labels_override由来）。要素数が
   * thresholds.length+1と一致する間だけ、凡例（`features/map/view/lens.ts: buildAxisRampLegend`）が
   * 数値レンジの前に添える。 */
  bandLabelsOverride?: readonly string[];
}

interface CatalogTileInput {
  property: string;
  weight: number;
  boolean?: boolean;
  true_value?: number;
  false_value?: number;
  has_unknown_fallback?: boolean;
  // `GET /api/axis-catalog`はpydanticの未設定optionalフィールドを
  // undefinedではなくnullとしてシリアライズするため、nullも許容する。
  categories?: Record<string, number> | null;
  breakpoints?: (readonly [number, number])[] | null;
  /** このtile_inputのタイル生値が、実行時にしか決まらないスケール定数での変換を要する場合true
   * （registry.py: TileInputSpec.needs_runtime_scale参照、例: accident_per_km→件/(km・年)への年数正規化）。
   * `rampAxesFromCatalogAxes`がweightへ掛け合わせて解決するため、地図の式はこのフラグを見ない。 */
  needs_runtime_scale?: boolean | null;
}

export interface CatalogAxis {
  axis_id: string;
  // 軸自身の表示名（トップレベル、display.labelとは独立）。display（地図ramp表示の宣言）が
  // kind="none"の軸（例: wind）でも設定される。
  // routeStyleModesFromCatalogAxes（routeStyleModes.ts）が公開軸のルート色分けモードの
  // ラベルとして使う。
  label: string;
  // 軸自身の説明文（1〜2文の要約、GET /api/axis-catalogのdescriptionと同じ値）。
  // ルート設定パネルの重み一覧が軸の説明として出す。
  description?: string;
  // 折れ点を通す前の生値の単位（GET /api/axis-catalogのraw_value_unit）。単位が定まる
  // 軸だけが持つ。ルート結果が得点の隣に生値を出すために使う。
  raw_value_unit?: string | null;
  // 生値へ走行距離を掛けた総量の単位（GET /api/axis-catalogのraw_value_total_unit）。
  // 総量を出しても判断が変わらない軸はnullで、フロントは単位の綴りから可否を判断しない。
  raw_value_total_unit?: string | null;
  // 生値の単位が定まらない軸の内訳（GET /api/axis-catalogのmaterial_breakdown）。
  // 材料まで分解した並びで、正規化重みの降順。フロントは並べ替えを持たず先頭から出す。
  material_breakdown?: readonly {
    material_id: string;
    label: string;
    dtype: string;
    unit: string;
    share: number;
    // categorical材料の「タグ生値→論理名」対訳。他の型では空。
    value_labels?: Record<string, string>;
  }[];
  // 軸自身の分類（観測/推定/動的）。display.category（地図レイヤーパネルのグルーピング用
  // 「terrain」「trafficSafety」等、別語彙）とは異なる概念。
  category?: string;
  display: {
    kind: string;
    label: string;
    category: string;
    tile_inputs: CatalogTileInput[];
    thresholds: number[];
  } | null;
  // この軸が参照する材料を一次属性idへ解決した一覧（GET /api/axis-catalogの
  // primary_attribute_ids、backend側で解決済み）。
  primary_attribute_ids?: string[];
  // 地図チップ表示要素（軸自身のデータ）。全てnull/undefined可
  // （未設定は各消費側の汎用フォールバックに委ねる）。
  icon_id?: string | null;
  chip_label?: string | null;
  panel_hint?: string | null;
  // falseならこの軸を地図上チップから丸ごと除外する
  // （secondaryAxes.ts: secondaryAxesFromCatalogAxes()参照）。未設定は
  // 「表示する」（true相当）として扱う。
  show_map_icon?: boolean;
  // 軸の折れ線の形。routeStyleModes.tsが、axis_idの分岐ではなくこのデータから
  // 「符号付き値を直接読むべきか」「その場合どの材料id（≒RouteSegmentDetailのフィールド名）を
  // 読むか」を判定する（map_value_kind・buildRangeSteppedMode参照）。
  shape?: AxisShape;
  // 軸スタジオが編集した生の上書き値（地図タイルramp表示のdisplay.thresholdsとは別）。地図の色分けは
  // `map_value_thresholds`（スケールを揃えた側）を使う。
  display_thresholds_override?: number[] | null;
  // display_thresholds_overrideと対になる、段階ごとの体感ラベルの上書き（domain/axis_definitions.py: AxisDefinition.display_band_labels_override参照）。
  display_band_labels_override?: string[] | null;
  // この軸が専用のway_id→値配信レイヤー（Redis経由）を持つかの宣言
  // （domain/axis_definitions.py: AxisDefinition.dedicated_way_value_layer参照）。
  // mapLayers.ts（isAxisStudioLayer）はaxis_idではなくこのデータで判定する。
  dedicated_way_value_layer?: boolean;
  // 地図がこの軸について塗る値の種類と単位（backend domain/dynamic_way_values.py:
  // map_value_kind/map_value_unit）。ルート確定前の専用way値レイヤーとルート確定後の
  // ルート線色分けが同じスケールで解釈する。
  map_value_kind?: MapValueKind;
  map_value_unit?: string;
  // `map_value_kind`が示すスケールでの段階境界（backend domain/dynamic_way_values.py:
  // map_value_thresholds）。地図の色分けはルート前後ともこれを使う。
  // `display_thresholds_override`は軸スタジオが編集した生値で、ramp表示を持つ軸では
  // 材料の重み付き和のスケールなので難易度と直接比べられない。
  map_value_thresholds?: number[] | null;
  // 専用way値配信API（`GET /api/region/dynamic-way-values/{axis_id}`）がこの軸について
  // 必要とするクエリパラメータの宣言（backend domain/axis_definitions.py:
  // AxisDefinition.dynamic_way_value_needs_time / _needs_bearing / _needs_speed）。
  // `dedicated_way_value_layer`がtrueの軸だけが意味を持つ。
  dynamic_way_value_needs_time?: boolean;
  dynamic_way_value_needs_bearing?: boolean;
  dynamic_way_value_needs_speed?: boolean;
}

/** 公開軸の表示名の辞書（軸id→軸定義の`label`）。**ここに無い軸idを画面へ出さない**——
 * 引けなかったときに軸idで埋めると、内部名（例: `wind`）がそのまま画面に出る。
 * 軸の名前は軸定義の`label`だけが持つ（地図表示の`display.label`は地図に出る軸にしか無い）。 */
export function axisLabelsFromCatalogAxes(axes: readonly CatalogAxis[]): Record<string, string> {
  return Object.fromEntries(axes.map((axis) => [axis.axis_id, axis.label]));
}

/** `runtimeScales`（GET /api/axis-catalogのmaterial_runtime_scales、tile property名→スケール係数）は、
 * `needs_runtime_scale`なtile_inputの`weight`へ構築時に一度だけ掛け合わせて解決する（地図の式は
 * 解決済みのweightだけを見る）。
 * 該当するtile propertyのスケール係数がまだ解決できていない場合（収録年数0件等で
 * backendがキーを含めなかった場合）はweight=0として寄与を無くす（安全側のデグレード。
 * RegionService.get_accident_years_coveredのdocstring参照）。 */
export function rampAxesFromCatalogAxes(
  axes: readonly CatalogAxis[],
  runtimeScales: Readonly<Record<string, number>> = {},
): RampAxis[] {
  return axes
    .filter((axis) => axis.display?.kind === "ramp")
    .map((axis) => ({
      axisId: axis.axis_id,
      label: axis.display!.label,
      category: axis.display!.category,
      tileInputs: axis.display!.tile_inputs.map((input) => ({
        property: input.property,
        weight: input.needs_runtime_scale ? input.weight * (runtimeScales[input.property] ?? 0) : input.weight,
        boolean: input.boolean,
        trueValue: input.true_value,
        falseValue: input.false_value,
        hasUnknownFallback: input.has_unknown_fallback,
        categories: input.categories ?? undefined,
        breakpoints: input.breakpoints ?? undefined,
      })),
      thresholds: axis.display!.thresholds,
      unit: axis.raw_value_unit ?? "",
      panelHint: axis.panel_hint ?? undefined,
      iconId: axis.icon_id ?? undefined,
      chipLabel: axis.chip_label ?? undefined,
      bandLabelsOverride: axis.display_band_labels_override ?? undefined,
    }));
}

/** mapLayers.ts のレイヤーID（チップ・パネル・visibility状態のキー） */
export type AxisMapLayerId = `axis:${string}`;

export function axisMapLayerId(axisId: string): AxisMapLayerId {
  return `axis:${axisId}`;
}

/** 専用のway_id→値配信レイヤーを持つ軸（`dedicated_way_value_layer=true`、現状: 風・勾配）。
 * ramp軸に対する`RampAxis`と同じ位置付けの、軸カタログ由来の地図向けビュー。
 * この型があることで、レイヤー登録・カタログ・可視性・フェッチのすべてを軸idの
 * ハードコードなしに導出できる（3件目の軸を軸スタジオで公開しただけで
 * 地図に現れる。ただし配信実装本体はbackend側の登録が別途必要）。 */
export interface DedicatedWayValueAxis {
  axisId: string;
  label: string;
  /** 地図チップの略名（4文字以下）。未設定はlabelへフォールバック。 */
  chipLabel?: string;
  /** 軸自身の説明文（`AxisDefinition.panel_hint`）。 */
  panelHint?: string;
  /** 専用way値配信APIへ添えるクエリパラメータの宣言。`features/map/useDedicatedWayValues.ts`が
   * 「どの軸のフェッチに時刻・想定速度を乗せるか」をaxis_idの分岐ではなくここから決める
   * （乗せない入力は依存配列からも外れるため、時刻を動かしても時刻非依存の軸は再フェッチしない）。 */
  needsTime: boolean;
  needsBearing: boolean;
  needsSpeed: boolean;
  /** 地図に塗るときの表示宣言。軸と同じカタログの行から作るため、軸が在れば必ず在る。 */
  display: DedicatedWayValueDisplay;
}

/** ビルド時静的json（CatalogAxis[]）・実行時APIのどちらからでも同じ形へ変換する共通関数
 * （rampAxesFromCatalogAxesと同じ片側importの方針）。 */
export function dedicatedWayValueAxesFromCatalogAxes(axes: readonly CatalogAxis[]): DedicatedWayValueAxis[] {
  return axes
    .filter((axis) => axis.dedicated_way_value_layer)
    .map((axis) => ({
      axisId: axis.axis_id,
      label: axis.label,
      chipLabel: axis.chip_label ?? undefined,
      panelHint: axis.panel_hint ?? undefined,
      needsTime: axis.dynamic_way_value_needs_time ?? false,
      needsBearing: axis.dynamic_way_value_needs_bearing ?? false,
      needsSpeed: axis.dynamic_way_value_needs_speed ?? false,
      display: {
        kind: axis.map_value_kind ?? "difficulty",
        unit: axis.map_value_unit ?? "",
        boundaries: axis.map_value_thresholds ?? undefined,
        bandLabels: axis.display_band_labels_override ?? undefined,
      },
    }));
}

// 共有ランプ配色（低→高、緑→黄→橙→赤）のアンカー。全ramp軸が同じ配色系統を使うことで
// 「低=緑〜高=赤」という読み方を1回覚えれば全軸に通用させる（軸ごとに独自配色を作らない）。
// 段階数（バンド数）は軸によって異なりうる（複数材料の組み合わせは
// thresholdsが4個ちょうどに収まるとは限らない）。rampColorForBandはこの4色をアンカーとして
// bandCount段階ぶんの色を線形補間で生成するため、bandCount=4のときは既存の4色と完全に
// 一致し（axisLayers.test.ts参照）、bandCount≠4の軸でも同じ緑→赤の配色系統のまま段階数
// ぶんの色を自動生成できる。
const RAMP_COLOR_ANCHORS: readonly [number, string][] = palette.evaluation_ramp_anchors.map((anchor) => [
  anchor.position,
  anchor.color,
]);

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function rgbToHex(rgb: readonly [number, number, number]): string {
  return "#" + rgb.map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
}

function lerpColor(a: string, b: string, t: number): string {
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  return rgbToHex([ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t]);
}

/** RAMP_COLOR_ANCHORS（緑(0)→赤(1)）をt（0〜1の相対位置）で線形補間する共通ロジック。
 * rampColorForBand（段階index/bandCountからの離散色）がこれを経由することで、
 * アンカー定義（緑→黄→橙→赤の4点）を1箇所だけに保つ（定数の片側import）。 */
function rampColorForRatio(t: number): string {
  const clamped = Math.min(1, Math.max(0, t));
  for (let i = 0; i < RAMP_COLOR_ANCHORS.length - 1; i++) {
    const [t0, c0] = RAMP_COLOR_ANCHORS[i];
    const [t1, c1] = RAMP_COLOR_ANCHORS[i + 1];
    if (clamped <= t1 || i === RAMP_COLOR_ANCHORS.length - 2) {
      const localT = t1 === t0 ? 0 : Math.min(1, Math.max(0, (clamped - t0) / (t1 - t0)));
      return lerpColor(c0, c1, localT);
    }
  }
  return RAMP_COLOR_ANCHORS[RAMP_COLOR_ANCHORS.length - 1][1];
}

/** bandCount段階中index番目(0始まり)の色。RAMP_COLOR_ANCHORSを緑(0)→赤(1)の相対位置で
 * 線形補間する。 */
export function rampColorForBand(index: number, bandCount: number): string {
  const t = bandCount <= 1 ? 0 : index / (bandCount - 1);
  return rampColorForRatio(t);
}
