import type { AxisInspectorResult } from "@/types/traffic";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { debugLog } from "@/lib/debugLog";
import { formatErrorDetail } from "@/lib/apiError";

interface PostRequestOptions {
  category: string;
  /** 「{errorLabel}に失敗しました」の形でエラーメッセージに使う対象名。 */
  errorLabel: string;
  /** 指定時はJSONボディとして送る（Content-Type: application/jsonも自動で付く）。
   * 省略時はボディ無しのPOST（refreshBasemapCacheのような操作系エンドポイント向け）。 */
  body?: unknown;
  timeoutMs?: number;
}

// 改善計画T470: fetchAxisInspector・refreshBasemapCacheが、fetch()自体の失敗（通信エラー）→
// !response.okの判定→エラーボディ解析→整形したErrorをthrow、という同じ約20行のPOST用骨格を
// 独立に持っていた（lib/fetchJson.tsのGET専用ラッパーと同型だが、POSTはボディ・成功時の
// レスポンス解釈が呼び出しごとに異なるため、GET側のfetchJsonとは別に本ファイル内へ持つ——
// routeApi.ts: postJsonと同じ判断）。成功時のレスポンス本体解析・成功ログのfields組み立ては
// 呼び出し側ごとに異なる（fetchAxisInspectorはJSONボディを持ちcompositeを追加ログするが
// refreshBasemapCacheはボディ無しでレスポンス本体も読まない）ため、ここでは「fetch→
// 通信エラー処理→ok確認→失敗時throw」までを共通化し、成功時のResponseはそのまま返す。
async function postAndCheckOk(
  path: string,
  { category, errorLabel, body, timeoutMs = 15000 }: PostRequestOptions,
): Promise<{ response: Response; durationMs: number; requestId: string | null }> {
  const startedAt = performance.now();
  const url = `${API_BASE_URL}${path}`;
  debugLog(category, "リクエスト開始", body !== undefined ? { url, body } : { url });

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      ...(body !== undefined ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    debugLog(
      category,
      "失敗 (通信エラー)",
      { durationMs: Math.round(performance.now() - startedAt), error: error instanceof Error ? error.message : String(error) },
      "error",
    );
    throw error instanceof Error ? error : new Error(`${errorLabel}に失敗しました`);
  }
  const durationMs = Math.round(performance.now() - startedAt);
  // バックエンドが全リクエストに付与するリクエストID(backend/app/infrastructure/request_log.py)。
  const requestId = response.headers.get("x-request-id");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    debugLog(category, `失敗 (HTTP ${response.status})`, { durationMs, requestId, errorBody }, "error");
    const detail = formatErrorDetail(errorBody?.detail) ?? `${errorLabel}に失敗しました[HTTP ${response.status}]`;
    throw new Error(requestId ? `${detail}[req: ${requestId}]` : detail);
  }
  return { response, durationMs, requestId };
}

const ROAD_SURFACE_TILE_PATH = "/api/region/road-surface-tiles/{z}/{x}/{y}.pbf";
const ACCIDENT_TILE_PATH = "/api/region/accident-tiles/{z}/{x}/{y}.pbf";
const POI_TILE_PATH = "/api/region/poi-tiles/{z}/{x}/{y}.pbf";

