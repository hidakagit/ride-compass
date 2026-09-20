import type { AxisInspectorResult } from "@/types/traffic";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { tileBaseUrl } from "@/lib/tileBaseUrl";
import { debugLog } from "@/lib/debugLog";
import { requestOk, type ApiResponse } from "@/lib/fetchJson";
import regionTileConfig from "@/types/generated/region-tile-config.json";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

interface PostRequestOptions {
  category: string;
  /** 「{errorLabel}に失敗しました」の形でエラーメッセージに使う対象名。 */
  errorLabel: string;
  /** JSONボディとして送る（Content-Type: application/jsonも自動で付く）。 */
  body: unknown;
  timeoutMs?: number;
}

// POST系は成功時のレスポンス本体の解釈・成功ログのfieldsが呼び出しごとに異なる
// （fetchAxisInspectorはJSONボディからcompositeを追加ログするが、refreshBasemapCacheは
// ボディ自体を読まない）ため、共通骨格のうち`requestOk`（成功時のResponseをそのまま返す
// 側、lib/fetchJson.ts参照）を使い、成功ログだけ呼び出し側が出す。
function postAndCheckOk(
  path: string,
  { category, errorLabel, body, timeoutMs = DEFAULT_API_TIMEOUT_MS }: PostRequestOptions,
): Promise<ApiResponse> {
  return requestOk(`${API_BASE_URL}${path}`, {
    method: "POST",
    body,
    timeoutMs,
    category,
    // GET系の「◯◯の取得に失敗しました」とは違い、POSTは操作の動詞をerrorLabelへ含める
    // （「地図キャッシュの更新」「内訳取得」）。
    messages: { failure: `${errorLabel}に失敗しました`, parseFailure: `${errorLabel}に失敗しました` },
    requestMeta: { body },
  });
}

const ROAD_SURFACE_TILE_PATH = "/api/region/road-surface-tiles/{z}/{x}/{y}.pbf";
const ACCIDENT_TILE_PATH = "/api/region/accident-tiles/{z}/{x}/{y}.pbf";
const POI_TILE_PATH = "/api/region/poi-tiles/{z}/{x}/{y}.pbf";

// **世代は手で上げない。** 焼き込むSQLの署名とDBの派生データ世代からbackendが導き、
// 実行時に配る（`GET /api/axis-catalog`の`tile_versions`、backend:
// services/tile_version_service.py）。
//
// 既存プロパティの**意味自体**を変える非互換変更のときだけ、デプロイの順序に注意が要る
// ——backendがその世代へ切り替わるより先に、変更を含むfrontendをデプロイする（逆順だと、
// 新世代前提の凡例フィルタが全地物に一致し、対象レイヤーが一時的に全線「不明・他」表示に
// なる。docs/architecture.md「Renderデプロイの反映確認」参照）。
//
// ビルド時生成物には持たない——バッチがタイルの読み先を作り直してもデプロイは起きない
// ため、生成物の値は次のデプロイまで古いままになる。
//
// 既定値は置かない。届く前にタイルを要求すると、世代の違う中身がブラウザのキャッシュへ
// 載って以後ずっと残る。呼び出し側（page.tsx）はカタログの取得完了まで地図のレイヤーを
// 作らず、`setTileVersions`で渡してから作る。
let tileVersions: Readonly<Record<string, string>> | null = null;
const tileVersionListeners = new Set<() => void>();

export function setTileVersions(versions: Readonly<Record<string, string>>): void {
  tileVersions = versions;
  tileVersionListeners.forEach((listener) => listener());
}

/** 世代が入れ替わったことを購読する（`useSyncExternalStore`用）。
 *
 * **カタログの到着と同一視しない**。世代を返さない版のbackendが200で応答すると、
 * カタログは「取得済み」なのに世代は揃わない——そこでURLを組み立てると例外になる。
 * 揃ったかどうかは`hasTileVersions()`だけが答えられる。 */
export function subscribeTileVersions(listener: () => void): () => void {
  tileVersionListeners.add(listener);
  return () => {
    tileVersionListeners.delete(listener);
  };
}

/** 配信されるタイルの系統。1つでも欠けたら「未取得」として扱う。
 *  backendの`tile_version_service.py: TILE_SHAPES`と同じ集合でなければならず、
 *  一致は生成物（`region-tile-config.json: tile_version_kinds`）との照合が固定する。 */
export const TILE_KINDS = ["road_surface", "poi", "accident"] as const;
type TileKind = (typeof TILE_KINDS)[number];

export function hasTileVersions(): boolean {
  // **空の辞書を「取得済み」と見なさない**。世代を返さない古いbackendが応答した場合
  // （デプロイの順序が前後した窓）、取得済み扱いにするとURL組み立てで例外になる。
  // 欠けているあいだはタイルを出さず、揃った時点で描き直す。
  return TILE_KINDS.every((kind) => Boolean(tileVersions?.[kind]));
}

