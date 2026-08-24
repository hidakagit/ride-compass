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
// - roadCondition（道路状態）: 道路の種類・路面の種類（T165で「道路情報」から分割）・指定路線
// - trafficSafety（交通・安全）: 車ストレス・事故・停止要因
// - bicycleInfra（自転車インフラ）: 自転車インフラ
// - terrain（地形）: 標高図
// - amenity（補給・施設、改善計画T101）: 補給・休憩ポイント。安全・リスクの指標ではなく
//   trafficSafetyへ含めるのは意味的に不適切なため独立カテゴリにした

import {
  RAMP_AXES,
  axisMapLayerId,
  type AxisMapLayerId,
} from "./axisLayers";

export type MapLayerId =
  | "elevation"
  | "roadType"
  | "roadSurface"
  | "carStress"
  | "bicycleInfra"
  | "designation"
  | "tunnel"
  | "stopPoi"
  | "supplyPoi"
  | "accidents"
  | "route"
  // 気象庁 降水ナウキャスト（改善計画T171）。route以外で初のkind="dynamic"レイヤーだが、
  // route（選択中候補にひもづく）とは異なり地域全体への重ね描き（elevation等と同じ
  // 「選択候補に関係なく常設」の性質）のため、kind自体はstaticのまま、dataNature="dynamic"
  // （下記）だけで区別する。詳細はkind/MapLayerDataNatureのコメント参照。
  | "precipitationNowcast"
  // 風の矢印（改善計画T178、フォローアップで自前実装へ移行）。Open-Meteo REST API経由の
  // 格子点サンプリング（バックエンド新設、GeoJSON source + symbolレイヤー）。
  // precipitationNowcastと同じ理由でkind="static"・dataNature="dynamic"。
  | "windVector"
  // 雷ナウキャスト・竜巻発生確度ナウキャスト（改善計画T204）。precipitationNowcastと同じ
  // 理由でkind="static"・dataNature="dynamic"。「回避一択」の危険（雷・竜巻）のため
  // 評価軸には組み込まず警告表示のみ（T170〜T178節の設計判断を踏襲）。
  | "thunderNowcast"
  | "tornadoNowcast"
  // 二次軸の汎用rampレイヤー（改善計画T145b）。backendレジストリ生成物
  // （axis-catalog.json）のkind="ramp"軸から自動生成されるためIDは動的
  // （axisLayers.ts: axisMapLayerId参照）。
  | AxisMapLayerId;

// kindは「選択中ルートにひもづくデータか、地域に固定で選択候補に関係なく重ね描きする
// データか」を表す（dynamic=route、選択中候補が変わるたびに描き直す。static=それ以外、
// 一度追加したらvisibilityの切替だけで表示・非表示する）。「値が時間で変わるかどうか」は
// 別軸（dataNature、下記）で表す。降水ナウキャスト（precipitationNowcast）は値こそ
// 時々刻々変わるが、route選択とは無関係にstaticレイヤーと同じ「常設・visibility切替のみ」の
// 描画方式のためkind="static"のまま、dataNature="dynamic"で区別する。
export type MapLayerKind = "static" | "dynamic";

// staticレイヤーの中分類（改善計画T86）。staticが8種に達しflatな一覧のまま並んでいたため、
// サイドバー（MapLayersPanel）の見出しをkind単位からこの単位へ変更する。dynamic（route）は
// 今のところ1種のみのため中分類を持たない（category未指定）。
export type MapLayerCategory = "roadCondition" | "trafficSafety" | "bicycleInfra" | "terrain" | "amenity" | "weather";

// カテゴリの表示順・見出し文言の単一ソース（改善計画T86→T128）。以前はMapLayersPanel.tsx
// だけが持っていたが、T128（地図上チップのカテゴリ束ね）でMapOverlayControls.tsxも
// 同じ対応表を要するようになったため、両者が参照するここへ集約する
// （設計原則8: UI語彙のカタログ集約、片側importで揃える）。
export const MAP_LAYER_CATEGORY_ORDER: readonly MapLayerCategory[] = [
  "roadCondition",
  "trafficSafety",
  "bicycleInfra",
  "terrain",
  "amenity",
  "weather",
];
export const MAP_LAYER_CATEGORY_LABELS: Record<MapLayerCategory, string> = {
  roadCondition: "道路状態",
  trafficSafety: "交通・安全",
  bicycleInfra: "自転車インフラ",
  terrain: "地形",
  amenity: "補給・施設",
  // 改善計画T171/T178: 降水ナウキャスト・風（矢印）等、動的グループのメンバー用。
  weather: "気象",
};

