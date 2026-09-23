// 地図レイヤーのカタログ（単一ソース）。
//
// 地図上のチップ行とその▶パネル（MapOverlayControls）がこの配列を列挙して描画する。
// レイヤーを追加するときは、ここへ MapLayerDescriptor を1つ足せば、チップ・表示状態の既定値
// （`defaultOn`）・表示専用の凡例（`readOnlyLegend`）が揃う。画面側（features/map/view・
// MapOverlayControls）は変更しない。
//
// 地図に描く宣言（features/map/scene/groups/ の家族。絞り込める凡例は scene/legends.ts）は
// 別途必要で、**ここが1箇所では済まない**。書き忘れるとチップはONになり凡例も出るのに
// 地図には何も出ない。
//
// kind は「データの性質」による分類（static: 地域に固定で時間によって変わらないデータ
// [タイル配信系]／dynamic: 選択中ルートや時間によって変わるデータ）。静的データと動的データを
// 混同しない、という設計方針を表す。
//
// categoryはkind:"static"レイヤーのみが持つ中分類で、▶パネル（MapOverlayControls）の
// グループ見出しに使う。staticをflatな一覧のまま並べると、増えるほど見つけにくくなる
// ため、kindより一段細かい単位で分ける。区分は`MapLayerCategory`が正本で、並び順は
// `MAP_LAYER_CATEGORY_ORDER`が決める。例: 道路状態（道路の種類・路面の種類）、
// 交通・安全（事故・停止要因）、地形・土地、補給・施設。
// 補給・休憩ポイントを交通・安全へ含めないのは、安全・リスクの指標ではないため。
// 「自転車インフラ」の専用地図レイヤー・カテゴリは持たない。公開軸
// bicycle_infra_qualityがramp軸として地図レンズを自動で得る（axisLayers.ts）ため、
// 静的レイヤー側で重ねて持つ必要が無い。ramp軸は軸スタジオ由来のレイヤーとして
// この区分の外に置く（isAxisStudioLayer）。

import weatherScales from "@/types/generated/weather-scales.json";
import { mapDisplay } from "@/types/generated/mapDisplay";
import { primaryAttributes } from "@/types/generated/primaryAttributes";
import { LANDCOVER_TILE_MIN_ZOOM, ROAD_TILE_MIN_ZOOM } from "@/services/regionApi";
import { axisIconFor } from "./axisIconPalette";
import {
  AccidentIcon,
  ElevationIcon,
  HillshadeIcon,
  LandcoverIcon,
  OnewayIcon,
  RaindropIcon,
  RoadIcon,
  RoadSurfaceIcon,
  RouteIcon,
  ShieldIcon,
  StopPoiIcon,
  SupplyPoiIcon,
  TunnelIcon,
  WindIcon,
  type MapIconComponent,
} from "./icons";
import { legendKindList, type LegendEntry } from "./legendFilter";
import { LANDCOVER_PAINTED_CLASSES } from "./landcoverClasses";
import { PRECIPITATION_INTENSITY_LEVELS } from "./precipitationNowcast";
import { WIND_SPEED_LEGEND_LEVELS } from "./windLayer";
import { pointLegendAxes } from "@/features/map/scene/legends";
import {
  axisMapLayerId,
  dedicatedWayValueMapLayerId,
  type AxisMapLayerId,
  type DedicatedWayValueAxis,
  type DedicatedWayValueMapLayerId,
  type RampAxis,
} from "./axisLayers";

/** 一次属性を描くレイヤーの名前。**名前は源泉の一次属性の宣言が持つ**（同じものを画面で名付け直さない）。 */
function attributeLabel(attrId: (typeof primaryAttributes)[number]["attr_id"]): string {
  return primaryAttributes.find((attr) => attr.attr_id === attrId)!.label;
}

/** チップの説明文へ差し込む種別名の並び。**凡例と同じ宣言から作る**——説明文が別に
 * 数え上げると、種別を足したときに説明文だけが古くなる。 */
function pointKindList(role: string): string {
  const axis = pointLegendAxes().find((entry) => entry.layerId === role);
  return axis === undefined ? "" : legendKindList(axis.entries);
}

/** 地図に載るものの名前。**静的な一覧は源泉が持つ**（`domain/map_display.py`が一次属性から
 * 導く）——画面で並べ直すと、属性を1つ足したときに書き忘れても型が通る。軸スタジオ由来の
 * 軸は運用で増えるため実行時に決まり、ここには現れない。 */
export type MapLayerId = (typeof mapDisplay.layerIds)[number] | AxisMapLayerId | DedicatedWayValueMapLayerId;

// kindは「選択中ルートにひもづくデータか、地域に固定で選択候補に関係なく重ね描きする
// データか」を表す（dynamic=route、選択中候補が変わるたびに描き直す。static=それ以外、
// 一度追加したらvisibilityの切替だけで表示・非表示する）。「値が時間で変わるかどうか」は
// 別軸（dataNature、下記）で表す。降水ナウキャスト（precipitationNowcast）は値こそ
// 時々刻々変わるが、route選択とは無関係にstaticレイヤーと同じ「常設・visibility切替のみ」の
// 描画方式のためkind="static"のまま、dataNature="dynamic"で区別する。
type MapLayerKind = (typeof mapDisplay.layerKinds)[number];

// staticレイヤーの中分類。▶パネル（MapOverlayControls）の見出しに使う。dynamic（route）は
// 今のところ1種のみのため中分類を持たない（category未指定）。
export type MapLayerCategory = (typeof mapDisplay.layerCategories)[number]["key"];

