// 軸カタログ（`GET /api/axis-catalog`）の軸を、地図が読む形（ramp軸・専用配信軸）へ移す。軸の共通の項目は
// `catalogAxis.ts`が行から移し、ここは地図の表示の項目だけを足す。
//
// 軸の地図表示は`domain/axis_display.py: axis_display_for()`が軸スタジオの公開状態から都度作り、
// **ビルド時の写しは持たない**——写しを持つと、API障害時に古い軸で地図が描かれ、伝播の失敗が
// 見えなくなる。取得できるまでは軸0件で描く（`hooks/useAxisCatalog.ts`）。軸は軸スタジオで公開すれば、
// 材料がタイルにある限り再デプロイなしに地図のレイヤーとして現れる。

import type { DedicatedWayValueDisplay } from "./dedicatedWayValueLayer";
import type { MapLegendScale } from "./valueScale";
import { catalogAxisFromEntry, type CatalogAxis } from "@/lib/catalogAxis";
import type { AxisCatalogEntry } from "@/types/route";

interface AxisTileInput {
  property: string;
  weight: number;
  /** true=真偽値材料。weightは無視し、trueValue/falseValueで寄与値を直接指定する。 */
  boolean?: boolean;
  trueValue?: number;
  falseValue?: number;
  /** true=タイルプロパティの欠損が「true/falseどちらでもない不明」を表す（例:
   * 未分類の路面）。欠損時はtrueValue/falseValueどちらにも倒さず、
   * 灰色「不明」表示にする（registry.py: TileInputSpec.has_unknown_fallback参照）。既定false（欠損=falseとみなしてよい材料、例:
   * lit・has_tunnel⟵tunnel）はtrueValue/falseValueへ通常どおり倒す。 */
  hasUnknownFallback?: boolean;
  /** N値文字列材料（例: highway）。タイルプロパティの
   * 文字列値をこの辞書で引いた点数×weightを寄与値とする。未登録値の道は「不明」
   * （registry.py: TileInputSpec.categories参照）。 */
  categories?: Record<string, number>;
  /** 自己変換材料（例: maxspeed_kmh/lanes_count）。材料自身が持つ
   * 区分線形breakpointsでタイルプロパティの生値をinterpolateし、小数1桁へ丸めた値×weightを
   * 寄与値とする（registry.py: TileInputSpec.breakpoints参照）。 */
  breakpoints?: readonly (readonly [number, number])[];
  /** true=タイルの生値を材料の値へ換算する係数（`tile_runtime_scales`）が届いていない。どの道でも
   * この材料の寄与を出せないので、どの道でも軸の値が「不明」になる（寄与0として塗ると、材料が無いのに
   * 最良側の色で塗る）。 */
  scaleMissing?: boolean;
}

/** 地図のramp表示を持つ軸。 */
export interface RampAxis extends CatalogAxis {
  tileInputs: readonly AxisTileInput[];
  /** 昇順の色段階境界値。値 < thresholds[0] が最も低い段階 */
  thresholds: readonly number[];
  /** 凡例が`thresholds`を書く目盛り（同じ件数・同じ順。ルート後の線の凡例と同じ文字になる）。 */
  legend: MapLegendScale;
  /** 段階ごとの体感ラベル（軸自身のデータ、display_band_labels_override由来）。要素数が
   * thresholds.length+1と一致する間だけ、凡例（`features/map/view/lens.ts: buildAxisRampLegend`）が
   * 数値レンジの前に添える。 */
  bandLabelsOverride?: readonly string[];
}

/** 公開軸の表示名の辞書（軸id→軸定義の`label`）。**ここに無い軸idを画面へ出さない**——
 * 引けなかったときに軸idで埋めると、内部名（例: `wind`）がそのまま画面に出る。
 * 軸の名前は軸定義の`label`だけが持つ。 */
export function axisLabelsFromCatalogAxes(axes: readonly AxisCatalogEntry[]): Record<string, string> {
  return Object.fromEntries(axes.map((axis) => [axis.axis_id, axis.label]));
}

