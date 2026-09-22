"use client";

import { useEffect, useSyncExternalStore } from "react";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { preferenceAxisFromCatalog } from "@/lib/evaluationAxes";
import type { AxisCatalogEntry, RoutePreferenceWeights } from "@/types/route";
import { getAxisCatalog } from "@/services/axisCatalogApi";
import { setTileVersions } from "@/services/regionApi";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import {
  axisLabelsFromCatalogAxes,
  dedicatedWayValueAxesFromCatalogAxes,
  rampAxesFromCatalogAxes,
  type CatalogAxis,
  type DedicatedWayValueAxis,
  type RampAxis,
} from "@/components/Map/axisLayers";
import { secondaryAxesFromCatalogAxes, type SecondaryAxisSummary } from "@/components/Map/secondaryAxes";
import {
  ROUTE_STYLE_MODES_WITHOUT_AXES,
  routeStyleModesFromCatalogAxes,
  type RouteStyleMode,
} from "@/components/Map/routeStyleModes";

interface AxisCatalog {
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
  /** 区間を割る下限（km）。これ未満の共有区間では割らない（`lib/routeSplice.ts`）。 */
  minStretchKm: "splice.min_stretch_km",
} as const;

/** 較正値を1つ引く。**引けなければ`undefined`**——ここで既定を作らない。既定を作ると、
 * 宣言から消えた値を「0」等として使い続け、較正したのとは別の挙動で黙って動く。 */
export function clientTuningValue(catalog: AxisCatalog, id: string): number | undefined {
  return Object.hasOwn(catalog.clientTuning, id) ? catalog.clientTuning[id] : undefined;
}

// 軸は`GET /api/axis-catalog`が配るものだけを使う。**ビルド時の写しを持たない**——
// 持つと、APIが失敗したときに古い軸で地図が描かれ、伝播の失敗が見えなくなる。
// 取得できるまでは軸が1つも無い状態で、呼び出し側は`loaded`で区別する。
const EMPTY_CATALOG: AxisCatalog = {
  clientTuning: routeGenerateConfig.client_tuning,
  axes: [],
  defaultWeights: {},
  rampAxes: [],
  dedicatedAxes: [],
  axisLabels: {},
  accidentYears: [],
  secondaryAxes: [],
  routeStyleModes: ROUTE_STYLE_MODES_WITHOUT_AXES,
  loaded: false,
  failed: false,
};

/** GET /api/axis-catalogのAxisCatalogEntry（displayが必ず非null）を、axisLayers.ts/
 * secondaryAxes.tsの変換関数が受け取れるCatalogAxis形（displayが`{...} | null`、
 * ビルド時静的json由来）へ合わせる。tile_inputs/thresholdsはbackendで既定値付き
 * （常に配列で返るが、OpenAPI生成型は既定値ありのフィールドをoptionalとしてマークするため
 * 型上はundefinedを許容する）ため、undefined時は空配列を補う。 */
function toCatalogAxis(entry: AxisCatalogEntry): CatalogAxis {
  return {
    axis_id: entry.axis_id,
    label: entry.label,
    description: entry.description,
    raw_value_unit: entry.raw_value_unit,
    material_breakdown: entry.material_breakdown,
    category: entry.category,
    display: {
      kind: entry.display.kind,
      label: entry.display.label,
      category: entry.display.category,
      tile_inputs: (entry.display.tile_inputs ?? []).map((input) => ({
        property: input.property,
        weight: input.weight,
        boolean: input.boolean,
        true_value: input.true_value,
        false_value: input.false_value,
        has_unknown_fallback: input.has_unknown_fallback,
        categories: input.categories ?? null,
        breakpoints: input.breakpoints ?? null,
        needs_runtime_scale: input.needs_runtime_scale,
      })),
      thresholds: entry.display.thresholds ?? [],
      unit: entry.display.unit,
      note: entry.display.note,
    },
    primary_attribute_ids: entry.primary_attribute_ids,
    icon_id: entry.icon_id,
    chip_label: entry.chip_label,
    panel_hint: entry.panel_hint,
    show_map_icon: entry.show_map_icon,
    shape: entry.shape,
    display_thresholds_override: entry.display_thresholds_override,
    display_band_labels_override: entry.display_band_labels_override,
    dedicated_way_value_layer: entry.dedicated_way_value_layer,
    map_value_kind: entry.map_value_kind,
    map_value_unit: entry.map_value_unit,
    map_value_thresholds: entry.map_value_thresholds,
    dynamic_way_value_needs_time: entry.dynamic_way_value_needs_time,
    dynamic_way_value_needs_bearing: entry.dynamic_way_value_needs_bearing,
    dynamic_way_value_needs_speed: entry.dynamic_way_value_needs_speed,
  };
}