// タイル内容の世代。タイルへ焼き込むプロパティが増えた（内容の互換性が変わった）ときに
// 上げると、URLが変わることでブラウザHTTPキャッシュ（Cache-Control: max-age=3600）に残る
// 旧世代タイルを踏まなくなる。バックエンドのファイルキャッシュ側の世代
// （region_service.pyの_tile_cache_path）と対で更新すること。
// v11: 改善計画T122。shoulder材料タグ（付与率0.0%の死に補正、T102実測）を撤去した。
// プロパティ削除を伴うが、shoulderは元々全fetchで実質未使用だったため、v9のような
// 厳格なデプロイ順序制約はない。
// v10: 安全度レシピ（T148で削除済み）。当時の材料タグ（shoulder/lit、tunnelは既存
// プロパティを再利用）追加のため世代を上げた。lit自体はT139でnight軸へ転用され現在も使用中。
// v9: 車ストレスレシピ外出し基盤。計算済みのcar_stress最終値プロパティを廃止し、
// 材料タグ（cycleway_class/maxspeed_kmh/lanes_count/motor_vehicle_no）へ差し替えた
// （最終値の計算は改善計画T292以降、components/Map/axisLayers.tsの汎用rampパイプラインが
// MapLibre expressionとして行う。専用手書きexpression`carStressExpression.ts`は廃止済み）。
// v2〜v8はプロパティ追加のみで旧フロントとの後方互換が保たれていたが、v9はプロパティ削除を
// 伴う初めての非互換変更。backend（road_graph_repository.py）がこの世代へ切り替わるより先に
// この変更を含むfrontendをデプロイすること（逆順だと、この世代のcar_stress前提の凡例
// フィルタが全地物に一致し、車ストレスレイヤーが一時的に全線「不明・他」表示になる。
// docs/architecture.md「Renderデプロイの反映確認」参照）。
// v8: 改善計画T93（統合レビュー2026-08-17 F-1）。T92のcar_stress判定ロジック変更
// （secondary系base値4→3、shared_lane/share_busway・lanes<=1補正）がタイル世代の対上げを
// 伴っていなかったため、キャッシュ陳腐化を断つために世代のみ更新（プロパティ構成は不変）。
// v7: 改善計画T90。車ストレスの区間別判定内訳表示のため、osm_way_idプロパティを追加した。
// v6: 改善計画T74。designation_attributesをosm_way_id基準（road_edges遅延構築非依存）へ
// 変更し、designationプロパティの3値目"both"（N10・N12両方該当）を追加した。
// v5: 指定路線コンフレーション機構（外部静的データソース T51）でdesignationプロパティを
// 追加し、car_stressへKSJ N10/N12該当の+1補正を組み込んだ。
// v4: 静的道路属性P0（docs/static-road-attributes-plan.md）でsmoothness/tunnel/bridge/
// car_stress/bicycle_infraプロパティを追加した。
// v3: surface正準分類の拡充（chipseal/bricks=良い、rock/unhewn_cobblestone=悪い、T7）で
// surface_goodの値が変わった。
// v2: surface（正規化済み生タグ）・highwayプロパティ追加（色分けモード用）。
// v12: 改善計画T145b。二次軸rampレイヤー用の事前集計密度プロパティ
// （accident_per_km/stop_per_km/intersection_per_km）を追加。
// v13: 改善計画T289。一方通行（一次属性、oneway）プロパティを追加。
// v14: 改善計画T337。cycleway_classプロパティを削除した（どの評価軸・地図表示からも
// 参照されない未使用材料だったため。cycleway由来の材料はbicycle_infraのみ現存）。
// 削除のみで参照側への影響は無いため、v9のような非互換変更ではない。
// v15: 改善計画T338フォローアップ。designation（3値、地図表示は引き続きこちらを使う）が
// 畳み込む前の正規化フラグis_emergency_transport/is_critical_logisticsを追加した
// （評価軸材料として軸スタジオから選べるようにするため）。追加のみで参照側への影響は
// 無いため、v9のような非互換変更ではない。
// v16: 改善計画T347。bicycle_infraプロパティを削除した（地図表示は専用レイヤーごと廃止し、
// 評価軸側は新設の公開軸「自転車インフラ」bicycle_infra_qualityへ置き換えたため、
// 地図表示・評価軸のどちらからも一切参照されなくなった）。
// v17: 改善計画T367。公開軸「自転車インフラ」（bicycle_infra_quality）が参照する
// 5正規化フラグ材料（highway_is_cycleway等）を追加した。v16でtile_propertyを失って以降
// derive_ramp_inputsの対象外＝地図に一切出ない状態が続いていたため復活させる。
const ROAD_SURFACE_TILE_VERSION = "17";

