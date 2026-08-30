// 二次軸の汎用rampレイヤー定義（改善計画T145b「事実はタイルに、解釈はクライアントに」）。
//
// 改善計画T308: 軸の地図表示情報（display）は`GET /api/axis-catalog`が実行時に返す
// （`domain/axis_display.py: axis_display_for()`が軸スタジオの公開状態を都度反映する）。
// `RAMP_AXES`/`AXIS_LABELS`（本ファイル下部）はビルド時静的生成物axis-catalog.json由来の
// **フォールバック専用**の値で、`useAxisCatalog`フック（hooks/useAxisCatalog.ts）が
// マウント時に上記APIを取得できるまで・失敗時に使う。新しい軸は、
//   1. 軸スタジオ（GUI）またはbackendのAXIS_DEFINITIONSへ軸を追加・公開する
//   2. タイルへ事実プロパティを焼き込む（way_attribute_counts等、材料がタイル非依存でなければ）
// だけで、再デプロイなしに地図レイヤーとして現れる（軸スタジオでの公開操作が
// `useAxisCatalog`経由で即座に反映される。docs/decisions/
// t308-axis-map-display-auto-derivation.md参照）。
//
// rampの値は tile_inputs から組み立てる。数値材料はΣ property×weight（例: 停止密度 =
// stop_per_km + 0.3×intersection_per_km、backend側の軸内係数
// [domain/difficulty.py: UNSIGNALED_INTERSECTION_WEIGHT等]がカタログ経由で反映される
// ——設計原則2: 片側import。フロントに同じ係数を手書きしない）。プロパティ欠損は
// タイル側が「0をNULLIFでキー省略」した結果なのでcoalesceで0へ倒す
// （_ROAD_SURFACE_TILE_MVT_SQLのコメント参照）。
// 真偽値材料（改善計画T278、例: 舗装質=surface_good、夜間=no_lit/has_tunnel）はMVTの
// 真偽値プロパティを["==",["get",property],true]のような比較でしか読めず数値の重み付け
// 結合が成立しないため、tile_inputs.boolean=trueのときはtrueValue/falseValueで
// 寄与値を直接指定する（weightは無視。domain/axis_display.py: derive_ramp_inputs参照）。

import type { LegendEntry } from "./legendFilter";
import type { components } from "@/types/generated/api";
import axisCatalog from "@/types/generated/axis-catalog.json";

// 改善計画T440: AxisDefinition.shapeのフロント側型（GET /api/axis-catalog:
// AxisCatalogEntry.shapeと同じ、OpenAPI生成物由来）。
export type AxisShape = components["schemas"]["BreakpointLinearShape"] | components["schemas"]["CategoricalShape"];

export interface AxisTileInput {
  property: string;
  weight: number;
  /** true=真偽値材料（改善計画T278）。weightは無視し、trueValue/falseValueで寄与値を直接指定する。 */
  boolean?: boolean;
  /** 材料がタイルプロパティの否定（例: no_lit⟵lit）の場合true。 */
  invert?: boolean;
  trueValue?: number;
  falseValue?: number;
  /** true=タイルプロパティの欠損が「true/falseどちらでもない不明」を表す（例:
   * surface_good、未分類の路面）。欠損時はtrueValue/falseValueどちらにも倒さず、
   * 灰色「不明」表示にする（レビュー指摘の修正、registry.py: TileInputSpec.
   * has_unknown_fallback参照）。既定false（欠損=falseとみなしてよい材料、例:
   * no_lit⟵lit・has_tunnel⟵tunnel）はtrueValue/falseValueへ通常どおり倒す。 */
  hasUnknownFallback?: boolean;
  /** N値文字列材料（改善計画T292、例: highway/designation）。タイルプロパティの
   * 文字列値をこの辞書で引いた点数×weightを寄与値とする。未登録値は0扱い
   * （registry.py: TileInputSpec.categories参照）。 */
  categories?: Record<string, number>;
  /** 自己変換材料（改善計画T292、例: maxspeed_kmh/lanes_count）。材料自身が持つ
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
  unit: string;
  note: string;
  /** 改善計画T310: 地図の見え方パネル向けの噛み砕いた説明文（軸自身のデータ）。
   * 未設定はnote（開発者向け実装メモ）へフォールバック（mapLayers.ts参照）。 */
  panelHint?: string;
  /** 改善計画T310: 地図チップのアイコン（axisIconPalette.tsxのicon_id）。未設定は
   * 汎用フォールバック（AxisRampIcon）。 */
  iconId?: string;
  /** 改善計画: 地図チップの略名（4文字以下、確定命名表どおり、CatalogAxis.chip_label由来）。
   * 未設定はlabel（正式名）へフォールバック（mapLayers.ts参照）。以前はこのフィールド自体が
   * 無く、ramp軸駆動の地図チップ（推定グループの軸タイル・地図の見え方パネル双方）が
   * 常にlabelへフォールバックし続けていた（実機フィードバック「推定軸のアイコングループも
   * 観測アイコングループのようなサイズにして、他と同じく4文字略字までアイコン含めたい」で
   * 発覚、2026-08-27）。 */
  chipLabel?: string;
}