function buildCatalog(
  entries: readonly AxisCatalogEntry[],
  materialRuntimeScales: Readonly<Record<string, number>>,
  clientTuning: Readonly<Record<string, number>>,
  accidentYears: readonly number[],
): AxisCatalog {
  const defaultWeights: RoutePreferenceWeights = {};
  for (const entry of entries) defaultWeights[entry.axis_id] = entry.default_weight;
  const catalogAxes = entries.map(toCatalogAxis);
  // 静的フォールバック（evaluationAxes.ts: PREFERENCE_AXES）と同じ変換を使う。
  // 別々に組み立てると、片方にだけフィールドを書き足した状態が型検査を通ってしまう
  // （`PreferenceAxisDef`のフィールドはすべてoptionalのため）。
  const axes: PreferenceAxisDef[] = catalogAxes.map(preferenceAxisFromCatalog);
  return {
    clientTuning,
    axes,
    defaultWeights,
    rampAxes: rampAxesFromCatalogAxes(catalogAxes, materialRuntimeScales),
    dedicatedAxes: dedicatedWayValueAxesFromCatalogAxes(catalogAxes),
    axisLabels: axisLabelsFromCatalogAxes(catalogAxes),
    accidentYears,
    secondaryAxes: secondaryAxesFromCatalogAxes(catalogAxes),
    routeStyleModes: routeStyleModesFromCatalogAxes(catalogAxes),
    loaded: true,
    failed: false,
  };
}

// page.tsxとRouteSettingsPanel.tsx（page.tsxの子として初回描画時からマウントされる）が
// 同時にこのフックを呼びうるため、同時に飛んでいる（未解決の）フェッチだけをこの
// モジュールレベル変数で共有し、解決/失敗したら即座にクリアする（解決後の結果を
// 永続キャッシュしない——軸スタジオでの公開操作を再デプロイなしに反映するため、
// 後続の別マウント[例: モバイルのBottomSheetでタブを開き直す]では改めて最新を取得する）。
let inFlightCatalogFetch: ReturnType<typeof getAxisCatalog> | null = null;

function fetchAxisCatalogDeduped(): ReturnType<typeof getAxisCatalog> {
  if (inFlightCatalogFetch) return inFlightCatalogFetch;
  const request = getAxisCatalog().finally(() => {
    if (inFlightCatalogFetch === request) inFlightCatalogFetch = null;
  });
  inFlightCatalogFetch = request;
  return request;
}

// 上記の「同時に飛んでいる場合」の重複排除だけでは、page.tsxが先にマウント・フェッチ
// 完了した後にRouteSettingsPanel.tsxが再マウント（モバイルのBottomSheetでタブを
// 開き直す等）してフェッチし直すケースを救えない。解決済みカタログをモジュールレベルの
// 単一ストアとして持ち、全呼び出し元がuseSyncExternalStoreで同じオブジェクト参照を
// 購読することで、2インスタンス間で`axes`配列が食い違うことは構造的に起こらない
// （どちらかのフェッチが解決すれば全呼び出し元へ即座に反映される）。
let sharedCatalog: AxisCatalog = EMPTY_CATALOG;
const catalogListeners = new Set<() => void>();

function publishCatalog(next: AxisCatalog): void {
  sharedCatalog = next;
  catalogListeners.forEach((listener) => listener());
}

function subscribeToCatalog(listener: () => void): () => void {
  catalogListeners.add(listener);
  return () => {
    catalogListeners.delete(listener);
  };
}

