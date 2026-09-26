// 地図レイヤーのカタログ。地図のチップとその▶パネルがこの並びを列挙して描く。種別・情報源・性質・既定の表示は
// 源泉（backendの`domain/map_display.py`）が宣言し、ここは見せ方（名前・アイコン・説明・表示専用の凡例）だけを足す。
// 地図に描く宣言（`scene/groups/`、絞り込める凡例は`scene/legends.ts`）は別に要る——書き忘れるとチップはONになり
// 凡例も出るのに、地図には何も出ない。

import weatherScales from "@/types/generated/weather-scales.json";
import { mapDisplay } from "@/types/generated/mapDisplay";
import regionTileConfig from "@/types/generated/region-tile-config.json";
import { axisIconFor } from "@/components/ui/icons/axisIconPalette";
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
  TrackGradeIcon,
  TunnelIcon,
  WindIcon,
  type MapIconComponent,
} from "@/components/ui/icons/icons";
import type { LegendEntry } from "@/lib/mapDisplay/legendFilter";
import { LANDCOVER_PAINTED_CLASSES } from "./landcoverClasses";
import { PRECIPITATION_INTENSITY_LEVELS } from "./precipitationNowcast";
import { WIND_SPEED_LEGEND_LEVELS } from "./windLayer";
import { pointLegendAxes } from "@/features/map/scene/legends";
import {
  axisMapLayerId,
  type AxisMapLayerId,
  type DedicatedWayValueAxis,
  type RampAxis,
} from "@/lib/mapDisplay/axisLayers";

/** チップの説明文へ差し込む種別名の並び（凡例と同じ宣言から作る）。 */
function pointKindList(role: string): string {
  return legendKindList(pointLegendAxes().find((entry) => entry.layerId === role)!.entries);
}

/** 源泉が宣言する、地図に載るものの名前。 */
type StaticMapLayerId = (typeof mapDisplay.layers)[number]["id"];

/** 地図に載るものの名前。静的な一覧は源泉が持ち、軸スタジオ由来のものは実行時に決まる。 */
export type MapLayerId = StaticMapLayerId | AxisMapLayerId | DedicatedWayValueMapLayerId;

// 選んだルートに付くデータ（選び直すたびに描き直す）か、地域に固定のデータ（表示の切り替えだけ）か。値が時間で
// 変わるかは別の`dataNature`が表す（降水ナウキャストは地域に固定で、値が時間で変わる）。
type MapLayerKind = (typeof mapDisplay.layerKinds)[number];

// 地域に固定のレイヤーの中分類（▶パネルの見出し）。ルートは持たない。
export type MapLayerCategory = (typeof mapDisplay.layerCategories)[number]["key"];

export const MAP_LAYER_CATEGORY_ORDER: readonly MapLayerCategory[] = mapDisplay.layerCategories.map(
  (category) => category.key,
);

/** 生データか、複数の要因から計算した推定指標（合成）か、時刻で中身が変わるデータか。 */
export type MapLayerDataNature = (typeof mapDisplay.layerDataNatures)[number];

/** 絞り込めない表示専用の凡例の1ブロック（配信元が色を焼き込んだラスタ等）。絞り込める凡例は`scene/legends.ts`が出す。 */
interface ReadOnlyLegendBlock {
  /** ブロックの見出し。単一ブロックのレイヤーは空文字列。 */
  label: string;
  legend: readonly LegendEntry[];
}

/** 表示専用の凡例の`filter`へ入れるダミー（描画へ当てないので、一致しない式でよい）。 */
const UNUSED_LEGEND_FILTER: unknown[] = ["==", 1, 0];

function readOnlyEntries(levels: readonly Omit<LegendEntry, "filter">[]): LegendEntry[] {
  return levels.map((level) => ({ ...level, filter: UNUSED_LEGEND_FILTER }));
}

/** そのレイヤーの絵がどこから来るか。取得状態はここから導く（同じタイルを読むレイヤーは同時に空・失敗になる）。
 * `ownFetch`はMapLibreのソースを経由せず自前で取るもので、取得状態はそのフェッチ自身が出す。 */
export type MapLayerDataSource = (typeof mapDisplay.layerDataSources)[number]["key"];