// カテゴリの表示順・見出し文言の単一ソース。MapOverlayControls.tsxが参照する
// （UI語彙のカタログ集約、片側importで揃える）。
export const MAP_LAYER_CATEGORY_ORDER: readonly MapLayerCategory[] = mapDisplay.layerCategories.map(
  (category) => category.key,
);

/** 生データ（OSM/警察庁の生タグ・生座標をそのまま分類表示）か、複数要因から計算した
 * 推定指標（合成）か、時刻で内容が変わる動的データか。表示グルーピングの単位ではなく、
 * (a) `isAxisStudioLayer`が"composite"を「軸スタジオ由来のため地図UIチップには出さない」
 * 判定の入力に使う、(b) MapOverlayControls.tsxが"dynamic"（降水ナウキャスト等、帯単位の
 * 絞り込み機能を持たないレイヤー）を▶パネルの内訳から除外する判定に使う、
 * の2点で使われる。 */
export type MapLayerDataNature = (typeof mapDisplay.layerDataNatures)[number];

/** 絞り込めない表示専用の凡例の1ブロック。
 *
 * 配信元が色を焼き込んだラスタ等、カテゴリ単位で選べないレイヤーが持つ。絞り込める
 * 凡例（`hiddenKeys`と保存先の`axisId`を持つ）はここではなく`scene/legends.ts`が出す
 * ——型の上で分けてあるので、ここへ絞り込めるつもりの凡例を書いても黙って読み専用にはならない。 */
interface ReadOnlyLegendBlock {
  /** ブロックの見出し。単一ブロックのレイヤーは空文字列。 */
  label: string;
  legend: readonly LegendEntry[];
}

/** 表示専用凡例の`LegendEntry.filter`に入れるダミー。この凡例は描画へ適用されないため
 * 式自体に意味が無く、一致しない式を入れてある。 */
const UNUSED_LEGEND_FILTER: unknown[] = ["==", 1, 0];

function readOnlyEntries(levels: readonly Omit<LegendEntry, "filter">[]): LegendEntry[] {
  return levels.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER }));
}

/** そのレイヤーの絵がどこから来るか。
 *
 * 取得状態（読み込み中・空・失敗）の算出はここから導く。同じタイルを読むレイヤーが
 * 同時に空・失敗になるのが正しい振る舞いなため、複数のレイヤーが同じ値を名乗る。
 *
 * `ownFetch`はMapLibreのソースを経由せず自前のJSで取りに行くもの（動的気象レイヤー・
 * ルート）。MapLibreのソースイベントは外部フェッチの待ち時間・失敗を観測できないため、
 * それぞれのフェッチ自身が状態を出す。 */
export type MapLayerDataSource = (typeof mapDisplay.layerDataSources)[number];

/** 地図上チップ（MapOverlayControls.tsx）最上位の3グループ。「対象（何についての情報か）」で束ねる。
 * - road（道路）: 道路の純粋な属性のみ（道路種別・路面種別・トンネル・一方通行）
 * - environment（環境）: 標高／降水ナウキャスト・風（矢印）・雷・竜巻等の面レイヤー
 * - spot（スポット）: 停止要因POI・補給POI・事故地点等の点レイヤー
 * 評価軸（ramp軸・専用way値配信軸）はこの3グループのどれにも属さず、地図上チップとして
 * 出さない——評価軸はルートの有無に応じて「重み配分を検討する材料」「生成済みルートを
 * 分析する材料」と役割が変わる道具であり、道路・環境・スポットのようにルートの状態に
 * 関係なく意味が一定な「地図そのものの見え方」設定とは性質が異なるため。評価軸の色分けは
 * ルート未確定時はルート設定パネル（RouteSettingsPanel.tsx）の軸ごとの行から、ルート
 * 確定後は「地図の色分け」（RouteAxisProfile.tsx、routeStyleModes.ts参照）から、
 * それぞれ起動する。軸スタジオ由来のレイヤー（ramp軸・専用way値配信軸）を地図UIの3グループ
 * 判定から除外する判定は`isAxisStudioLayer`（下記）が担う。 */
export type MapOverlayGroup = (typeof mapDisplay.overlayGroups)[number]["key"];

export const MAP_OVERLAY_GROUP_LABELS: Readonly<Record<string, string>> = Object.fromEntries(
  mapDisplay.overlayGroups.map((group) => [group.key, group.label]),
);
/** チップの表示順。**源泉の並びがそのまま並び順**（画面は並べ替えない）。 */
export const MAP_OVERLAY_GROUP_ORDER: readonly MapOverlayGroup[] = mapDisplay.overlayGroups.map((group) => group.key);

/** 種別が属するグループ。種別を1つ足すときは源泉の側で所属も決まる。 */
const GROUP_BY_CATEGORY: Readonly<Record<string, MapOverlayGroup>> = Object.fromEntries(
  mapDisplay.layerCategories.map((category) => [category.key, category.group]),
);

/** 軸スタジオ由来のレイヤーか。ramp軸（dataNature==="composite"）・専用way_id→動的値
 * 配信層を持つ軸（`axisStudioLayer`、buildMapLayersが軸カタログから生成する際に立てる）は、
 * 地図上チップ（MapOverlayControls.tsx）がこの判定を使って
 * これらのレイヤーを描画対象から除外する（mapOverlayGroupForが返すundefinedは
 * 「route等、単独チップとして出す」ものと「軸スタジオ由来のため地図UIには一切出さない」
 * ものの2種類が混在するため、区別に使う専用の判定）。
 *
 * 判定をレイヤーIDの集合ではなく記述子自身のフラグで行うのは、実行時カタログ（軸スタジオで
 * 新規公開された軸を含む）から生成した記述子と、ビルド時静的json由来のID集合とが食い違うと
 * 、新規軸だけが地図チップへ漏れ出るため。 */
