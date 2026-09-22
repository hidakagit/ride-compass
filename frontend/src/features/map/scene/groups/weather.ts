/** 動的気象（降水・風・災害）。
 *
 * 1つのチップ（グループ）が複数の名前付きソースを持ち、ソースごとに描き方が決まっている。
 * **中身は時刻の変化で何度も入れ替わる**ため、ソースは作り直さず中身だけを差し替える。
 * **中身の種類が宣言と一致するときだけ**表示する——種類が合わないものを出すと、
 * 前の時刻の絵が残ったように見える。
 *
 * 同じ（グループ, ソース）に描き方の違う宣言を並べてよい（降水は60分以内がラスタ、
 * それ以降は格子の塗り）。届いた中身の種類が、そのうちどれを出すかを決める。
 */
import type { FilterSpecification } from "maplibre-gl";

import { createLidenIcon } from "@/components/Map/lidenIcon";
import { LIDEN_MARK_VALUE_PROPERTY } from "@/components/Map/lidenLayer";
import { jmaPlaceholderTileUrl } from "@/components/Map/jmaNowcastFrames";
import { PRECIPITATION_COLOR_STOPS, PRECIPITATION_NONE_THRESHOLD_MM } from "@/components/Map/precipitationNowcast";
import { RISK_LEVEL_COLORS } from "@/components/Map/riskMap";
import { createWindArrowIcon } from "@/components/Map/windArrowIcon";
import { WIND_CALM_THRESHOLD_MS, WIND_SPEED_COLOR_STOPS } from "@/components/Map/windLayer";
import jmaTileConfig from "@/types/generated/jma-tile-config.json";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";
import { zoomScaleExpression } from "../sceneBuilders";

/** 面の濃さ。道路の線が透けて読める程度に留める。 */
const AREA_OPACITY = 0.55;

/** 記号の縁取り。背景の明暗に関わらず記号の形が読めるようにする。**主層と同じレイヤーの
 * paintで出す**——別レイヤーにすると、同じ位置に2枚並ぶぶん衝突判定で縁取りが全部落ちる。 */
const MARK_HALO_COLOR = "rgba(31, 41, 55, 0.85)";
const MARK_HALO_WIDTH_PX = 1.5;

const WIND_ICON_MIN_SCALE = 0.9;
const WIND_ICON_MAX_SCALE = 2.6;
/** この風速で最大の大きさになる。 */
const WIND_FULL_SCALE_MS = 15;
const LIDEN_SCALE = 0.8;
const LIDEN_COLOR = "#facc15";

/** 描き方。面は下・線と点は上に置く（面どうしが重なると読めなくなるため）。 */
const TIER_OF = {
  rasterTile: "area",
  gridFill: "area",
  vectorTile: "observedLine",
  gridMark: "point",
} as const;

export type WeatherRenderKind = keyof typeof TIER_OF;

/** いま届いている中身。種類が宣言と合うときだけ描く。 */
export type WeatherPayload =
  | { readonly kind: "rasterTile"; readonly tiles: readonly string[] }
  | { readonly kind: "vectorTile"; readonly tiles: readonly string[] }
  | { readonly kind: "gridFill"; readonly data: unknown }
  | { readonly kind: "gridMark"; readonly data: unknown };

/** 要素1つぶんの宣言。**ここへ1行足すと1要素増える**（ソースid・レイヤーid・段・
 * 差し替え方はすべてここから決まる）。 */
export type WeatherElement = {
  readonly group: string;
  readonly source: string;
  readonly kind: WeatherRenderKind;
  /** 種類ごとに決まる見た目。 */
  readonly paint: Readonly<Record<string, unknown>>;
  readonly layout?: Readonly<Record<string, unknown>>;
  readonly sourceSpec: SceneSourceEntry["spec"];
  readonly sourceLayer?: string;
  /** 中身が届く前に指すタイル。**タイルを持たないソース宣言は成り立たない**ため、
   * 届くまでの間もここを指す（実データのない架空のURL）。 */
  readonly placeholderTiles?: readonly string[];
  /** 中身が届く前の GeoJSON（同じ理由で、空の中身を持たせる）。 */
  readonly placeholderData?: unknown;
  readonly filter?: FilterSpecification;
  /** 記号を描くのに要るアイコン。登録してからでないと出ない。 */
  readonly icon?: { readonly id: string; readonly create: () => ImageData };
};

const EMPTY_FEATURE_COLLECTION = { type: "FeatureCollection", features: [] } as const;

function jmaZoom(elementId: keyof typeof jmaTileConfig): { minzoom: number; maxzoom: number } {
  const spec = jmaTileConfig[elementId];
  return { minzoom: spec.min_zoom, maxzoom: spec.max_zoom };
}

