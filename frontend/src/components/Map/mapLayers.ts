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
// kind は「データの性質」による分類（static: 地域に固定で時間によって変わらないデータ
// [タイル配信系]／dynamic: 選択中ルートや時間によって変わるデータ）。静的データと動的データを
// 混同しない、という設計方針（docs/static-road-attributes-plan.md）を表す。
//
// category（改善計画T86）は kind:"static" レイヤーのみが持つ中分類で、サイドバー
// （MapLayersPanel）のグループ見出しに使う。staticが8種に達しflatな一覧のまま並ぶと
// 見つけやすさが悪化するため、kindより一段細かい単位で分ける:
// - roadCondition（道路状態）: 道路情報・指定路線
// - trafficSafety（交通・安全）: 交通ストレス・事故・停止要因
// - bicycleInfra（自転車インフラ）: 自転車インフラ
// - terrain（地形）: 標高図

export type MapLayerId =
  | "elevation"
  | "road"
  | "trafficStress"
  | "safety"
  | "bicycleInfra"
  | "designation"
  | "stopPoi"
  | "accidents"
  | "route";

export type MapLayerKind = "static" | "dynamic";

// staticレイヤーの中分類（改善計画T86）。staticが8種に達しflatな一覧のまま並んでいたため、
// サイドバー（MapLayersPanel）の見出しをkind単位からこの単位へ変更する。dynamic（route）は
// 今のところ1種のみのため中分類を持たない（category未指定）。
export type MapLayerCategory = "roadCondition" | "trafficSafety" | "bicycleInfra" | "terrain";

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
  /** サイドバー（MapLayersPanel）のグループ見出しに使う中分類（改善計画T86）。
   * kind:"static"のレイヤーのみ持つ（dynamicは今のところroute1種のみのため不要）。 */
  category?: MapLayerCategory;
  /** ONにすると何が表示されるかの短い説明（チップのtitleに使う） */
  description: string;
  /** サイドバー設定パネル（MapLayersPanel）のセクション本文に出す説明文（改善計画T84）。
   * descriptionより詳しい判定基準・注意点を書く場所で、以前はMapLayersPanel.tsxの
   * switch文へレイヤーごとハードコードされておりカタログ集約の方針（設計原則8）から
   * 外れていた。未指定のレイヤー（道路情報・ルート等）はパネル側が独自の特殊なJSXを持つ。 */
  panelHint?: string;
  /** panelHintの下に箇条書きで出す判定根拠の内訳（改善計画T89）。「交通ストレスの判定基準が
   * 分かりにくい」という実機フィードバックを受け、1〜2文の要約（panelHint）だけでは
   * 「何がどう加点/減点されるか」まで伝わらなかった箇所を補う。backend/app/domain/traffic.py:
   * traffic_stress_levelの補正ロジックと1:1対応させ、ロジックが変わったらここも追従する。 */
  panelHintDetail?: readonly string[];
}