/** 地図のチップの最上位のグループ（何についての情報か。例: 道路・環境・スポット）。評価軸はどれにも属さない。 */
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

/** 軸スタジオ由来のレイヤー（ramp軸・専用配信の軸）か。地図のチップに出さない。idの集合でなく記述子の印で決める。 */
export function isAxisStudioLayer(layer: {
  id: MapLayerId;
  dataNature?: MapLayerDataNature;
  axisStudioLayer?: boolean;
}): boolean {
  return layer.axisStudioLayer === true || layer.dataNature === "composite";
}

/** レイヤーが属するグループ。軸スタジオ由来のものは中分類だけ見るとどこかへ紛れ込むので、先に除く。 */
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
  label: string;
  /** チップの下の短い名前（チップの幅は文字数で決まるので、長い名前はここで縮める）。無ければlabel。 */
  chipLabel?: string;
  kind: MapLayerKind;
  /** 省略できない（描く側の対応表で引く形だと、書き忘れても汎用のアイコンで見分けの付かないまま出続ける）。 */
  icon: MapIconComponent;
  /** 省略できない（書き忘れたレイヤーは取得状態を持たず、チップの状態の印が出ない）。 */
  dataSource: MapLayerDataSource;
  /** ▶を開いたときの表示専用の凡例。無いレイヤーは絞り込める凡例か、画面の状態から組む凡例を持つ。 */
  readOnlyLegend?: readonly ReadOnlyLegendBlock[];
  /** 専用配信の軸から作ったレイヤーか（ramp軸は`dataNature`の合成で同じ判定を受ける）。 */
  axisStudioLayer?: boolean;
  /** 中分類（グループの判定・グループ内の並び・小見出し）。ルートは持たない。 */
  category?: MapLayerCategory;
  dataNature?: MapLayerDataNature;
  /** ONにすると何が出るかの短い説明（チップのtitle）。 */
  description: string;
  /** 表示の設定パネルで項目の(i)が出す、descriptionより詳しい説明。 */
  panelHint?: string;
  defaultOn?: boolean;
  /** このズーム未満では配信元のタイルが要求されない（ONにしても何も出ない。チップに案内を出す）。 */
  tileMinZoom?: number;
}

type LayerDeclaration = Pick<
  MapLayerDescriptor,
  "dataSource" | "kind" | "category" | "dataNature" | "defaultOn" | "tileMinZoom"
>;

/** 源泉が宣言する、描き方以外のもの（種別・情報源・性質・既定表示）。最小ズームは情報源が持つ。 */
function declaredLayer(spec: {
  dataSource: MapLayerDataSource;
  category: MapLayerCategory | null;
  kind: MapLayerKind;
  dataNature: MapLayerDataNature;
  defaultOn: boolean;
}): LayerDeclaration {
  const minZoom = mapDisplay.layerDataSources.find((source) => source.key === spec.dataSource)!.minZoom;
  return {
    dataSource: spec.dataSource,
    kind: spec.kind,
    category: spec.category ?? undefined,
    dataNature: spec.dataNature,
    defaultOn: spec.defaultOn,
    tileMinZoom: minZoom ?? undefined,
  };
}

/** 源泉が宣言するレイヤー。名前も源泉が持つ（一次属性を描くものは属性の名前）。 */
function staticLayer(id: StaticMapLayerId): { id: StaticMapLayerId; label: string } & LayerDeclaration {
  const layer = mapDisplay.layers.find((candidate) => candidate.id === id)!;
  return { id, label: layer.label, ...declaredLayer(layer) };
}

