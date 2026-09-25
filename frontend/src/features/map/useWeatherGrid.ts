"use client";

import { useCallback, useEffect, useRef, useState } from "react";
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
import { getWindGrid, getWindGridDetail } from "@/services/weatherApi";
import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";
import { usePolledFetch } from "@/features/map/usePolledFetch";

// 配信元（気象庁MSM）の更新の間隔に合わせる（短くしても新しい値は無く、MB級の応答を取り直すだけ）。
const WEATHER_GRID_REFRESH_INTERVAL_MS = 3 * 60 * 60 * 1000;
// 初期値（描くたびに新しい配列を渡すと、dataの参照が無用に変わる）。
const EMPTY_GRID: WindGridPoint[] = [];

interface UseWeatherGridResult {
  /** 粗い格子（関東の全域、今より前は切り詰め済み）。 */
  grid: WindGridPoint[];
  /** 詳細格子（ズームしたときだけ、表示範囲の付近を密に。切り詰め済み）。 */
  detailGrid: WindGridPoint[];
  /** 詳細格子があればそれ、無ければ粗い格子。 */
  effectiveGrid: WindGridPoint[];
  /** effectiveGridの間隔（度）。取ったときの値を返す（呼ぶ側でズームから計算し直すと、取った後にズームが動いたとき
   * 中身と食い違う）。 */
  effectiveGridSpacingDeg: number;
  loading: boolean;
  /** 粗い格子の取得の失敗（詳細格子の失敗は黙って粗い格子へ戻るだけ）。 */
  error: string | null;
  /** 粗い格子を一度でも取り終えたか（成否は問わない）。 */
  hasFetched: boolean;
}

/** 風の矢印と降水の延長予報が共有する格子（1回の取得に風と降水が載る）。`enabled`の間だけ取り、ズームしたときだけ
 * 詳細格子も取る。 */
export function useWeatherGrid(enabled: boolean, mapViewport: MapViewport | null): UseWeatherGridResult {
  // 取り損ねた地点を前回の値で補うための、切り詰める前の格子。
  const rawGridRef = useRef<WindGridPoint[]>([]);
  const fetchCoarseGrid = useCallback(async () => {
    const rawGrid = mergeWindGridKeepingStale(rawGridRef.current, await getWindGrid());
    rawGridRef.current = rawGrid;
    return trimWindGridToCurrentAndFuture(rawGrid);
  }, []);
  const {
    data: grid,
    loading,
    error,
    hasFetched,
  } = usePolledFetch<WindGridPoint[]>(fetchCoarseGrid, EMPTY_GRID, {
    enabled,
    intervalMs: WEATHER_GRID_REFRESH_INTERVAL_MS,
    label: "気象格子データ",
    debugLogCategory: "api:windGrid",
  });

  const [detailGrid, setDetailGrid] = useState<WindGridPoint[]>([]);
  const [detailSpacingDeg, setDetailSpacingDeg] = useState(WIND_GRID_SPACING_DEG);

  const debouncedMapViewport = useDebouncedValue(mapViewport, MAP_FETCH_DEBOUNCE_MS);
  // 補う元の詳細格子。補うのは今の範囲の中の点だけ（範囲の外は画面の外で、溜めるとパンの跡が残り続ける）。
  const rawDetailGridRef = useRef<WindGridPoint[]>([]);
  // 前回の間隔。間隔が変わった回は補わない（古い間隔の点は新しい格子に乗らず、セルの大きさが中身と食い違う）。
  const rawDetailGridSpacingRef = useRef<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    const dropDetail = () => {
      rawDetailGridRef.current = [];
      rawDetailGridSpacingRef.current = null;
      setDetailGrid([]);
    };
    // effectの中で同期にsetStateしない（react-hooks/set-state-in-effect）。
    Promise.resolve().then(async () => {
      if (cancelled) return;
      if (!enabled || !debouncedMapViewport || debouncedMapViewport.zoom < WIND_DETAIL_MIN_ZOOM) {
        dropDetail();
        return;
      }
      const spacingDeg = windGridDetailSpacingDegForZoom(debouncedMapViewport.zoom);
      const bbox = clampWindDetailBbox(debouncedMapViewport, spacingDeg);
      try {
        const freshGrid = await getWindGridDetail(bbox, spacingDeg);
        if (cancelled) return;
        const spacingChanged = rawDetailGridSpacingRef.current !== spacingDeg;
        const relevantPrevious = spacingChanged
          ? []
          : rawDetailGridRef.current.filter(
              (point) =>
                point.longitude >= bbox.minLon &&
                point.longitude <= bbox.maxLon &&
                point.latitude >= bbox.minLat &&
                point.latitude <= bbox.maxLat,
            );
        const rawGrid = mergeWindGridKeepingStale(relevantPrevious, freshGrid);
        rawDetailGridRef.current = rawGrid;
        rawDetailGridSpacingRef.current = spacingDeg;
        // 粗い格子と同じく切り詰める（揃えないと、切り替えたときに同じ添字が別の時刻を指す）。
        setDetailGrid(trimWindGridToCurrentAndFuture(rawGrid));
        setDetailSpacingDeg(spacingDeg);
      } catch {
        // 補助の機能なので、失敗は知らせず粗い格子へ戻る（取得のログは記録済み）。
        if (!cancelled) dropDetail();
      }
    });
    return () => {
      cancelled = true;
    };
  }, [enabled, debouncedMapViewport]);

  // 詳細格子があれば粗い格子を置き換える（半透明の面を2枚重ねると、重なった所だけ濃く見える）。
  const effectiveGrid = detailGrid.length > 0 ? detailGrid : grid;
  const effectiveGridSpacingDeg = detailGrid.length > 0 ? detailSpacingDeg : WIND_GRID_SPACING_DEG;

  return { grid, detailGrid, effectiveGrid, effectiveGridSpacingDeg, loading, error, hasFetched };
}
