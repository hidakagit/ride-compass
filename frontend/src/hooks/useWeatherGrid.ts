"use client";

// 風の格子点マップのフェッチ・マージ・detail切り替えを1つのフックへ抽出したもの
// （風と延長降水予報が共有できる形にしてある）。
// バックエンド（GET /api/weather/wind-grid・wind-grid-detail）は1回のフェッチで
// 風向・風速・降水量（precipitation_mm）をまとめて返すため、風の矢印と
// 延長降水予報アイコンは同じ格子点データを共有でき、enabledをどちらか一方でもONなら
// trueにして呼び出すだけで両機能ぶんのフェッチを1本化できる（呼び出し側はpage.tsxが
// 表示用に個別のFeatureCollectionへ変換する、windLayer.ts/precipitationNowcast.ts参照）。
import { useEffect, useRef, useState } from "react";
import {
  clampWindDetailBbox,
  mergeWindGridKeepingStale,
  trimWindGridToCurrentAndFuture,
  windGridDetailSpacingDegForZoom,
  WIND_DETAIL_MIN_ZOOM,
  WIND_GRID_SPACING_DEG,
  type MapViewport,
} from "@/components/Map/windLayer";
import type { WindGridPoint } from "@/types/weather";
import { getWindGrid, getWindGridDetail } from "@/services/weatherApi";
import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";

// バックエンド側のTTLキャッシュ（weather_client.py: WIND_GRID_CACHE_TTL_SECONDS）に合わせた
// 間隔で再取得する。これより短い間隔で再取得してもキャッシュヒットするだけで新しいデータは
// 得られず、624地点ぶんの応答（約0.9MB）を無駄に再ダウンロードするだけになる。
const WEATHER_GRID_REFRESH_INTERVAL_MS = 3 * 60 * 60 * 1000;
// パン・ズームのたびに（デバウンス済みとはいえ）呼ばれうるため、道路情報の絞り込み等の
// LEGEND_FILTER_DEBOUNCE_MSより長め。地図フィルタの再適用と違いネットワーク往復を伴うため、
// より鷹揚な間隔にしている（値自体はuseDebouncedValue.ts:
// MAP_FETCH_DEBOUNCE_MSへ集約、他の地図系フェッチデバウンスと共有）。

export interface UseWeatherGridResult {
  /** 粗い格子（関東本土全域を常時カバー、trim済み＝「現在」より前を切り捨て済み）。 */
  grid: WindGridPoint[];
  /** 詳細格子（ズームイン時のみ現在のビューポート付近を密にカバー、trim済み）。 */
  detailGrid: WindGridPoint[];
  /** 詳細格子が取得できていればそちらを優先し、無ければgridを使う（呼び出し側の既定の選択）。 */
  effectiveGrid: WindGridPoint[];
  /** effectiveGridの格子間隔（度）。detailGridを使っている間はズーム依存の間隔
   * （windGridDetailSpacingDegForZoom、T185）、gridへフォールバックしている間はWIND_GRID_
   * SPACING_DEG。gridFillのセルサイズ（precipitationNowcast.ts: precipitationRenderPayload）が
   * effectiveGridと矛盾しない間隔を使うために必要（実際のフェッチに使った値を返す。
   * windGridDetailSpacingDegForZoomを呼び出し側で再計算すると、フェッチ後にズームが
   * 動いていた場合に実際のデータと食い違いうる）。 */
  effectiveGridSpacingDeg: number;
  /** 粗い格子の初回フェッチ中かどうか。 */
  loading: boolean;
  /** 粗い格子の取得に失敗したときのメッセージ（詳細格子側の失敗は補助的な機能のため
   * サイレントにフォールバックするだけで、ここには反映されない）。 */
  error: string | null;
}

/** 風の矢印・延長降水予報（T183）が共有する格子点マップのフェッチ・状態管理。
 * enabledがtrueの間だけ取得し、OFFの間はfetch自体しない（他の外部APIと同じ「表示中の
 * ものだけ叩く」方針）。mapViewportはズームインしたときだけ詳細格子を追加取得するために
 * 使う（WIND_DETAIL_MIN_ZOOM未満では取得しない）。 */
