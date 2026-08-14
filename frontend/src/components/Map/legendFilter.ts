// 色分けモードの凡例エントリと、凡例タップによるカテゴリ表示/非表示フィルタの共通定義。
// 路面レイヤーの絞り込み軸（roadFilterAxes.ts、無方向・地域タイル）とルートレイヤーの
// モード（routeStyleModes.ts、有向・選択ルート基準）の両系統が同じ凡例UI
// （MapOverlayControls）とフィルタ機構を共有するため、ここへ切り出している。

export interface LegendEntry {
  /** カテゴリの安定識別子（表示/非表示状態のキー。ラベル文言の変更に影響されない） */
  key: string;
  color: string;
  label: string;
  /** この地物がカテゴリに属するときtrueになるMapLibre式（凡例フィルタ用の述語） */
  filter: unknown[];
  /** line-widthのpx値（roadFilterAxes.tsのROAD_LINE_WIDTH_AXIS_ID等、色ではなく太さで
   * 地図に反映する軸のみ持つ）。凡例・チェックボックスのプレビューは、これがあれば
   * 色スウォッチの代わりに太さバーを描く（色はその軸では地図上のどこにも出ないため）。 */
  width?: number;
  /** trueなら地図上でこのカテゴリが破線になる（roadFilterAxes.tsのROAD_LINE_DASH_AXIS_ID
   * 参照）。凡例・チェックボックスのプレビュー（WidthSwatch）も合わせて破線で描く。 */
  dashed?: boolean;
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

// 路面レイヤーは「路面の種類」「道路の種類」等、互いに独立した分類軸を複数同時に
// 絞り込みたいことがある（例: 路面の種類=アスファルト かつ 道路の種類=自転車・歩行者道、
// の2条件を同時に満たす区間だけ残す）。各軸のフィルタ式をANDで束ねて1つの式にする。
export function buildCombinedLegendFilterExpression(
  axes: readonly { legend: readonly LegendEntry[]; hiddenKeys: readonly string[] }[]
): unknown[] | null {
  const clauses = axes
    .map(({ legend, hiddenKeys }) => buildLegendFilterExpression(legend, hiddenKeys))
    .filter((expr): expr is unknown[] => expr !== null);
  if (clauses.length === 0) return null;
  if (clauses.length === 1) return clauses[0];
  return ["all", ...clauses];
}
