// 軸カタログ（`GET /api/axis-catalog`）の軸を、地図が読む形（ramp軸・専用配信軸）へ移す。
//
// 軸の地図表示は`domain/axis_display.py: axis_display_for()`が軸スタジオの公開状態から都度作り、
// **ビルド時の写しは持たない**——写しを持つと、API障害時に古い軸で地図が描かれ、伝播の失敗が
// 見えなくなる。取得できるまでは軸0件で描く（`hooks/useAxisCatalog.ts`）。軸は軸スタジオで公開すれば、
// 材料がタイルにある限り再デプロイなしに地図のレイヤーとして現れる。

import type { DedicatedWayValueDisplay } from "./dedicatedWayValueLayer";
import type { AxisCatalogEntry } from "@/types/route";

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
  /** 地図チップの略名（4文字以下、軸カタログの`chip_label`由来）。未設定はlabel（正式名）へ
   * フォールバックする（mapLayers.ts参照）。 */
  chipLabel?: string;
  /** 段階ごとの体感ラベル（軸自身のデータ、display_band_labels_override由来）。要素数が
   * thresholds.length+1と一致する間だけ、凡例（`features/map/view/lens.ts: buildAxisRampLegend`）が
   * 数値レンジの前に添える。 */
  bandLabelsOverride?: readonly string[];
}

/** 公開軸の表示名の辞書（軸id→軸定義の`label`）。**ここに無い軸idを画面へ出さない**——
 * 引けなかったときに軸idで埋めると、内部名（例: `wind`）がそのまま画面に出る。
 * 軸の名前は軸定義の`label`だけが持つ（地図表示の`display.label`は地図に出る軸にしか無い）。 */
export function axisLabelsFromCatalogAxes(axes: readonly AxisCatalogEntry[]): Record<string, string> {
  return Object.fromEntries(axes.map((axis) => [axis.axis_id, axis.label]));
}

/** `runtimeScales`（GET /api/axis-catalogのmaterial_runtime_scales、tile property名→スケール係数）は、
 * `needs_runtime_scale`なtile_inputの`weight`へ構築時に一度だけ掛け合わせて解決する（地図の式は
 * 解決済みのweightだけを見る）。
 * 該当するtile propertyのスケール係数がまだ解決できていない場合（収録年数0件等で
 * backendがキーを含めなかった場合）はweight=0として寄与を無くす（安全側のデグレード。
 * RegionService.get_accident_years_coveredのdocstring参照）。 */
export function rampAxesFromCatalogAxes(
  axes: readonly AxisCatalogEntry[],
  runtimeScales: Readonly<Record<string, number>> = {},
): RampAxis[] {
  return axes
    .filter((axis) => axis.display.kind === "ramp")
    .map((axis) => ({
      axisId: axis.axis_id,
      label: axis.display.label,
      category: axis.display.category,
      tileInputs: (axis.display.tile_inputs ?? []).map((input) => ({
        property: input.property,
        weight: input.needs_runtime_scale ? input.weight * (runtimeScales[input.property] ?? 0) : input.weight,
        boolean: input.boolean,
        trueValue: input.true_value,
        falseValue: input.false_value,
        hasUnknownFallback: input.has_unknown_fallback,
        categories: input.categories ?? undefined,
        breakpoints: input.breakpoints ?? undefined,
      })),
      thresholds: axis.display.thresholds ?? [],
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

export function dedicatedWayValueAxesFromCatalogAxes(axes: readonly AxisCatalogEntry[]): DedicatedWayValueAxis[] {
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