/** 生データ（OSM/警察庁の生タグ・生座標をそのまま分類表示）か、複数要因から計算した
 * 推定指標（合成）か、時刻で内容が変わる動的データか。地図上チップの最上位グルーピングに
 * 使う（改善計画T166、次数反転。T171で3値目「dynamic」を追加）。
 * T128時点ではtrafficSafetyカテゴリを展開したときの小見出しとしてのみ使っていたが、
 * T166でチップ最上位の分類そのものへ昇格した（categoryは観測グループ内の小見出しへ
 * 役割を移した、下記MapLayerDescriptor.categoryのコメント参照）。 */
export type MapLayerDataNature = "raw" | "composite" | "dynamic";
export const MAP_LAYER_DATA_NATURE_LABELS: Record<MapLayerDataNature, string> = {
  composite: "推定指標（合成）",
  raw: "観測データ",
  // 改善計画T171: 降水ナウキャスト等、時刻を指定すると内容が変わるレイヤーの最上位グループ。
  dynamic: "動的データ",
};
/** 観測/推定/動的の表示順。地図の見え方パネル（サイドバー、MapLayersPanel）専用の順序。
 * 以前は地図チップ側（MapOverlayControls.tsx: buildChipGroups、「推定→観測」に確定済み
 * [T166]）と同じ配列をここから参照する単一ソースだったが、「パネル内は推定より観測を
 * 上にしてほしい」という実機フィードバックを受け、パネルだけ「観測→推定」へ反転した
 * （チップ側のbuildChipGroupsは変更していないため両者は独立して食い違う。意図的な
 * 差異であり、統一し直す指摘があれば再度揃える）。動的グループはT171で新設したばかりで
 * 既存2グループより関心の的が絞られるため末尾に置く。 */
export const MAP_LAYER_DATA_NATURE_ORDER: readonly MapLayerDataNature[] = ["raw", "composite", "dynamic"];
/** 地図チップ最上位グループの略名（4文字以下、改善計画T166確定命名表）。正式名は上記
 * MAP_LAYER_DATA_NATURE_LABELS。地図チップ=略名／サイドバー・研究タブ=正式名の使い分けは
 * 個別レイヤーのlabel/chipLabelと同じ規則（MapLayerDescriptorのコメント参照）。 */
export const MAP_LAYER_DATA_NATURE_CHIP_LABELS: Record<MapLayerDataNature, string> = {
  composite: "推定",
  raw: "観測",
  dynamic: "動的",
};

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
  /** サイドバー（MapLayersPanel）のグループ見出しに使う中分類（改善計画T86）。地図上チップ
   * では、T128時点ではこれ自体が最上位のグルーピング単位だったが、T166で最上位は
   * dataNature（観測/推定）へ役割を譲り、categoryは観測グループを展開したときの
   * 小見出し（トピック別）としてのみ使う（推定グループの中はcategoryを使わず6軸を
   * フラットに列挙する、MapOverlayControls.tsx参照）。kind:"static"のレイヤーのみ持つ
   * （dynamicは今のところroute1種のみのため不要）。 */
  category?: MapLayerCategory;
  /** 生データか推定指標（合成）か（MAP_LAYER_DATA_NATURE_LABELS参照）。地図上チップの
   * 最上位グルーピング単位（改善計画T166）。省略時は"raw"扱い（大半のレイヤーは
   * 生タグ・生座標の分類表示のため、明示するのは合成側のみで足りる）。 */
  dataNature?: MapLayerDataNature;
  /** ONにすると何が表示されるかの短い説明（チップのtitleに使う） */
  description: string;
  /** サイドバー設定パネル（MapLayersPanel）のセクション本文に出す説明文（改善計画T84）。
   * descriptionより詳しい判定基準・注意点を書く場所で、以前はMapLayersPanel.tsxの
   * switch文へレイヤーごとハードコードされておりカタログ集約の方針（設計原則8）から
   * 外れていた。未指定のレイヤー（道路情報・ルート等）はパネル側が独自の特殊なJSXを持つ。 */
  panelHint?: string;
  /** panelHintの下に箇条書きで出す判定根拠の内訳（改善計画T89）。「車ストレスの判定基準が
   * 分かりにくい」という実機フィードバックを受け、1〜2文の要約（panelHint）だけでは
   * 「何がどう加点/減点されるか」まで伝わらなかった箇所を補う。backend/app/domain/traffic.py:
   * car_stress_levelの補正ロジックと1:1対応させ、ロジックが変わったらここも追従する。 */
  panelHintDetail?: readonly string[];
}