// 路面の地域レイヤー（Step10）のベクタタイルURL。基礎地図タイルと同じ理由でフロントエンド
// 自身のオリジン（Next.jsのrewrites経由でバックエンドにプロキシ）を使う。ベクタタイルの
// 取得はMapLibreがWeb Worker内で行うため、相対パスのままだと「ページのオリジンに対して
// 解決する」というラスタタイル（Image要素の読み込み、メインスレッド）の挙動が通用せず、
// URLの構築に失敗することを実機確認した。window.location.originで明示的に絶対URL化する
// 必要があるため、モジュール読み込み時ではなく呼び出し時（クライアントサイドのみ）に
// 評価する関数として提供する。
export function roadSurfaceTileUrl(): string {
  return `${window.location.origin}${ROAD_SURFACE_TILE_PATH}?v=${ROAD_SURFACE_TILE_VERSION}`;
}

// 事故レイヤー（外部静的データソース T50）のタイル世代。バックエンド側
// （accident_service.pyのACCIDENT_TILE_VERSION）と対で更新すること。
// v1: 初回実装（involves_bicycle/fatal/occurred_yearプロパティ）。
const ACCIDENT_TILE_VERSION = "1";

export function accidentTileUrl(): string {
  return `${window.location.origin}${ACCIDENT_TILE_PATH}?v=${ACCIDENT_TILE_VERSION}`;
}

// 停止要因POIレイヤー（改善計画T54）の世代。バックエンド（region_service.py:
// POI_TILE_VERSION）と対で上げる。ROAD_SURFACE_TILE_VERSIONと同じ理由（ブラウザHTTP
// キャッシュのバスト用）。
// v3: T101（補給・休憩ポイントPOIレイヤー）。osm_raw_pois.kindへコンビニ・自販機・
// トイレ・給水・駐輪場を追加。
// v2: T97。地図の独立可視化レイヤーとしては使われなくなっていた（T96）intersectionレイヤーの
// 配信自体をバックエンドから削除し、stop_poiのみの1レイヤー構成へ変更した世代。
// v1: 初版（stop_poi・intersectionの2レイヤー）。
const POI_TILE_VERSION = "3";

// 停止要因POIの地域レイヤー（改善計画T54）のベクタタイルURL。
// roadSurfaceTileUrlと同じ理由（MapLibreのWeb Worker内取得のため絶対URL化が必要）で
// 呼び出し時に評価する関数として提供する。
export function poiTileUrl(): string {
  return `${window.location.origin}${POI_TILE_PATH}?v=${POI_TILE_VERSION}`;
}

// バックエンド（domain/region.py）のROAD_TILE_MIN_ZOOM/MAX_ZOOMと一致させる。
// POI/交差点密度レイヤーもT54で同じズーム範囲に準拠する（api/routers/region.py参照）。
export const ROAD_TILE_MIN_ZOOM = 12;
export const ROAD_TILE_MAX_ZOOM = 15;

// 区間インスペクタ（改善計画T146）。地図上の道路クリックで得たosm_way_id（路面タイルの
// MVTプロパティに含まれる識別子）から一次属性・全二次軸（車の圧迫感を含む）・合成コストを
// 取得するAPI。緯度経度の空間マッチではなくosm_way_id完全一致にしている理由は
// backend/app/services/region_service.py: get_axis_inspectorのdocstring参照
// （交差点付近での取り違えを実機確認で発見し、この方式にした）。タイルURL系
// （roadSurfaceTileUrl等）と違いMapLibreのWeb Worker経由ではなくアプリのfetch()から
// 直接呼ぶため、ここだけ絶対URL化（window.location.origin）が不要（weatherApi.ts等と同じ）。
// POST+JSONボディなのはosm_way_idを本文で渡す既存の設計を踏襲（backend/app/api/routers/
// region.py参照）。改善計画T292: 車ストレス専用の内訳取得（旧fetchCarStressBreakdown、
// レシピ上書きパラメータ）は専用Pythonレシピの廃止に伴い削除し、このAPIへ一本化した。
export async function fetchAxisInspector(osmWayId: number): Promise<AxisInspectorResult | null> {
  const { response, durationMs, requestId } = await postAndCheckOk("/api/region/axis-inspector", {
    category: "api:axis-inspector",
    errorLabel: "内訳取得",
    body: { osm_way_id: osmWayId },
  });
  const data: AxisInspectorResult | null = await response.json();
  debugLog("api:axis-inspector", "成功", { durationMs, requestId, composite: data?.composite_difficulty });
  return data;
}

