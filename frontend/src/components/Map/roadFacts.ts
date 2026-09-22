// 地図上の道をクリックしたときに出す「この道の事実」。路面タイルへ焼き込み済みの
// プロパティだけから作る純関数で、DOM・MapLibre・Reactを知らない。
//
// 値の対訳は生成物（materialCatalog）と点の分類の宣言から引く——
// 手書きで持つと、同じ値を地図のポップアップと軸スタジオで別の呼び方をすることになる。

import materialCatalog from "@/types/generated/material-catalog.json";

export interface RoadSurfacePopupProperties {
  /** 区間インスペクタで全軸の内訳を引き直すための識別子。 */
  osm_way_id?: number | null;
  /** クリックされたフィーチャーそのものの識別子。区間単位のズームでは区間のid、
   * way単位のズームではosm_way_idの文字列。**内訳を地図の色と同じ単位で計算させる**
   * ためにそのまま送る（どちらでもbackendが受け取れる）。 */
  feature_key?: string | null;
  /** OSMの道路名・路線番号（表示専用の生値）。対訳表を持たない第三者編集データ。 */
  name?: string | null;
  ref?: string | null;
  surface_good?: boolean | null;
  smoothness?: string | null;
  tunnel?: boolean | null;
  bridge?: boolean | null;
  /** 一方通行（一次属性、OSM onewayタグ）。未該当（双方向）はプロパティ欠落。 */
  oneway?: boolean | null;
}

interface RoadFactRow {
  label: string;
  value: string;
}

const SMOOTHNESS_LABELS: Record<string, string> =
  (materialCatalog.find((m) => m.material_id === "smoothness")?.value_labels as
    Record<string, string> | null | undefined) ?? {};

/** 道路名。`name`（通称）と`ref`（路線番号）は独立したタグで、片方だけ持つwayが多い
 * （番号だけの国道・名前だけの市道）。両方あれば「名前[番号]」として1つに畳む。 */
export function roadDisplayName(properties: RoadSurfacePopupProperties): string | null {
  const name = properties.name || null;
  const ref = properties.ref || null;
  if (name && ref) return `${name}[${ref}]`;
  return name ?? ref;
}

/** 「項目: 値」の行。**値を持たない項目は行ごと出さない**——「なし」を並べると、
 * 実際に該当する項目が同じ密度の中に埋もれる。 */
export function roadFactRows(properties: RoadSurfacePopupProperties): RoadFactRow[] {
  const rows: RoadFactRow[] = [
    {
      label: "路面",
      value: properties.surface_good == null ? "不明" : properties.surface_good ? "舗装路" : "未舗装路",
    },
  ];
  if (properties.smoothness) {
    rows.push({ label: "路面状態", value: SMOOTHNESS_LABELS[properties.smoothness] ?? properties.smoothness });
  }
  if (properties.tunnel) rows.push({ label: "トンネル", value: "あり" });
  if (properties.bridge) rows.push({ label: "橋・高架", value: "あり" });
  if (properties.oneway) rows.push({ label: "一方通行", value: "あり" });
  return rows;
}
