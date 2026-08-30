"use client";

// way_id→動的値配信層（風・勾配、改善計画T405→T414→T423）のフェッチ・状態管理。
// useWeatherGrid.ts（風の詳細格子）のdetailGrid取得effectと同じ「viewportをデバウンスして
// から、タイル単位でまとめてfetchする」パターンを踏襲する——パン・ズームのたびに個別way_idを
// 都度問い合わせず、表示中のタイル範囲ぶんをまとめて1回のリクエストで取得するという設計方針
// （T405.md）に沿う。enabledがOFFの間はfetchせず（他の外部APIと同じ「表示中のものだけ叩く」
// 方針）、結果も空へ戻す。
//
// 改善計画T423（T411の実施）: 旧hooks/useWindAxisPenalties.tsを材料id駆動へ汎用化した
// （風・勾配どちらもこのフックを使う）。`byTile`（材料id・タイルごとの生応答）を新たに
// 返すようにした——評価軸グループ（線、setFeatureState）はway_id単位でマージした`values`を
// 使えば足りるが、勾配の環境グループgridFill（gradientGridFill.ts）はタイル境界をセルとする
// 面表示のため、タイル単位の生データが要る（風のgridFillは別経路[useWeatherGrid由来の格子点]
// のためbyTileを使わない）。

import { useEffect, useRef, useState } from "react";
import { mergeDynamicWayValues, tilesCoveringViewport, type TileXY } from "@/components/Map/dynamicWayValues";
import type { MapViewport } from "@/components/Map/windLayer";
import { fetchDynamicWayValues, ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM } from "@/services/regionApi";
import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";

// コンパススライダー（WindBearingSlider）はドラッグ中onChangeを連続発火するため、bearingDeg
// もviewportと同様にデバウンスする（そのまま依存配列へ入れるとドラッグ1回で可視タイル数×
// 連続イベント数ぶんのfetchが発生してしまう）。

export interface TileDynamicWayValues {
  tile: TileXY;
  values: Record<string, number>;
}

export interface UseDynamicWayValuesResult {
  /** way_id→値（複数タイルを統合済み）。評価軸グループのsetFeatureStateにそのまま使える。 */
  values: ReadonlyMap<number, number>;
  /** タイルごとの生応答（統合前）。環境グループのgridFill（タイル境界をセルとする面表示）が
   * タイル単位の集計に使う。 */
  byTile: readonly TileDynamicWayValues[];
}

const EMPTY_RESULT: UseDynamicWayValuesResult = { values: new Map(), byTile: [] };

/** enabled中、現在のビューポート（デバウンス済み）を覆う道路タイル分をまとめて取得し、
 * way_id→値のMapへ統合して返す。連続する呼び出しの間に古いリクエストが後から解決しても
 * 新しい結果を上書きしないよう、リクエストの世代（seq）で最新のものだけを反映する
 * （useWeatherGridのcancelledパターンと同じ意図、複数タイルのPromise.allをまたぐため
 * 世代番号で判定する）。
 *
 * `materialId`（"wind"/"gradient"）ごとに呼び出し側が別々にこのフックを使う想定
 * （page.tsx参照）。`bearingDeg`はviewportと同様デバウンス後の値を使い、どちらかが
 * 変わるたびに依存配列経由で再フェッチする（enabled/debouncedViewportの変化と同じ扱い）。
 * `at`は時刻に依存する材料（風）だけが意味を持つ（勾配はundefinedのまま渡してよい）。 */
export function useDynamicWayValues(
  materialId: string,
  enabled: boolean,
  mapViewport: MapViewport | null,
  bearingDeg: number,
  at: Date | undefined
): UseDynamicWayValuesResult {
  const [result, setResult] = useState<UseDynamicWayValuesResult>(EMPTY_RESULT);
  const debouncedViewport = useDebouncedValue(mapViewport, MAP_FETCH_DEBOUNCE_MS);
  const debouncedBearingDeg = useDebouncedValue(bearingDeg, MAP_FETCH_DEBOUNCE_MS);
  const requestSeqRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    // setState呼び出しを含むため、effect本体からの直接同期呼び出しを避けてマイクロタスク
    // 経由で実行する（useWeatherGridと同じreact-hooks/set-state-in-effect対策）。
    Promise.resolve().then(async () => {
      if (cancelled) return;
      if (!enabled || !debouncedViewport) {
        setResult(EMPTY_RESULT);
        return;
      }
      const tiles: TileXY[] = tilesCoveringViewport(debouncedViewport, ROAD_TILE_MIN_ZOOM, ROAD_TILE_MAX_ZOOM);
      const seq = ++requestSeqRef.current;
      const responses = await Promise.all(
        tiles.map((tile) => fetchDynamicWayValues(materialId, tile.z, tile.x, tile.y, debouncedBearingDeg, at))
      );
      if (cancelled || seq !== requestSeqRef.current) return;
      setResult({
        values: mergeDynamicWayValues(responses),
        byTile: tiles.map((tile, index) => ({ tile, values: responses[index] })),
      });
    });
    return () => {
      cancelled = true;
    };
  }, [materialId, enabled, debouncedViewport, debouncedBearingDeg, at]);

  return result;
}