export function isAxisStudioLayer(layer: {
  id: MapLayerId;
  dataNature?: MapLayerDataNature;
  axisStudioLayer?: boolean;
}): boolean {
  return layer.axisStudioLayer === true || layer.dataNature === "composite";
}

/** レイヤー1件が属するMapOverlayGroupを判定する。category/
 * dataNatureの既存フィールドだけで機械的に判定できるが、軸スタジオ由来のレイヤー
 * （isAxisStudioLayer、ramp軸・専用way値配信軸）は明示的に対象外（undefined）にする——
 * category値だけを見ると「道路」「スポット」「環境」のいずれかに紛れ込んでしまうため
 * （例: category="trafficSafety"はaccidents等と同じ値）、category判定の
 * 前に必ず除外する。route等、どのグループにも属さないレイヤーもundefinedを返す。 */
export function mapOverlayGroupFor(layer: {
  id: MapLayerId;
  category?: MapLayerCategory;
  dataNature?: MapLayerDataNature;
  axisStudioLayer?: boolean;
}): MapOverlayGroup | undefined {
  if (isAxisStudioLayer(layer)) return undefined;
  if (layer.category === undefined) return undefined;
  return GROUP_BY_CATEGORY[layer.category];
}

export interface MapLayerDescriptor {
  id: MapLayerId;
  /** サイドバーのセクション見出し・条件サマリ・チップのtitleで使う正式名称 */
  label: string;
  /** 地図上のアイコンチップ下に出す短縮表記。未指定ならlabelをそのまま使う。
   * チップ幅は文字数に連動するため、
   * 長いlabelはここで短くしてチップ幅を他レイヤーと揃える。正式名称は引き続きlabel
   * （サイドバー見出し・条件サマリ・チップのtitle）で示すため、意味の省略は許容する。 */
  chipLabel?: string;
  kind: MapLayerKind;
  /** 地図上チップ・設定パネルの行頭に出すアイコン（`icons.tsx`）。
   *
   * **省略できない。** ここを持たずに描画側の対応表で引く形だと、レイヤーを足した人が
   * 表を忘れても汎用フォールバックのアイコンで描けてしまい、他のレイヤーと見分けが
   * 付かないまま出続ける。軸カタログ由来のレイヤーは軸自身が持つ`iconId`から引く
   * （`axisIconFor`）。 */
  icon: MapIconComponent;
  /** 絵の出所（`MapLayerDataSource`）。
   *
   * **省略できない。** 描画側の対応表で引く形だと、表へ書き忘れたレイヤーは
   * 取得状態を持たないままになり、チップの状態ドットが永久に出ない。 */
  dataSource: MapLayerDataSource;
  /** 絞り込めない表示専用の凡例。▶を開いたときの中身になる。
   *
   * 省略したレイヤーは、絞り込める凡例（`scene/legends.ts`）か、画面の状態から
   * 組み立てる凡例（ルートのレンズ・災害の要素トグル）を持つ。 */
  readOnlyLegend?: readonly ReadOnlyLegendBlock[];
  /** 軸スタジオの軸から生成したレイヤーか（専用way値配信軸）。ramp軸は
   * dataNature==="composite"で同じ判定を受けるためこのフラグを持たない（isAxisStudioLayer参照）。 */
  axisStudioLayer?: boolean;
  /** 地図上チップ・サイドバーどちらの最上位グルーピング（mapOverlayGroupFor）も、
   * これ自体（`MapLayerCategory`の値）を入力の一部として
   * 使う。合わせてサイドバーの表示順（MAP_LAYER_CATEGORY_ORDER）・地図上チップの
   * 「道路」「環境」「スポット」各グループ内のトピック別小見出しにも使う。
   * kind:"static"のレイヤーのみ持つ（dynamicは今のところroute1種のみのため不要）。 */
  category?: MapLayerCategory;
  /** 生データか推定指標（合成）か時刻で変わる動的データか（MapLayerDataNature参照）。
   * isAxisStudioLayerが"composite"を「軸スタジオ由来のため地図UIチップには出さない」
   * 判定に使う。省略時は"raw"扱い（大半のレイヤーは生タグ・生座標の分類表示のため、
   * 明示するのは合成/動的側のみで足りる）。 */
  dataNature?: MapLayerDataNature;
  /** ONにすると何が表示されるかの短い説明（チップのtitleに使う） */
  description: string;
  /** 地図上チップ（MapOverlayControls）の「表示する項目を選ぶ」パネルで、項目の情報
   * アイコンから出す説明文。descriptionより詳しい判定基準・注意点を書く場所
   * （UI語彙のカタログ集約）。 */
  panelHint?: string;
  /** 利用者の操作を待たずに既定で表示するか。**性質で決める**——防災級の情報は、予兆が
   * 出てからチップをONにするのでは手遅れになるため、チップは持たせたまま既定表示にする。
   * 省略時はOFF（明示的にONにして初めて出る、という地図レイヤーの原則。初期表示から
   * 地図を覆うと視界を圧迫する。design-principles.md「UI仕様」）。
   * `buildDefaultLayerVisibility`がこの宣言から初期値を導く。 */
  defaultOn?: boolean;
  /** 配信元のタイルがこのズーム未満では要求されない（ONにしても地図には何も出ない）。
   * 宣言すると、ズーム不足の間チップに案内を出し凡例を空にする扱いが自動で付く
   * （`tileZoomTooWideLayerIds`）。省略時は判定しない——広いズームでも出るもの
   * （国土地理院のラスタ等）はここを持たない。 */
  tileMinZoom?: number;
}

