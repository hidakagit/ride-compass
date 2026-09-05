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
// - terrain（地形）: 標高図
// - amenity（補給・施設、改善計画T101）: 補給・休憩ポイント。安全・リスクの指標ではなく
//   trafficSafetyへ含めるのは意味的に不適切なため独立カテゴリにした
// 改善計画T347: 旧bicycleInfra（自転車インフラ）カテゴリ・専用レイヤーはここから削除した
// （このカテゴリの利用者が当該レイヤー1つだけだったため、レイヤーの廃止に伴いカテゴリ自体も
// 廃止。評価軸側は新設の公開軸「自転車インフラ」bicycle_infra_qualityへ置き換え、地図
// レイヤーは持たない[show_map_icon=false]）。

import {
  axisMapLayerId,
  type AxisMapLayerId,
  type CatalogAxis,
  type RampAxis,
} from "./axisLayers";
import axisCatalog from "@/types/generated/axis-catalog.json";

export type MapLayerId =
  | "elevation"
  | "roadType"
  | "roadSurface"
  | "designation"
  | "tunnel"
  | "oneway"
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
  // way_id→wind_drag_ratio配信層（改善計画T405/T414）。評価軸としての風——道路自身の
  // 向きではなくユーザー指定の走行方位から計算したwind_drag_ratioをway単位でsetFeatureState
  // 経由で線色分けする、windVector（面・矢印、探索用）とは独立の見せ方
  // （docs/tasks/T400.md「2. 動的要素…の二重表現」節）。改善計画T418で地図上チップとしては
  // 撤去し、ルート設定パネル（RouteSettingsPanel.tsx）から起動する形へ移設した。
  // category/dataNatureの値自体はwindVectorと同じkind="static"・dataNature="dynamic"の
  // まま変えていない（値は時間で変わるが、表示方式はvisibility切替のみの常設レイヤーという
  // 性質はwindVectorと同じ）。`isAxisStudioLayer`がid="windAxis"を特別扱いして、地図上
  // チップ（MapOverlayControls.tsx）・サイドバー（MapLayersPanel.tsx）どちらにも
  // 現れないようにする。
  | "windAxis"
  // 環境グループの勾配面表示（改善計画T423）。windVectorに相当する「向きに依存する
  // 材料の環境グループ表現」だが、勾配には風のような独立した空間フィールド（矢印で表す
  // ベクトル場）が無いため矢印表示は持たず、gridFill（タイル境界をセルとする面表示、
  // gradientGridFill.ts）のみを持つ。
  | "gradientFill"
  // way_id→勾配（effective_gradient）配信層（改善計画T423）。windAxisと同型——道路自身の
  // 向きが本質的に必要という点が風とは異なる性質（T423.mdの重要な注意点参照）だが、
  // 配信・setFeatureState連携の枠組み自体はwindAxisと共有する（dynamicWayValues.ts）。
  | "gradientAxis"
  // 災害。雷ナウキャスト・竜巻発生確度ナウキャスト・雷放電位置データ（落雷）・キキクル
  // 4種（土砂災害・大雨・浸水・洪水）の7要素を1つのチップへまとめたグループで、7要素は
  // MapView.tsxのDYNAMIC_WEATHER_RENDERERSの名前付きソースとして同時に描画する。
  // 「回避一択」の危険のため評価軸には組み込まず表示のみを行う。線状降水帯予測マップは
  // rasrf系統（降水短時間予報と同じ）のため、ここではなく"precipitationNowcast"チップの
  // 傘下（4つ目のソース）にある。
  | "disaster"
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
export type MapLayerCategory = "roadCondition" | "trafficSafety" | "terrain" | "amenity" | "weather" | "disaster";

