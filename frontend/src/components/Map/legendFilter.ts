// 色分けモードの凡例エントリと、凡例タップによるカテゴリ表示/非表示フィルタの共通定義。
// 路面レイヤーのモード（roadStyleModes.ts、無方向・地域タイル）とルートレイヤーのモード
// （routeStyleModes.ts、有向・選択ルート基準）の両系統が同じ凡例UI（MapOverlayControls）と
// フィルタ機構を共有するため、ここへ切り出している。

export interface LegendEntry {
  /** カテゴリの安定識別子（表示/非表示状態のキー。ラベル文言の変更に影響されない） */
  key: string;
  color: string;
  label: string;
  /** この地物がカテゴリに属するときtrueになるMapLibre式（凡例フィルタ用の述語） */
  filter: unknown[];
}

// 凡例で非表示にしたカテゴリを除外するMapLibreフィルタ式を組み立てる。
// 全カテゴリ表示中はnull（フィルタ無し）。未知のキーは無視する（モード切替や定義変更で
// 過去の非表示キーが残っていても安全）。
export function buildLegendFilterExpression(
  legend: readonly LegendEntry[],
  hiddenKeys: readonly string[]
): unknown[] | null {
  const hidden = legend.filter((entry) => hiddenKeys.includes(entry.key));
  if (hidden.length === 0) return null;
  return ["all", ...hidden.map((entry) => ["!", entry.filter])];
}
