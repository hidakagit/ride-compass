"use client";

import { useEffect, useState } from "react";
import { debugLog } from "@/lib/debugLog";

export interface UsePolledFetchResult<T> {
  data: T;
  /** 初回フェッチが完了するまでtrue（2回目以降のポーリングでは変化しない）。使わない
   * 呼び出し側は無視してよい。 */
  loading: boolean;
  /** 直近の取得失敗メッセージ（成功時はnullへ戻る）。使わない呼び出し側は無視してよい。 */
  error: string | null;
}

export interface UsePolledFetchOptions {
  /** falseの間はフェッチ・ポーリングを一切行わない（既存のdata/loading/errorは変化しない）。 */
  enabled: boolean;
  intervalMs: number;
  /** デフォルトのエラーメッセージ・debugLogの文言に使う対象名（例:「降水ナウキャスト」）。 */
  label: string;
  debugLogCategory?: string;
}

/** マウント（enabled=true）時に即座に1回フェッチし、以降intervalMsごとに再フェッチし続ける
 * ポーリングフック（改善計画T470）。
 *
 * useDynamicWeatherLayers.tsに「cancelledフラグ+Promise+catch」の同型フェッチ骨格が
 * 5箇所（降水ナウキャスト・降水短時間予報・雷竜巻ナウキャスト・キキクル・線状降水帯予測
 * マップ）独立実装されていたのを、この1フックへ集約する。cancelledフラグで、依存変化・
 * アンマウント後に古いフェッチのレスポンスが新しい状態を上書きするのを防ぐ（Reactの
 * 定石パターン）。
 */
export function usePolledFetch<T>(
  fetcher: () => Promise<T>,
  initialValue: T,
  { enabled, intervalMs, label, debugLogCategory = "api:jma-nowcast-times" }: UsePolledFetchOptions,
): UsePolledFetchResult<T> {
  const [data, setData] = useState<T>(initialValue);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const load = async (isFirstLoad: boolean) => {
      if (isFirstLoad) setLoading(true);
      try {
        const result = await fetcher();
        if (cancelled) return;
        setData(result);
        setError(null);
      } catch (err: unknown) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : `${label}の取得に失敗しました`;
        debugLog(debugLogCategory, `${label}の読み込みに失敗`, { error: message }, "warn");
        setError(message);
      } finally {
        if (!cancelled && isFirstLoad) setLoading(false);
      }
    };
    Promise.resolve().then(() => load(true));
    const intervalId = window.setInterval(() => load(false), intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [enabled, intervalMs, fetcher, label, debugLogCategory]);

  return { data, loading, error };
}