// カテゴリの表示順・見出し文言の単一ソース（改善計画T86→T128）。以前はMapLayersPanel.tsx
// だけが持っていたが、T128（地図上チップのカテゴリ束ね）でMapOverlayControls.tsxも
// 同じ対応表を要するようになったため、両者が参照するここへ集約する
// （設計原則8: UI語彙のカタログ集約、片側importで揃える）。
export const MAP_LAYER_CATEGORY_ORDER: readonly MapLayerCategory[] = [
  "roadCondition",
  "trafficSafety",
  "terrain",
  "amenity",
  "weather",
  "disaster",
];

/** 生データ（OSM/警察庁の生タグ・生座標をそのまま分類表示）か、複数要因から計算した
 * 推定指標（合成）か、時刻で内容が変わる動的データか。改善計画T166でチップ最上位の
 * 分類そのものへ一時昇格したが、T406で地図上チップ（MapOverlayControls.tsx）の最上位は
 * 「道路/評価軸/環境/スポット」の4チップへ再編され、さらにT418で評価軸チップ自体を
 * 地図UIから撤去した（評価軸はルートの有無に応じて役割が変わる道具のため、ルート設定/
 * ルート結果パネルへ移設。docs/tasks/T418.md参照）。
 * このMapLayerDataNature自体は表示グルーピングの単位ではなくなったが、(a)
 * `isAxisStudioLayer`が"composite"を「軸スタジオ由来のため地図UIチップには出さない」
 * 判定の入力に使う、(b) MapLayersPanel.tsxが"dynamic"（降水ナウキャスト等、帯単位の
 * 絞り込み機能を持たないレイヤー。ユーザー判断2026-08-25）をサイドバーの詳細セクションから
 * 除外する判定に引き続き使う、の2点で残っている。 */
export type MapLayerDataNature = "raw" | "composite" | "dynamic";

/** 改善計画T406/T418: 地図上チップ（MapOverlayControls.tsx）・サイドバー
 * （MapLayersPanel.tsx）最上位の3グループ。「対象（何についての情報か）」で束ねる
 * （docs/tasks/T400.md「1. パネルの最上位グルーピング」節）。
 * - road（道路）: 道路の純粋な属性のみ（道路種別・路面種別・指定路線・トンネル・一方通行）
 * - environment（環境）: 標高／降水ナウキャスト・風（矢印）・雷・竜巻等の面レイヤー
 * - spot（スポット）: 停止要因POI・補給POI・事故地点等の点レイヤー
 * T406時点は軸スタジオが作る全評価軸（car_stress等・windAxis）を「評価軸」チップとして
 * 道路と同列に並べていたが、T418でこのチップ自体を撤去した——評価軸はルートの有無に
 * 応じて「重み配分を検討する材料」「生成済みルートを分析する材料」と役割が変わる道具で
 * あり、道路・環境・スポットのようにルートの状態に関係なく意味が一定な「地図そのものの
 * 見え方」設定とは性質が異なるため（docs/tasks/T418.md「目的」節）。評価軸の色分けは
 * ルート未確定時はルート設定パネル（RouteSettingsPanel.tsx）の軸ごとの行から、ルート
 * 確定後は「地図の色分け」（RouteAxisProfile.tsx、旧称「生成したルートの色分け」。
 * 改善計画T518で改称・統合。routeStyleModes.ts参照）から、それぞれ起動する。
 * 軸スタジオ由来のレイヤー（ramp軸・windAxis）を地図UIの3グループ判定から除外する判定は
 * `isAxisStudioLayer`（下記）が担う。 */
export type MapOverlayGroup = "road" | "environment" | "spot";

export const MAP_OVERLAY_GROUP_LABELS: Record<MapOverlayGroup, string> = {
  road: "道路",
  environment: "環境",
  spot: "スポット",
};
/** 地図チップの略名（4文字以下）。改善計画T413でサイドバーもMAP_OVERLAY_GROUP_LABELS
 * （正式名）を使うようになったため、地図チップ=略名／サイドバー=正式名という他レイヤーの
 * label/chipLabelと同じ使い分けになった。 */