/** 帯の下限と色の並びから、値→色の段階式を作る。 */
function bandColorExpression(value: unknown, stops: readonly { from: number; color: string }[]): unknown {
  const rest = stops.slice(1).flatMap((stop) => [stop.from, stop.color]);
  return ["step", ["to-number", value], stops[0]?.color ?? "rgba(0,0,0,0)", ...rest];
}

function aboveFilter(property: string, min: number): FilterSpecification {
  return [">", ["to-number", ["get", property]], min] as unknown as FilterSpecification;
}

/** 配信元のラスタタイル1枚ぶんの宣言（キキクル・ナウキャスト）。 */
function rasterElement(group: string, source: string, product: keyof typeof jmaTileConfig, path: string): WeatherElement {
  return {
    group,
    source,
    kind: "rasterTile",
    sourceSpec: { type: "raster", tileSize: 256, ...jmaZoom(product), attribution: "気象庁" },
    placeholderTiles: [path],
    paint: { "raster-opacity": AREA_OPACITY },
  };
}

function markElement(
  group: string,
  source: string,
  options: {
    readonly iconId: string;
    readonly createIcon: () => ImageData;
    readonly color: unknown;
    readonly valueProperty: string;
    readonly rotateProperty?: string;
    readonly minScale: number;
    readonly maxScale: number;
    readonly fullScaleValue: number;
    readonly minValueToShow?: number;
  },
): WeatherElement {
  return {
    group,
    source,
    kind: "gridMark",
    sourceSpec: { type: "geojson", attribution: "気象庁" },
    placeholderData: EMPTY_FEATURE_COLLECTION,
    icon: { id: options.iconId, create: options.createIcon },
    layout: {
      "icon-image": options.iconId,
      "icon-rotate":
        options.rotateProperty === undefined ? 0 : ["to-number", ["get", options.rotateProperty]],
      "icon-rotation-alignment": options.rotateProperty === undefined ? "viewport" : "map",
      // 記号が密なズームでは間引く（重ねると格子が塗り潰しに見える）。
      "icon-allow-overlap": false,
      "icon-ignore-placement": false,
      "icon-size": zoomScaleExpression([
        "interpolate",
        ["linear"],
        ["to-number", ["get", options.valueProperty]],
        0,
        options.minScale,
        options.fullScaleValue,
        options.maxScale,
      ]),
    },
    paint: {
      "icon-color": options.color,
      "icon-opacity": 1,
      "icon-halo-color": MARK_HALO_COLOR,
      "icon-halo-width": MARK_HALO_WIDTH_PX,
    },
    ...(options.minValueToShow === undefined
      ? {}
      : { filter: aboveFilter(options.valueProperty, options.minValueToShow) }),
  };
}

/** 動的気象で描くもの。**ここへ1件足すと要素が1つ増える。** */
export const WEATHER_ELEMENTS: readonly WeatherElement[] = [
  // 降水。60分以内は配信元のラスタ、それ以降は自前の格子を塗る。どちらが届くかは
  // 選んだ時刻で決まり、ここは両方を宣言しておく。
  rasterElement("precipitationNowcast", "main", "hrpns", jmaPlaceholderTileUrl("nowc", "hrpns")),
  {
    group: "precipitationNowcast",
    source: "main",
    kind: "gridFill",
    sourceSpec: { type: "geojson", attribution: "気象庁MSM" },
    placeholderData: EMPTY_FEATURE_COLLECTION,
    paint: {
      "fill-color": bandColorExpression(
        ["get", "mmPerHour"],
        PRECIPITATION_COLOR_STOPS.map((stop) => ({ from: stop.mmPerHour, color: stop.color })),
      ),
      "fill-opacity": AREA_OPACITY,
    },
    // 降っていない格子まで塗ると、地図全体が薄く覆われて下が読めない。
    filter: aboveFilter("mmPerHour", PRECIPITATION_NONE_THRESHOLD_MM),
  },
  rasterElement("precipitationNowcast", "linearRainband", "sjfcstmap", jmaPlaceholderTileUrl("rasrf", "sjfcstmap")),

  markElement("windVector", "arrow", {
    iconId: "weather-wind-arrow",
    createIcon: createWindArrowIcon,
    color: bandColorExpression(
      ["get", "speed"],
      WIND_SPEED_COLOR_STOPS.map((stop) => ({ from: stop.speedMs, color: stop.color })),
    ),
    valueProperty: "speed",
    rotateProperty: "bearing",
    minScale: WIND_ICON_MIN_SCALE,
    maxScale: WIND_ICON_MAX_SCALE,
    fullScaleValue: WIND_FULL_SCALE_MS,
    // ほぼ無風の矢印は向きが意味を持たない。
    minValueToShow: WIND_CALM_THRESHOLD_MS,
  }),

  // 災害。面を下に、見落としやすい線（洪水）と点（落雷）を上に置く。大雨は土砂・浸水を
  // 統合した指標なので、個別の2つより下に置く。
  rasterElement("disaster", "heavyRain", "rain_mesh", jmaPlaceholderTileUrl("risk", "rain_mesh")),
  rasterElement("disaster", "landslide", "land", jmaPlaceholderTileUrl("risk", "land")),
  rasterElement("disaster", "inundation", "inund", jmaPlaceholderTileUrl("risk", "inund")),
  rasterElement("disaster", "thunder", "thns", jmaPlaceholderTileUrl("nowc", "thns")),
  rasterElement("disaster", "tornado", "trns", jmaPlaceholderTileUrl("nowc", "trns")),
  {
    group: "disaster",
    source: "flood",
    kind: "vectorTile",
    sourceSpec: { type: "vector", ...jmaZoom("flood"), attribution: "気象庁" },
    sourceLayer: "flood",
    placeholderTiles: [jmaPlaceholderTileUrl("risk", "flood", "pbf")],
    paint: {
      "line-color": [
        "match",
        ["to-number", ["get", "level"]],
        1,
        RISK_LEVEL_COLORS[1].color,
        2,
        RISK_LEVEL_COLORS[2].color,
        3,
        RISK_LEVEL_COLORS[3].color,
        4,
        RISK_LEVEL_COLORS[4].color,
        RISK_LEVEL_COLORS[0].color,
      ],
      // 低いズームで目立たせすぎず、拡大するほど個々の川筋を追えるようにする。
      "line-width": ["interpolate", ["linear"], ["zoom"], 6, 1.5, 10, 3, 14, 5],
    },
    // 平常時の基準線（level=0）まで出すと、危険情報が無い日も川が全部塗られる。
    filter: aboveFilter("level", 0),
  },
  markElement("disaster", "liden", {
    iconId: "weather-liden",
    createIcon: createLidenIcon,
    // 落雷の強弱を配信元が持たないため、大きさはズームだけで決まる。
    color: LIDEN_COLOR,
    valueProperty: LIDEN_MARK_VALUE_PROPERTY,
    minScale: LIDEN_SCALE,
    maxScale: LIDEN_SCALE,
    fullScaleValue: 1,
  }),
];