function tileVersion(kind: TileKind): string {
  const version = tileVersions?.[kind];
  if (!version) {
    // 呼ぶ側の順序が崩れた場合にだけ起きる。黙って既定値を使うと、世代の違うタイルが
    // キャッシュへ載ったことに誰も気づけない。
    throw new Error(`タイル世代が未取得のまま${kind}のURLを組み立てようとしました`);
  }
  return version;
}

// 路面の地域レイヤー（Step10）のベクタタイルURL。オリジンは`tileBaseUrl()`
// （lib/tileBaseUrl.ts: 既定はフロント自身のオリジン＝Next.jsのrewrites経由、
// `NEXT_PUBLIC_TILE_BASE_URL`設定時はbackend直接）に従う。ベクタタイルの取得はMapLibreが
// Web Worker内で行うため相対パスでは解決できず絶対URLが必要で、`window`をSSR時に参照しない
// よう呼び出し時（クライアントサイドのみ）に評価する関数として提供する。
export function roadSurfaceTileUrl(): string {
  return `${tileBaseUrl()}${ROAD_SURFACE_TILE_PATH}?v=${tileVersion("road_surface")}`;
}

export function accidentTileUrl(): string {
  return `${tileBaseUrl()}${ACCIDENT_TILE_PATH}?v=${tileVersion("accident")}`;
}

// 停止要因POIと補給休憩POIは同じタイルを共有する（staticAttributeLayers.ts参照）。

// 停止要因POIの地域レイヤーのベクタタイルURL。
// roadSurfaceTileUrlと同じ理由（MapLibreのWeb Worker内取得のため絶対URL化が必要）で
// 呼び出し時に評価する関数として提供する。
export function poiTileUrl(): string {
  return `${tileBaseUrl()}${POI_TILE_PATH}?v=${tileVersion("poi")}`;
}

// 土地被覆ラスタタイル（Esri×Impact Observatory 10m LULCをそのまま塗った面）。世代・
// ズーム範囲の正はbackend（domain/landcover.py・services/landcover_tile_service.py）で、
// 生成物経由で受け取る。ラスタタイルはMapLibreがメインスレッドのImage要素で取るため
// Worker制約は無いが、オリジンの決め方は他タイルと揃える（lib/tileBaseUrl.ts）。
const LANDCOVER_TILE_PATH = "/api/region/landcover-tiles/{z}/{x}/{y}.png";
const LANDCOVER_TILE_VERSION = regionTileConfig.landcover.tile_version;
export const LANDCOVER_TILE_MIN_ZOOM = regionTileConfig.landcover.min_zoom;
export const LANDCOVER_TILE_MAX_ZOOM = regionTileConfig.landcover.max_zoom;

export function landcoverTileUrl(): string {
  return `${tileBaseUrl()}${LANDCOVER_TILE_PATH}?v=${LANDCOVER_TILE_VERSION}`;
}

// 路面タイルを要求するズーム範囲。正はbackend（domain/region.py）で、生成物経由で受け取る
// （手書きで複製すると、backendだけ広げてもフロントが要求せずレイヤーが黙って消える）。
// POIタイルも同じズーム範囲に準拠する（api/routers/region.py参照）。
export const ROAD_TILE_MIN_ZOOM = regionTileConfig.road_tile_min_zoom;
export const ROAD_TILE_MAX_ZOOM = regionTileConfig.road_tile_max_zoom;

// 区間インスペクタ（改善計画T146）。地図上の道路クリックで得たosm_way_id（路面タイルの
// MVTプロパティに含まれる識別子）から一次属性・全二次軸・合成コストを
// 取得するAPI。緯度経度の空間マッチではなくosm_way_id完全一致にしている理由は
// backend/app/services/region_service.py: get_axis_inspectorのdocstring参照
// （交差点付近での取り違えを実機確認で発見し、この方式にした）。タイルURL系
// （roadSurfaceTileUrl等）と違いMapLibreのWeb Worker経由ではなくアプリのfetch()から
// 直接呼ぶため、ここだけ絶対URL化（window.location.origin）が不要（weatherApi.ts等と同じ）。
// POST+JSONボディなのはosm_way_idを本文で渡す既存の設計を踏襲（backend/app/api/routers/
// region.py参照）。
export async function fetchAxisInspector(
  osmWayId: number,
  featureKey?: string | null,
): Promise<AxisInspectorResult | null> {
  const { response, durationMs, requestId } = await postAndCheckOk("/api/region/axis-inspector", {
    category: "api:axis-inspector",
    errorLabel: "内訳取得",
    // クリックされたフィーチャーの識別子。区間単位のズームで押した道は、内訳も
    // 区間単位で計算される（送らないと地図の色と内訳の数字が食い違う）。
    body: { osm_way_id: osmWayId, ...(featureKey != null ? { feature_key: featureKey } : {}) },
  });
  const data: AxisInspectorResult | null = await response.json();
  debugLog("api:axis-inspector", "成功", { durationMs, requestId, composite: data?.composite_difficulty });
  return data;
}

