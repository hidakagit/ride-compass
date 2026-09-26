"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { setJmaTileIndex } from "@/features/map/layers/jmaTileProtocol";
import { getQueryClient } from "@/lib/queryClient";
import { fetchJmaTileIndex } from "@/services/weatherApi";
import refreshIntervals from "@/types/generated/refresh-intervals.json";

// backendがインデックスを作り直す間隔で取り直す。取得が遅れても実害は「間引きが効かず従来どおり取りに行く」だけ。
const JMA_TILE_INDEX_REFRESH_INTERVAL_MS = refreshIntervals.jma_tile_index_seconds * 1000;

/**
 * JMA動的タイルの在否インデックスを定期取得し、タイル要求を横取りする側
 * （`jmaTileProtocol.ts`）へ渡す。
 *
 * 取得できていない間・失敗した間はインデックス無し（=間引きなし）で動くため、この
 * フックが動かなくても表示は欠けない。
 */
export function useJmaTileIndex(): void {
  const { data } = useQuery(
    {
      queryKey: ["jma-tile-index"],
      queryFn: fetchJmaTileIndex,
      refetchInterval: JMA_TILE_INDEX_REFRESH_INTERVAL_MS,
    },
    getQueryClient(),
  );

  useEffect(() => {
    setJmaTileIndex(data ?? null);
  }, [data]);
}
