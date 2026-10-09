// 地図レイヤーのカタログ。地図のチップとその▶パネルがこの並びを列挙して描く。種別・情報源・性質・既定の表示・名前・
// 説明は源泉（backendの`domain/map_display.py`）が宣言し、ここはアイコンと表示専用の凡例だけを足す。
// 地図に描く宣言（`scene/groups/`、絞り込める凡例は`scene/legends.ts`）は別に要る——書き忘れるとチップはONになり
// 凡例も出るのに、地図には何も出ない。

import weatherScales from "@/types/generated/weather-scales.json";
import { mapDisplay } from "@/types/generated/mapDisplay";
import {
  AccidentIcon,
  BicycleIcon,
  HillshadeIcon,
  RaindropIcon,
  RoadSurfaceIcon,
  RouteIcon,
  ShieldIcon,
  StopPlaceIcon,
  StopPoiIcon,
  SupplyPoiIcon,
  TunnelIcon,
  WindIcon,
  type MapIconComponent,
} from "@/components/ui/icons/icons";
import type { LegendEntry } from "@/lib/mapDisplay/legendFilter";
import { TILE_VERSION_GATED_SOURCES } from "@/lib/mapDisplay/tileVersionGated";
import { PRECIPITATION_INTENSITY_LEVELS } from "./precipitationNowcast";
import { WIND_SPEED_LEGEND_LEVELS } from "./windLayer";
import { axisMapLayerId, type AxisMapLayerId, type RampAxis } from "@/lib/mapDisplay/axisLayers";
import type { MapAxisCatalog } from "@/features/map/mapAxisCatalog";
import { axisNamesInText, type CatalogAxis } from "@/lib/catalogAxis";
import { FIXED_LENS_LABELS, LENS_DIFFICULTY_ID } from "@/lib/mapDisplay/routeStyleModes";

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
type MapLayerDataNature = (typeof mapDisplay.layerDataNatures)[number];

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

/** 名前付きソースの宣言（同じソースを名乗る要素は名前・コマの規則・配信を共有するので、先頭の要素で引く）。 */
function weatherSourceOf(source: string) {
  const element = mapDisplay.weatherElements.find((candidate) => candidate.source === source);
  if (!element) throw new Error(`${source}は宣言されていない`);
  return element;
}

/** 名前付きソースを重ねる幅（「今」から何時間先まで）。源泉が要素の描くコマの規則として宣言する値。 */
function windowHoursOf(source: string): number {
  const minutes = weatherSourceOf(source).frameRule.windowMinutes;
  if (minutes == null) throw new Error(`${source}は重ねる幅を宣言していない`);
  return minutes / 60;
}

const LINEAR_RAINBAND_HOURS = windowHoursOf("linearRainband");

/** 名前付きソースの予測が届く先（分）。源泉が配信の要素ごとに宣言する値。 */
function forecastMinutesOf(source: string): number {
  const minutes = weatherSourceOf(source).jmaElements[0]?.forecastMinutes;
  if (minutes == null) throw new Error(`${source}は予測が届く先を宣言していない`);
  return minutes;
}

type WeatherElementDeclaration = (typeof mapDisplay.weatherElements)[number];

const DISASTER_ELEMENTS = mapDisplay.weatherElements.filter((element) => element.group === "disaster");

/** 名前の並び。同じ名前を名乗る要素（描き方違いの同じ名前付きソース）は1つにする。 */
function labelList(elements: readonly WeatherElementDeclaration[]): string {
  return [...new Set(elements.map((element) => element.label))].join("・");
}

/** 災害の凡例。同じ段で塗る要素の名前を見出しにして、段を並べる（並びは要素が最初に現れた順）。 */
function disasterLegendBlocks(): ReadOnlyLegendBlock[] {
  const scales = [...new Set(DISASTER_ELEMENTS.flatMap((element) => element.levelScale ?? []))];
  return scales.map((scale) => ({
    label: labelList(DISASTER_ELEMENTS.filter((element) => element.levelScale === scale)),
    legend: readOnlyEntries(weatherScales[scale]),
  }));
}

/** 源泉が宣言するレイヤーのアイコン。省略できない（描く側の対応表で引く形だと、書き忘れても汎用のアイコンで
 * 見分けの付かないまま出続ける）。 */
const STATIC_LAYER_ICONS: Record<StaticMapLayerId, MapIconComponent> = {
  hillshade: HillshadeIcon,
  surface: RoadSurfaceIcon,
  tunnel: TunnelIcon,
  cycleway: BicycleIcon,
  stop_poi: StopPoiIcon,
  supply_poi: SupplyPoiIcon,
  stop_place: StopPlaceIcon,
  accident_point: AccidentIcon,
  precipitationNowcast: RaindropIcon,
  windVector: WindIcon,
  disaster: ShieldIcon,
  route: RouteIcon,
};

