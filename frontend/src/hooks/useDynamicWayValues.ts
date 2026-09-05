"use client";

// way_id→動的値配信層（風・勾配）のフェッチ・状態管理。
// useWeatherGrid.ts（風の詳細格子）のdetailGrid取得effectと同じ「viewportをデバウンスして
// から、タイル単位でまとめてfetchする」パターンを踏襲する——パン・ズームのたびに個別way_idを
// 都度問い合わせず、表示中のタイル範囲ぶんをまとめて1回のリクエストで取得する。enabledが
// OFFの間はfetchせず（他の外部APIと同じ「表示中のものだけ叩く」方針）、結果も空へ戻す。
//
// 風・勾配どちらもこのフックを使う。`byTile`（材料id・タイルごとの生応答）は、評価軸
// グループ（線、setFeatureState）向けにway_id単位でマージした`values`とは別に、勾配の
// 環境グループgridFill（gradientGridFill.ts）がタイル境界をセルとする面表示のためタイル
// 単位の生データを必要とすることから持つ（風はgridFillを持たずway_id単位のvaluesだけで
// 足りるため、byTileは使わない）。

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
  /** 現在のビューポートぶんのフェッチが進行中か。falseへ戻るまでの間、
   * まだ一度も値を受け取っていないway（feature-stateキー未設定）は「取得中」、フェッチ
   * 完了後になお値を持たないwayは「その範囲に値が無い」と呼び出し側が区別できるようにする
   * （valueScale.ts: COLOR_LOADING/COLOR_NO_DATA参照）。 */
  loading: boolean;
  /** 直近に完了したフェッチで、いずれかのタイルの取得が通信失敗（HTTPエラー・
   * ネットワークエラー）したか。falseは「本当にその範囲にway_idが無い」場合と区別する
   * （fetchDynamicWayValuesのerrorをタイル横断でOR集約する）。 */
  error: boolean;
}

const EMPTY_RESULT: UseDynamicWayValuesResult = { values: new Map(), byTile: [], loading: false, error: false };

/** enabled中、現在のビューポート（デバウンス済み）を覆う道路タイル分をまとめて取得し、
 * way_id→値のMapへ統合して返す。連続する呼び出しの間に古いリクエストが後から解決しても
 * 新しい結果を上書きしないよう、リクエストの世代（seq）で最新のものだけを反映する
 * （useWeatherGridのcancelledパターンと同じ意図、複数タイルのPromise.allをまたぐため
 * 世代番号で判定する）。
 *
 * `materialId`（"wind"/"gradient"）ごとに呼び出し側が別々にこのフックを使う想定
 * （page.tsx参照）。`bearingDeg`はviewportと同様デバウンス後の値を使い、どちらかが
 * 変わるたびに依存配列経由で再フェッチする（enabled/debouncedViewportの変化と同じ扱い）。
 * `at`は時刻に依存する材料（風）だけが意味を持つ（勾配はundefinedのまま渡してよい）。
 * `speedKmh`（想定速度）は走行速度に依存する材料（風の`wind_drag_ratio`）だけがbackend側で
 * 使う（それ以外の材料は無視するため渡しても害はない）。 */
export function useDynamicWayValues(
  materialId: string,
  enabled: boolean,
  mapViewport: MapViewport | null,
  bearingDeg: number,
  at: Date | undefined,
  speedKmh?: number
): UseDynamicWayValuesResult {
  const [result, setResult] = useState<UseDynamicWayValuesResult>(EMPTY_RESULT);
  const debouncedViewport = useDebouncedValue(mapViewport, MAP_FETCH_DEBOUNCE_MS);
  const debouncedBearingDeg = useDebouncedValue(bearingDeg, MAP_FETCH_DEBOUNCE_MS);
  // 想定速度の入力欄も連続入力されるため、向きと同じくデバウンスする。
  const debouncedSpeedKmh = useDebouncedValue(speedKmh, MAP_FETCH_DEBOUNCE_MS);
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
      setResult((prev) => ({ ...prev, loading: true }));
      const tiles: TileXY[] = tilesCoveringViewport(debouncedViewport, ROAD_TILE_MIN_ZOOM, ROAD_TILE_MAX_ZOOM);
      const seq = ++requestSeqRef.current;
      const responses = await Promise.all(
        tiles.map((tile) =>
          fetchDynamicWayValues(materialId, tile.z, tile.x, tile.y, debouncedBearingDeg, at, debouncedSpeedKmh)
        )
      );
      if (cancelled || seq !== requestSeqRef.current) return;
      setResult({
        values: mergeDynamicWayValues(responses.map((response) => response.values)),
        byTile: tiles.map((tile, index) => ({ tile, values: responses[index].values })),
        loading: false,
        error: responses.some((response) => response.error),
      });
    });
    return () => {
      cancelled = true;
    };
  }, [materialId, enabled, debouncedViewport, debouncedBearingDeg, at, debouncedSpeedKmh]);

  return result;
}