interface CatalogTileInput {
  property: string;
  weight: number;
  boolean?: boolean;
  invert?: boolean;
  true_value?: number;
  false_value?: number;
  has_unknown_fallback?: boolean;
  // JSON生成物（axis-catalog.json）はpydantic model_dump()の未設定optionalフィールドを
  // undefinedではなくnullとしてシリアライズするため、nullも許容する。
  categories?: Record<string, number> | null;
  breakpoints?: (readonly [number, number])[] | null;
  /** 改善計画T404: このtile_inputのタイル生値が実行時にしか決まらないスケール定数での
   * 変換を要する場合true（backend/app/domain/registry.py: TileInputSpec.
   * needs_runtime_scale参照、例: accident_per_km→件/(km・年)への年数正規化）。
   * `rampAxesFromCatalogAxes`が`runtimeScales`引数（GET /api/axis-catalogの
   * material_runtime_scales、tile property名→スケール係数）を使ってweightへ
   * 事前に掛け合わせて解決するため、後段（buildAxisRampValueExpression等）は
   * このフラグを意識しなくてよい。 */
  needs_runtime_scale?: boolean | null;
}

export interface CatalogAxis {
  axis_id: string;
  // 改善計画T352: 軸自身の表示名（トップレベル、display.labelとは独立）。
  // display（地図ramp表示の宣言）がkind="none"の軸（例: wind）でも設定される。
  // routeStyleModesFromCatalogAxes（routeStyleModes.ts）がsupports_route_coloring軸の
  // ルート色分けモードのラベルとして使う。
  label: string;
  // コードレビュー指摘の修正: 軸自身の分類（観測/推定/動的）。display.category
  // （地図レイヤーパネルのグルーピング用「terrain」「trafficSafety」等、別語彙）とは
  // 異なる概念。secondaryAxes.tsが「動的」軸（wind等、専用の動的UIを別途持つため
  // 推定指標チップグループには出さない）を除外するために使う。
  category?: string;
  display: {
    kind: string;
    label: string;
    category: string;
    tile_inputs: CatalogTileInput[];
    thresholds: number[];
    unit: string;
    note: string;
  } | null;
  // 改善計画T308: この軸が参照する材料を一次属性idへ解決した一覧（GET /api/axis-catalogの
  // primary_attribute_ids、backend側で解決済み）。ビルド時静的json（axis-catalog.json）には
  // このフィールドが無いため、その場合はundefined（secondaryAxes.ts側で[]へ補う）。
  primary_attribute_ids?: string[];
  // 改善計画T310: 地図チップ表示要素（既存軸だけ特別扱いしていたSECONDARY_AXIS_ICONS等の
  // 軸id→値の手書き辞書を撤去し、軸自身のデータとして持たせたもの）。全てnull/undefined可
  // （未設定は各消費側の汎用フォールバックに委ねる）。
  icon_id?: string | null;
  chip_label?: string | null;
  panel_hint?: string | null;
  // 改善計画T318: falseならこの軸を地図上チップ・地図の見え方パネルの両方から丸ごと
  // 除外する（secondaryAxes.ts: secondaryAxesFromCatalogAxes()参照）。未設定は
  // 「表示する」（true相当）として扱う——ビルド時静的json（axis-catalog.json）は
  // backendが必ずtrue/falseを返すため実質常に値を持つが、型上はoptionalにしておく。
  show_map_icon?: boolean;
  // 改善計画T352: この軸のdifficultyを、ルート地図の色分けモード
  // （routeStyleModes.ts: routeColorableModesFromCatalogAxes）の選択肢として動的に
  // 使えるかの宣言。未設定はfalse相当（対象外）として扱う。
  supports_route_coloring?: boolean;
  // 改善計画T440: 「軸スタジオで決められること」（AxisDefinitionが実際に持つ未公開の
  // フィールド）をまとめて返す方針（ユーザー指摘「axis-catalogは、軸スタジオで決められる
  // こと全部返すほうがいい」）で追加。routeStyleModes.tsが、axis_idのハードコード分岐では
  // なくこのデータから「符号付き値を直接読むべきか」「その場合どの材料id
  // （≒RouteSegmentDetailのフィールド名）を読むか」を判定する
  // （isSignedAbsShape・buildRangeSteppedMode参照）。
  shape?: AxisShape;
  // 改善計画T440: 地図タイルramp表示（display.thresholds、kind="ramp"の軸のみ）経由では
  // なく、生の上書き値をそのまま返す。ルート結果の色分けのしきい値
  // （routeStyleModes.ts: buildRangeSteppedMode）の唯一の正として使う。
  display_thresholds_override?: number[] | null;
  // 改善計画T440: この軸が専用のway_id→値配信レイヤー（Redis経由）を持つかの宣言
  // （domain/axis_definitions.py: AxisDefinition.dedicated_way_value_layer参照）。
  // mapLayers.ts（isAxisStudioLayer）・RouteSettingsPanel.tsx（mapColorLayerIdFor）が、
  // axis_idのハードコード比較（wind/gradientのみ）ではなくこのデータを使う。
  dedicated_way_value_layer?: boolean;
}

