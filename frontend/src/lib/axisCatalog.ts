/** `GET /api/axis-catalog`の応答から、画面が読む形の軸カタログを導く。
 *
 * **フックではなくここに置く**——導出は純関数で、フックが持っているのは「いつ取りに行き、
 * 誰と共有するか」だけ。同居させると、導出を確かめたい側がストアごと引き回すことになる。
 */
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { preferenceAxisFromCatalog } from "@/lib/evaluationAxes";
import type { AxisCatalogEntry, RoutePreferenceWeights } from "@/types/route";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import {
  axisLabelsFromCatalogAxes,
  dedicatedWayValueAxesFromCatalogAxes,
  rampAxesFromCatalogAxes,
  type DedicatedWayValueAxis,
  type RampAxis,
} from "@/lib/mapDisplay/axisLayers";
import { secondaryAxesFromCatalogAxes, type SecondaryAxisSummary } from "@/lib/secondaryAxes";
import {
  ROUTE_STYLE_MODES_WITHOUT_AXES,
  routeStyleModesFromCatalogAxes,
  type RouteStyleMode,
} from "@/lib/mapDisplay/routeStyleModes";

/** 軸カタログ。`GET /api/axis-catalog`の応答から導いた、画面が読む形。 */
export interface AxisCatalog {
  /** axisId・label・descriptionの一覧。 */
  axes: readonly PreferenceAxisDef[];
  /** axis_idから既定重みを引く。未知のaxis_idには0を返す。 */
  defaultWeights: RoutePreferenceWeights;
  /** 地図のramp表示を持つ軸。 */
  rampAxes: readonly RampAxis[];
  /** 専用のway_id→値配信レイヤーを持つ軸。レイヤー登録・カタログ・可視性・フェッチの
   * 全てがこの一覧から導出される。 */
  dedicatedAxes: readonly DedicatedWayValueAxis[];
  /** axis_id→表示名の辞書。 */
  axisLabels: Record<string, string>;
  /** axis_id→識別色。どの画面でも同じ軸は同じ色になるよう、ここで1回だけ決める。 */
  axisColors: Readonly<Record<string, string>>;
  /** 事故データの収録年（backendの取込の宣言そのもの）。地図の説明文が範囲を書くのに使う。
   * フェッチ完了まで・エラー時は空で、その間は説明文が年に触れない。 */
  accidentYears: readonly number[];
  /** 二次軸(推定指標)一覧。地図チップの「推定指標」グループが読む。 */
  secondaryAxes: readonly SecondaryAxisSummary[];
  /** ルート地図の色分けモード一覧。公開軸を無条件で含む。取得できるまでは軸に依らない
   * モードだけ（`ROUTE_STYLE_MODES_WITHOUT_AXES`）。 */
  routeStyleModes: readonly RouteStyleMode[];
  /** フロントが使う較正値（id → いま効いている値）。backendの`domain/tuning.py`が宣言し、
   * 管理画面から変えた値が再デプロイなしにここへ届く。取得できるまではビルド時生成物
   * （route-generate-config.json）の既定。 */
  clientTuning: Readonly<Record<string, number>>;
  /** GET /api/axis-catalogの取得が成功し、他フィールドが実際のDB由来の値であることを表す。
   * falseの間（未取得・取得失敗）は他フィールドが空のため、「軸スタジオの現在の公開軸集合と
   * 一致している」ことを要求する処理（route_preferenceのキー整合等）は、このフラグで
   * 未確定状態を区別しなければならない。取得成功時にaxesが0件（全軸非公開）であっても
   * trueになる——0件も確定した実際の状態である。 */
  loaded: boolean;
  /** GET /api/axis-catalogの取得を試みて失敗し、まだ一度も成功していないことを表す。
   * `loaded`とは同時にtrueにならない（未取得=両方false、成功=loadedのみ、失敗=failedのみ）。
   * この状態では他フィールドが空のため、`loaded`を要求する処理
   * （route_preference・lens_axis_idの送信）は黙って省略される。利用者へ何も知らせないと
   * 「重みを設定したのに反映されない」ことに気づけないため、UIはこのフラグで失敗と
   * 再試行導線を見せる（RouteSettingsPanel.tsx）。 */
  failed: boolean;
}

/** フロントが読む較正値のid。**ここに並んだidは、ビルド時生成物
 * （route-generate-config.json）に必ず在る**ことをテストが固定する——backendの宣言から
 * 消す/綴りを変えると、フロントは引けないまま黙って別の値で動くため。 */
export const CLIENT_TUNING_IDS = {
  /** 区間を割る下限（km）。これ未満の共有区間では割らない（`features/route/routeSplice.ts`）。 */
  minStretchKm: "splice.min_stretch_km",
} as const;

/** 較正値を1つ引く。**引けなければ`undefined`**——ここで既定を作らない。既定を作ると、
 * 宣言から消えた値を「0」等として使い続け、較正したのとは別の挙動で黙って動く。 */
export function clientTuningValue(catalog: AxisCatalog, id: string): number | undefined {
  return Object.hasOwn(catalog.clientTuning, id) ? catalog.clientTuning[id] : undefined;
}

/** 軸の識別色。色に意味は持たせず、色相環を軸数で等分して表示順に割り当てる（軸数が
 * いくつでも衝突せず、重みを0にした軸があっても他の軸の色は動かない）。 */
function axisColorsOf(axes: readonly PreferenceAxisDef[]): Record<string, string> {
  return Object.fromEntries(axes.map((axis, index) => [axis.axisId, `hsl(${(index * 360) / axes.length}, 62%, 55%)`]));
}

// 軸は`GET /api/axis-catalog`が配るものだけを使う。**ビルド時の写しを持たない**——
// 持つと、APIが失敗したときに古い軸で地図が描かれ、伝播の失敗が見えなくなる。
// 取得できるまでは軸が1つも無い状態で、呼び出し側は`loaded`で区別する。
export const EMPTY_CATALOG: AxisCatalog = {
  clientTuning: routeGenerateConfig.client_tuning,
  axes: [],
  defaultWeights: {},
  rampAxes: [],
  dedicatedAxes: [],
  axisLabels: {},
  axisColors: {},
  accidentYears: [],
  secondaryAxes: [],
  routeStyleModes: ROUTE_STYLE_MODES_WITHOUT_AXES,
  loaded: false,
  failed: false,
};

export function axisCatalogFromResponse(
  entries: readonly AxisCatalogEntry[],
  materialRuntimeScales: Readonly<Record<string, number>>,
  clientTuning: Readonly<Record<string, number>>,
  accidentYears: readonly number[],
): AxisCatalog {
  const defaultWeights: RoutePreferenceWeights = {};
  for (const entry of entries) defaultWeights[entry.axis_id] = entry.default_weight;
  const axes: PreferenceAxisDef[] = entries.map(preferenceAxisFromCatalog);
  return {
    clientTuning,
    axes,
    defaultWeights,
    rampAxes: rampAxesFromCatalogAxes(entries, materialRuntimeScales),
    dedicatedAxes: dedicatedWayValueAxesFromCatalogAxes(entries),
    axisLabels: axisLabelsFromCatalogAxes(entries),
    axisColors: axisColorsOf(axes),
    accidentYears,
    secondaryAxes: secondaryAxesFromCatalogAxes(entries),
    routeStyleModes: routeStyleModesFromCatalogAxes(entries),
    loaded: true,
    failed: false,
  };
}