export const MAP_OVERLAY_GROUP_CHIP_LABELS: Record<MapOverlayGroup, string> = {
  road: "道路",
  environment: "環境",
  spot: "スポット",
};
/** チップの表示順（道路→環境→スポット、docs/tasks/T400.md「最終形」の記載順のうち
 * 評価軸[T418で撤去]を除いた並び）。 */
export const MAP_OVERLAY_GROUP_ORDER: readonly MapOverlayGroup[] = ["road", "environment", "spot"];

// 改善計画T440: 専用のway_id→動的値配信層を持つ軸（軸データのdedicated_way_value_layer、
// domain/axis_definitions.py参照）のMapLayerIdを、axis_idのハードコード比較ではなく
// ビルド時静的axis-catalog.json（RAMP_AXES/AXIS_LABELS等と同じ「片側import」の
// 静的フォールバック生成物、useAxisCatalog.tsが実行時APIを取得完了するまでの間・
// 軸スタジオ非対応の純粋関数から使う値）から導出する。レイヤーIDの命名規約
// （`${axis_id}Axis`、windAxis/gradientAxisの実例で確認済み）に従い文字列を組み立て、
// 実際にMapLayerIdとして配線済みのものだけを残す（未配線のIDが混入しても無視される）。
const DEDICATED_WAY_VALUE_LAYER_IDS: ReadonlySet<string> = new Set(
  (axisCatalog.axes as CatalogAxis[])
    .filter((axis) => axis.dedicated_way_value_layer)
    .map((axis) => `${axis.axis_id}Axis`)
);

/** 軸スタジオ由来のレイヤーか（改善計画T418、T423でgradientAxisを追加）。ramp軸
 * （dataNature==="composite"）・専用way_id→動的値配信層を持つ軸
 * （DEDICATED_WAY_VALUE_LAYER_IDS、上記）はいずれも、T406時点は地図上チップの
 * 「評価軸」グループへ束ねられていたが、T418でそのチップ自体を撤去しルート設定パネルへ
 * 移設した。地図上チップ（MapOverlayControls.tsx）・サイドバー（MapLayersPanel.tsx）の
 * 両方が、この判定を使ってこれらのレイヤーを描画対象から除外する（mapOverlayGroupForが
 * 返すundefinedは「route等、単独チップとして出す」ものと「軸スタジオ由来のため地図UIには
 * 一切出さない」ものの2種類が混在するため、区別に使う専用の判定）。 */
export function isAxisStudioLayer(layer: { id: MapLayerId; dataNature?: MapLayerDataNature }): boolean {
  return DEDICATED_WAY_VALUE_LAYER_IDS.has(layer.id) || layer.dataNature === "composite";
}

/** レイヤー1件が属するMapOverlayGroupを判定する（改善計画T406/T418）。category/
 * dataNatureの既存フィールドだけで機械的に判定できるが、軸スタジオ由来のレイヤー
 * （isAxisStudioLayer、windAxis・ramp軸）は明示的に対象外（undefined）にする——
 * category値だけを見ると「道路」「スポット」「環境」のいずれかに紛れ込んでしまうため
 * （例: car_stressのcategory="trafficSafety"はaccidents等と同じ値）、category判定の
 * 前に必ず除外する。route等、どのグループにも属さないレイヤーもundefinedを返す。 */
