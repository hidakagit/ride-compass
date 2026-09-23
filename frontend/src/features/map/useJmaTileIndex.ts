"use client";

import { useEffect } from "react";

import { setJmaTileIndex } from "@/features/map/layers/jmaTileProtocol";
import { usePolledFetch } from "@/features/map/usePolledFetch";
import type { JmaTileIndexResponse } from "@/features/map/layers/jmaTileIndex";
import { fetchJmaTileIndex } from "@/services/weatherApi";

// backendのプリウォームは10分間隔でインデックスを作り直す。取得が遅れても実害は
// 「間引きが効かず従来どおり取りに行く」だけのため、間隔はそれより短ければよい。
const JMA_TILE_INDEX_REFRESH_INTERVAL_MS = 5 * 60 * 1000;

/**
 * JMA動的タイルの在否インデックスを定期取得し、タイル要求を横取りする側
 * （`jmaTileProtocol.ts`）へ渡す。
 *
 * 取得できていない間・失敗した間はインデックス無し（=間引きなし）で動くため、この
 * フックが動かなくても表示は欠けない。
 */
export function useJmaTileIndex(): void {
  const { data } = usePolledFetch<JmaTileIndexResponse | null>(fetchJmaTileIndex, null, {
    enabled: true,
    intervalMs: JMA_TILE_INDEX_REFRESH_INTERVAL_MS,
    label: "JMAタイル在否インデックス",
    debugLogCategory: "api:jma-tile-index",
  });

  useEffect(() => {
    setJmaTileIndex(data);
  }, [data]);
}