/** `runtimeScales`（GET /api/axis-catalogのtile_runtime_scales、tile property名→スケール係数）は、
 * `needs_runtime_scale`なtile_inputの`weight`へ構築時に一度だけ掛け合わせて解決する（地図の式は
 * 解決済みのweightだけを見る）。
 * 該当するtile propertyのスケール係数が届いていない場合（事故データの収録年を読めず、backendが
 * キーを含めなかった場合）は、その入力を`scaleMissing`にする——寄与を0にすると、材料の値が無いのに
 * 最良側の色で塗る。 */
export function rampAxesFromCatalogAxes(
  axes: readonly AxisCatalogEntry[],
  runtimeScales: Readonly<Record<string, number>>,
): RampAxis[] {
  return axes
    .filter((axis) => axis.display.kind === "ramp")
    .map((axis) => ({
      ...catalogAxisFromEntry(axis),
      tileInputs: axis.display.tile_inputs.map((input) => ({
        property: input.property,
        ...(input.needs_runtime_scale
          ? Object.hasOwn(runtimeScales, input.property)
            ? { weight: input.weight * runtimeScales[input.property] }
            : { weight: 0, scaleMissing: true }
          : { weight: input.weight }),
        boolean: input.boolean,
        trueValue: input.true_value,
        falseValue: input.false_value,
        hasUnknownFallback: input.has_unknown_fallback,
        categories: input.categories ?? undefined,
        breakpoints: input.breakpoints ?? undefined,
      })),
      thresholds: axis.display.thresholds,
      legend: axis.map_paint.legend,
      bandLabelsOverride: axis.display_band_labels_override ?? undefined,
    }));
}

/** mapLayers.ts のレイヤーID（チップ・パネル・visibility状態のキー） */
export type AxisMapLayerId = `axis:${string}`;

export function axisMapLayerId(axisId: string): AxisMapLayerId {
  return `axis:${axisId}`;
}

/** 専用のフィーチャー→値配信レイヤーを持つ軸（`dedicated_way_value_layer=true`）。
 * ramp軸に対する`RampAxis`と同じ位置付けの、軸カタログ由来の地図向けビュー。
 * この型があることで、レイヤー登録・カタログ・可視性・フェッチのすべてを軸idの
 * ハードコードなしに導出できる（3件目の軸を軸スタジオで公開しただけで
 * 地図に現れる。ただし配信実装本体はbackend側の登録が別途必要）。 */
export interface DedicatedWayValueAxis extends CatalogAxis {
  /** 専用way値配信APIへ添えるクエリパラメータ（軸カタログの`dynamic_way_value_conditions`）。`features/map/useDedicatedWayValues.ts`が
   * 「どの軸のフェッチに時刻・想定速度を乗せるか」をaxis_idの分岐ではなくここから決める
   * （乗せない入力は依存配列からも外れるため、時刻を動かしても時刻非依存の軸は再フェッチしない）。 */
  needsTime: boolean;
  needsBearing: boolean;
  needsSpeed: boolean;
  /** 配信が、走行方位で値の決まらない道（値がnull）を返しうるか。trueの軸だけ凡例に「向きで決まらない」の行を持つ。 */
  undeterminedByBearing: boolean;
  /** 地図に塗るときの表示宣言。軸と同じカタログの行から作るため、軸が在れば必ず在る。 */
  display: DedicatedWayValueDisplay;
}

export function dedicatedWayValueAxesFromCatalogAxes(axes: readonly AxisCatalogEntry[]): DedicatedWayValueAxis[] {
  return axes
    .filter((axis) => axis.dedicated_way_value_layer)
    .map((axis) => ({
      ...catalogAxisFromEntry(axis),
      needsTime: axis.dynamic_way_value_conditions.includes("at"),
      needsBearing: axis.dynamic_way_value_conditions.includes("bearing_deg"),
      needsSpeed: axis.dynamic_way_value_conditions.includes("speed_kmh"),
      undeterminedByBearing: axis.dynamic_way_value_undetermined_by_bearing,
      display: {
        kind: axis.map_paint.value.kind,
        boundaries: axis.map_paint.thresholds,
        legend: axis.map_paint.legend,
        bandLabels: axis.display_band_labels_override ?? undefined,
      },
    }));
}
