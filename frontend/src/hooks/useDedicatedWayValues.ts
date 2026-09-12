"use client";

// 専用way値配信軸（`dedicated_way_value_layer=true`の軸、現状: 風・勾配）の
// way_id→値フェッチ・状態管理。
// useWeatherGrid.ts（風の詳細格子）のdetailGrid取得effectと同じ「viewportをデバウンスして
// から、タイル単位でまとめてfetchする」パターンを踏襲する——パン・ズームのたびに個別way_idを
// 都度問い合わせず、表示中のタイル範囲ぶんをまとめて1回のリクエストで取得する。取得対象の
// 軸が0件の間はfetchせず（他の外部APIと同じ「表示中のものだけ叩く」方針）、結果も空へ戻す。
//
// 対象の軸ごとに別インスタンスを持たず、1つのフックが軸の配列を受け取って全軸ぶんを賄う
// （Reactのフック規則により、実行時に増減しうる軸の件数だけフックを呼ぶことはできない
// ——軸スタジオで3件目が公開されても呼び出し側の変更が要らないようにするための構造）。
// 時刻・想定速度をどの軸のリクエストへ載せるかは軸カタログの宣言（`needsTime`/`needsSpeed`）
// から決め、載せない軸はその入力が変わっても再フェッチしない（キーが変わらないため）。
//
// `byTile`（軸・タイルごとの生応答）は、評価軸グループ（線、setFeatureState）向けに
// way_id単位でマージした`values`とは別に、勾配の環境グループgridFill（gradientGridFill.ts）が
// タイル境界をセルとする面表示のためタイル単位の生データを必要とすることから持つ。

import { useEffect, useRef, useState } from "react";
import { mergeDynamicWayValues, tilesCoveringViewport, type TileXY } from "@/components/Map/dynamicWayValues";
import type { DedicatedWayValueAxis } from "@/components/Map/axisLayers";
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

export interface DedicatedWayValuesResult {
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
  /** 一度でも取得を試みて完了したか（成否は問わない）。対象軸に含まれていない間はfalseのまま。
   * 「まだ取りに行っていない」と「取得したが値が無かった」を呼び出し側が区別するために使う
   * （`mapLayers.ts: deriveFetchLayerStatus`）。 */
  hasFetched: boolean;
}

const EMPTY_DEDICATED_WAY_VALUES_RESULT: DedicatedWayValuesResult = {
  values: new Map(),
  byTile: [],
  loading: false,
  error: false,
  hasFetched: false,
};

const EMPTY_RESULTS: ReadonlyMap<string, DedicatedWayValuesResult> = new Map();

/** その軸の1回のフェッチを一意に決める入力（軸id＋その軸へ載せるクエリパラメータ＋
 * 向き＋対象タイル集合）。同じキーの間は再フェッチしない——時刻に依存しない軸は時刻が
 * 変わってもキーが変わらないため、時刻スライダーの操作で巻き添えの再取得が起きない。 */
function requestKey(
  axisId: string,
  at: Date | undefined,
  speedKmh: number | undefined,
  bearingDeg: number,
  tiles: readonly TileXY[]
): string {
  const tileKey = tiles.map((tile) => `${tile.z}/${tile.x}/${tile.y}`).join(",");
  return [axisId, at?.toISOString() ?? "", speedKmh ?? "", bearingDeg, tileKey].join("|");
}

/** `axes`（取得対象の専用way値配信軸。呼び出し側がuseMemoで安定した参照を渡すこと）について、
 * 現在のビューポート（デバウンス済み）を覆う道路タイル分をまとめて取得し、軸id→結果のMapを
 * 返す。連続する呼び出しの間に古いリクエストが後から解決しても新しい結果を上書きしないよう、
 * リクエストの世代（seq）で最新のものだけを反映する（useWeatherGridのcancelledパターンと
 * 同じ意図、複数タイルのPromise.allをまたぐため世代番号で判定する）。
 *
 * `bearingDeg`はviewportと同様デバウンス後の値を使い、どちらかが変わるたびに再フェッチする。
 * `at`（時刻）・`speedKmh`（想定速度）は全軸で共有の入力で、実際にリクエストへ載るのは
 * それを必要とすると宣言した軸（`needsTime`/`needsSpeed`）だけ。 */