// way_id→動的値配信層（風・勾配、改善計画T405→T414→T423、docs/tasks/T400.md「2. 動的要素…の
// 二重表現」節）。「評価軸」グループ向けに、指定タイル内のway_idごとの値（風=wind_penalty、
// 勾配=effective_gradient）をまとめて取得する。road-surface-tiles（MapLibreのWeb Worker
// 経由）とは別経路で、fetchAxisInspectorと同じくアプリのfetch()から直接呼ぶ（絶対URL化は
// 不要）。バージョンクエリを持たない（road-surface-tilesと異なりブラウザHTTPキャッシュに
// 乗せない想定の軽量JSON、値自体はbackend側のRedis TTLで新鮮さを管理するため）。
//
// 改善計画T423（T411の実施）: エンドポイントパスを`wind`固定から`{material_id}`駆動へ
// 一本化したのに合わせ、フロント側の関数も`fetchWindWayPenalties`から材料id引数を取る
// `fetchDynamicWayValues`へ汎用化した。
const DYNAMIC_WAY_VALUES_PATH = "/api/region/dynamic-way-values";

/** 指定タイル（road-surface-tilesと同じz/x/y）内のway_idごとの動的値（風=wind_penalty、
 * 勾配=effective_gradient）をまとめて取得する。失敗時は例外を投げず空オブジェクトへ
 * フォールバックする——背景の色分けレイヤーという補助的な機能のため、道路タイル自体の
 * 表示・他レイヤーを巻き込んで止めない（useWeatherGridのdetailGrid取得と同じ
 * 「補助機能はサイレントにフォールバック」方針）。
 *
 * 改善計画T414: `bearingDeg`（ユーザーがコンパススライダーで指定した走行方位、0〜360度、
 * 北=0・時計回り）を必須クエリパラメータとして渡す。`at`は環境グループ（矢印・gridFill）と
 * 共有する時刻（省略時はbackend側が現在時刻を使う。勾配は時刻に依存しないため常に省略）。 */
export async function fetchDynamicWayValues(
  materialId: string,
  z: number,
  x: number,
  y: number,
  bearingDeg: number,
  at?: Date
): Promise<Record<string, number>> {
  const params = new URLSearchParams({ bearing_deg: String(bearingDeg) });
  if (at) params.set("at", at.toISOString());
  const url = `${API_BASE_URL}${DYNAMIC_WAY_VALUES_PATH}/${materialId}/${z}/${x}/${y}?${params.toString()}`;
  const logCategory = `api:${materialId}-way-values`;
  const startedAt = performance.now();
  debugLog(logCategory, "リクエスト開始", { url });
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(15000) });
    const durationMs = Math.round(performance.now() - startedAt);
    if (!response.ok) {
      debugLog(logCategory, `失敗 (HTTP ${response.status})`, { durationMs }, "error");
      return {};
    }
    const data = (await response.json()) as Record<string, number>;
    debugLog(logCategory, "成功", { durationMs, wayCount: Object.keys(data).length });
    return data;
  } catch (error) {
    debugLog(
      logCategory,
      "失敗 (通信エラー)",
      {
        durationMs: Math.round(performance.now() - startedAt),
        error: error instanceof Error ? error.message : String(error),
      },
      "error",
    );
    return {};
  }
}

export async function refreshBasemapCache(): Promise<void> {
  // 以前はtry/catchも!response.okのチェックも無く、ネットワークエラー時は
  // 未処理のPromise rejectionになり、失敗時に呼び出し元(MapView.tsx)へ何も伝わらず
  // 「変わらないデータを更新」ボタンが無反応に見えていた（改善計画T328で発見・修正）。
  const { durationMs, requestId } = await postAndCheckOk("/api/basemap/refresh", {
    category: "api:basemap-refresh",
    errorLabel: "地図キャッシュの更新",
  });
  debugLog("api:basemap-refresh", "成功", { durationMs, requestId });
}