// 改善計画T308: ビルド時静的json（CatalogAxis[]）・実行時API（GET /api/axis-catalog、
// AxisCatalogEntry[]、displayが必ず非nullな点以外はCatalogAxisと構造的に同じ）の
// どちらからもRAMP_AXES/AXIS_LABELSと同じ形へ変換できる共通関数（片側import、
// 変換ロジックを2箇所へ手書きしない）。hooks/useAxisCatalog.tsがこれらを呼んで
// 実行時フェッチ結果から同じ形の値を組み立てる。

/** 全軸（ramp/noneを問わない。改善計画T298: kind="bespoke"は利用ゼロのため削除済み）の
 * ラベル辞書。区間インスペクタ（改善計画T146）が「一次属性→二次軸スコア」を表示する際、
 * 軸ごとに専用UIを持たずカタログのラベルへ汎用的に頼るために使う。
 * 改善計画T466（コメント訂正、ゼロベース網羅レビュー指摘）: `wind: "風"`の直書きは
 * 「windはレジストリ未登録のためカタログに無く、ここでのみ補う」という以前の理由は
 * 誤り——windは現在axis-catalog.json（静的・実行時とも）に登録済みで、通常は
 * `axes`からのspreadが同じ値で上書きするだけの無害な冗長コードに見える。しかし
 * この直書きには実際は別の役割がある: 全軸非公開（`axes`が空配列）等でカタログから
 * windが一時的に欠落しても、windAxisLayer.ts等が参照するこの辞書のキー自体は
 * 常に存在させる安全網として機能する（`useAxisCatalog.test.ts`の回帰テスト
 * 「全軸非公開でaxesが0件でもaxisLabelsはwindを含む」が検証している）。削除しない。 */
export function axisLabelsFromCatalogAxes(axes: readonly CatalogAxis[]): Record<string, string> {
  return {
    wind: "風",
    ...Object.fromEntries(axes.map((axis) => [axis.axis_id, axis.display?.label ?? axis.axis_id])),
  };
}

/** `runtimeScales`（改善計画T404、GET /api/axis-catalogのmaterial_runtime_scales、
 * tile property名→スケール係数）は、`needs_runtime_scale`なtile_inputの`weight`へ
 * 構築時に一度だけ掛け合わせて解決する（後段のbuildAxisRampValueExpression等は
 * 解決済みのweightだけを見ればよく、実行時スケールの概念を意識しなくてよい）。
 * 該当するtile propertyのスケール係数がまだ解決できていない場合（ビルド時静的
 * フォールバックaxis-catalog.jsonの使用中、または収録年数0件等でbackendがキーを
 * 含めなかった場合）はweight=0として寄与を無くす（安全側のデグレード。RegionService.
 * get_accident_years_coveredのdocstring参照）。 */
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
        invert: input.invert,
        trueValue: input.true_value,
        falseValue: input.false_value,
        hasUnknownFallback: input.has_unknown_fallback,
        categories: input.categories ?? undefined,
        breakpoints: input.breakpoints ?? undefined,
      })),
      thresholds: axis.display!.thresholds,
      unit: axis.display!.unit,
      note: axis.display!.note,
      panelHint: axis.panel_hint ?? undefined,
      iconId: axis.icon_id ?? undefined,
      chipLabel: axis.chip_label ?? undefined,
    }));
}

