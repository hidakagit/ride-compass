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
  /** trueなら「データ欠損・対象外」の受け皿カテゴリ（不明・他／対象外）であり、他の
   * カテゴリのような実際の判定値ではないことを示す。凡例の描画側（MapLayersPanel・
   * MapOverlayControls）が区切り線＋弱調表示にする（改善計画T89）。車ストレスの凡例が
   * 「1・2・3・4・不明」の5項目に見え「1〜5評価」と誤解されるという実機フィードバックを
   * 受け、数値/順序段階と受け皿カテゴリを視覚的に分離する。 */
  isFallback?: boolean;
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
//
// baseFilter（改善計画T101）: 停止要因POI・補給休憩POIは同じベクタタイルの同じ
// source-layer（stop_poi）を共有しつつ、kind値の集合で2つの独立したMapLibreレイヤーへ
// 分ける必要がある。凡例の非表示操作が無い（hiddenKeys=[]）ときbuildLegendFilterExpression
// はnull（フィルタ無し=全件表示）を返すため、baseFilter無しだとその瞬間だけ相手方の
// kind値も表示されてしまう。baseFilterは「非表示操作の有無に関わらず常にANDする」
// 恒常的な絞り込みで、この用途にのみ使う（他の軸は指定不要＝挙動不変）。
export function buildCombinedLegendFilterExpression(
  axes: readonly { legend: readonly LegendEntry[]; hiddenKeys: readonly string[]; baseFilter?: unknown[] | null }[]
): unknown[] | null {
  const clauses = axes
    .map(({ legend, hiddenKeys, baseFilter }) => {
      const hideFilter = buildLegendFilterExpression(legend, hiddenKeys);
      if (baseFilter && hideFilter) return ["all", baseFilter, hideFilter];
      return baseFilter ?? hideFilter;
    })
    .filter((expr): expr is unknown[] => expr !== null && expr !== undefined);
  if (clauses.length === 0) return null;
  if (clauses.length === 1) return clauses[0];
  return ["all", ...clauses];
}

export interface LegendFilterSummaryAxis {
  /** 軸の名前（例:「路面の種類」）。カテゴリ名だけでは短く言えない場合のフォールバック文言に使う */
  label: string;
  legend: readonly LegendEntry[];
  hiddenKeys: readonly string[];
}

// 軸ごとに「表示中カテゴリを列挙」と「除外カテゴリを列挙」の短い方を選び、どちらも
// 3件以上になる場合は軸名によるフォールバック（「◯◯を絞り込み中」）へ落とす。
// 詳細な内訳はサイドバー（MapLayersPanel）の凡例・絞り込み編集で確認できるため、
// ここでは「何かに絞られている」ことが一目で分かる簡潔さを優先する。
// レイヤー固有の語彙を持たない（LegendEntryだけに依存する）ので、将来の凡例付き
// レイヤー（車ストレス等）でもそのまま使える。
function summarizeLegendFilterParts(axes: readonly LegendFilterSummaryAxis[]): string[] {
  const parts: string[] = [];
  for (const axis of axes) {
    const hidden = axis.legend.filter((entry) => axis.hiddenKeys.includes(entry.key));
    if (hidden.length === 0) continue;
    const visible = axis.legend.filter((entry) => !axis.hiddenKeys.includes(entry.key));
    if (visible.length === 0) {
      // 全カテゴリ非表示は「何も出ない」状態なので、そのことが分かる文言にする
      parts.push(`${axis.label}をすべて非表示`);
    } else if (visible.length <= 2) {
      parts.push(`${visible.map((entry) => entry.label).join("・")}のみ`);
    } else if (hidden.length <= 2) {
      parts.push(`${hidden.map((entry) => entry.label).join("・")}以外`);
    } else {
      parts.push(`${axis.label}を絞り込み中`);
    }
  }
  return parts;
}

// 適用中の絞り込みを地図上に1行で示すための要約文を作る（絞り込み無しならnull）。
export function summarizeLegendFilters(axes: readonly LegendFilterSummaryAxis[]): string | null {
  const parts = summarizeLegendFilterParts(axes);
  return parts.length > 0 ? parts.join("／") : null;
}