export type WeatherState = {
  /** 表示ON/OFFと中身。鍵は `${group}/${source}`。 */
  readonly shown: ReadonlyMap<string, { readonly visible: boolean; readonly payload?: WeatherPayload }>;
};

export function weatherElementKey(element: Pick<WeatherElement, "group" | "source">): string {
  return `${element.group}/${element.source}`;
}

/** 登録が要るアイコン。**出す前に登録しないと記号が描かれない。** */
export const WEATHER_ICONS: readonly { id: string; create: () => ImageData }[] = WEATHER_ELEMENTS.flatMap(
  (element) => (element.icon === undefined ? [] : [element.icon]),
);

/** レイヤー・ソースの役割。**綴りはここだけが決める**（凡例・テストもここから引く）。 */
export function weatherElementRole(element: Pick<WeatherElement, "group" | "source" | "kind">): string {
  return `${element.group}-${element.source}-${element.kind}`;
}

export const weatherGroup = declareGroup<WeatherState>("weather", (state) => {
  const sources: SceneSourceEntry[] = [];
  const layers: SceneLayerEntry[] = [];

  for (const element of WEATHER_ELEMENTS) {
    const shown = state.shown.get(weatherElementKey(element));
    const payload = shown?.payload;
    const matches = payload !== undefined && payload.kind === element.kind;
    const id = `weather-${weatherElementRole(element)}`;

    sources.push({
      id,
      spec: element.sourceSpec,
      ...(element.sourceLayer === undefined ? {} : { sourceLayer: element.sourceLayer }),
      ...(matches && "tiles" in payload
        ? { tiles: payload.tiles }
        : element.placeholderTiles === undefined
          ? {}
          : { tiles: element.placeholderTiles }),
      ...(matches && "data" in payload
        ? { data: payload.data }
        : element.placeholderData === undefined
          ? {}
          : { data: element.placeholderData }),
    });

    layers.push({
      role: weatherElementRole(element),
      tier: TIER_OF[element.kind],
      source: id,
      ...(element.sourceLayer === undefined ? {} : { sourceLayer: element.sourceLayer }),
      type: layerTypeOf(element.kind),
      paint: element.paint,
      ...(element.layout === undefined ? {} : { layout: element.layout }),
      visible: (shown?.visible ?? false) && matches,
      ...(element.filter === undefined ? {} : { filter: element.filter }),
    });
  }

  return { sources, layers };
});

function layerTypeOf(kind: WeatherRenderKind): SceneLayerEntry["type"] {
  switch (kind) {
    case "rasterTile":
      return "raster";
    case "gridFill":
      return "fill";
    case "vectorTile":
      return "line";
    case "gridMark":
      return "symbol";
  }
}
