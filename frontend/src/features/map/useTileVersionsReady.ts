"use client";

import { useSyncExternalStore } from "react";
import { hasTileVersions, subscribeTileVersions } from "@/services/regionApi";

/** タイル世代が揃っているか。揃うまで地図のタイルソースは作られない。
 *
 * **軸カタログの取得完了で代用しない**。カタログが200で返っても世代を含まない版の
 * backendが応答した窓では、揃ったことにしてURLを組み立てた側が例外になる。
 * 逆にカタログの取得が失敗した間はここもfalseのままで、再試行が成功した時点で
 * 購読側へ伝わる（`setTileVersions`が通知する）。
 *
 * サーバー側スナップショットはfalse——SSR時点では取得していない。 */
export function useTileVersionsReady(): boolean {
  return useSyncExternalStore(subscribeTileVersions, hasTileVersions, () => false);
}
