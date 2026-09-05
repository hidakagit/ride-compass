"use client";

import { useEffect, useState } from "react";

// 値の変化をdelayMsだけ遅らせて返すフック。
// 「地図の見え方」系の設定は即時反映が原則だが、道路情報レイヤーの絞り込みチェックは
// 連続で複数タップされることが多く、1タップごとにMapLibreのフィルタ再適用（タイル全体の
// 再描画）を走らせると操作しづらい。地図への反映だけをこのフックで数百ms遅らせ、連続
// タップを1回の再描画へまとめる（UI上のチェック状態は即時に変わる。遅れるのは地図側だけ）。
// ネットワーク往復を伴う地図系フェッチ（風グリッド詳細[useWeatherGrid.ts]・way_id→
// 動的値配信[useDynamicWayValues.ts、ビューポート・走行方位デバウンス両方]）はこの定数を
// 共有する（設計原則「定数の片側import」）。地図フィルタの再適用
// （LEGEND_FILTER_DEBOUNCE_MS、page.tsx、ネットワーク往復を伴わずより短い400msでよい）
// とは別物として扱う。
export const MAP_FETCH_DEBOUNCE_MS = 500;

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