/** 収録年の言い方。連続していれば範囲で、飛んでいれば並べて出す。
 *
 * 年そのものは取込の宣言（backendの`source_runs.profile`）が正本で、
 * `GET /api/axis-catalog`の`accident_years`が運ぶ。**ここで年を書かない**——
 * 文字列で持つと取り込み直したときに黙って食い違う。空のときは範囲に触れない。 */
function coverageYearsLabel(years: readonly number[]): string {
  if (years.length === 0) return "";
  const sorted = [...years].sort((a, b) => a - b);
  if (sorted.length === 1) return `${sorted[0]}年`;
  const continuous = sorted.every((year, index) => index === 0 || year === sorted[index - 1] + 1);
  return continuous ? `${sorted[0]}〜${sorted[sorted.length - 1]}年` : `${sorted.join("・")}年`;
}

export function buildMapLayers(
  rampAxes: readonly RampAxis[],
  dedicatedAxes: readonly DedicatedWayValueAxis[],
  accidentYears: readonly number[] = [],
): readonly MapLayerDescriptor[] {
  // 取れていないときは年に触れない（取得前に既定の年を出すと、それが正しいように見える）。
  // 収録範囲は取込プロファイルのbboxが決めるため、説明文では名乗らない——地図はデータの
  // ある所にしか点を打たないので、範囲は見れば分かる。
  const accidentCoverage = coverageYearsLabel(accidentYears);
  return [
    {
      id: "elevation",
      dataSource: "gsiRelief",
      icon: ElevationIcon,
      // ルート指標の「獲得標高」と紛らわしいため、地図レイヤー側は「標高図」と呼び分ける
      label: attributeLabel("elevation"),
      kind: "static",
      category: "terrain",
      description: "国土地理院の色別標高図を重ねる",
      // ラスタタイルのため他レイヤーのような凡例ベースの絞り込みを持たず、操作はON/OFFだけ。
      panelHint: "国土地理院の色別標高図を重ねる",
    },
    {
      id: "hillshade",
      dataSource: "gsiTerrain",
      icon: HillshadeIcon,
      // 「標高図」が何mかを塗るのに対し、こちらは坂の在りかだけを塗る。名前もその違いで
      // 分ける——どちらも「標高」と呼ぶと、ONにして何が出るのかが区別できない。
      label: "起伏",
      kind: "static",
      category: "terrain",
      description: "斜面に陰影を付ける[平地は塗らない]",
      // 陰影のため凡例ベースの絞り込みを持たず、操作はON/OFFだけ。
      panelHint: "国土地理院の標高データから斜面の陰影を作る。平らな所は塗らないため、下の地図の色が残る",
    },
    {
      id: "landcover",
      // 色・表示名はbackendのレジストリ（domain/landcover.py: LANDCOVER_CLASSES）由来の
      // 生成物がそのまま単一の情報源で、地図タイルの塗りと同じ値を使う。
      readOnlyLegend: [
        {
          label: "",
          legend: LANDCOVER_PAINTED_CLASSES.map((cls) => ({
            key: cls.percentField,
            label: cls.label,
            color: cls.color,
            filter: UNUSED_LEGEND_FILTER,
          })),
        },
      ],
      dataSource: "landcoverRaster",
      icon: LandcoverIcon,
      tileMinZoom: LANDCOVER_TILE_MIN_ZOOM,
      // 塗るのは自然被覆だけ（建物は塗らない、domain/landcover.py: LANDCOVER_CLASSES）。
      // 「土地被覆」のままだと、都心でONにしても何も出ないことが名前と食い違う。
      label: attributeLabel("landcover"),
      // 配信元の10m画素をそのまま塗った面。道路の周囲がどう使われているか（`way_landcover`が
      // 道1本ぶんへ畳んでいる元のデータ）を、畳む前の1画素1クラスのまま見るためのもの。
      description: "周囲の緑・水辺・農地を面で重ねる[建物は塗らない]",
      kind: "static",
      category: "terrain",
      panelHint:
        "衛星画像から分類した10m四方ごとの土地の使われ方です。1区画に1種類だけが入るため、" +
        "評価軸が使う「道路の周囲100mの割合」とは違い、混ざらずそのまま見えます。" +
        "建物は塗りません——市街地では画素のほとんどがそのクラスになり、地図が単色で" +
        "覆われるだけになるためです（建物があることは基礎地図から分かります）。" +
        "区間インスペクタの内訳には建物も出ます。",
    },
    {
      id: "highway",
      dataSource: "roadTiles",
      icon: RoadIcon,
      tileMinZoom: ROAD_TILE_MIN_ZOOM,
      label: attributeLabel("highway"),
      chipLabel: "道路種別",
      kind: "static",
      category: "roadCondition",
      description: "道路種別を線の太さで表示[幹線道路ほど太く・自転車専用道路ほど細く]",
      // 道路種別ごとの濃淡（分類と色は`scene/groups/roadLines.ts`が宣言する）。
      // 「路面の種類」がONの間はそちらの色分けが優先されるため、この濃淡は「路面の種類」が
      // OFFのときだけ見える。
      panelHint:
        "太さに加え、「路面の種類」レイヤーがOFFの間は種別ごとの濃淡[幹線道路ほど濃く・" +
        "自転車専用道路ほど薄く]でも表示します。「路面の種類」がONのときは、色はそちらの" +
        "配色を優先します。",
    },
    {
      id: "surface",
      dataSource: "roadTiles",
      icon: RoadSurfaceIcon,
      tileMinZoom: ROAD_TILE_MIN_ZOOM,
      label: attributeLabel("surface"),
      chipLabel: "路面",
      kind: "static",
      category: "roadCondition",
      description: "路面の材質を色で表示[アスファルト・砂利・土など]",
    },
    {
      // トンネル（一次属性、OSMのtunnelタグ）。road_surfaceソースの
      // 独立レイヤー。
      id: "tunnel",
      dataSource: "roadTiles",
      icon: TunnelIcon,
      tileMinZoom: ROAD_TILE_MIN_ZOOM,
      label: attributeLabel("tunnel"),
      kind: "static",
      category: "roadCondition",
      description: "トンネル区間[OSMのtunnelタグ]を色分け表示",
      panelHint:
        "OSMのtunnelタグが該当する区間です。「夜間」軸[推定グループ]の材料の1つとして、" +
        "夜間の危険度の判定に使われます。night軸自体も専用レイヤーを持ちます。",
    },
    {
      // 一方通行（一次属性）。一方通行の逆方向はグラフの読み出し
      // （backend/app/infrastructure/road_graph_repository.py）でEdge自体が作られないため探索の
      // 正しさには無関係で、評価軸（route_preference）にも組み込まない表示専用の一次属性。
      // 上下線が分かれた道の片側はここへ出さない（道路としては双方向で、逆方向は数m隣に
      // ある。判定はbackend側、`way_materials.divided`）。
      id: "oneway",
      dataSource: "roadTiles",
      icon: OnewayIcon,
      tileMinZoom: ROAD_TILE_MIN_ZOOM,
      label: attributeLabel("oneway"),
      kind: "static",
      category: "roadCondition",
      description: "来た道を戻れない区間を色分け表示",
      panelHint:
        "その向きにしか通れない区間です。上下線が分かれているだけの道（逆方向が数m隣にある）" +
        "は除いてあります。ルート探索は既に一方通行の向きを守っており（逆走経路自体が" +
        "生成されません）、このレイヤーは表示のみで評価には影響しません。",
    },
    {
      id: "stop_poi",
      dataSource: "poiTiles",
      icon: StopPoiIcon,
      label: attributeLabel("stop_poi"),
      kind: "static",
      category: "trafficSafety",
      tileMinZoom: ROAD_TILE_MIN_ZOOM,
      description: `${pointKindList("stop_poi")}の位置を種別ごとに色分け表示`,
      panelHint:
        `${pointKindList("stop_poi")}の位置です。評価の「停止密度」軸が近傍のこれらを` +
        "数えて算出しているものを、種別ごとの色分けで直接確認できます。",
    },
    {
      id: "supply_poi",
      dataSource: "poiTiles",
      icon: SupplyPoiIcon,
      label: attributeLabel("supply_poi"),
      // 地図上のチップ幅は文字数に連動する（他レイヤーは4文字以内）ため、
      // 「補給・休憩」（読点込み5文字）だとこのチップだけ幅が広がってしまう。読点を省いた
      // 「補給休憩」（4文字）に短縮（正式名称は引き続きlabelの「補給・休憩ポイント」）。
      chipLabel: "補給休憩",
      kind: "static",
      category: "amenity",
      tileMinZoom: ROAD_TILE_MIN_ZOOM,
      description: `${pointKindList("supply_poi")}の位置を種別ごとに色分け表示`,
      // 実店舗とどれだけ合っているかの目安として、backend/scripts/measure_poi_freshness.pyで
      // OSM側の最終編集日時を計測している。コンビニは関東全域で直近2年以内の編集が62.4%と
      // 明確に新しいが、自販機・トイレ・給水・駐輪場は5年以上未編集が58〜59%と高く、
      // 閉店・撤去にデータが追いついていないリスクが相対的に高い。取込自体は5種すべて
      // 対象にしつつ、利用者へは正直にこの差を伝える（コンビニを優先的な目安、他4種は
      // 参考程度に）。
      panelHint:
        `${pointKindList("supply_poi")}の位置です。自販機は飲み物が買えると分かって` +
        "いるものだけを「飲料自販機」として出し、売っているものが分からないものは薄い色の" +
        "「自販機(中身不明)」として区別します（たばこ・切符の機械は出しません）。" +
        "コンビニはOSMデータの更新が比較的新しく目安として使いやすい一方、自販機・トイレ・" +
        "給水・駐輪場は閉店・撤去にデータが追いついていないことがあります。現地の状況と" +
        "異なる場合があることをご留意ください。",
    },
    {
      id: "accident_point",
      dataSource: "accidentTiles",
      icon: AccidentIcon,
      label: attributeLabel("accident_point"),
      chipLabel: "事故",
      kind: "static",
      category: "trafficSafety",
      description: `警察庁交通事故統計オープンデータ${accidentCoverage ? `[${accidentCoverage}]` : ""}の発生地点を表示`,
      panelHint:
        `警察庁が公開する交通事故統計オープンデータ[本票${accidentCoverage ? `、${accidentCoverage}` : ""}]の` +
        "発生地点です。死亡事故（事故後24時間以内）は円を大きく表示します。",
    },
    // 二次軸の汎用rampレイヤー（「事実はタイルに、解釈はクライアントに」）。実行時の
    // `GET /api/axis-catalog`が配るkind="ramp"軸から自動生成する。新しい軸は軸スタジオでの
    // 公開＋タイルへの事実焼き込みだけでここへ現れる（このファイルの編集は不要）。
    // 凡例（段階・色・絞り込み）は`scene/legends.ts`と`axisLayers.ts: buildAxisRampLegend`が
    // 他の静的レイヤーと同じ仕組みで提供する。
    ...rampAxes.map((axis): MapLayerDescriptor => ({
      id: axisMapLayerId(axis.axisId),
      dataSource: "roadTiles",
      icon: axisIconFor(axis.iconId),
      label: axis.label,
      chipLabel: axis.chipLabel,
      kind: "static",
      category: axis.category as MapLayerCategory,
      // ramp軸は定義上「一次属性（tile_inputs）を重み付けで合成した二次軸スコア」
      // （axisLayers.ts冒頭コメント参照）のため、常にcomposite（生データではない）。
      dataNature: "composite",
      // 路面タイルへ焼き込んだ値を読むため、世代が届くまでは他の路面系と同じく描けない。
      // 単位が定まらない軸（unit=""）は空の[]を出さない。
      description: `${axis.label}${axis.unit ? `[${axis.unit}]` : ""}をway単位の事前集計から色分け表示`,
      panelHint: axis.panelHint,
    })),
    {
      // 気象庁 降水ナウキャスト。実況（過去〜現在、5分毎）と60分先までの短時間予測を
      // ラスタタイルで重ね描きする。60分より先は、風と共有の格子点マップ由来の降水量を、
      // 格子セルを降水強度に応じた色で塗るgridFill表現（precipitationNowcast.ts:
      // precipitationRenderPayload）へ内部で
      // 切り替わる。表示・トグルは1つのまま、内部だけ時間によって使い分ける。他の静的
      // レイヤーと異なり、表示中の時刻を地図上の時刻スライダー（風と共有の1本のスライダー、
      // layerVisibility.precipitationNowcast/windVectorのどちらかがONの間だけ表示、page.tsx参照）
      // で切り替えられる。
      id: "precipitationNowcast",
      // 線状降水帯予測マップは「降水」チップの傘下のソースとして統合されているため、
      // 専用の凡例ブロックをここへ並べる（実データはriskMap.tsが単一の情報源）。
      readOnlyLegend: [
        {
          label: "",
          legend: readOnlyEntries(PRECIPITATION_INTENSITY_LEVELS),
        },
        {
          label: "線状降水帯予測マップ（現在〜3時間先のみ）",
          // 色は配信元タイルの実際の塗り色そのもの（源泉が宣言する）。危険度の段の色で
          // 代用すると、近いだけの別の色になり、地図の塗りと凡例が黙ってずれる。
          // 予測領域は格子単位で塗られ矩形に見えるため、形状も書いておく——降水ナウキャストの
          // 細かい雨域と重なると、矩形の塗りが描画不具合のように見える。
          legend: [
            {
              key: "linearRainband",
              label: "今後3時間以内に大雨のおそれ（矩形の予測領域）",
              color: weatherScales.linear_rainband_color,
              filter: UNUSED_LEGEND_FILTER,
            },
          ],
        },
      ],
      dataSource: "ownFetch",
      icon: RaindropIcon,
      label: "降水ナウキャスト",
      chipLabel: "降水",
      kind: "static",
      category: "weather",
      dataNature: "dynamic",
      description:
        "気象庁の降水ナウキャスト・降水短時間予報・延長予報・線状降水帯予測マップを重ねて表示" +
        "[実況〜60分先は5分刻み、60分〜15時間先は気象庁の降水短時間予報、以降は気象庁MSMの" +
        "予報1時間刻み。線状降水帯予測マップは現在〜3時間先の間だけ追加で重畳]",
      panelHint:
        "気象庁の高解像度降水ナウキャストです。ONにすると地図上に時刻スライダーが現れ、" +
        "実況（直近）から60分先までの雨雲の分布を切り替えて確認できます。60分より先は、" +
        "同じ気象庁の降水短時間予報へ自動的に切り替わり、15時間先まで" +
        "確認できます——こちらは実況の外挿ではなく数値予報モデルによる予測のため、先に" +
        "なるほど不確実性が増します。15時間より先は、風と同じ仕組み（気象庁MSMの" +
        "格子点予報）による、格子を降水強度に応じた色で塗る延長予報表示へさらに切り替わり、" +
        "1〜3日先まで確認できます（降水短時間予報よりも粗い5kmメッシュのモデル予報です）。加えて、現在〜3時間先の" +
        "間だけ、気象庁の線状降水帯予測マップを重ねて表示します（今後3時間以内に大雨の" +
        "おそれがある領域を赤で示すもので、予測は格子単位のため矩形に見えます。" +
        "今まさに発生している線状降水帯の雨域を示すものではありません）。" +
        "非公式の内部APIを利用している実況・60分先までの" +
        "部分・線状降水帯予測マップは、取得に失敗することがあります。",
    },
    {
      // 風の矢印。固定格子点（バックエンド/api/weather/wind-grid。範囲と間隔はbackendの
      // `domain/wind_grid.py`が決める）を
      // 気象庁MSM（ローカルへ同期した.omファイル）からサンプリングする自前実装のため、
      // GPLv2ライブラリ・気象庁の非公式配信のどちらにも依存しない。
      id: "windVector",
      // 矢印（風速そのもの、向きに依存しない）の配色専用で、道路の色分け（風の評価軸、
      // 走行方位に対する向かい風/追い風）とは別の配色系統のため、「地図の色の凡例」との
      // 混同を避けて「矢印（風速）」と明示する。
      readOnlyLegend: [
        {
          label: "矢印（風速）",
          legend: readOnlyEntries(WIND_SPEED_LEGEND_LEVELS),
        },
      ],
      dataSource: "ownFetch",
      icon: WindIcon,
      label: "風（矢印）",
      chipLabel: "風",
      kind: "static",
      category: "weather",
      dataNature: "dynamic",
      description: "気象庁MSMの風向・風速予報を矢印で表示[1〜3日先まで]",
      panelHint:
        "気象庁MSM（メソ数値予報モデル、5kmメッシュ）による風向・風速を格子点で矢印表示します。" +
        "矢印の向きが風向、長さ・太さ・色の濃淡が風速の強さを表します。ごく弱い風の地点は" +
        "矢印を表示しません。ONにすると地図上に時刻スライダーが現れ、1時間刻みで切り替えられます" +
        "（先まで見られる範囲は配信中の予報の長さによって1〜3日の間で変わります）。走行方位に対する向かい風/追い風の強さは、地図上部中央の" +
        "「レンズ」で風の評価軸を選ぶと、道路の色分けとして別途確認できます。",
    },
    // 専用のway_id→値配信レイヤーを持つ軸（`dedicated_way_value_layer=true`、現状: 風・勾配）。
    // ramp軸と同じく軸カタログから自動生成する。label/chipLabel/panelHintはこの記述子が
    // 地図UIに現れない（isAxisStudioLayer）ため実際には表示されないが、他の記述子と同じ
    // 型を満たすため軸自身のデータから埋める（軸ごとの手書き文言をここへ持たない）。
    // このエントリは地図の組み立てに実際に使う——情報源
    // （`dataSource`）をここから引く。無いと
    // そのレイヤーを描こうとした時点で落ちる。
    // ズーム不足の案内（`tileZoomTooWideLayerIds`）の対象には入らない。案内の出し先は
    // チップで、このレイヤーはチップを持たないため出す場所が無い（同じタイルを共有する
    // ので実際には一緒に消えるが、それは道路のチップ側の案内で分かる）。
    ...dedicatedAxes.map((axis): MapLayerDescriptor => ({
      id: dedicatedWayValueMapLayerId(axis.axisId),
      dataSource: "roadTiles",
      // 地図上チップとして描かれない（`axisStudioLayer`）ため実際には使われないが、
      // 記述子の型を満たすために汎用のものを持つ。
      icon: axisIconFor(undefined),
      label: `${axis.label}（評価軸）`,
      chipLabel: axis.chipLabel,
      kind: "static",
      dataNature: "dynamic",
      axisStudioLayer: true,
      description: `${axis.label}を視界内の全道路へ一律に線色分け表示`,
      panelHint: axis.panelHint,
    })),
    {
      // 災害（雷ナウキャスト・竜巻発生確度ナウキャスト・雷放電位置データ・キキクル等）。
      // 配下をまとめて1つのチップでON/OFFし、名前付きソースとして同時に描画する。雷・竜巻・落雷は時刻スライダーに連動し、
      // キキクルは「現在の危険度」単一値のみの配信のため連動しない（riskMap.ts参照）。
      // 「回避一択」の危険のため評価軸には組み込まず表示のみを行う。
      id: "disaster",
      dataSource: "ownFetch",
      icon: ShieldIcon,
      label: "災害",
      chipLabel: "災害",
      kind: "static",
      category: "disaster",
      dataNature: "dynamic",
      // 他の気象レイヤーと違い既定ONにする。**危険度が出ている間は広い範囲が塗られ、
      // 他の面レイヤー（緑と水・標高図）は完全に覆われる**（注意報が出ている状態で地図
      // 全面が黄緑になり、基礎地図の色も読めなくなる）。危険度ゼロの領域は配信元のタイルが
      // 透明なので影響が出るのは警戒度が上がっている間だけで、そのときは防災の情報を
      // 優先する。利用者は災害チップをOFFにすれば戻せる。
      defaultOn: true,
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
      // 危険度の読み方。配信元が色を焼き込んだ画像なので絞り込めない。キキクル4種は同じ段を使う。
      readOnlyLegend: [
        { label: "キキクル（土砂災害・大雨・浸水・洪水）", legend: readOnlyEntries(weatherScales.risk_levels) },
        { label: "雷ナウキャスト（活動度）", legend: readOnlyEntries(weatherScales.thunder_activity) },
        { label: "竜巻発生確度ナウキャスト", legend: readOnlyEntries(weatherScales.tornado_potential) },
      ],
    },
    {
      id: "route",
      dataSource: "ownFetch",
      icon: RouteIcon,
      label: "ルート",
      kind: "dynamic",
      description: "選択中ルート沿いの情報[風・勾配・路面・総合難易度]を色分け表示",
      // 候補を出したら見えている必要がある（探索の結果そのもの）。
      defaultOn: true,
    },
  ];
}