export const MAP_LAYERS: readonly MapLayerDescriptor[] = [
  {
    id: "elevation",
    // ルート指標の「獲得標高」と紛らわしいため、地図レイヤー側は「標高図」と呼び分ける
    label: "標高図",
    kind: "static",
    category: "terrain",
    description: "国土地理院の色別標高図を重ねる",
    panelHint: "国土地理院の色別標高図を重ねる",
  },
  {
    id: "road",
    // 実体は「路面の種類（色）×道路の種類（太さ）」の複合レイヤーのため、「路面」では
    // 半分しか表せない。ルート色分けモードの「舗装/未舗装」・評価重みの「舗装率」との
    // 用語衝突（同じ「路面」が3つの別物を指す）を避ける改名（T30）。
    label: "道路情報",
    kind: "static",
    category: "roadCondition",
    description: "道路を路面の種類[色]と道路の種類[太さ]で表示",
  },
  {
    id: "trafficStress",
    label: "交通ストレス",
    chipLabel: "ストレス",
    kind: "static",
    category: "trafficSafety",
    description: "道路種別・車線数・制限速度・自転車インフラから推定した交通ストレス(1-5)を色分け表示",
    // 判定基準が不明という実機フィードバック（モバイル実機フィードバック対応T39）を受け、
    // backend/app/domain/traffic.py: traffic_stress_levelの要約を明記する。
    // 改善計画T89: T39の1文要約だけでは「4段階であること」「何が加点/減点されるか」まで
    // 伝わらず「1〜5評価」と誤解される実機フィードバックが再発。panelHintの冒頭で段階数を
    // 明示し、内訳はpanelHintDetail（箇条書き）へ分離した。
    // 改善計画T92: 「指定路線がほぼ全部ストレス最大（赤）で判定が粗い」という指摘を受け、
    // 判定ロジック自体を見直した（幹線道路の一律扱いをやめ、県道級は国道級と分離、
    // 既存タグの中で未活用だった項目を追加）。この一覧もその変更に合わせて更新している。
    panelHint: "道路の種別をもとに5段階[1=快適〜5=ストレス大]で判定した目安です。実際の交通量そのものは加味していません。",
    panelHintDetail: [
      "基準値: 道路の種別[生活道路・県道・国道など]で決まります。国道・幹線道路が最も高く、県道はやや低めです",
      "分離された自転車道が併設: -2 ／ 自転車レーンが併設・自転車と共有の車線表示: -1",
      "制限速度30km/h以下: -1 ／ 60km/h以上: +1",
      "車線数4以上: +1 ／ 対面通行の1車線: -1",
      "指定路線[緊急輸送道路・重要物流道路、下の「指定路線」レイヤーで個別に確認できます]に該当: +1",
      "車両通行不可[自転車専用]の区間は上記の補正に関わらず1に固定",
      "上記の合計が1〜5の範囲を超える場合は範囲内に収まるよう丸めます[信号・一時停止の多さは、別の「停止要因」レイヤーで確認できます]",
      "「不明・他」はpath/footway・高速道路等、判定基準に登録の無い道路種別です",
    ],
  },
  {
    id: "safety",
    label: "安全度",
    kind: "static",
    category: "trafficSafety",
    description: "道路種別・自転車インフラ・街灯・トンネル等から推定した安全度(1-4)を色分け表示",
    // 交通ストレスと同じ材料（highway/cycleway/maxspeed/lanes/指定路線）に加え、
    // 街灯[lit]・トンネル[tunnel]を組み合わせる（改善計画: 安全度レシピ。路肩[shoulder]は
    // 実測0.0%の死に補正だったため改善計画T122で撤去）。
    // 「走りにくさ（交通ストレス）」ではなく「事故りやすさ（客観的リスク）」という別概念
    // であることをtrafficStressのpanelHintDetailと対で明記する。
    panelHint: "道路の種別・自転車インフラ・街灯・トンネル等をもとに4段階[1=安全〜4=危険]で判定した目安です。交通ストレス（走りにくさ）とは別の、事故・怪我のリスクを表す指標です。",
    panelHintDetail: [
      "基準値: 道路の種別[生活道路・県道・国道など]で決まります。国道・幹線道路が最も高く、県道はやや低めです",
      "分離された自転車道が併設: -2 ／ 自転車レーンが併設・自転車と共有の車線表示: -1",
      "制限速度30km/h以下: -1 ／ 60km/h以上: +1",
      "車線数4以上: +1",
      "街灯あり: -1 ／ トンネル: +1",
      "指定路線[緊急輸送道路・重要物流道路、下の「指定路線」レイヤーで個別に確認できます]に該当: +1",
      "車両通行不可[自転車専用]の区間は上記の補正に関わらず1に固定",
      "上記の合計が1〜4の範囲を超える場合は範囲内に収まるよう丸めます",
      "「不明・他」はpath/footway・高速道路等、判定基準に登録の無い道路種別です",
    ],
  },
  {
    id: "bicycleInfra",
    label: "自転車インフラ",
    chipLabel: "インフラ",
    kind: "static",
    category: "bicycleInfra",
    description: "分離自転車道・自転車レーン等、自転車走行環境の分類を色分け表示",
    // 「道路情報（路面）」との違いが分からないという実機フィードバック（同T40）を受け、
    // 両者が独立した軸であることを明記する。
    panelHint:
      "自転車が走る帯の構造[専用道・レーン・車道混在など]を表します。道路情報レイヤーの" +
      "路面の種類[アスファルト/砂利など、舗装の物理的な状態]とは別の軸で、" +
      "組み合わせて確認できます。",
  },
  {
    id: "designation",
    // 外部静的データソース T51（国土数値情報 N10/N12）。指定路線コンフレーション機構が
    // road_edgesへ対応付けた緊急輸送道路・重要物流道路を色分け表示する。
    label: "指定路線[緊急輸送・重要物流]",
    chipLabel: "指定路線",
    kind: "static",
    category: "roadCondition",
    description: "国土数値情報の緊急輸送道路・重要物流道路[KSJ N10/N12]に該当する区間を色分け表示",
    // バッファマッチ（20m、交差率50%以上）でroad_edgesへ対応付けた区間を色分けする。
    // 該当区間はtrafficStress軸にも+1の補正として反映される
    // （road_graph_repository.py: traffic_stress_level参照）。
    // 改善計画T89: 「交通ストレスと指定路線は何が違うのか」という実機フィードバックを受け、
    // 指定路線が「行政指定という事実」の表示であり、交通ストレスはそれを含む複数要因
    // （道路種別・車線数・制限速度・自転車インフラ）を合成した推定指標であるという
    // 役割の違いを明記する（trafficStressのpanelHintDetailと対で参照）。
    panelHint:
      "国土数値情報の緊急輸送道路[N10]・重要物流道路[N12]に該当する区間です。" +
      "大型車の通行が多いと推定される目安として交通ストレスの評価にも加点されますが、" +
      "指定路線かどうか自体を個別に確認できるよう別レイヤーとして表示しています。",
  },
  {
    id: "stopPoi",
    label: "停止要因",
    kind: "static",
    category: "trafficSafety",
    description: "信号・横断歩道・一時停止・踏切の位置を種別ごとに色分け表示",
    panelHint:
      "信号・横断歩道・一時停止・踏切の位置です。評価の「停止密度」軸が近傍のこれらを" +
      "数えて算出しているものを、種別ごとの色分けで直接確認できます。",
  },
  {
    id: "accidents",
    label: "事故[警察庁統計]",
    chipLabel: "事故",
    kind: "static",
    category: "trafficSafety",
    description: "警察庁交通事故統計オープンデータ[関東7都県、2022〜2024年]の発生地点を表示",
    panelHint:
      "警察庁が公開する交通事故統計オープンデータ[本票、関東7都県・2022〜2024年]の" +
      "発生地点です。死亡事故は円を大きく表示します。2019〜2021年は本票のCSV形式が" +
      "異なるため未対応です。",
  },
  {
    id: "route",
    label: "ルート",
    kind: "dynamic",
    description: "選択中ルート沿いの情報[風・勾配・路面・総合難易度]を色分け表示",
  },
];