/** ▶を開いたときの表示専用の凡例。無いレイヤーは絞り込める凡例か、画面の状態から組む凡例を持つ。 */
const READ_ONLY_LEGENDS: Partial<Record<StaticMapLayerId, readonly ReadOnlyLegendBlock[]>> = {
  // 1つのチップのまま、時刻の段ごとに配信元を切り替える（段は源泉が宣言する）。
  precipitationNowcast: [
    {
      label: "",
      legend: readOnlyEntries(PRECIPITATION_INTENSITY_LEVELS),
    },
    {
      label: `${weatherSourceOf("linearRainband").label}[現在〜${LINEAR_RAINBAND_HOURS}時間先のみ]`,
      // 色は配信元の塗り色そのもの。矩形に見えることも書く（細かい雨域と重なると描画の不具合に見える）。
      legend: [
        {
          key: "linearRainband",
          label: `今後${LINEAR_RAINBAND_HOURS}時間以内に大雨のおそれ[矩形の予測領域]`,
          color: weatherScales.linear_rainband_color,
          filter: UNUSED_LEGEND_FILTER,
        },
      ],
    },
    {
      label: `${weatherSourceOf("linearRainbandArea").label}[実況〜${forecastMinutesOf("linearRainbandAreaForecast")}分先のみ]`,
      // 文言は配信元の公式の画面の凡例に合わせる。
      legend: [
        {
          key: "linearRainbandArea",
          label: "大雨災害発生の危険度が急激に高まっている線状降水帯の雨域[赤い輪郭線]",
          color: weatherScales.linear_rainband_outline_color,
          filter: UNUSED_LEGEND_FILTER,
        },
      ],
    },
  ],
  // 道路の色分け（向かい風・追い風）と別の配色なので、凡例は「矢印[風速]」と明示する。
  windVector: [
    {
      label: "矢印[風速]",
      legend: readOnlyEntries(WIND_SPEED_LEGEND_LEVELS),
    },
  ],
  // 配信元が色を焼き込んだ画像なので絞り込めない。
  disaster: disasterLegendBlocks(),
};

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
export function isAxisStudioLayer(layer: MapLayerDescriptor): layer is AxisStudioLayerDescriptor {
  return layer.axisStudioLayer === true || layer.dataNature === "composite";
}

/** チップが属するグループ。中分類だけで決めるので、軸スタジオ由来のレイヤーは渡さない——チップの一覧
 * （`features/map/view/overlayChips.ts: overlayChips`）が先に除く。 */
export function mapOverlayGroupFor(layer: { category?: MapLayerCategory }): MapOverlayGroup | undefined {
  if (layer.category === undefined) return undefined;
  return GROUP_BY_CATEGORY[layer.category];
}

