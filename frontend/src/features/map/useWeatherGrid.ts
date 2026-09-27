"use client";

import { keepPreviousData, useQuery, type QueryClient } from "@tanstack/react-query";
import {
  clampWindDetailBbox,
  mergeWindGridKeepingStale,
  windGridDetailSpacingDegForZoom,
  WIND_DETAIL_MIN_ZOOM,
  type MapViewport,
  type SpacedWindGrid,
} from "@/features/map/layers/windLayer";
import type { WindGridPoint } from "@/types/weather";
import { getWindGrid, getWindGridDetail, type Bbox } from "@/services/weatherApi";
import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";
import { getQueryClient } from "@/lib/queryClient";
import refreshIntervals from "@/types/generated/refresh-intervals.json";

// 配信元（気象庁MSM）の更新の間隔に合わせる（短くしても新しい値は無く、MB級の応答を取り直すだけ）。
const WEATHER_GRID_REFRESH_INTERVAL_MS = refreshIntervals.msm_seconds * 1000;
// 空の格子は1つを使い回す（描くたびに新しい配列を返すと、読む側の参照の比較が無用に変わる）。
const EMPTY_GRID: WindGridPoint[] = [];

const COARSE_GRID_KEY = ["wind-grid"] as const;
const DETAIL_GRID_KEY = "wind-grid-detail";

interface UseWeatherGridResult {
  /** 粗い格子（関東の全域）。取ってから時間が経つと先頭の時刻が過去になる（落とすのは時系列を作る側）。 */
  grid: WindGridPoint[];
  /** 詳細格子（ズームしたときだけ、表示範囲の付近を密に）と、それを取ったときの間隔。無ければnull。間隔も格子と
   * 一緒に持つ（呼ぶ側でズームから計算し直すと、取った後にズームが動いたとき中身と食い違う）。どちらで描くかは
   * 時刻ごとに決まる（`windLayer.ts: gridAtTime`）。 */
  detail: SpacedWindGrid | null;
  /** 粗い格子をまだ一度も取り終えていない間の取得中。 */
  loading: boolean;
  /** 粗い格子の取得の失敗（詳細格子の失敗は黙って粗い格子へ戻るだけ）。 */
  error: string | null;
  /** 粗い格子を一度でも取り終えたか（成否は問わない）。無効の間は偽——真のまま残すと、表示を消しただけの状態を
   * 「取りに行った結果、値が無かった」と読まれる（`mapLayers.ts: deriveFetchLayerStatus`）。 */
  hasFetched: boolean;
}

const DISABLED: UseWeatherGridResult = {
  grid: EMPTY_GRID,
  detail: null,
  loading: false,
  error: null,
  hasFetched: false,
};

/** 同じ間隔の詳細格子のうち、最後に届いたもの。範囲を動かすたびにキーが変わるので、補う元はキャッシュから引く
 * （間隔が違う格子の点は新しい格子に乗らず、セルの大きさが中身と食い違うので使わない）。 */
function latestDetailGrid(client: QueryClient, spacingDeg: number): readonly WindGridPoint[] {
  let latest: { updatedAt: number; points: readonly WindGridPoint[] } | undefined;
  for (const query of client.getQueryCache().findAll({ queryKey: [DETAIL_GRID_KEY, spacingDeg] })) {
    const detail = query.state.data as SpacedWindGrid | undefined;
    if (detail !== undefined && (latest === undefined || query.state.dataUpdatedAt >= latest.updatedAt)) {
      latest = { updatedAt: query.state.dataUpdatedAt, points: detail.points };
    }
  }
  return latest?.points ?? EMPTY_GRID;
}

async function fetchDetailGrid(client: QueryClient, bbox: Bbox, spacingDeg: number): Promise<SpacedWindGrid> {
  const fresh = await getWindGridDetail(bbox, spacingDeg);
  // 補うのは今の範囲の中の点だけ（範囲の外は画面の外で、溜めるとパンの跡が残り続ける）。
  const previous = latestDetailGrid(client, spacingDeg).filter(
    (point) =>
      point.longitude >= bbox.minLon &&
      point.longitude <= bbox.maxLon &&
      point.latitude >= bbox.minLat &&
      point.latitude <= bbox.maxLat,
  );
  return { spacingDeg, points: mergeWindGridKeepingStale(previous, fresh) };
}

/** 風の矢印と降水の延長予報が共有する格子（1回の取得に風と降水が載る）。`enabled`の間だけ取り、ズームしたときだけ
 * 詳細格子も取る。どちらも配信元の更新の間隔で取り直す。 */
export function useWeatherGrid(enabled: boolean, mapViewport: MapViewport | null): UseWeatherGridResult {
  const client = getQueryClient();
  const coarse = useQuery(
    {
      queryKey: COARSE_GRID_KEY,
      queryFn: async () => mergeWindGridKeepingStale(client.getQueryData(COARSE_GRID_KEY) ?? [], await getWindGrid()),
      enabled,
      refetchInterval: WEATHER_GRID_REFRESH_INTERVAL_MS,
    },
    client,
  );

  const debouncedMapViewport = useDebouncedValue(mapViewport, MAP_FETCH_DEBOUNCE_MS);
  const zoomedIn = enabled && debouncedMapViewport !== null && debouncedMapViewport.zoom >= WIND_DETAIL_MIN_ZOOM;
  const spacingDeg = zoomedIn ? windGridDetailSpacingDegForZoom(debouncedMapViewport.zoom) : null;
  const bbox = spacingDeg !== null ? clampWindDetailBbox(debouncedMapViewport!, spacingDeg) : null;
  const detail = useQuery(
    {
      queryKey: [DETAIL_GRID_KEY, spacingDeg, bbox],
      queryFn: () => fetchDetailGrid(client, bbox!, spacingDeg!),
      enabled: zoomedIn,
      refetchInterval: WEATHER_GRID_REFRESH_INTERVAL_MS,
      // 範囲を動かして取り直す間は前の範囲の格子を出したままにする（粗い格子へ一瞬戻すと、重ねた面がちらつく）。
      placeholderData: keepPreviousData,
    },
    client,
  );

  if (!enabled) return DISABLED;
  // 詳細格子の失敗は知らせず粗い格子へ戻る（取得のログは記録済み）。
  const detailGrid = zoomedIn && detail.data !== undefined && detail.data.points.length > 0 ? detail.data : null;
  return {
    grid: coarse.data ?? EMPTY_GRID,
    detail: detailGrid,
    loading: coarse.isLoading,
    error: coarse.error?.message ?? null,
    hasFetched: coarse.isFetched,
  };
}
