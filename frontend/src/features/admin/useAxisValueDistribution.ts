"use client";

// 編集中のshapeに対する生値分布の取得。折れ点だけを動かしている間は再取得しない
// （折れ点は分布の形を変えないため。各階級の点数は軽い問い合わせの`useScoresPreview`が取る）。

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { ValueDistribution } from "@/features/admin/AxisStudio/scoreDistribution";
import { fetchAxisValueDistribution } from "@/features/admin/adminApi";
import { MAP_FETCH_DEBOUNCE_MS, useDebouncedValue } from "@/hooks/useDebouncedValue";
import { getQueryClient } from "@/lib/queryClient";
import type { AxisShape } from "@/types/route";

interface AxisValueDistributionResult {
  distribution: ValueDistribution | null;
  loading: boolean;
  error: string | null;
}

const NO_DISTRIBUTION: AxisValueDistributionResult = { distribution: null, loading: false, error: null };

/**
 * `termsKey`は「分布の形を決める部分」（材料id・重み・required・preprocess）を文字列化した
 * もの。折れ点を含めないことで、折れ点のドラッグ中に通信が走らない。取り直している間は前の分布を
 * 出したまま`loading`を立てる。
 */
export function useAxisValueDistribution(
  enabled: boolean,
  termsKey: string,
  shapeForRequest: () => AxisShape,
): AxisValueDistributionResult {
  const debouncedKey = useDebouncedValue(termsKey, MAP_FETCH_DEBOUNCE_MS);
  const shapeRef = useRef(shapeForRequest);

  // refの書き込みはレンダー中ではなくeffectで行う（レンダー中のref操作は
  // Reactの並行レンダリングで一貫性を失う）。
  useEffect(() => {
    shapeRef.current = shapeForRequest;
  });

  const active = enabled && debouncedKey !== "";
  const { data, error, isFetching } = useQuery(
    {
      queryKey: ["axis-value-distribution", debouncedKey],
      queryFn: () => fetchAxisValueDistribution(shapeRef.current()),
      enabled: active,
      placeholderData: keepPreviousData,
    },
    getQueryClient(),
  );

  if (!active) return NO_DISTRIBUTION;
  if (error) {
    return {
      distribution: null,
      loading: isFetching,
      error: error instanceof Error ? error.message : "分布の取得に失敗しました",
    };
  }
  return { distribution: data ?? null, loading: isFetching, error: null };
}
