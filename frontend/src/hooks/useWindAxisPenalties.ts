"use client";

// way_id→wind_penalty配信層（改善計画T405）のフェッチ・状態管理。useWeatherGrid.ts
// （風の詳細格子）のdetailGrid取得effectと同じ「viewportをデバウンスしてから、タイル単位で
// まとめてfetchする」パターンを踏襲する——パン・ズームのたびに個別way_idを都度問い合わせず、
// 表示中のタイル範囲ぶんをまとめて1回のリクエストで取得するという設計方針（T405.md）に
// 沿う。enabledがOFFの間はfetchせず（他の外部APIと同じ「表示中のものだけ叩く」方針）、
// 結果も空へ戻す。

import { useEffect, useRef, useState } from "react";
import { tilesCoveringViewport, mergeWindWayPenalties, type TileXY } from "@/components/Map/windAxisLayer";
import type { MapViewport } from "@/components/Map/windLayer";
import { fetchWindWayPenalties, ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM } from "@/services/regionApi";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";

// パン・ズームのたびに（デバウンス済みとはいえ）呼ばれうるため、道路情報の絞り込み等の
// LEGEND_FILTER_DEBOUNCE_MSより長め。useWeatherGrid.tsのWEATHER_GRID_DETAIL_VIEWPORT_
// DEBOUNCE_MSと同じ値（ネットワーク往復を伴う地図系フェッチの標準的な間隔として揃える）。
const WIND_AXIS_VIEWPORT_DEBOUNCE_MS = 500;
// コンパススライダー（WindBearingSlider）はドラッグ中onChangeを連続発火するため、bearingDeg
// もviewportと同様にデバウンスする（そのまま依存配列へ入れるとドラッグ1回で可視タイル数×
// 連続イベント数ぶんのfetchが発生してしまう）。

/** enabled中、現在のビューポート（デバウンス済み）を覆う道路タイル分をまとめて取得し、
 * way_id→wind_penaltyのMapへ統合して返す。連続する呼び出しの間に古いリクエストが後から
 * 解決しても新しい結果を上書きしないよう、リクエストの世代（seq）で最新のものだけを
 * 反映する（useWeatherGridのcancelledパターンと同じ意図、複数タイルのPromise.allを
 * またぐため世代番号で判定する）。
 *
 * 改善計画T414: `bearingDeg`（コンパススライダー、環境グループと共有）・`at`
 * （共有タイムライン、環境グループと共有）を毎回のフェッチへ渡す。`bearingDeg`は
 * viewportと同様デバウンス後の値を使い、どちらかが変わるたびに依存配列経由で再フェッチする
 * （enabled/debouncedViewportの変化と同じ扱い）。 */
export function useWindAxisPenalties(
  enabled: boolean,
  mapViewport: MapViewport | null,
  bearingDeg: number,
  at: Date | undefined
): ReadonlyMap<number, number> {
  const [penalties, setPenalties] = useState<Map<number, number>>(() => new Map());
  const debouncedViewport = useDebouncedValue(mapViewport, WIND_AXIS_VIEWPORT_DEBOUNCE_MS);
  const debouncedBearingDeg = useDebouncedValue(bearingDeg, WIND_AXIS_VIEWPORT_DEBOUNCE_MS);
  const requestSeqRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    // setState呼び出しを含むため、effect本体からの直接同期呼び出しを避けてマイクロタスク
    // 経由で実行する（useWeatherGridと同じreact-hooks/set-state-in-effect対策）。
    Promise.resolve().then(async () => {
      if (cancelled) return;
      if (!enabled || !debouncedViewport) {
        setPenalties(new Map());
        return;
      }
      const tiles: TileXY[] = tilesCoveringViewport(debouncedViewport, ROAD_TILE_MIN_ZOOM, ROAD_TILE_MAX_ZOOM);
      const seq = ++requestSeqRef.current;
      const responses = await Promise.all(
        tiles.map((tile) => fetchWindWayPenalties(tile.z, tile.x, tile.y, debouncedBearingDeg, at))
      );
      if (cancelled || seq !== requestSeqRef.current) return;
      setPenalties(mergeWindWayPenalties(responses));
    });
    return () => {
      cancelled = true;
    };
  }, [enabled, debouncedViewport, debouncedBearingDeg, at]);

  return penalties;
}
