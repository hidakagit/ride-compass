"use client";

import { useEffect, useState } from "react";

// ネットワーク往復を伴う取得を、入力が落ち着くまで待たせる長さ。取得する側どうしはこの値を共有する。
// 凡例の絞り込みを地図へ反映する遅れ（`features/map/view/useMapView.ts: LEGEND_FILTER_DEBOUNCE_MS`）は
// 往復を伴わないぶん短くてよいので、別の値にする。
export const MAP_FETCH_DEBOUNCE_MS = 500;

/** 値の変化をdelayMsだけ遅らせて返す。**初回の値は遅れない**（初期値としてそのまま返る）
 * ので、最初の1回も遅らせたい側はこのフックを使わず自前で待つ。 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
