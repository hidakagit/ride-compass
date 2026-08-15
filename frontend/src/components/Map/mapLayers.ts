// 地図レイヤーのカタログ（単一ソース）。
//
// 地図上のチップ行（MapOverlayControls）とサイドバーの設定パネル（MapLayersPanel）は
// どちらもこの配列を列挙して描画する。レイヤーを追加するときは、
//   1. ここへ MapLayerDescriptor を1つ足す
//   2. page.tsx で表示状態(layerVisibility)の初期値とサマリ計算を1行ずつ足す
//   3. MapLayersPanel にそのレイヤーの設定セクションの中身を足す（凡例・絞り込み等）
// だけでチップ・条件サマリ・サイドバーのセクション枠が揃う。地図描画そのもの
// （MapView.tsxのソース/レイヤー登録）は従来どおり別途必要。
//
// kind は「データの性質」による分類で、サイドバーのグループ見出しに使う:
// - static: 地域に固定で時間によって変わらないデータ（タイル配信系。標高図・路面、
//   将来の交通ストレス・自転車インフラ・信号など）
// - dynamic: 選択中ルートや時間によって変わるデータ（ルート沿いの風・勾配、
//   将来の天候オーバーレイなど）
// 静的データと動的データを混同しない、という設計方針（docs/static-road-attributes-plan.md）
// をUI上のグルーピングにもそのまま反映する。

export type MapLayerId = "elevation" | "road" | "route";

export type MapLayerKind = "static" | "dynamic";

export interface MapLayerDescriptor {
  id: MapLayerId;
  /** チップ・サイドバーのセクション見出しに共通で使う表示名 */
  label: string;
  kind: MapLayerKind;
  /** ONにすると何が表示されるかの短い説明（チップのtitle・サイドバーの補足に使う） */
  description: string;
}

export const MAP_LAYERS: readonly MapLayerDescriptor[] = [
  {
    id: "elevation",
    // ルート指標の「獲得標高」と紛らわしいため、地図レイヤー側は「標高図」と呼び分ける
    label: "標高図",
    kind: "static",
    description: "国土地理院の色別標高図を重ねる",
  },
  {
    id: "road",
    label: "路面",
    kind: "static",
    description: "道路を路面材質・種類で色分け表示",
  },
  {
    id: "route",
    label: "ルート",
    kind: "dynamic",
    description: "選択中ルート沿いの情報（風・勾配）を色分け表示",
  },
];

export type MapLayerVisibility = Record<MapLayerId, boolean>;

/** サイドバーの各レイヤー設定セクションのDOM id（地図上の条件サマリからのスクロール先） */
export function layerSectionDomId(id: MapLayerId): string {
  return `map-layer-section-${id}`;
}