// ramp軸（RAMP_AXES、現状stop_density/accident）のpanelHint（改善計画: 地図の見え方
// パネルの推定指標説明を簡略化）。axis.note（backendレジストリの実装メモ、開発者向け）を
// そのまま出すと読みにくいという実機フィードバックを受け、エンドユーザー向けの言い換えを
// ここに持つ（下記MAP_LAYERSのRAMP_AXES.map参照）。未登録の軸（将来ramp軸が増えた場合）は
// axis.noteへフォールバックする。
const RAMP_AXIS_PANEL_HINTS: Record<string, string> = {
  stop_density: "信号・横断歩道・一時停止・踏切等の停止要因が、沿線でどれだけ密集しているかの目安です。実際の位置は「停止要因」レイヤーで確認できます。",
  accident: "警察庁の交通事故統計をもとに、自転車関連事故が沿線でどれだけ近くに集中しているかの目安です[死亡事故は重めに算入]。実際の発生地点は「事故」レイヤーで確認できます。",
};

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
    // 改善計画T165（地図レイヤー階層の次数反転）: 旧「道路情報」（road、1レイヤーに
    // 路面の種類・道路の種類の2属性が同居する複合レイヤー、T30で用語衝突を避けるため
    // 妥協的に付けた名前）を、一次属性1つ=1レイヤーの原則に合わせ論理2レイヤーへ分割した。
    // MapView.tsx側の物理描画は引き続き1本のMapLibre線レイヤー（region-road-surface-
    // tiles-line）に合成する（同じ道路ジオメトリへ線レイヤーを2枚重ねると上が下を
    // 塗り潰し「色×太さ」の多重表現が壊れるため）。ON/OFF・凡例・絞り込み・データ状態は
    // 他のレイヤーと同じ汎用機構（roadType/roadSurfaceそれぞれ独立したMapLayerId）に乗る。
    id: "roadType",
    label: "道路の種類",
    chipLabel: "道路種別",
    kind: "static",
    category: "roadCondition",
    description: "道路種別を線の太さで表示[幹線道路ほど太く・自転車専用道路ほど細く]",
    // 実機フィードバック「道路種別が支配的な場合、色がすべて灰色で違和感がある」への対応
    // （roadFilterAxes.ts: HIGHWAY_GROUPS、COLOR_HIGHWAY_*参照）。「路面の種類」がONの間は
    // そちらの色分けが優先されるため、この濃淡は「路面の種類」がOFFのときだけ見える。
    panelHint:
      "太さに加え、「路面の種類」レイヤーがOFFの間は種別ごとの濃淡[幹線道路ほど濃く・" +
      "自転車専用道路ほど薄く]でも表示します。「路面の種類」がONのときは、色はそちらの" +
      "配色を優先します。",
  },
  {
    id: "roadSurface",
    label: "路面の種類",
    chipLabel: "路面",
    kind: "static",
    category: "roadCondition",
    description: "路面の材質を色で表示[アスファルト・砂利・土など]",
  },
  {
    id: "carStress",
    label: "車の圧迫感",
    chipLabel: "圧迫感",
    kind: "static",
    category: "trafficSafety",
    dataNature: "composite",
    description: "道路種別・車線数・制限速度・自転車インフラから推定した車の圧迫感(1-5)を色分け表示",
    // 判定基準が不明という実機フィードバック（モバイル実機フィードバック対応T39）を受け、
    // backend/app/domain/traffic.py: car_stress_levelの要約を明記する。
    // 改善計画T89: T39の1文要約だけでは「4段階であること」「何が加点/減点されるか」まで
    // 伝わらず「1〜5評価」と誤解される実機フィードバックが再発。panelHintの冒頭で段階数を
    // 明示し、内訳はpanelHintDetail（箇条書き）へ分離した。
    // 改善計画T92: 「指定路線がほぼ全部ストレス最大（赤）で判定が粗い」という指摘を受け、
    // 判定ロジック自体を見直した（幹線道路の一律扱いをやめ、県道級は国道級と分離、
    // 既存タグの中で未活用だった項目を追加）。この一覧もその変更に合わせて更新している。
    panelHint: "道路の種別をもとに5段階[1=快適〜5=圧迫大]で判定した目安です。実際の交通量そのものは加味していません。",
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
    id: "bicycleInfra",
    label: "自転車インフラ",
    chipLabel: "インフラ",
    kind: "static",
    category: "bicycleInfra",
    description: "分離自転車道・自転車レーン等、自転車走行環境の分類を色分け表示",
    // 「道路情報（路面）」との違いが分からないという実機フィードバック（同T40）を受け、
    // 両者が独立した軸であることを明記する（T165で「道路情報」は「路面の種類」レイヤーへ
    // 論理分割されたため、参照先の名称もそちらへ更新した）。
    panelHint:
      "自転車が走る帯の構造[専用道・レーン・車道混在など]を表します。「路面の種類」レイヤーの" +
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
    // 該当区間はcarStress軸にも+1の補正として反映される
    // （road_graph_repository.py: car_stress_level参照）。
    // 改善計画T89: 「車ストレスと指定路線は何が違うのか」という実機フィードバックを受け、
    // 指定路線が「行政指定という事実」の表示であり、車ストレスはそれを含む複数要因
    // （道路種別・車線数・制限速度・自転車インフラ）を合成した推定指標であるという
    // 役割の違いを明記する（carStressのpanelHintDetailと対で参照）。
    panelHint:
      "国土数値情報の緊急輸送道路[N10]・重要物流道路[N12]に該当する区間です。" +
      "大型車の通行が多いと推定される目安として車の圧迫感の評価にも加点されますが、" +
      "指定路線かどうか自体を個別に確認できるよう別レイヤーとして表示しています。",
  },
  {
    // トンネル（一次属性、OSMのtunnelタグ）。これまで観測配下に専用レイヤーを持たず、
    // 区間ポップアップのみで確認できたが（改善計画: 地図上に描画可能な状態で保持している
    // 要素の洗い出しで判明）、他の一次属性と同じ独立レイヤーとして観測グループへ追加する。
    // designation・bicycleInfraと同じroad_surfaceソースの独立レイヤー。
    id: "tunnel",
    label: "トンネル",
    kind: "static",
    category: "roadCondition",
    description: "トンネル区間[OSMのtunnelタグ]を色分け表示",
    panelHint:
      "OSMのtunnelタグが該当する区間です。「夜間」軸[推定グループ]の材料の1つとして、" +
      "夜間の危険度の判定に使われます[改善計画T278でnight軸自体も専用レイヤーを持つようになりました]。",
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
    id: "supplyPoi",
    label: "補給・休憩ポイント",
    // 地図上のチップ幅は文字数に連動する（他レイヤーは4文字以内: 指定路線/インフラ等）ため、
    // 「補給・休憩」（読点込み5文字）だとこのチップだけ幅が広がってしまう。読点を省いた
    // 「補給休憩」（4文字）に短縮（正式名称は引き続きlabelの「補給・休憩ポイント」）。
    chipLabel: "補給休憩",
    kind: "static",
    category: "amenity",
    description: "コンビニ・自販機・トイレ・給水・駐輪場の位置を種別ごとに色分け表示",
    // ユーザー懸念「実店舗とどれだけ合っているか」への回答として、backend/scripts/
    // measure_poi_freshness.py（改善計画T101、2026-08-18）でOSM側の最終編集日時を
    // 実測した。コンビニは関東全域で直近2年以内の編集が62.4%と明確に新しいが、
    // 自販機・トイレ・給水・駐輪場は5年以上未編集が58〜59%と高く、閉店・撤去に
    // データが追いついていないリスクが相対的に高い。取込自体は5種すべて対象にしつつ、
    // 利用者へは正直にこの差を伝える（コンビニを優先的な目安、他4種は参考程度に）。
    panelHint:
      "コンビニ・自販機・トイレ・給水・駐輪場の位置です。コンビニはOSMデータの更新が" +
      "比較的新しく目安として使いやすい一方、自販機・トイレ・給水・駐輪場は閉店・撤去に" +
      "データが追いついていないことがあります。現地の状況と異なる場合があることをご留意ください。",
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
  // 二次軸の汎用rampレイヤー（改善計画T145b「事実はタイルに、解釈はクライアントに」）。
  // backendレジストリ生成物（axis-catalog.json）のkind="ramp"軸から自動生成する。
  // 新しい軸はbackendのレジストリ登録＋タイルへの事実焼き込みだけでここへ現れる
  // （このファイルの編集は不要）。凡例（段階・色・絞り込み）はSTATIC_FILTER_AXES
  // （staticAttributeLayers.ts、axisLayers.ts: buildAxisRampLegend由来）が
  // 他の静的レイヤーと同じ仕組みで提供するため、panelHintDetail（文字のみの内訳）は持たない
  // （改善計画: 停止密度・事故密度の凡例追加）。
  ...RAMP_AXES.map(
    (axis): MapLayerDescriptor => ({
      id: axisMapLayerId(axis.axisId),
      label: axis.label,
      kind: "static",
      category: axis.category as MapLayerCategory,
      // ramp軸は定義上「一次属性（tile_inputs）を重み付けで合成した二次軸スコア」
      // （axisLayers.ts冒頭コメント参照）のため、常にcomposite（生データではない）。
      dataNature: "composite",
      // unit=""（改善計画T278の自動導出軸、真偽値材料由来のためkm単位等が無い）の場合は
      // 空の[]を出さない。
      description: `${axis.label}${axis.unit ? `[${axis.unit}]` : ""}をway単位の事前集計から色分け表示`,
      // axis.note（backendレジストリの実装メモ、registry_defaults.py）は開発者向けに
      // 書かれており「way単位の事前集計（way_attribute_counts）由来」等の実装用語を
      // 含むため、そのままpanelHintへ出すと読みにくいという実機フィードバックを受けた。
      // 「何を集計した目安か＋実地点はどこで確認できるか」という他の静的レイヤーの
      // 説明文と同じ型で言い換えたものをRAMP_AXIS_PANEL_HINTSに持ち、優先して使う
      // （未登録の軸はaxis.noteへフォールバック。片側importの例外として、この言い換えは
      // エンドユーザー向け文言でありレジストリ側に置く性質のものではないためフロント固有）。
      panelHint: RAMP_AXIS_PANEL_HINTS[axis.axisId] ?? axis.note,
    }),
  ),
  {
    // 気象庁 降水ナウキャスト（改善計画T170/T171、T183で延長予報を追加、T184で動的レイヤー
    // 全体を再設計）。実況（過去〜現在、5分毎）と60分先までの短時間予測をラスタタイルで
    // 重ね描きする。60分より先（ユーザー要望「1時間より先も、短時間雨予報を出してほしい」）は、
    // 風と共有の格子点マップ由来の降水量を、格子セルを降水強度に応じた色で塗るgridFill表現
    // （precipitationNowcast.ts: precipitationRenderPayload、MapView.tsx: DYNAMIC_WEATHER_
    // RENDERERS）へ内部で切り替わる。表示・トグルは1つのまま（ユーザー要望「アイコンは1つ。
    // ただし内部は時間によって使い分けて」——「アイコン」だった旧デザインはT184でgridFillへ
    // 置き換えたが、表示・トグルが1つという要件自体は変わらない）。他の静的レイヤーと異なり、
    // 表示中の時刻を地図上の時刻スライダー（風と共有の1本のスライダー、
    // layerVisibility.precipitationNowcast/windVectorのどちらかがONの間だけ表示、page.tsx参照）
    // で切り替えられる。
    id: "precipitationNowcast",
    label: "降水ナウキャスト",
    chipLabel: "降水",
    kind: "static",
    category: "weather",
    dataNature: "dynamic",
    description: "気象庁の降水ナウキャストと延長予報を重ねて表示[実況〜60分先は5分刻み、以降は約48時間先までOpen-Meteo予報1時間刻み]",
    panelHint:
      "気象庁の高解像度降水ナウキャストです。ONにすると地図上に時刻スライダーが現れ、" +
      "実況（直近）から60分先までの雨雲の分布を切り替えて確認できます。60分より先は、" +
      "風と同じ仕組み（Open-Meteo経由の格子点予報）による、格子を降水強度に応じた色で塗る" +
      "延長予報表示へ自動的に切り替わり、約48時間先まで確認できます（直近ほどの精度ではない" +
      "粗いモデル予報です）。非公式の内部APIを利用している実況・60分先までの部分は、" +
      "取得に失敗することがあります。",
  },
  {
    // 風の矢印（改善計画T178、フォローアップで自前実装へ移行）。関東本土全域の固定格子点
    // （バックエンド/api/weather/wind-grid）をOpen-Meteo REST API経由でサンプリングする
    // 自前実装のため、GPLv2ライブラリ・気象庁の非公式配信のどちらにも依存しない。
    id: "windVector",
    label: "風（矢印）",
    chipLabel: "風",
    kind: "static",
    category: "weather",
    dataNature: "dynamic",
    description: "Open-Meteoの風向・風速予報を矢印で表示[関東本土の格子点、約48時間先まで]",
    panelHint:
      "Open-Meteoの数値予報モデルによる風向・風速を関東本土全域の格子点で矢印表示します。" +
      "矢印の向きが風向、長さ・太さ・色の濃淡が風速の強さを表します。ごく弱い風の地点は" +
      "矢印を表示しません。ONにすると地図上に時刻スライダーが現れ、1時間刻みで約48時間先" +
      "まで切り替えて確認できます。",
  },
  {
    // 雷ナウキャスト（改善計画T204）。T171実装メモが「プロダクトコード未確認のため
    // 別レイヤー・別調査として残す」としていた宿題。降水ナウキャストと同じ気象庁配信
    // （bosai/jmatile/data/nowc/、プロダクトコードthns）だが、実況〜60分先までのみで
    // それより先の延長予報は無い（範囲外はT184共通契約どおり描画しない）。「回避一択」の
    // 危険のため評価軸には組み込まず警告表示のみ。
    id: "thunderNowcast",
    label: "雷ナウキャスト",
    chipLabel: "雷",
    kind: "static",
    category: "weather",
    dataNature: "dynamic",
    description: "気象庁の雷ナウキャストを表示[実況〜60分先、10分刻み]",
    panelHint:
      "気象庁の雷ナウキャスト（活動度1〜4）です。ONにすると地図上に時刻スライダーが現れ、" +
      "実況（直近）から60分先までの雷の状況を切り替えて確認できます。活動度2以上が表示" +
      "されている領域では、直ちに建物の中など安全な場所への避難が必要です。非公式の内部" +
      "APIを利用しているため、取得に失敗することがあります。",
  },
  {
    // 竜巻発生確度ナウキャスト（改善計画T204、雷と同じN3配信のため同時に実装）。雷とは
    // 独立したON/OFFにする（同じ地図上に雷・竜巻を重ねると見分けにくいという判断、
    // 必要な情報だけを選んで表示できるようにする）。
    id: "tornadoNowcast",
    label: "竜巻発生確度ナウキャスト",
    chipLabel: "竜巻",
    kind: "static",
    category: "weather",
    dataNature: "dynamic",
    description: "気象庁の竜巻発生確度ナウキャストを表示[実況〜60分先、10分刻み]",
    panelHint:
      "気象庁の竜巻発生確度ナウキャスト（発生確度1・2）です。ONにすると地図上に時刻" +
      "スライダーが現れ、実況（直近）から60分先までの竜巻等の激しい突風の可能性を切り替えて" +
      "確認できます。発生確度2は気象庁の「竜巻注意」情報につながる絞り込んだ予測です。" +
      "非公式の内部APIを利用しているため、取得に失敗することがあります。",
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

// roadType/roadSurface（T165で「道路情報」から論理分割）/carStress/bicycleInfra/
// designation/tunnelは同じroad_surfaceベクタタイル（MapView.tsx: ROAD_TILE_SOURCE_ID/
// ROAD_TILE_SOURCE_LAYER、LAYER_DATA_SOURCES参照）を共有しているため、そのタイルの
// minzoom未満（regionZoomTooWide）ではタイル自体が要求されず、6レイヤーとも同時に
// loading/emptyと判定される。「表示範囲が広すぎます」という案内が既にある
// ズーム範囲外の間は、レイヤーのデータ状態表示（T87）を二重に出さないための判定に使う
// （MapView.tsx側のregionZoomTooWide算出・MapLayersPanel.tsx側の抑制の両方が参照する単一の
// 定義。片方だけ更新して食い違う、という改善計画の設計原則8違反を避けるため）。
export const ROAD_SURFACE_SHARED_LAYER_IDS: readonly MapLayerId[] = [
  "roadType",
  "roadSurface",
  "carStress",
  "bicycleInfra",
  "designation",
  "tunnel",
  // 二次軸rampレイヤー（T145b）も同じroad_surfaceタイルへ焼き込まれたプロパティを読む
  ...RAMP_AXES.map((axis) => axisMapLayerId(axis.axisId)),
];