/** 最上位グループを同時に開けておける数。
 *
 * 開いたグループのメンバーはチップ列へ縦に積まれるため、**開くほど地図が縦に隠れる**
 * （375×812では、すべて畳んだ状態で画面の縦の23%、1グループ開くと54%、すべて開くと72%を占める）。
 * 主用途が走行中のスマホであることを踏まえ、1つに絞る——レイヤーを足したときに伸びるのは
 * そのグループの中だけになり、グループが増えても上限は動かない。
 *
 * 並べ方をここで決めるのは、チップ列の中身がレイヤーカタログから導かれるため
 * （`buildMapLayers`・`mapOverlayGroupFor`）。描画する側に持たせると、カタログを増やした
 * 人がこの制約に気づけない。 */
export const MAP_OVERLAY_MAX_EXPANDED_GROUPS = 1;

export type MapLayerVisibility = Record<MapLayerId, boolean>;

/** チップ下に出す、ズーム不足の案内。 */
export const TILE_ZOOM_TOO_WIDE_NOTICE = "ズームインすると表示されます";

/** チップ下に出す、タイル世代が届いていないときの案内。
 *
 * この状態では地図に何も描けない（世代の違う中身をブラウザのキャッシュへ残さないため、
 * 届くまでソースを作らない）。**何も出ないこと自体は正しい挙動**で、直すべきなのは
 * 「出ない理由が画面のどこにも無い」ことだけである。 */