/** チップに出るレイヤー。 */
export interface ChipLayerDescriptor {
  id: MapLayerId;
  label: string;
  kind: MapLayerKind;
  /** 省略できない（描く側の対応表で引く形だと、書き忘れても汎用のアイコンで見分けの付かないまま出続ける）。 */
  icon: MapIconComponent;
  /** 省略できない（書き忘れたレイヤーは取得状態を持たず、チップの状態の印が出ない）。 */
  dataSource: MapLayerDataSource;
  /** ▶を開いたときの表示専用の凡例。無いレイヤーは絞り込める凡例か、画面の状態から組む凡例を持つ。 */
  readOnlyLegend?: readonly ReadOnlyLegendBlock[];
  axisStudioLayer?: never;
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
  ChipLayerDescriptor,
  "dataSource" | "kind" | "category" | "dataNature" | "defaultOn" | "tileMinZoom"
>;

/** 軸スタジオ由来のレイヤー。チップに出ない（表示はレンズだけが決める）ので、名前・アイコン・説明を持たず、
 * 地図の組み立てが情報源を引くためのidと源泉の宣言だけを持つ。 */
export interface AxisStudioLayerDescriptor extends LayerDeclaration {
  id: MapLayerId;
  /** 専用配信の軸から作ったレイヤーか（ramp軸は`dataNature`の合成で同じ判定を受ける）。 */
  axisStudioLayer?: true;
}

export type MapLayerDescriptor = ChipLayerDescriptor | AxisStudioLayerDescriptor;

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

/** 源泉の説明の文の差し込み口。 */
type LayerTextSlot = Extract<
  NonNullable<(typeof mapDisplay.layers)[number]["description" | "panelHint"]>[number],
  { name: string }
>;

type LayerTextPart = string | LayerTextSlot;

/** 説明の文の差し込み口の名前（源泉が宣言する）。 */
type LayerTextSlotName = LayerTextSlot["name"];

/** 源泉の説明の文の差し込み口を埋める。値が空の口は、前後の文ごと出さない。 */
function fillLayerText(text: readonly LayerTextPart[], values: Readonly<Record<LayerTextSlotName, string>>): string {
  return text
    .map((part) => {
      if (typeof part === "string") return part;
      const value = values[part.name];
      return value ? `${part.before}${value}${part.after}` : "";
    })
    .join("");
}

/** 収録年の言い方（連続なら範囲、飛んでいれば並べる）。年は取込の宣言が正本で、軸カタログが運ぶ。 */
function coverageYearsLabel(years: readonly number[]): string {
  if (years.length === 0) return "";
  const sorted = [...years].sort((a, b) => a - b);
  if (sorted.length === 1) return `${sorted[0]}年`;
  const continuous = sorted.every((year, index) => index === 0 || year === sorted[index - 1] + 1);
  return continuous ? `${sorted[0]}〜${sorted[sorted.length - 1]}年` : `${sorted.join("・")}年`;
}

/** レイヤーの一覧を組むのに要る軸カタログの項目。 */
type LayerCatalog = Pick<MapAxisCatalog, "axes" | "rampAxes" | "dedicatedAxes" | "accidentYears">;

const NO_AXES: LayerCatalog = { axes: [], rampAxes: [], dedicatedAxes: [], accidentYears: [] };

/** そのレイヤーが見せる元データを材料に持つ公開中の評価の名前（「A」「B」）。無ければ空文字で、呼ぶ側は評価に触れる一文を出さない。 */
function axisNamesReading(axes: readonly CatalogAxis[], layerId: StaticMapLayerId): string {
  return axisNamesInText(
    axes.filter((axis) => axis.primaryAttributeIds.includes(layerId) || axis.weatherLayerGroups.includes(layerId)),
  );
}

export function buildMapLayers({
  axes,
  rampAxes,
  dedicatedAxes,
  accidentYears,
}: LayerCatalog): readonly MapLayerDescriptor[] {
  // 取れていないときは年に触れない（既定の年を出すと、それが正しいように見える）。
  const accidentCoverage = coverageYearsLabel(accidentYears);
  // 並びはレンズの選択肢と同じ（公開中の評価と総合難易度）。
  const routeLenses = [...axes.map((axis) => axis.label), FIXED_LENS_LABELS[LENS_DIFFICULTY_ID]].join("・");
  const staticLayers = mapDisplay.layers.map((layer): ChipLayerDescriptor => {
    const slots = { axes: axisNamesReading(axes, layer.id), accidentYears: accidentCoverage, routeLenses };
    return {
      id: layer.id,
      label: layer.label,
      ...declaredLayer(layer),
      icon: STATIC_LAYER_ICONS[layer.id],
      readOnlyLegend: READ_ONLY_LEGENDS[layer.id],
      description: fillLayerText(layer.description, slots),
      panelHint: layer.panelHint ? fillLayerText(layer.panelHint, slots) : undefined,
    };
  });
  return [
    ...staticLayers,
    // ramp軸は軸カタログから作る（軸を公開すればここを変えずに現れる）。
    ...rampAxes.map((axis): AxisStudioLayerDescriptor => ({
      id: axisMapLayerId(axis.axisId),
      ...declaredLayer(mapDisplay.axisLayers.ramp),
    })),
    // 専用配信の軸。チップには出ないが、地図の組み立てが情報源をここから引く（無いと描く時点で落ちる）。
    ...dedicatedAxes.map((axis): AxisStudioLayerDescriptor => ({
      id: dedicatedWayValueMapLayerId(axis.axisId),
      ...declaredLayer(mapDisplay.axisLayers.dedicated),
      axisStudioLayer: true,
    })),
  ];
}

export type MapLayerVisibility = Record<MapLayerId, boolean>;

/** チップ下に出す、ズーム不足の案内。 */
export const TILE_ZOOM_TOO_WIDE_NOTICE = "ズームインすると表示されます";

/** チップ下に出す、タイルの世代が届いていないときの案内（届くまでソースを作らないので何も描けない）。 */
export const TILE_VERSIONS_MISSING_NOTICE = "配信情報を取得できず表示できません";

/** タイルの世代が届くまで何も描けないレイヤー。ramp軸も路面タイルを読むので含める。 */
export function tileVersionGatedLayerIds(rampAxes: readonly RampAxis[]): readonly MapLayerId[] {
  return buildMapLayers({ ...NO_AXES, rampAxes })
    .filter((layer) => TILE_VERSION_GATED_SOURCES.has(layer.dataSource))
    .map((layer) => layer.id);
}

/** そのズームではタイルが要求されず、ONにしても何も出ないレイヤー。軸のレイヤーはチップが無く案内の出し先が無いので含めない。 */
export function tileZoomTooWideLayerIds(zoom: number): readonly MapLayerId[] {
  return buildMapLayers(NO_AXES)
    .filter((layer) => layer.tileMinZoom !== undefined && zoom < layer.tileMinZoom)
    .map((layer) => layer.id);
}

/** チップからON/OFFできるレイヤーの既定の表示。軸のレイヤーはレンズだけが決めるので持たない。 */
export function buildDefaultLayerVisibility(): MapLayerVisibility {
  return Object.fromEntries(
    buildMapLayers(NO_AXES).map((layer) => [layer.id, layer.defaultOn === true]),
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

/** 開いたパネルへ文として出す状態。待ちは絞り込み・ON/OFFの取り直しのたびに一瞬出ては消え、パネルの中身を
 * 揺らすため文にせず、ドットだけで示す。 */
export function layerDataStatusNotice(status: LayerDataStatus | undefined): string | null {
  return status && status !== "loading" ? LAYER_DATA_STATUS_LABELS[status] : null;
}

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
