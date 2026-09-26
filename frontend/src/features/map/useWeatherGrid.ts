"use client";

import { keepPreviousData, useQuery, type QueryClient } from "@tanstack/react-query";
import {
  clampWindDetailBbox,
  mergeWindGridKeepingStale,
  trimWindGridToCurrentAndFuture,
  windGridDetailSpacingDegForZoom,
  WIND_DETAIL_MIN_ZOOM,
  WIND_GRID_SPACING_DEG,
  type MapViewport,
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

/** 詳細格子と、それを取ったときの間隔（取り直しの間は前の範囲の格子を出すので、間隔も格子と一緒に持つ）。 */
interface DetailGrid {
  spacingDeg: number;
  points: WindGridPoint[];
}

interface UseWeatherGridResult {
  /** 粗い格子（関東の全域、今より前は切り詰め済み）。 */
  grid: WindGridPoint[];
  /** 詳細格子（ズームしたときだけ、表示範囲の付近を密に。切り詰め済み）があればそれ、無ければ粗い格子。 */
  effectiveGrid: WindGridPoint[];
  /** effectiveGridの間隔（度）。取ったときの値を返す（呼ぶ側でズームから計算し直すと、取った後にズームが動いたとき
   * 中身と食い違う）。 */
  effectiveGridSpacingDeg: number;
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
  effectiveGrid: EMPTY_GRID,
  effectiveGridSpacingDeg: WIND_GRID_SPACING_DEG,
  loading: false,
  error: null,
  hasFetched: false,
};

// キャッシュには切り詰める前の格子を置く（取り損ねた地点を補う元になる）。切り詰めは読み出すときに行い、詳細格子も
// 粗い格子と同じく切り詰める（揃えないと、切り替えたときに同じ添字が別の時刻を指す）。
function trimDetail(detail: DetailGrid): DetailGrid {
  return { spacingDeg: detail.spacingDeg, points: trimWindGridToCurrentAndFuture(detail.points) };
}

/** 同じ間隔の詳細格子のうち、最後に届いたもの。範囲を動かすたびにキーが変わるので、補う元はキャッシュから引く
 * （間隔が違う格子の点は新しい格子に乗らず、セルの大きさが中身と食い違うので使わない）。 */
function latestDetailGrid(client: QueryClient, spacingDeg: number): WindGridPoint[] {
  let latest: { updatedAt: number; points: WindGridPoint[] } | undefined;
  for (const query of client.getQueryCache().findAll({ queryKey: [DETAIL_GRID_KEY, spacingDeg] })) {
    const detail = query.state.data as DetailGrid | undefined;
    if (detail !== undefined && (latest === undefined || query.state.dataUpdatedAt >= latest.updatedAt)) {
      latest = { updatedAt: query.state.dataUpdatedAt, points: detail.points };
    }
  }
  return latest?.points ?? EMPTY_GRID;
}

async function fetchDetailGrid(client: QueryClient, bbox: Bbox, spacingDeg: number): Promise<DetailGrid> {
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
 * 詳細格子も取る。 */
export function useWeatherGrid(enabled: boolean, mapViewport: MapViewport | null): UseWeatherGridResult {
  const client = getQueryClient();
  const coarse = useQuery(
    {
      queryKey: COARSE_GRID_KEY,
      queryFn: async () => mergeWindGridKeepingStale(client.getQueryData(COARSE_GRID_KEY) ?? [], await getWindGrid()),
      select: trimWindGridToCurrentAndFuture,
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
      select: trimDetail,
      enabled: zoomedIn,
      // 範囲を動かして取り直す間は前の範囲の格子を出したままにする（粗い格子へ一瞬戻すと、重ねた面がちらつく）。
      placeholderData: keepPreviousData,
    },
    client,
  );

  if (!enabled) return DISABLED;
  const grid = coarse.data ?? EMPTY_GRID;
  // 詳細格子の失敗は知らせず粗い格子へ戻る（取得のログは記録済み）。
  const detailGrid = zoomedIn ? (detail.data?.points ?? EMPTY_GRID) : EMPTY_GRID;
  // 詳細格子があれば粗い格子を置き換える（半透明の面を2枚重ねると、重なった所だけ濃く見える）。
  const useDetail = detailGrid.length > 0;
  return {
    grid,
    effectiveGrid: useDetail ? detailGrid : grid,
    effectiveGridSpacingDeg: useDetail ? detail.data!.spacingDeg : WIND_GRID_SPACING_DEG,
    loading: coarse.isLoading,
    error: coarse.error?.message ?? null,
    hasFetched: coarse.isFetched,
  };
}
