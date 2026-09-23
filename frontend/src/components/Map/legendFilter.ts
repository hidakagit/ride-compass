// 色分けモードの凡例エントリと、凡例タップによるカテゴリ表示/非表示フィルタの共通定義。
// 道路の線の分類（無方向・地域タイル）とルートレイヤーの
// モード（routeStyleModes.ts、有向・選択ルート基準）の両系統が同じ凡例UI
// （MapOverlayControls）とフィルタ機構を共有するため、ここへ切り出している。

/** 凡例に出る種別名を、説明文へ差し込める並びにする（受け皿カテゴリは除く）。
 *
 * **説明文が凡例と別に種別を数え上げると、種別を足したときに説明文だけが古くなる**
 * ——「車止めのある道を避けたい」利用者は、説明文にその語が無ければレイヤーを開かない。
 * 区切りが読点なのは、ラベル自体が中黒を含むため（「車止め・ゲート」）。
 */
export function legendKindList(legend: readonly LegendEntry[]): string {
  return legend
    .filter((entry) => entry.isFallback !== true)
    .map((entry) => entry.label)
    .join("、");
}

export interface LegendEntry {
  /** カテゴリの安定識別子（表示/非表示状態のキー。ラベル文言の変更に影響されない） */
  key: string;
  color: string;
  label: string;
  /** 大きさで意味を示す行の見本の直径。持つ行は色ではなく大きさを見せる（地図の点と同じ大きさ）。 */
  diameterPx?: number;
  /** この地物がカテゴリに属するときtrueになるMapLibre式（凡例フィルタ用の述語）。
   * 絞り込みを自分で持つレイヤー（scene のグループが宣言するもの）は持たない。 */
  filter?: unknown[];
  /** trueなら「データ欠損・対象外」の受け皿カテゴリ（不明・他／対象外）であり、他の
   * カテゴリのような実際の判定値ではないことを示す。凡例の描画側（▶パネル・
   * MapOverlayControls）が区切り線＋弱調表示にすることで、数値/順序段階と受け皿カテゴリを
   * 視覚的に分離する（凡例が「1・2・3・4・不明」の5項目に見え「1〜5評価」と
   * 誤解されることを避ける）。 */
  isFallback?: boolean;
}

// 凡例で非表示にしたカテゴリを除外するMapLibreフィルタ式を組み立てる。
// 全カテゴリ表示中はnull（フィルタ無し）。未知のキーは無視する（モード切替や定義変更で
// 過去の非表示キーが残っていても安全）。
export function buildLegendFilterExpression(
  legend: readonly LegendEntry[],
  hiddenKeys: readonly string[],
): unknown[] | null {
  const hidden = legend.filter((entry) => hiddenKeys.includes(entry.key));
  if (hidden.length === 0) return null;
  return ["all", ...hidden.flatMap((entry) => (entry.filter === undefined ? [] : [["!", entry.filter]]))];
}

// 路面レイヤーは「路面の種類」「道路の種類」等、互いに独立した分類軸を複数同時に
// 絞り込みたいことがある（例: 路面の種類=アスファルト かつ 道路の種類=自転車・歩行者道、
// の2条件を同時に満たす区間だけ残す）。各軸のフィルタ式をANDで束ねて1つの式にする。
//
// baseFilter: 停止要因POI・補給休憩POIは同じベクタタイルの同じ
// source-layer（stop_poi）を共有しつつ、kind値の集合で2つの独立したMapLibreレイヤーへ
// 分ける必要がある。凡例の非表示操作が無い（hiddenKeys=[]）ときbuildLegendFilterExpression
// はnull（フィルタ無し=全件表示）を返すため、baseFilter無しだとその瞬間だけ相手方の
// kind値も表示されてしまう。baseFilterは「非表示操作の有無に関わらず常にANDする」
// 恒常的な絞り込みで、この用途にのみ使う（他の軸は指定不要＝挙動不変）。
export function buildCombinedLegendFilterExpression(
  axes: readonly { legend: readonly LegendEntry[]; hiddenKeys: readonly string[]; baseFilter?: unknown[] | null }[],
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
  /** 非表示キーの保存先を識別するID（`page.tsx: hiddenLegendKeysByMode`のキー）。
   * **これを持つ軸だけがユーザー操作で絞り込める**——地図上チップの▶パネル
   * （`MapOverlayControls`）のどこから操作しても
   * 同じIDの同じ状態を書き換える。ラスタタイルのように配信元が色を焼き込み済みで
   * カテゴリ単位の絞り込みができない軸（降水ナウキャスト・風・災害の危険度凡例等）は
   * 持たず、その軸は読み取り専用の凡例として描画される。 */
  axisId?: string;
}