// ビルド時静的json由来のフォールバック専用値（モジュール先頭の注記参照）。
export const AXIS_LABELS: Record<string, string> = axisLabelsFromCatalogAxes(axisCatalog.axes as CatalogAxis[]);

export const RAMP_AXES: readonly RampAxis[] = rampAxesFromCatalogAxes(axisCatalog.axes as CatalogAxis[]);

/** mapLayers.ts のレイヤーID（チップ・パネル・visibility状態のキー） */
export type AxisMapLayerId = `axis:${string}`;

export function axisMapLayerId(axisId: string): AxisMapLayerId {
  return `axis:${axisId}`;
}

/** MapLibreのlayer id（MapView内部） */
export function axisLineLayerId(axisId: string): string {
  return `region-axis-${axisId}-line`;
}

// 共有ランプ配色（低→高、緑→黄→橙→赤）のアンカー。全ramp軸が同じ配色系統を使うことで
// 「低=緑〜高=赤」という読み方を1回覚えれば全軸に通用させる（軸ごとに独自配色を作らない）。
// 改善計画T292: 段階数（バンド数）は軸によって異なりうる（例: car_stressは複数材料の
// 組み合わせのためthresholdsが4個ちょうどに収まるとは限らない）。以前は4色固定配列
// だったため5段階以上の軸があると末尾の段階が同色に潰れる問題があった
// （旧CAR_STRESS_COLORSが専用の5段階配色を手書きしていた理由そのもの）。
// rampColorForBandはこの4色をアンカーとしてbandCount段階ぶんの色を線形補間で生成する
// ため、bandCount=4のときは既存の4色と完全に一致し（axisLayers.test.ts参照）、
// bandCount≠4の軸でも同じ緑→赤の配色系統のまま段階数ぶんの色を自動生成できる。
const RAMP_COLOR_ANCHORS: readonly [number, string][] = [
  [0, "#4caf50"],
  [1 / 3, "#ffb300"],
  [2 / 3, "#fb8c00"],
  [1, "#e53935"],
];

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
 * rampColorForBand（段階index/bandCountからの離散色）・rampColorForValue（0-100連続値からの
 * 色、改善計画T403でルート区間クリック内訳チャート用に追加）の両方がこれを経由することで、
 * アンカー定義（緑→黄→橙→赤の4点）を1箇所だけに保つ（設計原則2: 定数の片側import）。 */
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
 * 線形補間する。bandCount=4のとき旧AXIS_RAMP_COLORSと完全一致する（axisLayers.test.ts）。 */
export function rampColorForBand(index: number, bandCount: number): string {
  const t = bandCount <= 1 ? 0 : index / (bandCount - 1);
  return rampColorForRatio(t);
}

/** difficulty値（0=易しい〜100=大変、RouteSegmentDetail.axis_difficultiesと同じ基準）を
 * 統一パレット（RAMP_COLOR_ANCHORS）で連続的に着色する。ramp軸の地図色分け
 * （rampColorForBand、thresholdsによる段階色）とは異なり、区間内訳チャート
 * （routeSegmentChartPopup.ts、改善計画T403）はしきい値を持たない軸横断の値そのものを
 * 見せたいため、bandへ量子化せず値/maxの比率をそのまま連続スケールへ渡す。 */
export function rampColorForValue(value: number, max = 100): string {
  return rampColorForRatio(max <= 0 ? 0 : value / max);
}

// 既存4段階軸（gradient/surface_q/stop_density/night/accident等）・staticAttributeLayers.ts
// の非ramp用途（DESIGNATION/TUNNEL/ONEWAY等の固定4色引用）向けの後方互換export。
// rampColorForBand(i, 4)と完全に同じ値（後方互換テストで担保）。
export const AXIS_RAMP_COLORS = [
  rampColorForBand(0, 4),
  rampColorForBand(1, 4),
  rampColorForBand(2, 4),
  rampColorForBand(3, 4),
] as const;