export const TILE_VERSIONS_MISSING_NOTICE = "配信情報を取得できず表示できません";

/** 世代（`GET /api/axis-catalog`の`tile_versions`）が届くまで要求できない情報源。
 *
 * 世代は配信元の性質なので**情報源の側で宣言する**。レイヤーごとにも宣言させると
 * 同じことを2回言うことになり、ずれたときに「描けていないのにチップが黙る」。
 * 国土地理院のラスタ・土地被覆ラスタは世代を持たない別系統のため含まない。 */
const TILE_VERSION_GATED_SOURCES: ReadonlySet<MapLayerDataSource> = new Set(["roadTiles", "accidentTiles", "poiTiles"]);

/** タイル世代が届くまで何も描けないレイヤーのid。
 *
 * 軸を空で呼ばない——ramp軸は路面タイルへ焼き込んだ値を読むため、軸スタジオで公開が増えれば
 * そのまま対象になる。判定は記述子が宣言する情報源から導き、ここにidを並べない。 */
export function tileVersionGatedLayerIds(rampAxes: readonly RampAxis[]): readonly MapLayerId[] {
  return buildMapLayers(rampAxes, [])
    .filter((layer) => TILE_VERSION_GATED_SOURCES.has(layer.dataSource))
    .map((layer) => layer.id);
}