/** 収録年の言い方（連続なら範囲、飛んでいれば並べる）。年は取込の宣言が正本で、軸カタログが運ぶ。 */
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
  // 取れていないときは年に触れない（既定の年を出すと、それが正しいように見える）。
  const accidentCoverage = coverageYearsLabel(accidentYears);
  return [
    {
      ...staticLayer("elevation"),
      icon: ElevationIcon,
      description: "国土地理院の色別標高図を重ねる",
      panelHint: "国土地理院の色別標高図を重ねる",
    },
    {
      ...staticLayer("hillshade"),
      icon: HillshadeIcon,
      description: "斜面に陰影を付ける[平地は塗らない]",
      panelHint: "国土地理院の標高データから斜面の陰影を作る。平らな所は塗らないため、下の地図の色が残る",
    },
    {
      ...staticLayer("landcover"),
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
      icon: LandcoverIcon,
      description: "周囲の緑・水辺・農地を面で重ねる[建物は塗らない]",
      panelHint:
        "衛星画像から分類した10m四方ごとの土地の使われ方です。1区画に1種類だけが入るため、" +
        "評価軸が使う「道路の周囲100mの割合」とは違い、混ざらずそのまま見えます。" +
        "建物は塗りません——市街地では画素のほとんどがそのクラスになり、地図が単色で" +
        "覆われるだけになるためです（建物があることは基礎地図から分かります）。" +
        "区間インスペクタの内訳には建物も出ます。",
    },
    {
      ...staticLayer("highway"),
      icon: RoadIcon,
      chipLabel: "道路種別",
      description: "道路の種類を色で表示[幹線道路ほど濃い紫・農道や林道ほど明るい水色]",
      panelHint:
        "OSMのhighwayタグを区分にまとめて色分けしています。幹線道路が最も濃く、下位の道ほど明るい色です。" +
        "「路面」「トンネル」等と一緒に表示すると、同じ道に線を横へ並べて描きます。",
    },
    {
      ...staticLayer("surface"),
      icon: RoadSurfaceIcon,
      chipLabel: "路面",
      description: "路面の材質を色で表示[舗装・砂利・土など]",
      panelHint:
        "OSMのsurfaceタグ[路面の材質]を区分にまとめて色分けしています。タグの無い道は「データなし」[灰色の薄い破線]、" +
        "区分に当てはまらない値の道は「その他」[灰色]で出します[データなしは未舗装という意味ではありません]。",
    },
    {
      ...staticLayer("tracktype"),
      icon: TrackGradeIcon,
      chipLabel: "等級",
      description: "農道・林道の路面の等級を色で表示[1=固く締まった路面ほど濃く、5=柔らかい土・草ほど明るい色]",
      panelHint:
        "OSMのtracktypeタグ[農道・林道の路面の固さの等級]を色分けしています。路面の材質[surfaceタグ]とは別のタグで、" +
        "材質のタグが無い農道・林道にも付いていることがあります。タグの無い道は「データなし」[灰色の薄い破線]です。",
    },
    {
      ...staticLayer("tunnel"),
      icon: TunnelIcon,
      description: "トンネル区間[OSMのtunnelタグ]を色分け表示",
      panelHint:
        "OSMのtunnelタグが該当する区間です。「夜間」軸[推定グループ]の材料の1つとして、" +
        "夜間の危険度の判定に使われます。night軸自体も専用レイヤーを持ちます。",
    },
    {
      ...staticLayer("oneway"),
      icon: OnewayIcon,
      description: "来た道を戻れない区間を色分け表示",
      panelHint:
        "その向きにしか通れない区間です。上下線が分かれているだけの道（逆方向が数m隣にある）" +
        "は除いてあります。ルート探索は既に一方通行の向きを守っており（逆走経路自体が" +
        "生成されません）、このレイヤーは表示のみで評価には影響しません。",
    },
    {
      ...staticLayer("stop_poi"),
      icon: StopPoiIcon,
      description: `${pointKindList("stop_poi")}の位置を種別ごとに色分け表示`,
      panelHint:
        `${pointKindList("stop_poi")}の位置です。評価の「停止密度」軸が近傍のこれらを` +
        "数えて算出しているものを、種別ごとの色分けで直接確認できます。",
    },
    {
      ...staticLayer("supply_poi"),
      icon: SupplyPoiIcon,
      chipLabel: "補給休憩",
      description: `${pointKindList("supply_poi")}の位置を種別ごとに色分け表示`,
      // 鮮度の差の根拠は`backend/scripts/measure_poi_freshness.py`（OSMの最終編集日時）で測る。
      panelHint:
        `${pointKindList("supply_poi")}の位置です。自販機は飲み物が買えると分かって` +
        "いるものだけを「飲料自販機」として出し、売っているものが分からないものは薄い色の" +
        "「自販機(中身不明)」として区別します（たばこ・切符の機械は出しません）。" +
        "コンビニはOSMデータの更新が比較的新しく目安として使いやすい一方、自販機・トイレ・" +
        "給水・駐輪場は閉店・撤去にデータが追いついていないことがあります。現地の状況と" +
        "異なる場合があることをご留意ください。",
    },
    {
      ...staticLayer("accident_point"),
      icon: AccidentIcon,
      chipLabel: "事故",
      description: `警察庁交通事故統計オープンデータ${accidentCoverage ? `[${accidentCoverage}]` : ""}の発生地点を表示`,
      panelHint:
        `警察庁が公開する交通事故統計オープンデータ[本票${accidentCoverage ? `、${accidentCoverage}` : ""}]の` +
        "発生地点です。死亡事故（事故後24時間以内）は円を大きく表示します。",
    },
    // ramp軸は軸カタログから作る（軸を公開すればここを変えずに現れる）。
    ...rampAxes.map((axis): MapLayerDescriptor => ({
      id: axisMapLayerId(axis.axisId),
      ...declaredLayer(mapDisplay.axisLayers.ramp),
      icon: axisIconFor(axis.iconId),
      label: axis.label,
      chipLabel: axis.chipLabel,
      category: axis.category as MapLayerCategory,
      // 単位が定まらない軸（unit=""）は空の[]を出さない。
      description: `${axis.label}${axis.unit ? `[${axis.unit}]` : ""}をway単位の事前集計から色分け表示`,
      panelHint: axis.panelHint,
    })),
    {
      // 1つのチップのまま、時刻の段ごとに配信元を切り替える（段は源泉が宣言する）。
      ...staticLayer("precipitationNowcast"),
      readOnlyLegend: [
        {
          label: "",
          legend: readOnlyEntries(PRECIPITATION_INTENSITY_LEVELS),
        },
        {
          label: "線状降水帯予測マップ（現在〜3時間先のみ）",
          // 色は配信元の塗り色そのもの。矩形に見えることも書く（細かい雨域と重なると描画の不具合に見える）。
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
      icon: RaindropIcon,
      chipLabel: "降水",
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
      ...staticLayer("windVector"),
      // 道路の色分け（向かい風・追い風）と別の配色なので、凡例は「矢印（風速）」と明示する。
      readOnlyLegend: [
        {
          label: "矢印（風速）",
          legend: readOnlyEntries(WIND_SPEED_LEGEND_LEVELS),
        },
      ],
      icon: WindIcon,
      chipLabel: "風",
      description: "気象庁MSMの風向・風速予報を矢印で表示[1〜3日先まで]",
      panelHint:
        "気象庁MSM（メソ数値予報モデル、5kmメッシュ）による風向・風速を格子点で矢印表示します。" +
        "矢印の向きが風向、長さ・太さ・色の濃淡が風速の強さを表します。ごく弱い風の地点は" +
        "矢印を表示しません。ONにすると地図上に時刻スライダーが現れ、1時間刻みで切り替えられます" +
        "（先まで見られる範囲は配信中の予報の長さによって1〜3日の間で変わります）。走行方位に対する向かい風/追い風の強さは、地図上部中央の" +
        "「レンズ」で風の評価軸を選ぶと、道路の色分けとして別途確認できます。",
    },
    // 専用配信の軸。チップには出ないが、地図の組み立てが情報源をここから引く（無いと描く時点で落ちる）。
    ...dedicatedAxes.map((axis): MapLayerDescriptor => ({
      id: dedicatedWayValueMapLayerId(axis.axisId),
      ...declaredLayer(mapDisplay.axisLayers.dedicated),
      icon: axisIconFor(undefined),
      label: `${axis.label}（評価軸）`,
      chipLabel: axis.chipLabel,
      axisStudioLayer: true,
      description: `${axis.label}を視界内の全道路へ一律に線色分け表示`,
      panelHint: axis.panelHint,
    })),
    {
      // 回避するしかない危険なので、評価軸には入れず表示だけにする。
      ...staticLayer("disaster"),
      icon: ShieldIcon,
      chipLabel: "災害",
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
      // 配信元が色を焼き込んだ画像なので絞り込めない。
      readOnlyLegend: [
        { label: "キキクル（土砂災害・大雨・浸水・洪水）", legend: readOnlyEntries(weatherScales.risk_levels) },
        { label: "雷ナウキャスト（活動度）", legend: readOnlyEntries(weatherScales.thunder_activity) },
        { label: "竜巻発生確度ナウキャスト", legend: readOnlyEntries(weatherScales.tornado_potential) },
      ],
    },
    {
      ...staticLayer("route"),
      icon: RouteIcon,
      description: "選択中ルート沿いの情報[風・勾配・路面・総合難易度]を色分け表示",
    },
  ];
}

/** 最上位のグループを同時に開いておける数（理由は`docs/modules/frontend/static-map-layers.md`）。 */
export const MAP_OVERLAY_MAX_EXPANDED_GROUPS = 1;

export type MapLayerVisibility = Record<MapLayerId, boolean>;

/** チップ下に出す、ズーム不足の案内。 */
export const TILE_ZOOM_TOO_WIDE_NOTICE = "ズームインすると表示されます";

/** チップ下に出す、タイルの世代が届いていないときの案内（届くまでソースを作らないので何も描けない）。 */
export const TILE_VERSIONS_MISSING_NOTICE = "配信情報を取得できず表示できません";

/** 世代が届くまで要求できない情報源（世代を配るタイルの系統の名前が、そのまま情報源の名前）。 */
const TILE_VERSION_GATED_SOURCES: ReadonlySet<string> = new Set(regionTileConfig.tile_version_kinds);

/** タイルの世代が届くまで何も描けないレイヤー。ramp軸も路面タイルを読むので含める。 */
export function tileVersionGatedLayerIds(rampAxes: readonly RampAxis[]): readonly MapLayerId[] {
  return buildMapLayers(rampAxes, [])
    .filter((layer) => TILE_VERSION_GATED_SOURCES.has(layer.dataSource))
    .map((layer) => layer.id);
}

/** そのズームではタイルが要求されず、ONにしても何も出ないレイヤー。軸のレイヤーはチップが無く案内の出し先が無いので含めない。 */
export function tileZoomTooWideLayerIds(zoom: number): readonly MapLayerId[] {
  return buildMapLayers([], [])
    .filter((layer) => layer.tileMinZoom !== undefined && zoom < layer.tileMinZoom)
    .map((layer) => layer.id);
}

/** チップからON/OFFできるレイヤーの既定の表示。軸のレイヤーはレンズだけが決めるので持たない。 */
export function buildDefaultLayerVisibility(): MapLayerVisibility {
  return Object.fromEntries(
    buildMapLayers([], []).map((layer) => [layer.id, layer.defaultOn === true]),
  ) as MapLayerVisibility;
}

// レイヤーごとの取得の状態。正常なときはキー自体を持たない。
export type LayerDataStatus = "loading" | "empty" | "error";
export type LayerDataStatusByLayer = Partial<Record<MapLayerId, LayerDataStatus>>;

export const LAYER_DATA_STATUS_LABELS: Record<LayerDataStatus, string> = {
  loading: "読み込み中です",
  empty: "この範囲に表示できるデータがありません",
  error: "データの取得に失敗しました。しばらくしてから再読み込みしてください",
};

/** 自前で取るレイヤーの取得の状態（失敗 > 読み込み中 > 取れたが値なし）。まだ一度も取れていない間を「値なし」に
 * しない（有効にした直後や、取得がそもそも走っていない状態が「データが無い」と読めてしまう）。 */
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

/** ramp軸の`axis:${axisId}`とは別の名前（同じ軸がramp・専用配信の両方を持ちうる）。 */
type DedicatedWayValueMapLayerId = `${string}Axis`;

function dedicatedWayValueMapLayerId(axisId: string): DedicatedWayValueMapLayerId {
  return `${axisId}Axis`;
}

/** 凡例の種別名を説明文へ差し込める並びにする（受け皿は除く）。区切りが読点なのは、名前が中黒を含むため。 */
function legendKindList(legend: readonly LegendEntry[]): string {
  return legend
    .filter((entry) => entry.isFallback !== true)
    .map((entry) => entry.label)
    .join("、");
}