// way_id→動的値配信層（風・勾配、改善計画T405→T414→T423、docs/tasks/T400.md「2. 動的要素…の
// 二重表現」節）。「評価軸」グループ向けに、指定タイル内のway_idごとの値（風=wind_drag_ratio、
// 勾配=effective_gradient）をまとめて取得する。road-surface-tiles（MapLibreのWeb Worker
// 経由）とは別経路で、fetchAxisInspectorと同じくアプリのfetch()から直接呼ぶ（絶対URL化は
// 不要）。バージョンクエリを持たない（road-surface-tilesと異なりブラウザHTTPキャッシュに
// 乗せない想定の軽量JSON、値自体はbackend側のRedis TTLで新鮮さを管理するため）。
//
// エンドポイントパスは軸id駆動（`/api/region/dynamic-way-values/{axis_id}/{z}/{x}/{y}`）で、
// 軸ごとの関数を持たない。
const DYNAMIC_WAY_VALUES_PATH = "/api/region/dynamic-way-values";

export interface DynamicWayValuesResult {
  values: Record<string, number>;
  /** 通信失敗（HTTPエラー・ネットワークエラー・タイムアウト）ならtrue。backendが正常応答で
   * 空オブジェクトを返した場合（対象範囲に本当にway_idが無い）はfalseのまま——呼び出し側が
   * 「取得失敗」と「本当に空」を区別できるようにする。 */
  error: boolean;
}

/** 指定タイル（road-surface-tilesと同じz/x/y）内のway_idごとの動的値（風=wind_drag_ratio、
 * 勾配=effective_gradient）をまとめて取得する。失敗時は例外を投げず`error: true`へ
 * フォールバックする——背景の色分けレイヤーという補助的な機能のため、道路タイル自体の
 * 表示・他レイヤーを巻き込んで止めない（useWeatherGridのdetailGrid取得と同じ
 * 「補助機能はサイレントにフォールバック」方針。ただし失敗そのものは`error`で呼び出し側へ
 * 伝える——道路タイルは止めないが、道路の色分け自体が失敗したことは利用者へ示せるように
 * するため）。
 *
 * `bearingDeg`（ユーザーがコンパススライダーで指定した走行方位、0〜360度、北=0・時計回り）を
 * 必須クエリパラメータとして渡す。`at`は環境グループ（矢印・gridFill）と共有する時刻
 * （省略時はbackend側が現在時刻を使う。勾配は時刻に依存しないため常に省略）。 */
export async function fetchDynamicWayValues(
  axisId: string,
  z: number,
  x: number,
  y: number,
  bearingDeg: number,
  at?: Date,
  speedKmh?: number,
): Promise<DynamicWayValuesResult> {
  const params = new URLSearchParams({ bearing_deg: String(bearingDeg) });
  if (at) params.set("at", at.toISOString());
  // 走行速度に依存する軸（needs_speed）だけがbackend側で使う。他の軸へ渡しても無視される。
  if (speedKmh !== undefined && Number.isFinite(speedKmh)) params.set("speed_kmh", String(speedKmh));
  const url = `${API_BASE_URL}${DYNAMIC_WAY_VALUES_PATH}/${axisId}/${z}/${x}/${y}?${params.toString()}`;
  const logCategory = `api:${axisId}-way-values`;
  try {
    // 例外を投げない契約のためcatchで受けるが、fetch〜ok確認までは共通骨格（requestOk）を
    // 通す——x-request-idの記録もこれで揃い、失敗時にサーバーログと突き合わせられる。
    const { response, durationMs, requestId } = await requestOk(url, {
      timeoutMs: DEFAULT_API_TIMEOUT_MS,
      category: logCategory,
      messages: { failure: "道路の色分けの取得に失敗しました", parseFailure: "道路の色分けの解析に失敗しました" },
    });
    const data = (await response.json()) as Record<string, number>;
    debugLog(logCategory, "成功", { durationMs, requestId, wayCount: Object.keys(data).length });
    return { values: data, error: false };
  } catch {
    // 失敗の内訳（通信エラー/タイムアウト/HTTPエラー）は`requestOk`が既にdebugLogへ
    // 記録済みのため、ここでは重ねて記録しない。
    return { values: {}, error: true };
  }
}