// 「不明」（hasUnknownFallback材料のタイル欠損）専用の灰色。staticAttributeLayers.ts:
// COLOR_UNKNOWNと同じ値（既存の路面レイヤー等の「不明」表現と地図全体で統一する）。
// 循環import回避のため値を複製している（staticAttributeLayers.tsがaxisLayers.tsを
// importする向きのため、逆方向のimportはできない）。
export const COLOR_UNKNOWN = "#9ca3af";

/** hasUnknownFallback=trueのtile_inputについて、「不明」と判定すべきかを求める
 * MapLibre expression。該当する入力を持たない軸はnull（＝不明状態を持たない、
 * 従来どおりstep色分けのみでよい）。
 *
 * 改善計画T297: categories材料（N値文字列、例: highway）は、プロパティが欠損している
 * 場合に加えて、**値はあるがcategoriesに未登録**の場合も「不明」に含める（以前は
 * プロパティ欠損のみを見ており、値が未登録のケースを見落としていた——例:
 * highway="footway"はプロパティとしては常に存在するため、`!has(property)`だけでは
 * 一生「不明」にならなかった）。backend側の評価（`domain/axis_definitions.py:
 * evaluate_axis_scalar`のCategoricalShape分岐）は、未登録値も`mapping.get(value, None)`
 * によりNone（評価不能）を返す——required=Trueの材料でNoneは軸全体を評価不能にする
 * ため、「未登録値=寄与0（最良側）」ではなく「未登録値=評価不能（不明）」が
 * 評価側の実際の意味論であり、地図表示側もこれに合わせる。categoriesを持たない
 * 真偽値材料（例: surface_good）は従来どおりプロパティ欠損のみで判定する
 * （欠損以外の「未登録値」という状態がそもそも存在しないため）。 */
export function buildAxisRampUnknownExpression(axis: RampAxis): unknown[] | null {
  const checks = axis.tileInputs
    .filter((input) => input.hasUnknownFallback)
    .map((input) => {
      if (input.categories) {
        const knownValuePairs = Object.keys(input.categories).flatMap((key) => [key, false]);
        return ["match", ["coalesce", ["get", input.property], "__unknown__"], ...knownValuePairs, true];
      }
      return ["!", ["has", input.property]];
    });
  if (checks.length === 0) return null;
  return checks.length === 1 ? checks[0] : ["any", ...checks];
}

/** 数値材料はΣ property×weight、真偽値材料（改善計画T278）は
 * ["case", 真偽比較, trueValue, falseValue]、N値文字列材料・自己変換材料（改善計画T292）は
 * それぞれ["match", ...]・["interpolate", ...]で寄与値を組み立てるMapLibre expression。 */
export function buildAxisRampValueExpression(axis: RampAxis): unknown[] {
  const terms = axis.tileInputs.map((input) => {
    if (input.boolean) {
      const comparison = input.invert
        ? ["!=", ["get", input.property], true]
        : ["==", ["get", input.property], true];
      return ["case", comparison, input.trueValue ?? 0, input.falseValue ?? 0];
    }
    if (input.categories) {
      const value = [
        "match",
        ["coalesce", ["get", input.property], "__unknown__"],
        ...Object.entries(input.categories).flatMap(([key, score]) => [key, score * input.weight]),
        0,
      ];
      return value;
    }
    if (input.breakpoints) {
      // タイルプロパティが欠損している場合、backendのrequired=False材料と同じ
      // 「寄与0」規約に合わせる（coalesceでbreakpoints[0][0]へ倒すとinterpolateが
      // breakpoints[0][1]（例: -1）を返してしまい、欠損=寄与0の規約と食い違うため
      // レビュー指摘で修正）。
      const interpolated = ["interpolate", ["linear"], ["get", input.property], ...input.breakpoints.flat()];
      const value = input.weight === 1 ? interpolated : ["*", interpolated, input.weight];
      return ["case", ["!", ["has", input.property]], 0, value];
    }
    return ["*", ["coalesce", ["get", input.property], 0], input.weight];
  });
  if (terms.length === 1) return terms[0];
  return ["+", ...terms];
}