export function useDedicatedWayValues(
  axes: readonly DedicatedWayValueAxis[],
  mapViewport: MapViewport | null,
  bearingDeg: number,
  at: Date | undefined,
  speedKmh?: number
): ReadonlyMap<string, DedicatedWayValuesResult> {
  const [results, setResults] = useState<ReadonlyMap<string, DedicatedWayValuesResult>>(EMPTY_RESULTS);
  const debouncedViewport = useDebouncedValue(mapViewport, MAP_FETCH_DEBOUNCE_MS);
  const debouncedBearingDeg = useDebouncedValue(bearingDeg, MAP_FETCH_DEBOUNCE_MS);
  // 想定速度の入力欄も連続入力されるため、向きと同じくデバウンスする。
  const debouncedSpeedKmh = useDebouncedValue(speedKmh, MAP_FETCH_DEBOUNCE_MS);
  const requestSeqRef = useRef(0);
  // 軸ごとに「直近に取得済みの入力キー」を覚え、変わっていない軸は再フェッチしない。
  const fetchedKeysRef = useRef<Map<string, string>>(new Map());

  useEffect(() => {
    let cancelled = false;
    // setState呼び出しを含むため、effect本体からの直接同期呼び出しを避けてマイクロタスク
    // 経由で実行する（useWeatherGridと同じreact-hooks/set-state-in-effect対策）。
    Promise.resolve().then(async () => {
      if (cancelled) return;
      if (!debouncedViewport || axes.length === 0) {
        fetchedKeysRef.current = new Map();
        setResults((prev) => (prev.size === 0 ? prev : EMPTY_RESULTS));
        return;
      }
      const tiles: TileXY[] = tilesCoveringViewport(debouncedViewport, ROAD_TILE_MIN_ZOOM, ROAD_TILE_MAX_ZOOM);
      const params = axes.map((axis) => ({
        axisId: axis.axisId,
        at: axis.needsTime ? at : undefined,
        speedKmh: axis.needsSpeed ? debouncedSpeedKmh : undefined,
      }));
      const keys = new Map(params.map((param) => [param.axisId, requestKey(param.axisId, param.at, param.speedKmh, debouncedBearingDeg, tiles)]));
      const stale = params.filter((param) => fetchedKeysRef.current.get(param.axisId) !== keys.get(param.axisId));
      // 取得済みで入力も変わっていない軸だけが残っている（＝対象軸の集合も同じ）なら、
      // 新しいMapを作らずに現在の結果をそのまま使う（参照が変わるとMapView側の
      // setFeatureState反映effectが無用に再実行されるため）。
      if (stale.length === 0 && results.size === params.length) return;
      // 対象から外れた軸を落とし、再取得する軸だけloading=trueにする。
      setResults((prev) => {
        const next = new Map<string, DedicatedWayValuesResult>();
        for (const param of params) {
          const previous = prev.get(param.axisId) ?? EMPTY_DEDICATED_WAY_VALUES_RESULT;
          const isStale = stale.some((target) => target.axisId === param.axisId);
          next.set(param.axisId, isStale ? { ...previous, loading: true } : previous);
        }
        return next;
      });
      if (stale.length === 0) return;
      const seq = ++requestSeqRef.current;
      const fetched = await Promise.all(
        stale.map(async (param) => ({
          axisId: param.axisId,
          responses: await Promise.all(
            tiles.map((tile) =>
              fetchDynamicWayValues(param.axisId, tile.z, tile.x, tile.y, debouncedBearingDeg, param.at, param.speedKmh)
            )
          ),
        }))
      );
      if (cancelled || seq !== requestSeqRef.current) return;
      fetchedKeysRef.current = keys;
      setResults((prev) => {
        const next = new Map<string, DedicatedWayValuesResult>();
        for (const param of params) next.set(param.axisId, prev.get(param.axisId) ?? EMPTY_DEDICATED_WAY_VALUES_RESULT);
        for (const entry of fetched) {
          next.set(entry.axisId, {
            values: mergeDynamicWayValues(entry.responses.map((response) => response.values)),
            byTile: tiles.map((tile, index) => ({ tile, values: entry.responses[index].values })),
            loading: false,
            error: entry.responses.some((response) => response.error),
            hasFetched: true,
          });
        }
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
    // resultsは「同じ結果を作り直さない」ための早期returnの判定にのみ使うため、依存には含めない
    // （含めると自身のsetResultsで再実行され続ける）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [axes, debouncedViewport, debouncedBearingDeg, at, debouncedSpeedKmh]);

  return results;
}

/** 対象外の軸・未取得の軸を「空の結果」として扱うための読み出しヘルパー
 * （呼び出し側が`?? EMPTY`を書き散らさないため）。 */
export function dedicatedWayValuesFor(
  results: ReadonlyMap<string, DedicatedWayValuesResult>,
  axisId: string | undefined
): DedicatedWayValuesResult {
  if (!axisId) return EMPTY_DEDICATED_WAY_VALUES_RESULT;
  return results.get(axisId) ?? EMPTY_DEDICATED_WAY_VALUES_RESULT;
}