export function useWeatherGrid(enabled: boolean, mapViewport: MapViewport | null): UseWeatherGridResult {
  const [grid, setGrid] = useState<WindGridPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailGrid, setDetailGrid] = useState<WindGridPoint[]>([]);
  const [detailSpacingDeg, setDetailSpacingDeg] = useState(WIND_GRID_SPACING_DEG);

  // 再取得のたびにOpen-Meteo側の一時的な失敗（429等）で一部地点だけ抜け落ちることがあり、
  // そのまま置き換えると地図上に「その地点だけ塗られていない」穴ができる。前回成功していた
  // 地点を補って残すmergeWindGridKeepingStaleのため、trim前の生の状態をrefで持ち続ける
  // （grid自体はtrim後の表示用state、こちらは
  // マージ専用の内部状態）。
  const rawGridRef = useRef<WindGridPoint[]>([]);
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const load = async (isFirstLoad: boolean) => {
      if (isFirstLoad) setLoading(true);
      try {
        const rawGrid = mergeWindGridKeepingStale(rawGridRef.current, await getWindGrid());
        rawGridRef.current = rawGrid;
        // Open-Meteoのhourly.timeはその日の00:00始まりのため、そのままだと配列の前半に
        // 過去の時刻が並ぶ。過去の風・降水を振り返る用途はアプリの性質上無いため、
        // trimWindGridToCurrentAndFutureで「現在」より前を切り捨てる。
        const trimmed = trimWindGridToCurrentAndFuture(rawGrid);
        if (cancelled) return;
        setGrid(trimmed);
        setError(null);
      } catch (err: unknown) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "気象格子データの取得に失敗しました");
      } finally {
        if (!cancelled && isFirstLoad) setLoading(false);
      }
    };
    Promise.resolve().then(() => load(true));
    const intervalId = window.setInterval(() => load(false), WEATHER_GRID_REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [enabled]);

  // ズームインして狭い範囲を見ているときだけ、現在のビューポートに交差する密な格子を取得する。
  const debouncedMapViewport = useDebouncedValue(mapViewport, MAP_FETCH_DEBOUNCE_MS);
  // rawGridRefと同じ理由（穴あき対策のマージ用、trim前の生の状態）。ただしこちらはビューポート
  // に応じてbboxが動くため、無限に古い地点を溜め込まないよう、マージ前に「現在のbboxに
  // 含まれる地点だけ」へ絞り込んでから使う（bbox外の地点は既に画面外なので補う意味が無く、
  // 絞り込まないと遠く離れたパン履歴がずっとメモリに残り続けてしまう）。
  const rawDetailGridRef = useRef<WindGridPoint[]>([]);
  // 直前フェッチで使った格子間隔（T185）。ズームをまたいで間隔が変わると、古い間隔の格子点は
  // 新しい間隔のラティスに乗らない（絶対座標が一致しない）ため、そのままmergeWindGridKeepingStale
  // で持ち越すと2つの間隔の点が混在してgridFillのセルサイズが実データと食い違ってしまう。
  // 間隔が変わった回だけ穴あき対策の持ち越しを諦め、新しい間隔で作り直す。
  const rawDetailGridSpacingRef = useRef<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    // setState呼び出しを含むため、effect本体からの直接同期呼び出しを避けてマイクロタスク
    // 経由で実行する（react-hooks/set-state-in-effect対策）。
    Promise.resolve().then(async () => {
      if (cancelled) return;
      if (!enabled || !debouncedMapViewport || debouncedMapViewport.zoom < WIND_DETAIL_MIN_ZOOM) {
        // ズームアウトした・レイヤーOFFにした場合は詳細格子を捨てて粗い格子へ戻す
        // （古いズームイン時点の詳細格子が、ズームアウト後もそのまま使われ続けるのを防ぐ）。
        rawDetailGridRef.current = [];
        rawDetailGridSpacingRef.current = null;
        setDetailGrid([]);
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
                point.latitude <= bbox.maxLat
            );
        const rawGrid = mergeWindGridKeepingStale(relevantPrevious, freshGrid);
        rawDetailGridRef.current = rawGrid;
        rawDetailGridSpacingRef.current = spacingDeg;
        // gridと同じ切り詰め（trimWindGridToCurrentAndFuture）を適用しないと、frameIndexが
        // effectiveGridへ切り替わったときにindexの意味がずれてしまう（gridは「現在」開始、
        // detailGridがその日の00:00開始のままだと同じindexが指す時刻が食い違う）。grid・
        // detailGridは別々のタイミングでフェッチされるため、正時をまたいだ瞬間だけ切り詰め
        // 開始時刻が1時間ずれる可能性はあるが、次の再取得（30分TTL・ビューポート変更時）で
        // 自然に揃うため許容する。
        const trimmed = trimWindGridToCurrentAndFuture(rawGrid);
        setDetailGrid(trimmed);
        setDetailSpacingDeg(spacingDeg);
      } catch {
        // 補助的な機能のため、失敗時はエラー表示をせず静かに粗い格子へフォールバックする
        // （リクエスト自体のログはweatherApi.ts側で既に記録済み）。
        if (cancelled) return;
        rawDetailGridRef.current = [];
        rawDetailGridSpacingRef.current = null;
        setDetailGrid([]);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [enabled, debouncedMapViewport]);

  const effectiveGrid = detailGrid.length > 0 ? detailGrid : grid;
  const effectiveGridSpacingDeg = detailGrid.length > 0 ? detailSpacingDeg : WIND_GRID_SPACING_DEG;

  return { grid, detailGrid, effectiveGrid, effectiveGridSpacingDeg, loading, error };
}