/** thresholdsによるstep色分けのMapLibre expression。hasUnknownFallbackなtile_inputの
 * プロパティが欠損している場合は、step色分けより先にCOLOR_UNKNOWN（灰色）で塗る
 * （レビュー指摘の修正: 以前はfalseValueへ自動的に倒れ「不明」が「悪い」側の色で
 * 誤表示されていた）。 */
export function buildAxisRampColorExpression(axis: RampAxis): unknown[] {
  const bandCount = axis.thresholds.length + 1;
  const stepExpression: unknown[] = ["step", buildAxisRampValueExpression(axis), rampColorForBand(0, bandCount)];
  axis.thresholds.forEach((threshold, index) => {
    stepExpression.push(threshold, rampColorForBand(index + 1, bandCount));
  });
  const unknownExpression = buildAxisRampUnknownExpression(axis);
  if (unknownExpression === null) return stepExpression;
  return ["case", unknownExpression, COLOR_UNKNOWN, stepExpression];
}

/** 段階の下限（inclusive）・上限（exclusive）。両端はnull（下限/上限なし）。
 * buildAxisRampLegendとMapLayersPanel等の凡例UI・setStaticOverlayFiltersの絞り込みが
 * 同じ境界定義を共有する（片側importで揃える、設計原則2）。 */
function axisRampBand(thresholds: readonly number[], index: number): { lower: number | null; upper: number | null } {
  return {
    lower: index === 0 ? null : thresholds[index - 1],
    upper: index === thresholds.length ? null : thresholds[index],
  };
}

/** 段階ラベル（例: 「1回/km未満」「1〜2回/km」「4回/km以上」）。thresholds.length+1件。 */
function axisRampBandLabel(axis: RampAxis, lower: number | null, upper: number | null): string {
  if (lower === null) return `${upper}${axis.unit}未満`;
  if (upper === null) return `${lower}${axis.unit}以上`;
  return `${lower}〜${upper}${axis.unit}`;
}

/** ramp軸の凡例（改善計画: 地図アイコンチップのグルーピング・研究タブ整理・停止/事故密度の
 * 凡例追加）。既存レイヤー（車ストレス・自転車インフラ等、staticAttributeLayers.ts参照）と
 * 同じLegendEntry型で返すことで、色スウォッチ付きの凡例チェックボックス
 * （MapLayersPanel.tsx: renderLegendCheckboxes）・地図チップの▶展開凡例
 * （MapOverlayControls.tsx: legendDetails）・実際の絞り込み
 * （MapView.tsx: setStaticOverlayFilters、buildCombinedLegendFilterExpression）を
 * 他レイヤーと同じ仕組みでそのまま共有できる（新規UIコンポーネント不要）。
 * filterはbuildAxisRampValueExpression（地図の色分けが使うのと同じ線形結合）への
 * 範囲比較で、実際に塗られる色と凡例が食い違わないようにする。
 * hasUnknownFallbackな軸（例: surface_q）は末尾に「不明」エントリを追加し（既存の
 * staticAttributeLayers.tsの分類レイヤーと同じ「不明・他」の扱い方）、他の段階の
 * filterには「不明ではない」条件を足して二重分類を防ぐ（レビュー指摘の修正）。 */
export function buildAxisRampLegend(axis: RampAxis): LegendEntry[] {
  const valueExpression = buildAxisRampValueExpression(axis);
  const unknownExpression = buildAxisRampUnknownExpression(axis);
  const bandCount = axis.thresholds.length + 1;
  const bands = Array.from({ length: bandCount }, (_, index) => {
    const { lower, upper } = axisRampBand(axis.thresholds, index);
    const filterParts: unknown[] = ["all"];
    if (unknownExpression !== null) filterParts.push(["!", unknownExpression]);
    if (lower !== null) filterParts.push([">=", valueExpression, lower]);
    if (upper !== null) filterParts.push(["<", valueExpression, upper]);
    return {
      key: `${axis.axisId}-${index}`,
      label: axisRampBandLabel(axis, lower, upper),
      color: rampColorForBand(index, bandCount),
      filter: filterParts,
    };
  });
  if (unknownExpression === null) return bands;
  return [
    ...bands,
    {
      key: `${axis.axisId}-unknown`,
      label: "不明",
      color: COLOR_UNKNOWN,
      filter: ["all", unknownExpression],
      isFallback: true,
    },
  ];
}