export function mapOverlayGroupFor(layer: {
  id: MapLayerId;
  category?: MapLayerCategory;
  dataNature?: MapLayerDataNature;
}): MapOverlayGroup | undefined {
  if (isAxisStudioLayer(layer)) return undefined;
  if (layer.category === "roadCondition") return "road";
  if (layer.category === "terrain" || layer.category === "weather" || layer.category === "disaster")
    return "environment";
  if (layer.category === "trafficSafety" || layer.category === "amenity") return "spot";
  return undefined;
}

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
  /** 地図上チップ・サイドバーどちらの最上位グルーピング（mapOverlayGroupFor、改善計画T406/
   * T413/T418）も、これ自体（roadCondition/trafficSafety/terrain/amenity/weather）を
   * 入力の一部として使う。合わせてサイドバーの表示順（MAP_LAYER_CATEGORY_ORDER）・
   * 地図上チップの「道路」「環境」「スポット」各グループ内のトピック別小見出しにも使う。
   * kind:"static"のレイヤーのみ持つ（dynamicは今のところroute1種のみのため不要）。 */
  category?: MapLayerCategory;
  /** 生データか推定指標（合成）か時刻で変わる動的データか（MapLayerDataNature参照）。
   * isAxisStudioLayerが"composite"を「軸スタジオ由来のため地図UIチップには出さない」
   * 判定に使う。省略時は"raw"扱い（大半のレイヤーは生タグ・生座標の分類表示のため、
   * 明示するのは合成/動的側のみで足りる）。 */
  dataNature?: MapLayerDataNature;
  /** ONにすると何が表示されるかの短い説明（チップのtitleに使う） */
  description: string;
  /** サイドバー設定パネル（MapLayersPanel）のセクション本文に出す説明文（改善計画T84）。
   * descriptionより詳しい判定基準・注意点を書く場所で、以前はMapLayersPanel.tsxの
   * switch文へレイヤーごとハードコードされておりカタログ集約の方針（設計原則8）から
   * 外れていた。未指定のレイヤー（道路情報・ルート等）はパネル側が独自の特殊なJSXを持つ。 */
  panelHint?: string;
  /** 改善計画: MapLayersPanel（サイドバー「地図の見え方」パネル）の一覧から、この
   * レイヤーを除外するか。既定false（掲載する）。dataNature="dynamic"（帯単位の
   * 絞り込み機能を持たない、2026-08-25ユーザー判断、MapLayersPanel.tsx参照）と同じ
   * 理由——ON/OFFの単純な切替しか提供せず、絞り込み・凡例等サイドバー掲載の価値が
   * 無い場合に立てる。elevation（標高図、ラスタタイル）が実例——地図上チップ
   * （MapOverlayControls）のON/OFFで用途は完結しており、そちらだけを唯一の入口とする
   * （ユーザー指摘2026-08-31: 地図の見え方パネルに載せる意味が無い。地図上チップの
   * ON/OFF自体は引き続き必要）。dataNature自体を再利用しない理由: dataNatureは
   * 「データの性質」（生/合成/時々刻々変わる）を表す別概念のフィールドで、elevationは
   * 静的なラスタタイルのため"dynamic"に当てはめると意味が食い違う。 */
  hideFromLayersPanel?: boolean;
}

// ramp軸のpanelHint（改善計画: 地図の見え方パネルの推定指標説明を簡略化）。以前は
// 軸id→値の手書き辞書（RAMP_AXIS_PANEL_HINTS）を持っていたが、改善計画T310で軸自身の
// データ（axis.panelHint、AXIS_DEFINITIONS.panel_hint）へ移設し、既存軸限定の特別扱いを
// 解消した。axis.note（backendレジストリの実装メモ、開発者向け）をそのまま出すと
// 読みにくいという実機フィードバックを受け、未設定時のみaxis.noteへフォールバックする
// （下記buildMapLayersのrampAxes.map参照）。

