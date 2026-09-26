"use client";

// 専用way値配信軸（`dedicated_way_value_layer=true`の軸）のフィーチャー→値フェッチ・状態管理。
// viewportをデバウンスしてから、表示中のタイル範囲ぶんをまとめて取る——パン・ズームのたびに個別way_idを
// 都度問い合わせない。取得対象の軸が0件の間はfetchせず（他の外部APIと同じ「表示中のものだけ叩く」方針）、結果も空へ戻す。
//
// 対象の軸ごとに別インスタンスを持たず、1つのフックが軸の配列を受け取って全軸ぶんを賄う
// （Reactのフック規則により、実行時に増減しうる軸の件数だけフックを呼ぶことはできない
// ——軸スタジオで3件目が公開されても呼び出し側の変更が要らないようにするための構造）。
// 時刻・向き・想定速度をどの軸のリクエストへ載せるかは軸カタログの宣言
// （`needsTime`/`needsBearing`/`needsSpeed`）から決め、載せない軸はその入力が変わっても
// 再フェッチしない（キーが変わらないため）。

import { keepPreviousData, useQuery, type QueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { mergeDynamicWayValues, tilesCoveringViewport, type TileXY } from "@/features/map/layers/dynamicWayValues";
import type { DedicatedWayValueAxis } from "@/lib/mapDisplay/axisLayers";
import type { MapViewport } from "@/features/map/layers/windLayer";
import { fetchDynamicWayValues, ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM } from "@/services/regionApi";
import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";
import { getQueryClient } from "@/lib/queryClient";

// コンパススライダー（WindBearingSlider）はドラッグ中onChangeを連続発火するため、bearingDeg
// もviewportと同様にデバウンスする（そのまま依存配列へ入れるとドラッグ1回で可視タイル数×
// 連続イベント数ぶんのfetchが発生してしまう）。

interface DedicatedWayValuesResult {
  /** feature_key→値（複数タイルを統合済み）。評価軸グループのsetFeatureStateにそのまま
   * 使える（鍵は路面タイルの`feature_key`と同じ文字列）。 */
  values: ReadonlyMap<string, number>;
  /** 現在のビューポートぶんのフェッチが進行中か。falseへ戻るまでの間、
   * まだ一度も値を受け取っていないway（feature-stateキー未設定）は「取得中」、フェッチ
   * 完了後になお値を持たないwayは「その範囲に値が無い」と呼び出し側が区別できるようにする。 */
  loading: boolean;
  /** 直近に完了したフェッチで、いずれかのタイルの取得が通信失敗（HTTPエラー・
   * ネットワークエラー）したか。falseは「本当にその範囲にway_idが無い」場合と区別する
   * （fetchDynamicWayValuesのerrorをタイル横断でOR集約する）。 */
  error: boolean;
  /** 一度でも取得を試みて完了したか（成否は問わない）。対象軸に含まれていない間はfalseのまま。
   * 「まだ取りに行っていない」と「取得したが値が無かった」を呼び出し側が区別するために使う
   * （`mapLayers.ts: deriveFetchLayerStatus`）。 */
  hasFetched: boolean;
}

const EMPTY_DEDICATED_WAY_VALUES_RESULT: DedicatedWayValuesResult = {
  values: new Map(),
  loading: false,
  error: false,
  hasFetched: false,
};

const EMPTY_RESULTS: ReadonlyMap<string, DedicatedWayValuesResult> = new Map();

const ALL_AXES_KEY = "dedicated-way-values";
const AXIS_KEY = "dedicated-way-value";

/** 1軸ぶんの取得の入力。 */
interface AxisRequest {
  axisId: string;
  at: Date | undefined;
  bearingDeg: number | undefined;
  speedKmh: number | undefined;
  tiles: readonly TileXY[];
  /** その軸の1回のフェッチを一意に決める入力（軸id＋その軸へ載せるクエリパラメータ＋対象タイル集合）。 */
  key: string;
}

function requestKey({ axisId, at, speedKmh, bearingDeg, tiles }: Omit<AxisRequest, "key">): string {
  const tileKey = tiles.map((tile) => `${tile.z}/${tile.x}/${tile.y}`).join(",");
  return [axisId, at?.toISOString() ?? "", speedKmh ?? "", bearingDeg ?? "", tileKey].join("|");
}

async function fetchAxis(request: AxisRequest): Promise<DedicatedWayValuesResult> {
  const responses = await Promise.all(
    request.tiles.map((tile) =>
      fetchDynamicWayValues(request.axisId, tile.z, tile.x, tile.y, request.bearingDeg, request.at, request.speedKmh),
    ),
  );
  return {
    values: mergeDynamicWayValues(responses.map((response) => response.values)),
    loading: false,
    error: responses.some((response) => response.error),
    hasFetched: true,
  };
}

/** 全軸ぶんを取る。軸ごとの答えは軸の入力キーでキャッシュに置き、キーが変わっていない軸は取り直さない——時刻に
 * 依存しない軸は時刻が変わってもキーが変わらないため、時刻スライダーの操作で巻き添えの再取得が起きない。失敗を
 * 含む答えは取っておかず、次に全体を取るときに取り直す。 */
async function fetchAllAxes(
  client: QueryClient,
  requests: readonly AxisRequest[],
): Promise<ReadonlyMap<string, DedicatedWayValuesResult>> {
  const results = await Promise.all(
    requests.map((request) =>
      client.fetchQuery({
        queryKey: [AXIS_KEY, request.key],
        queryFn: () => fetchAxis(request),
        staleTime: (query) => (query.state.data?.error ? 0 : Infinity),
      }),
    ),
  );
  return new Map(requests.map((request, index) => [request.axisId, results[index]]));
}

/** `axes`（取得対象の専用way値配信軸。呼び出し側がuseMemoで安定した参照を渡すこと）について、
 * 現在のビューポート（デバウンス済み）を覆う道路タイル分をまとめて取得し、軸id→結果のMapを
 * 返す。取り直している軸は前の値を残したまま`loading`を立てる。
 *
 * `at`（時刻）・`bearingDeg`（向き）・`speedKmh`（想定速度）は全軸で共有の入力で、実際に
 * リクエストへ載るのはそれを必要とすると宣言した軸（`needsTime`/`needsBearing`/`needsSpeed`）だけ。
 * 向きと想定速度はviewportと同様デバウンス後の値を使う。 */
export function useDedicatedWayValues(
  axes: readonly DedicatedWayValueAxis[],
  mapViewport: MapViewport | null,
  bearingDeg: number,
  at: Date | undefined,
  speedKmh?: number,
): ReadonlyMap<string, DedicatedWayValuesResult> {
  const debouncedViewport = useDebouncedValue(mapViewport, MAP_FETCH_DEBOUNCE_MS);
  const debouncedBearingDeg = useDebouncedValue(bearingDeg, MAP_FETCH_DEBOUNCE_MS);
  // 想定速度の入力欄も連続入力されるため、向きと同じくデバウンスする。
  const debouncedSpeedKmh = useDebouncedValue(speedKmh, MAP_FETCH_DEBOUNCE_MS);
  const client = getQueryClient();

  const tiles = useMemo(
    () => (debouncedViewport ? tilesCoveringViewport(debouncedViewport, ROAD_TILE_MIN_ZOOM, ROAD_TILE_MAX_ZOOM) : []),
    [debouncedViewport],
  );
  const requests: AxisRequest[] =
    tiles.length === 0
      ? []
      : axes.map((axis) => {
          const request = {
            axisId: axis.axisId,
            at: axis.needsTime ? at : undefined,
            bearingDeg: axis.needsBearing ? debouncedBearingDeg : undefined,
            speedKmh: axis.needsSpeed ? debouncedSpeedKmh : undefined,
            tiles,
          };
          return { ...request, key: requestKey(request) };
        });
  const requestsKey = requests.map((request) => request.key).join("\n");

  const { data, isFetching, isPlaceholderData } = useQuery(
    {
      queryKey: [ALL_AXES_KEY, requestsKey],
      queryFn: () => fetchAllAxes(client, requests),
      enabled: requests.length > 0,
      placeholderData: keepPreviousData,
    },
    client,
  );

  // 入力キーが同じなら同じ結果の参照を返す（参照が変わるとMapView側のsetFeatureState反映が無用に走り直す）。
  return useMemo(() => {
    if (requests.length === 0) return EMPTY_RESULTS;
    const results = new Map<string, DedicatedWayValuesResult>();
    for (const request of requests) {
      const current = isPlaceholderData ? undefined : data?.get(request.axisId);
      // 入力の変わっていない軸は、全体の取り直しの間も手元の答えのまま（キャッシュにある）。
      const unchanged = client.getQueryData<DedicatedWayValuesResult>([AXIS_KEY, request.key]);
      const settled = current ?? (unchanged?.error === false ? unchanged : undefined);
      results.set(
        request.axisId,
        settled ?? { ...(data?.get(request.axisId) ?? EMPTY_DEDICATED_WAY_VALUES_RESULT), loading: isFetching },
      );
    }
    return results;
    // `requests`は描くたびに作り直す配列で、中身は`requestsKey`で決まる。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestsKey, data, isFetching, isPlaceholderData, client]);
}
