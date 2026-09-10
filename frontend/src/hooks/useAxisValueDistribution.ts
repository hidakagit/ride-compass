"use client";

// 編集中のshapeに対する生値分布の取得。折れ点だけを動かしている間は再取得しない
// （折れ点は分布の形を変えず、当てはめ方だけを変えるため。当てはめは
// components/AxisStudio/scoreDistribution.ts がクライアント側で行う）。

import { useEffect, useRef, useState } from "react";

import type { ValueDistribution } from "@/components/AxisStudio/scoreDistribution";
import { fetchAxisValueDistribution } from "@/services/axisPreviewApi";
import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";

export interface AxisValueDistributionResult {
  distribution: ValueDistribution | null;
  loading: boolean;
  error: string | null;
}

/**
 * `termsKey`は「分布の形を決める部分」（材料id・重み・required・preprocess）を文字列化した
 * もの。折れ点を含めないことで、折れ点のドラッグ中に通信が走らない。
 */
export function useAxisValueDistribution(
  enabled: boolean,
  termsKey: string,
  shapeForRequest: () => unknown,
): AxisValueDistributionResult {
  const [result, setResult] = useState<AxisValueDistributionResult>({
    distribution: null,
    loading: false,
    error: null,
  });
  const debouncedKey = useDebouncedValue(termsKey, MAP_FETCH_DEBOUNCE_MS);
  const shapeRef = useRef(shapeForRequest);
  const seqRef = useRef(0);

  // refの書き込みはレンダー中ではなくeffectで行う（レンダー中のref操作は
  // Reactの並行レンダリングで一貫性を失う）。
  useEffect(() => {
    shapeRef.current = shapeForRequest;
  });

  useEffect(() => {
    let cancelled = false;
    // setStateの同期呼び出しを避けてマイクロタスク経由で実行する
    // （useDedicatedWayValuesと同じreact-hooks/set-state-in-effect対策）。
    Promise.resolve().then(async () => {
      if (cancelled) return;
      if (!enabled || !debouncedKey) {
        setResult({ distribution: null, loading: false, error: null });
        return;
      }
      const seq = ++seqRef.current;
      setResult((prev) => ({ ...prev, loading: true, error: null }));
      try {
        const distribution = await fetchAxisValueDistribution(shapeRef.current());
        if (cancelled || seq !== seqRef.current) return;
        setResult({ distribution, loading: false, error: null });
      } catch (error: unknown) {
        if (cancelled || seq !== seqRef.current) return;
        setResult({
          distribution: null,
          loading: false,
          error: error instanceof Error ? error.message : "分布の取得に失敗しました",
        });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [enabled, debouncedKey]);

  return result;
}
