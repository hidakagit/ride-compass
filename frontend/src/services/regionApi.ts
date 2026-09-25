import type { AxisInspectorResult } from "@/types/traffic";
import { API_BASE_URL } from "@/lib/apiBaseUrl";
import { tileBaseUrl } from "@/lib/tileBaseUrl";
import { debugLog } from "@/lib/debugLog";
import { requestOk } from "@/lib/fetchJson";
import regionTileConfig from "@/types/generated/region-tile-config.json";
import { DEFAULT_API_TIMEOUT_MS } from "@/lib/apiTimeouts";

const ROAD_SURFACE_TILE_PATH = "/api/region/road-surface-tiles/{z}/{x}/{y}.pbf";
const ACCIDENT_TILE_PATH = "/api/region/accident-tiles/{z}/{x}/{y}.pbf";
const POI_TILE_PATH = "/api/region/poi-tiles/{z}/{x}/{y}.pbf";

// タイルの世代。**手で上げない**——焼き込むSQLの署名とDBの派生データ世代からbackendが導き、実行時に配る（軸カタログの
// `tile_versions`）。ビルド時の生成物に持たないのは、バッチがタイルを作り直してもデプロイは起きないため。
// 既定値は置かない——届く前にタイルを要求すると、世代の違う中身がブラウザのキャッシュへ載って残る。
// 既存の属性の意味を変える変更だけはデプロイの順序に注意が要る（docs/architecture/tech-stack.md「デプロイの反映確認」）。
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

/** 配信されるタイルの系統（源泉が配る一覧）。1つでも欠けたら「未取得」。 */
const TILE_KINDS = regionTileConfig.tile_version_kinds;
type TileKind = (typeof TILE_KINDS)[number];

export function hasTileVersions(): boolean {
  // 空の辞書を「取得済み」と見なさない（世代を返さない版のbackendが応答した窓では、URLの組み立てで例外になる）。
  return TILE_KINDS.every((kind) => Boolean(tileVersions?.[kind]));
}

function tileVersion(kind: TileKind): string {
  const version = tileVersions?.[kind];
  if (!version) {
    // 呼ぶ側の順序が崩れたときだけ起きる（黙って既定値を使うと、世代の違うタイルがキャッシュへ載っても気づけない）。
    throw new Error(`タイル世代が未取得のまま${kind}のURLを組み立てようとしました`);
  }
  return version;
}

// ベクタタイルのURL。MapLibreはWeb Workerの中で取るため相対パスでは解決できず、絶対URLが要る。`window`をSSRで
// 読まないよう、呼んだとき（クライアントだけ）に組み立てる。
export function roadSurfaceTileUrl(): string {
  return `${tileBaseUrl()}${ROAD_SURFACE_TILE_PATH}?v=${tileVersion("road_surface")}`;
}

export function accidentTileUrl(): string {
  return `${tileBaseUrl()}${ACCIDENT_TILE_PATH}?v=${tileVersion("accident")}`;
}

// 停止要因と補給の点は同じタイルを分け合う（種別の集合で分ける）。
export function poiTileUrl(): string {
  return `${tileBaseUrl()}${POI_TILE_PATH}?v=${tileVersion("poi")}`;
}

// 土地被覆のラスタタイル。世代はbackendが生成物で配る。オリジンの決め方は他のタイルと揃える。
const LANDCOVER_TILE_PATH = "/api/region/landcover-tiles/{z}/{x}/{y}.png";
const LANDCOVER_TILE_VERSION = regionTileConfig.landcover.tile_version;

export function landcoverTileUrl(): string {
  return `${tileBaseUrl()}${LANDCOVER_TILE_PATH}?v=${LANDCOVER_TILE_VERSION}`;
}

// 路面タイル（POIタイルも同じ）を要求するズーム範囲。正はbackendで、生成物で受け取る。
export const ROAD_TILE_MIN_ZOOM = regionTileConfig.road_tile_min_zoom;
export const ROAD_TILE_MAX_ZOOM = regionTileConfig.road_tile_max_zoom;

/** 地図が今指定している走行の条件。専用way値配信軸（風・勾配）が地図を塗るのに使うものと
 * 同じ値で、これを送らないと**1本の道が往復2方向で違う値を持つ**軸を算出できない。 */
export interface RideConditions {
  bearingDeg: number;
  at?: Date;
  speedKmh?: number;
}

