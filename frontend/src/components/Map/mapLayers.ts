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

export type MapLayerId =
  | "elevation"
  | "road"
  | "trafficStress"
  | "bicycleInfra"
  | "designation"
  | "stopPoi"
  | "intersections"
  | "accidents"
  | "route";

export type MapLayerKind = "static" | "dynamic";

export interface MapLayerDescriptor {
  id: MapLayerId;
  /** サイドバーのセクション見出し・条件サマリ・チップのtitleで使う正式名称 */
  label: string;
  /** 地図上のアイコンチップ下に出す短縮表記。未指定ならlabelをそのまま使う。
   * チップ幅は文字数に連動するため（MapOverlayControls.module.cssの.iconChip参照）、
   * 長いlabelはここで短くしてチップ幅を他レイヤーと揃える。正式名称は引き続きlabel
   * （サイドバー見出し・条件サマリ・チップのtitle）で示すため、意味の省略は許容する。 */
  chipLabel?: string;
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
    // 実体は「路面の種類（色）×道路の種類（太さ）」の複合レイヤーのため、「路面」では
    // 半分しか表せない。ルート色分けモードの「舗装/未舗装」・評価重みの「舗装率」との
    // 用語衝突（同じ「路面」が3つの別物を指す）を避ける改名（T30）。
    label: "道路情報",
    kind: "static",
    description: "道路を路面の種類（色）と道路の種類（太さ）で表示",
  },
  {
    id: "trafficStress",
    label: "交通ストレス",
    chipLabel: "ストレス",
    kind: "static",
    description: "道路種別・車線数・制限速度・自転車インフラから推定した交通ストレス(1-4)を色分け表示",
  },
  {
    id: "bicycleInfra",
    label: "自転車インフラ",
    chipLabel: "インフラ",
    kind: "static",
    description: "分離自転車道・自転車レーン等、自転車走行環境の分類を色分け表示",
  },
  {
    id: "designation",
    // 外部静的データソース T51（国土数値情報 N10/N12）。指定路線コンフレーション機構が
    // road_edgesへ対応付けた緊急輸送道路・重要物流道路を色分け表示する。
    label: "指定路線（緊急輸送・重要物流）",
    chipLabel: "指定路線",
    kind: "static",
    description: "国土数値情報の緊急輸送道路・重要物流道路（KSJ N10/N12）に該当する区間を色分け表示",
  },
  {
    id: "stopPoi",
    label: "停止要因",
    kind: "static",
    description: "信号・横断歩道・一時停止・踏切の位置を種別ごとに色分け表示",
  },
  {
    id: "intersections",
    label: "交差点密度",
    // chipLabel未指定のままだと5文字の"交差点密度"がそのままチップ幅（width: max-content）に
    // 反映され、他レイヤーのチップ（trafficStress/bicycleInfra/accidentsは4文字以下の
    // chipLabelで揃えている）より横に長くなり列が不揃いに見えていた（実機フィードバック）。
    chipLabel: "交差点",
    kind: "static",
    description: "接続路3本以上の交差点を表示（接続数が多いほど大きい円）",
  },
  {
    id: "accidents",
    label: "事故（警察庁統計）",
    chipLabel: "事故",
    kind: "static",
    description: "警察庁交通事故統計オープンデータ（関東7都県、2022〜2024年）の発生地点を表示",
  },
  {
    id: "route",
    label: "ルート",
    kind: "dynamic",
    description: "選択中ルート沿いの情報（風・勾配・路面・総合難易度）を色分け表示",
  },
];

export type MapLayerVisibility = Record<MapLayerId, boolean>;

/** サイドバーの各レイヤー設定セクションのDOM id（地図上の条件サマリからのスクロール先） */
export function layerSectionDomId(id: MapLayerId): string {
  return `map-layer-section-${id}`;
}
