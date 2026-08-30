"use client";

import { useEffect, useState } from "react";

// 値の変化をdelayMsだけ遅らせて返すフック。
// 「地図の見え方」系の設定は即時反映が原則（UI一貫性再編T31）だが、道路情報レイヤーの
// 絞り込みチェックは連続で複数タップされることが多く、1タップごとにMapLibreのフィルタ
// 再適用（タイル全体の再描画）を走らせると操作しづらい——という過去フィードバックが
// 旧「下書き→適用」方式の由来だった。適用ボタンを無くす代わりに、地図への反映だけを
// このフックで数百ms遅らせ、連続タップを1回の再描画へまとめる（UI上のチェック状態は
// 即時に変わる。遅れるのは地図側だけ）。
// 改善計画T470: ネットワーク往復を伴う地図系フェッチ（風グリッド詳細[useWeatherGrid.ts]・
// way_id→動的値配信[useDynamicWayValues.ts、ビューポート・走行方位デバウンス両方]）が、
// 「同じ値を使う」とコメントで示し合わせるだけの独立定義（500）を3ファイルへ持っていた
// （設計原則「定数の片側import」違反）。地図フィルタの再適用（LEGEND_FILTER_DEBOUNCE_MS、
// page.tsx、ネットワーク往復を伴わずより短い400msでよい）とは別物として、ここへ集約する。
export const MAP_FETCH_DEBOUNCE_MS = 500;

export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