export type MapLayerVisibility = Record<MapLayerId, boolean>;

/** サイドバーの各レイヤー設定セクション（<details>）のDOM id */
export function layerSectionDomId(id: MapLayerId): string {
  return `map-layer-section-${id}`;
}

// レイヤーごとのデータ取得状態（改善計画T87）。「表示OFF」「ズーム範囲外」（road専用の
// zoomWarning）はどちらも既存の案内があるが、タイル取得失敗（T59の背景にあった502障害等）と
// そのレイヤーの対象データが0件（T54で判明したosm_raw_pois未取込のような欠損）を区別する
// 表示が無く、どちらも単に「何も描画されない」状態になっていた。表示ONかつ正常時
// （既知件数のデータが描画できている状態）はundefined（=キー自体を持たない）とし、
// 特別な表示を出さない。MapView.tsxのsourcedata/sourcedataloading/errorイベントから算出する。
export type LayerDataStatus = "loading" | "empty" | "error";
export type LayerDataStatusByLayer = Partial<Record<MapLayerId, LayerDataStatus>>;

export const LAYER_DATA_STATUS_LABELS: Record<LayerDataStatus, string> = {
  loading: "読み込み中です",
  empty: "この範囲に表示できるデータがありません",
  error: "データの取得に失敗しました。しばらくしてから再読み込みしてください",
};

// road/trafficStress/safety/bicycleInfra/designationは同じroad_surfaceベクタタイル
// （MapView.tsx: ROAD_TILE_SOURCE_ID/ROAD_TILE_SOURCE_LAYER、LAYER_DATA_SOURCES参照）を
// 共有しているため、そのタイルのminzoom未満（regionZoomTooWide）ではタイル自体が要求されず、
// 5レイヤーとも同時にloading/emptyと判定される。「表示範囲が広すぎます」という案内が既にある
// ズーム範囲外の間は、レイヤーのデータ状態表示（T87）を二重に出さないための判定に使う
// （MapView.tsx側のregionZoomTooWide算出・MapLayersPanel.tsx側の抑制の両方が参照する単一の
// 定義。片方だけ更新して食い違う、という改善計画の設計原則8違反を避けるため）。
export const ROAD_SURFACE_SHARED_LAYER_IDS: readonly MapLayerId[] = [
  "road",
  "trafficStress",
  "safety",
  "bicycleInfra",
  "designation",
];