function getCatalogSnapshot(): AxisCatalog {
  return sharedCatalog;
}

function getCatalogServerSnapshot(): AxisCatalog {
  return EMPTY_CATALOG;
}

/** テスト専用: モジュールレベルの共有ストアをリセットする。本番コードからは呼ばない。 */
export function __resetAxisCatalogStoreForTests(): void {
  sharedCatalog = EMPTY_CATALOG;
  inFlightCatalogFetch = null;
}

function loadAxisCatalog(): void {
  fetchAxisCatalogDeduped()
    .then((response) => {
      // 取得成功時はaxesが空でもそのままbuildCatalogへ渡す（フェッチ未完了・失敗時のみ
      // 静的フォールバックに留まる、という区別に一本化する——「まだ取得中/取得失敗」と
      // 「取得成功したが軸が0件（全軸非公開）」を同一視すると、軸スタジオで全軸を
      // 非公開にしても静的フォールバックの軸が表示され続けてしまう）。
      // タイル世代は地図のソースURLに入るため、カタログを公開する前に渡す
      // （`hasTileVersions()`がtrueになってから地図のレイヤーが作られる）。
      setTileVersions(response.tile_versions ?? {});
      publishCatalog(
        buildCatalog(
          response.axes,
          response.material_runtime_scales ?? {},
          // 取れた値が空でも既定へ戻さない（宣言が1件も持たない状態と区別が付かないため、
          // 空なら空のまま渡す）。使う側は自分が要るidが無ければ既定を持たない。
          response.client_tuning ?? {},
          response.accident_years ?? [],
        ),
      );
    })
    .catch(() => {
      // 他の呼び出し元が既に取得済みの正常なカタログは、この呼び出し元だけの失敗で
      // 巻き戻さない。まだ一度も成功していない場合だけ、失敗したことをUIへ見せられるよう
      // フラグを立てる（フェッチ自体の記録はfetchJsonがdebugLogへ済ませている）。
      if (!sharedCatalog.loaded && !sharedCatalog.failed) {
        publishCatalog({ ...sharedCatalog, failed: true });
      }
    });
}

/** 軸カタログの取得をやり直す（`failed`状態からの明示的な再試行導線用）。
 * 既に成功していれば何もしない。再取得中は`failed`を下ろし、UIが「取得中」へ戻る。 */
export function retryAxisCatalogFetch(): void {
  if (sharedCatalog.loaded) return;
  publishCatalog({ ...sharedCatalog, failed: false });
  loadAxisCatalog();
}

/** 軸カタログ。マウント時に一度`GET /api/axis-catalog`を取得し、軸スタジオがDBへ
 * 追加・公開した軸を反映する（is_publishedの切替も含め、再デプロイ不要で即座に
 * 反映される）。取得完了までとエラー時はビルド時点の静的カタログ（フォールバック）を
 * 返すため、呼び出し側は常に何かしらの一覧を受け取れる（loading状態を個別に扱う
 * 必要がない）。
 *
 * フォールバック中（`loaded=false`）の値を「軸スタジオの現在の公開軸集合」と取り違えて
 * 送信すると、実際の公開軸と食い違うroute_preferenceを送ってしまい422になりうる
 * （`page.tsx: handleGenerate`参照）。フォールバック値をUIの初期描画・地図レイヤーの初期状態
 * 用に使うことは問題ないが、APIへ送るペイロードの構築等「軸スタジオの現在の状態と一致して
 * いなければならない」処理では、必ず`loaded`を確認すること。このフックはaxis_idから
 * 観測/推定/動的カテゴリを引く手段を提供しない——backendのGET /api/axis-catalog
 * レスポンス自体には引き続き`category`フィールドが含まれる（他用途のため）が、
 * このフックはそれを消費しない。 */
export function useAxisCatalog(): AxisCatalog {
  useEffect(() => {
    loadAxisCatalog();
  }, []);

  return useSyncExternalStore(subscribeToCatalog, getCatalogSnapshot, getCatalogServerSnapshot);
}