/** そのズームではタイルが要求されず、ONにしても何も出ないレイヤーのid。
 *
 * 軸を空で呼ぶ——軸スタジオ由来のレイヤーは地図上チップを持たず、案内の出し先が無い
 * （同じタイルを共有するため実際には消えるが、それは道路のチップ側の案内で分かる）。 */
export function tileZoomTooWideLayerIds(zoom: number): readonly MapLayerId[] {
  return buildMapLayers([], [])
    .filter((layer) => layer.tileMinZoom !== undefined && zoom < layer.tileMinZoom)
    .map((layer) => layer.id);
}

/** 地図チップ・サイドバーからON/OFFできるレイヤーの既定値を、記述子の`defaultOn`から導く。
 *
 * 軸スタジオ由来のレイヤー（ramp軸・専用way値配信軸）のキーは持たない——表示はレンズ
 * （axisVisibility）だけが決めており、ON/OFFの入口が地図チップにもサイドバーにも無い
 * （`isAxisStudioLayer`）。そのため軸を空で呼ぶ。 */
export function buildDefaultLayerVisibility(): MapLayerVisibility {
  return Object.fromEntries(
    buildMapLayers([], []).map((layer) => [layer.id, layer.defaultOn === true]),
  ) as MapLayerVisibility;
}