// 改善計画T308: ramp軸部分はbuildMapLayers(rampAxes)として関数化し、
// hooks/useAxisCatalog.tsが実行時に取得したrampAxes（軸スタジオの公開軸を含む）から
// 呼べるようにした。テスト（axisLayers.test.ts、MapLayersPanel.test.tsx）からは
// buildMapLayers(RAMP_AXES)として直接呼べる。
export function buildMapLayers(rampAxes: readonly RampAxis[]): readonly MapLayerDescriptor[] {
  return [
  {
    id: "elevation",
    // ルート指標の「獲得標高」と紛らわしいため、地図レイヤー側は「標高図」と呼び分ける
    label: "標高図",
    kind: "static",
    category: "terrain",
    description: "国土地理院の色別標高図を重ねる",
    panelHint: "国土地理院の色別標高図を重ねる",
    // ユーザー指摘（2026-08-31）: ラスタタイルのため他レイヤーのような凡例ベースの
    // 絞り込みができず、MapLayersPanel.tsxのrenderSectionBody（case "elevation"）も
    // 説明文のみで設定項目を一切持たない。ON/OFF自体は地図上チップ（MapOverlayControls）
    // 側で完結しているため、サイドバー「地図の見え方」パネルへ重複掲載する意味が無い。
    hideFromLayersPanel: true,
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
    id: "designation",
    // 外部静的データソース T51（国土数値情報 N10/N12）。指定路線コンフレーション機構が
    // road_edgesへ対応付けた緊急輸送道路・重要物流道路を色分け表示する。
    label: "指定路線[緊急輸送・重要物流]",
    chipLabel: "指定路線",
    kind: "static",
    category: "roadCondition",
    description: "国土数値情報の緊急輸送道路・重要物流道路[KSJ N10/N12]に該当する区間を色分け表示",
    // バッファマッチ（20m、交差率50%以上）でroad_edgesへ対応付けた区間を色分けする。
    // 該当区間は車の圧迫感軸（axis:car_stress）にも+1の補正として反映される
    // （改善計画T292: domain/axis_definitions.py: car_stress_designation_adjustment参照）。
    // 改善計画T89: 「車ストレスと指定路線は何が違うのか」という実機フィードバックを受け、
    // 指定路線が「行政指定という事実」の表示であり、車ストレスはそれを含む複数要因
    // （道路種別・車線数・制限速度・自転車インフラ関連の正規化フラグ）を合成した推定指標
    // であるという役割の違いを明記する（car_stress軸自身のpanel_hint、AXIS_DEFINITIONS
    // 参照と対で参照）。
    panelHint:
      "国土数値情報の緊急輸送道路[N10]・重要物流道路[N12]に該当する区間です。" +
      "大型車の通行が多いと推定される目安として車の圧迫感の評価にも加点されますが、" +
      "指定路線かどうか自体を個別に確認できるよう別レイヤーとして表示しています。",
  },
  {
    // トンネル（一次属性、OSMのtunnelタグ）。これまで観測配下に専用レイヤーを持たず、
    // 区間ポップアップのみで確認できたが（改善計画: 地図上に描画可能な状態で保持している
    // 要素の洗い出しで判明）、他の一次属性と同じ独立レイヤーとして観測グループへ追加する。
    // designationと同じroad_surfaceソースの独立レイヤー。
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
    // 一方通行（一次属性、OSM onewayタグ。改善計画T289）。tunnelと同じ「観測配下に専用
    // レイヤーが無いまま保持していた要素」パターン。一方通行の逆方向は既にRoad Graph構築時
    // （backend/app/domain/graph.py: build_road_graph）にEdge自体が生成されないため探索の
    // 正しさには無関係で、評価軸（route_preference）にも組み込まない表示専用の一次属性。
    id: "oneway",
    label: "一方通行",
    kind: "static",
    category: "roadCondition",
    description: "一方通行区間[OSMのonewayタグ]を色分け表示",
    panelHint:
      "OSMのonewayタグが該当する区間です。ルート探索は既に一方通行の向きを守っており" +
      "（逆走経路自体が生成されません）、このレイヤーは表示のみで評価には影響しません。",
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
  // 他の静的レイヤーと同じ仕組みで提供する（改善計画: 停止密度・事故密度の凡例追加）。
  ...rampAxes.map(
    (axis): MapLayerDescriptor => ({
      id: axisMapLayerId(axis.axisId),
      label: axis.label,
      chipLabel: axis.chipLabel,
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
      // 説明文と同じ型で言い換えたものを軸自身のpanelHint（改善計画T310、AXIS_DEFINITIONS.
      // panel_hint）に持ち、優先して使う（未設定の軸はaxis.noteへフォールバック）。
      panelHint: axis.panelHint ?? axis.note,
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
    description:
      "気象庁の降水ナウキャスト・降水短時間予報・延長予報・線状降水帯予測マップを重ねて表示" +
      "[実況〜60分先は5分刻み、60分〜15時間先は気象庁予報、以降は約48時間先までOpen-Meteo" +
      "予報1時間刻み。線状降水帯予測マップは現在〜3時間先の間だけ追加で重畳]",
    panelHint:
      "気象庁の高解像度降水ナウキャストです。ONにすると地図上に時刻スライダーが現れ、" +
      "実況（直近）から60分先までの雨雲の分布を切り替えて確認できます。60分より先は、" +
      "同じ気象庁の降水短時間予報（改善計画T407）へ自動的に切り替わり、15時間先まで" +
      "確認できます——こちらは実況の外挿ではなく数値予報モデルによる予測のため、先に" +
      "なるほど不確実性が増します。15時間より先は、風と同じ仕組み（Open-Meteo経由の" +
      "格子点予報）による、格子を降水強度に応じた色で塗る延長予報表示へさらに切り替わり、" +
      "約48時間先まで確認できます（気象庁予報よりも粗いモデル予報です）。加えて、現在〜3時間先の" +
      "間だけ、気象庁の線状降水帯予測マップ（今後3時間以内に大雨のおそれがある領域）を重ねて" +
      "表示します（改善計画T432、赤色の領域）。非公式の内部APIを利用している実況・60分先までの" +
      "部分・線状降水帯予測マップは、取得に失敗することがあります。",
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
      "矢印を表示しません。ONにすると地図上に時刻スライダーが現れ、1時間刻みで約48時間先まで" +
      "切り替えられます。走行方位に対する向かい風/追い風の強さは、ルート設定パネルの" +
      "「風」の「地図で色分け」ボタンから道路の色分けとして別途確認できます。",
  },
  {
    // way_id→wind_drag_ratio配信層（改善計画T405/T414、docs/tasks/T400.md「2. 動的要素…の
    // 二重表現」節）。上のwindVector（格子点・矢印表示、探索用の「環境」表現）とは
    // 独立した評価軸としての表現——ユーザー指定の走行方位と最寄りの風グリッド値から
    // wind_drag_ratioを計算し、backendのRedis配信層（タイル単位キー）・新設APIを経由して
    // MapLibreのsetFeatureStateで道路線そのものを色分けする。改善計画T418で地図上チップ
    // としては撤去し、ルート設定パネル（RouteSettingsPanel.tsx）の「風」行から起動する形へ
    // 移設した——label/chipLabel/descriptionはisAxisStudioLayerによりMapOverlayControls/
    // MapLayersPanelの表示対象からは除外される。
    // 改善計画T446（コード実態と食い違っていた旧コメントの訂正）: RouteSettingsPanel.tsx
    // 自体はこのMapLayerDescriptorを直接参照しない（`mapColorLayerIdFor`経由で
    // layerVisibility[layerId]のON/OFFだけを扱う、tooltip文言も自前のハードコード文字列）。
    // このエントリが実際に使われているのは、(1) MapLayerId型の定義そのものと、(2)
    // road_surfaceタイル（promoteId付きway_id）を共有するレイヤーとして
    // buildRoadSurfaceSharedLayerIds（下記）へ含め、regionZoomTooWide判定
    // （MapView.tsx: isRoadSurfaceGroupVisible→updateRoadZoomHint、「表示範囲が広すぎます」
    // バナー）の対象にすることの2点のみ。
    id: "windAxis",
    label: "風（評価軸）",
    chipLabel: "風軸",
    kind: "static",
    category: "weather",
    dataNature: "dynamic",
    description: "指定した時刻・向きで進んだ場合の向かい風/追い風の強さを視界内の全道路へ一律に線色分け表示",
    panelHint:
      "ONにすると地図下部のコンパススライダーが使えるようになります。指定した時刻・" +
      "走行方位（向き）と、各道路の最寄りの風予報格子点の風向・風速から、向かい風/追い風の" +
      "強さを計算して視界内の全道路を一律に色分けします（改善計画T414、道路自身の向きは" +
      "計算に使いません——実際にどちらへ走るかはユーザーが指定する値のため）。赤に近いほど" +
      "向かい風が強く、緑に近いほど追い風が強いことを表します。ルートを生成・選択すると、" +
      "この一律の色分けは終了し、代わりに「地図の色分け」の「風」で、ルート自身の実際の" +
      "進行方向・到達時刻に基づく色分けをルート線だけに適用できます。",
  },
  {
    // 環境グループの勾配面表示（改善計画T423）。windVectorと異なり独立した空間フィールドを
    // 持たないため（gradientGridFill.tsのモジュールdocstring参照）、矢印は無くgridFillのみ。
    id: "gradientFill",
    label: "勾配（面）",
    chipLabel: "勾配",
    kind: "static",
    category: "terrain",
    dataNature: "dynamic",
    description: "指定した走行方位で進んだ場合の実効勾配を、周辺道路網の平均としてタイル単位の面塗りで表示",
    panelHint:
      "ONにすると地図下部にコンパススライダーが現れます。指定した走行方位（向き）と、" +
      "そのタイル内の道路網が持つ実際の勾配・向きから、実効的な勾配（登り/下り）の平均を" +
      "タイル単位の面で色分けします（改善計画T423）。「評価軸」グループの「勾配」（線）と" +
      "同じ向きの指定を共有します。",
  },
  {
    // way_id→勾配（effective_gradient）配信層（改善計画T423、docs/tasks/T400.md「2. 動的
    // 要素…の二重表現」節）。上のgradientFill（タイル単位の面表示、探索用の「環境」表現）
    // とは独立した評価軸としての表現——windAxisと同型（改善計画T418で地図上チップとしては
    // 撤去し、ルート設定パネル[RouteSettingsPanel.tsx]の「勾配」行から起動する形へ移設）。
    // windAxis同様buildRoadSurfaceSharedLayerIds（下記）にも含める——実際の用途はwindAxisの
    // コメント参照（改善計画T446、以前はwindAxisのみ含みここが非対称のまま残っていた）。
    id: "gradientAxis",
    label: "勾配（評価軸）",
    chipLabel: "勾配軸",
    kind: "static",
    category: "terrain",
    dataNature: "dynamic",
    description: "指定した走行方位で進んだ場合の実効勾配を視界内の全道路へ一律に線色分け表示",
    panelHint:
      "ONにすると地図下部のコンパススライダーが使えるようになります。指定した走行方位と、" +
      "各道路自身の勾配・向きから、その方向へ走った場合の実効的な勾配を計算して視界内の" +
      "全道路を一律に色分けします（改善計画T423）。登るほど赤に、下るほど青に近づきます。" +
      "「環境」グループの「勾配」（面塗り）と同じ向きの指定を共有します。ルートを生成・" +
      "選択すると、この一律の色分けは終了し、代わりに「地図の色分け」の「勾配」" +
      "で、ルート自身の実際の進行方向に基づく色分けをルート線だけに適用できます。",
  },
  {
    // 災害（雷ナウキャスト・竜巻発生確度ナウキャスト・雷放電位置データ・キキクル4種）。
    // 7要素を1つのチップでまとめてON/OFFし、MapView.tsxのDYNAMIC_WEATHER_RENDERERSが
    // 名前付きソースとして同時に描画する。雷・竜巻・落雷は時刻スライダーに連動し、
    // キキクル4種は「現在の危険度」単一値のみの配信のため連動しない（riskMap.ts参照）。
    // 「回避一択」の危険のため評価軸には組み込まず表示のみを行う。
    id: "disaster",
    label: "災害",
    chipLabel: "災害",
    kind: "static",
    category: "disaster",
    dataNature: "dynamic",
    description:
      "気象庁の雷・竜巻・落雷とキキクル4種（土砂災害・大雨・浸水・洪水）をまとめて表示" +
      "[雷・竜巻・落雷は実況〜60分先、キキクルは現在の危険度のみ]",
    panelHint:
      "気象庁の防災情報をまとめて表示します。雷ナウキャスト（活動度1〜4）・竜巻発生確度" +
      "ナウキャスト（発生確度1・2）・雷放電位置データ（実際の落雷地点）は時刻スライダーに" +
      "連動し、実況（直近）から60分先までを切り替えて確認できます。キキクル4種（土砂災害・" +
      "大雨・浸水・洪水）は5段階（注意・警戒・危険・災害切迫、平常時は表示なし）で色分け" +
      "した現在の危険度で、「現在の危険度」単一値のみの配信のため時刻スライダーには連動" +
      "しません。平常時は危険度ゼロの領域が透明のため、ONのままでも地図の見た目は" +
      "変わりません。非公式の内部APIを利用しているため、取得に失敗することがあります。",
  },
  {
    id: "route",
    label: "ルート",
    kind: "dynamic",
    description: "選択中ルート沿いの情報[風・勾配・路面・総合難易度]を色分け表示",
  },
  ];
}

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

// roadType/roadSurface（T165で「道路情報」から論理分割）/designation/tunnel/
// onewayは同じroad_surfaceベクタタイル（MapView.tsx: ROAD_TILE_SOURCE_ID/
// ROAD_TILE_SOURCE_LAYER、LAYER_DATA_SOURCES参照）を共有しているため、そのタイルの
// minzoom未満（regionZoomTooWide）ではタイル自体が要求されず、同時に
// loading/emptyと判定される。「表示範囲が広すぎます」という案内が既にある
// ズーム範囲外の間は、レイヤーのデータ状態表示（T87）を二重に出さないための判定に使う
// （MapView.tsx側のregionZoomTooWide算出・MapLayersPanel.tsx側の抑制の両方が参照する単一の
// 定義。片方だけ更新して食い違う、という改善計画の設計原則8違反を避けるため）。
// 改善計画T308: buildMapLayers()と同じ理由で関数化。テスト（axisLayers.test.ts、
// MapView.dataStatus.test.ts）からbuildRoadSurfaceSharedLayerIds(RAMP_AXES)として直接呼べる。
export function buildRoadSurfaceSharedLayerIds(rampAxes: readonly RampAxis[]): readonly MapLayerId[] {
  return [
    "roadType",
    "roadSurface",
    "designation",
    "tunnel",
    "oneway",
    // 改善計画T405/T423/T446: way_id→wind_drag_ratio/勾配配信層（評価軸としての風・勾配）も
    // 同じroad_surfaceタイル（ソース）を再利用する独立レイヤーのため、ズーム範囲外判定
    // （regionZoomTooWide）はここに含める。ただしデータ自体（wind_drag_ratio/勾配値）はタイルの
    // プロパティではなく別経路のfetchで来るため、T87のloading/empty/error状態表示
    // （useLayerDataStatus）の対象には含めていない（MapView.tsx: getLayerVisibility参照。
    // 改善計画T418で地図上チップは撤去しルート設定パネルへ移設したが、この対象外の判断
    // 自体は変更不要と判断しそのまま維持した）。勾配は改善計画T423で風と対称の機構として
    // 追加されたが、このリストへの追加が漏れたまま非対称になっていた（改善計画T446で解消）。
    "windAxis",
    "gradientAxis",
    // 二次軸rampレイヤー（T145b）も同じroad_surfaceタイルへ焼き込まれたプロパティを読む
    // （改善計画T292: car_stressもここに含まれるようになった）。
    ...rampAxes.map((axis) => axisMapLayerId(axis.axisId)),
  ];
}