/** 上記に、クリックされた点を含む道路タイルを足したもの（レンズが引いたのと同じタイルを
 * 指すため、backendは同じキャッシュから値を引ける）。 */
export interface AxisInspectorConditions extends RideConditions {
  z: number;
  x: number;
  y: number;
}

/** 地図で押した道（`osm_way_id`）の一次属性・全軸・合成を取る。 */
export async function fetchAxisInspector(
  osmWayId: number,
  featureKey?: string | null,
  conditions?: AxisInspectorConditions | null,
): Promise<AxisInspectorResult | null> {
  const body = {
    osm_way_id: osmWayId,
    // 押した地物の識別子。区間単位のズームで押した道は内訳も区間単位で計算される（地図の色と数字を揃える）。
    ...(featureKey != null ? { feature_key: featureKey } : {}),
    ...(conditions != null
      ? {
          z: conditions.z,
          x: conditions.x,
          y: conditions.y,
          bearing_deg: conditions.bearingDeg,
          ...(conditions.at != null ? { at: conditions.at.toISOString() } : {}),
          ...(conditions.speedKmh != null ? { speed_kmh: conditions.speedKmh } : {}),
        }
      : {}),
  };
  const { response, durationMs, requestId } = await requestOk(`${API_BASE_URL}/api/region/axis-inspector`, {
    method: "POST",
    body,
    timeoutMs: DEFAULT_API_TIMEOUT_MS,
    category: "api:axis-inspector",
    messages: { failure: "内訳の取得に失敗しました", parseFailure: "内訳の取得に失敗しました" },
    requestMeta: { body },
  });
  const data: AxisInspectorResult | null = await response.json();
  debugLog("api:axis-inspector", "成功", { durationMs, requestId, composite: data?.composite_difficulty });
  return data;
}

// 専用配信の軸の、タイルの中のway_idごとの値。パスは軸idで決まり、軸ごとの関数を持たない。世代のクエリを持たない
// （ブラウザのキャッシュに載せない軽いJSONで、新しさはbackendが持つ）。
const DYNAMIC_WAY_VALUES_PATH = "/api/region/dynamic-way-values";

interface DynamicWayValuesResult {
  values: Record<string, number>;
  /** 通信失敗（HTTPエラー・ネットワークエラー・タイムアウト）ならtrue。backendが正常応答で
   * 空オブジェクトを返した場合（対象範囲に本当にway_idが無い）はfalseのまま——呼び出し側が
   * 「取得失敗」と「本当に空」を区別できるようにする。 */
  error: boolean;
}

/** 路面タイルと同じz/x/yの中のway_idごとの値。失敗しても例外にせず`error: true`を返す（色分けは補助の機能なので、
 * 道路や他のレイヤーを巻き込んで止めない。失敗したことは利用者へ示せるよう返す）。走行方位・時刻・速度は、その軸が
 * 要るものだけを呼ぶ側が渡す。 */
export async function fetchDynamicWayValues(
  axisId: string,
  z: number,
  x: number,
  y: number,
  bearingDeg: number | undefined,
  at?: Date,
  speedKmh?: number,
): Promise<DynamicWayValuesResult> {
  const params = new URLSearchParams();
  if (bearingDeg !== undefined) params.set("bearing_deg", String(bearingDeg));
  if (at) params.set("at", at.toISOString());
  if (speedKmh !== undefined && Number.isFinite(speedKmh)) params.set("speed_kmh", String(speedKmh));
  const url = `${API_BASE_URL}${DYNAMIC_WAY_VALUES_PATH}/${axisId}/${z}/${x}/${y}?${params.toString()}`;
  const logCategory = `api:${axisId}-way-values`;
  try {
    const { response, durationMs, requestId } = await requestOk(url, {
      timeoutMs: DEFAULT_API_TIMEOUT_MS,
      category: logCategory,
      messages: { failure: "道路の色分けの取得に失敗しました", parseFailure: "道路の色分けの解析に失敗しました" },
    });
    const data = (await response.json()) as Record<string, number>;
    debugLog(logCategory, "成功", { durationMs, requestId, wayCount: Object.keys(data).length });
    return { values: data, error: false };
  } catch {
    // 失敗の内訳は`requestOk`が記録済み。
    return { values: {}, error: true };
  }
}