// レイヤーごとのデータ取得状態。「表示OFF」「ズーム範囲外」（`tileZoomTooWideLayerIds`）は
// どちらも既存の案内があるが、タイル取得失敗とそのレイヤーの対象データが0件の場合を
// 区別する表示に使う。表示ONかつ正常時（既知件数のデータが描画できている状態）は
// undefined（=キー自体を持たない）とし、特別な表示を出さない。MapView.tsxの
// sourcedata/sourcedataloading/errorイベントから算出する。
export type LayerDataStatus = "loading" | "empty" | "error";
export type LayerDataStatusByLayer = Partial<Record<MapLayerId, LayerDataStatus>>;

export const LAYER_DATA_STATUS_LABELS: Record<LayerDataStatus, string> = {
  loading: "読み込み中です",
  empty: "この範囲に表示できるデータがありません",
  error: "データの取得に失敗しました。しばらくしてから再読み込みしてください",
};

/** loading/error/payloadの有無からLayerDataStatusを1つ決める（エラー中 > 読込中 > 読込済み
 * だが値なし。正常時はundefined＝キー自体を持たない）。実際の外部フェッチが自前のJSコードで
 * 完結し、結果を`map.getSource(id).setData(...)`等で流し込むだけのレイヤー（MapLibreの
 * sourcedata/errorイベントを経由しない、`computeLayerDataStatus`の対象外）が共通して使う。
 *
 * `hasFetched`は「一度でも取得を試みて完了したか」。まだ取りに行っていない間を`"empty"`
 * （＝「この範囲に表示できるデータがありません」）にすると、レイヤーを有効化した直後や、
 * 配線ミスでフェッチ自体が走っていない状態が「データが無い」と読めてしまう。`"empty"`は
 * 上記のとおり「読込済みだが値なし」だけを指す。 */
export function deriveFetchLayerStatus(
  loading: boolean,
  error: string | null,
  hasPayload: boolean,
  hasFetched: boolean,
): LayerDataStatus | undefined {
  if (error) return "error";
  if (loading) return "loading";
  if (!hasFetched) return undefined;
  if (!hasPayload) return "empty";
  return undefined;
}
