/** 動的気象（降水・風・災害）。
 *
 * **何を描くか（チップ・名前付きソース・描き方の種類・配信元）は源泉が配る**
 * （`mapDisplay.weatherElements`、backendの`domain/weather_elements.py: WEATHER_ELEMENTS`）。
 * ここが持つのは描き方（paint・layout・filter・記号）だけ。
 *
 * 1つのチップ（グループ）が複数の名前付きソースを持ち、ソースごとに描き方が決まっている。
 * **中身は時刻の変化で何度も入れ替わる**ため、ソースは作り直さず中身だけを差し替える。
 * **中身の種類が宣言と一致するときだけ**表示する——種類が合わないものを出すと、
 * 前の時刻の絵が残ったように見える。
 *
 * 同じ（グループ, ソース）に描き方の違う宣言が並ぶことがある（降水は60分以内がラスタ、
 * それ以降は格子の塗り）。届いた中身の種類が、そのうちどれを出すかを決める。
 */
import { mapDisplay } from "@/types/generated/mapDisplay";
import palette from "@/types/generated/palette.json";
import weatherScales from "@/types/generated/weather-scales.json";
import type { FilterSpecification } from "maplibre-gl";

import { createLidenIcon } from "@/features/map/layers/lidenIcon";
import { JMA_POINT_VALUE_PROPERTY, jmaPlaceholderTileUrl } from "@/features/map/layers/jmaDelivery";
import { PRECIPITATION_COLOR_STOPS, PRECIPITATION_NONE_THRESHOLD_MM } from "@/features/map/layers/precipitationNowcast";
import { createWindArrowIcon } from "@/features/map/layers/windArrowIcon";
import { WIND_CALM_THRESHOLD_MS, WIND_SPEED_COLOR_STOPS } from "@/features/map/layers/windLayer";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "@/features/map/scene/mapSceneGroups";
import { AREA_OPACITY } from "./areaRasters";
import { zoomScaleExpression, sceneSourceId, type SceneSourceId } from "@/features/map/scene/sceneBuilders";

/** キキクルの危険度の段（源泉`domain/weather_display.py`）。洪水の線を、配信元のタイルが持つ段の番号で塗る。 */
const RISK_LEVELS = weatherScales.risk_levels;
const LOWEST_RISK_LEVEL = RISK_LEVELS.reduce((lowest, level) => (level.level < lowest.level ? level : lowest));

const WEATHER = mapDisplay.weather;

type DeclaredElement = (typeof mapDisplay.weatherElements)[number];

type WeatherRenderKind = DeclaredElement["kind"];

/** 描き方ごとの、重なりの段とレイヤーの型。 */
const LAYER_OF_KIND = {
  rasterTile: { tier: "area", type: "raster" },
  gridFill: { tier: "area", type: "fill" },
  vectorTile: { tier: "observedLine", type: "line" },
  outline: { tier: "observedLine", type: "line" },
  gridMark: { tier: "point", type: "symbol" },
} as const satisfies Record<WeatherRenderKind, Pick<SceneLayerEntry, "tier" | "type">>;

/** いま届いている中身。種類が宣言と合うときだけ描く。 */
export type WeatherPayload =
  | { readonly kind: "rasterTile"; readonly tiles: readonly string[] }
  | { readonly kind: "vectorTile"; readonly tiles: readonly string[] }
  | { readonly kind: "gridFill"; readonly data: unknown }
  | { readonly kind: "gridMark"; readonly data: unknown }
  | { readonly kind: "outline"; readonly data: unknown };

/** 要素1つぶんの見た目。画面が決めてよいのはここだけ。 */
type Drawing = {
  readonly paint: Readonly<Record<string, unknown>>;
  readonly layout?: Readonly<Record<string, unknown>>;
  readonly filter?: FilterSpecification;
  /** 記号を描くのに要るアイコン。登録してからでないと出ない。 */
  readonly icon?: { readonly id: string; readonly create: () => ImageData };
  /** 主の線の下に敷く縁取りの線の見た目。背景の色に関わらず線を読めるようにする。 */
  readonly casing?: { readonly paint: Readonly<Record<string, unknown>> };
};

/** 宣言1件の鍵（チップ/名前付きソース/描き方）。同じ名前付きソースを描き方違いで2要素が名乗るため、
 * 描き方まで含めないと一意にならない。 */
type ElementKey<E> = E extends {
  readonly group: infer G extends string;
  readonly source: infer S extends string;
  readonly kind: infer K extends string;
}
  ? `${G}/${S}/${K}`
  : never;

/** 配信元が描いた画像は、どの要素も同じ濃さで重ねるだけなので個別の見た目を持たない。 */
type DrawnKey = ElementKey<Exclude<DeclaredElement, { kind: "rasterTile" }>>;

const EMPTY_FEATURE_COLLECTION = { type: "FeatureCollection", features: [] } as const;

/** 帯の下限と色の並びから、値→色の段階式を作る。 */
function bandColorExpression(value: unknown, stops: readonly { from: number; color: string }[]): unknown {
  const rest = stops.slice(1).flatMap((stop) => [stop.from, stop.color]);
  return ["step", ["to-number", value], stops[0]?.color ?? "rgba(0,0,0,0)", ...rest];
}

function aboveFilter(property: string, min: number): FilterSpecification {
  return [">", ["to-number", ["get", property]], min] as unknown as FilterSpecification;
}

const RASTER_DRAWING: Drawing = { paint: { "raster-opacity": AREA_OPACITY } };

/** 線状降水帯の雨域の輪郭線。色・太さは配信元の公式の画面の描画定義の値で、塗らず、属性も読まない。 */
const RAINBAND_OUTLINE_DRAWING: Drawing = {
  paint: {
    "line-color": weatherScales.linear_rainband_outline_color,
    "line-width": WEATHER.rainbandOutlineWidthPx,
  },
  layout: { "line-join": "round", "line-cap": "round" },
  casing: {
    paint: {
      "line-color": weatherScales.linear_rainband_outline_casing_color,
      "line-width": WEATHER.rainbandOutlineCasingWidthPx,
    },
  },
};

function markDrawing(options: {
  readonly iconId: string;
  readonly createIcon: () => ImageData;
  readonly color: unknown;
  readonly valueProperty: string;
  readonly rotateProperty?: string;
  readonly minScale: number;
  readonly maxScale: number;
  readonly fullScaleValue: number;
  readonly minValueToShow?: number;
}): Drawing {
  return {
    icon: { id: options.iconId, create: options.createIcon },
    layout: {
      "icon-image": options.iconId,
      "icon-rotate": options.rotateProperty === undefined ? 0 : ["to-number", ["get", options.rotateProperty]],
      "icon-rotation-alignment": options.rotateProperty === undefined ? "viewport" : "map",
      // 記号が密なズームでは間引く（重ねると格子が塗り潰しに見える）。
      "icon-allow-overlap": false,
      "icon-ignore-placement": false,
      "icon-size": zoomScaleExpression(
        [
          "interpolate",
          ["linear"],
          ["to-number", ["get", options.valueProperty]],
          0,
          options.minScale,
          options.fullScaleValue,
          options.maxScale,
        ],
        WEATHER.markSizeByZoom,
      ),
    },
    paint: {
      "icon-color": options.color,
      "icon-opacity": 1,
      // 記号の縁取り。背景の明暗に関わらず記号の形が読めるようにする。**主層と同じレイヤーの
      // paintで出す**——別レイヤーにすると、同じ位置に2枚並ぶぶん衝突判定で縁取りが全部落ちる。
      "icon-halo-color": palette.semantic.mark_halo,
      "icon-halo-width": WEATHER.markHaloWidthPx,
    },
    ...(options.minValueToShow === undefined
      ? {}
      : { filter: aboveFilter(options.valueProperty, options.minValueToShow) }),
  };
}

/** 配信元のラスタ以外の要素の見た目。**源泉に要素が増えて見た目が無ければ型検査が落ちる**
 * （鍵は生成物から導く）。 */
const DRAWINGS: { readonly [K in DrawnKey]: Drawing } = {
  "precipitationNowcast/main/gridFill": {
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
  "windVector/arrow/gridMark": markDrawing({
    iconId: "weather-wind-arrow",
    createIcon: createWindArrowIcon,
    color: bandColorExpression(
      ["get", "speed"],
      WIND_SPEED_COLOR_STOPS.map((stop) => ({ from: stop.speedMs, color: stop.color })),
    ),
    valueProperty: "speed",
    rotateProperty: "bearing",
    minScale: WEATHER.windIconScaleRange[0],
    maxScale: WEATHER.windIconScaleRange[1],
    fullScaleValue: WEATHER.windFullScaleMs,
    // ほぼ無風の矢印は向きが意味を持たない。
    minValueToShow: WIND_CALM_THRESHOLD_MS,
  }),
  "disaster/flood/vectorTile": {
    paint: {
      "line-color": [
        "match",
        ["to-number", ["get", "level"]],
        ...RISK_LEVELS.flatMap((level) => [level.level, level.color]),
        LOWEST_RISK_LEVEL.color,
      ],
      "line-width": zoomScaleExpression(1, WEATHER.floodLineWidthByZoom),
    },
    // 平常時の基準線（level=0）まで出すと、危険情報が無い日も川が全部塗られる。
    filter: aboveFilter("level", 0),
  },
  "precipitationNowcast/linearRainbandArea/outline": RAINBAND_OUTLINE_DRAWING,
  "precipitationNowcast/linearRainbandAreaForecast/outline": RAINBAND_OUTLINE_DRAWING,
  "disaster/liden/gridMark": markDrawing({
    iconId: "weather-liden",
    createIcon: createLidenIcon,
    // 落雷の強弱を配信元が持たないため、大きさはズームだけで決まる。
    color: palette.semantic.lightning,
    valueProperty: JMA_POINT_VALUE_PROPERTY,
    minScale: WEATHER.lightningIconScale,
    maxScale: WEATHER.lightningIconScale,
    fullScaleValue: 1,
  }),
};

/** 源泉の宣言1件を、地図へ渡すソース・レイヤーの材料へ移したもの。 */
type WeatherElement = {
  readonly group: string;
  readonly source: string;
  readonly kind: WeatherRenderKind;
  readonly drawing: Drawing;
  readonly sourceSpec: SceneSourceEntry["spec"];
  readonly sourceLayer?: string;
  /** 中身が届く前に指すタイル。**タイルを持たないソース宣言は成り立たない**ため、
   * 届くまでの間もここを指す（実データのない架空のURL）。**このURLは実際に要求されうる**
   * ——開発サーバーでは二重実行で一瞬表示状態になりうるので、配信元へ無駄な要求が
   * 飛んでも害のない先にしておく。 */
  readonly placeholderTiles?: readonly string[];
  /** 中身が届く前の GeoJSON（同じ理由で、空の中身を持たせる）。 */
  readonly placeholderData?: unknown;
};

function drawingOf(element: DeclaredElement): Drawing {
  if (element.kind === "rasterTile") return RASTER_DRAWING;
  return DRAWINGS[`${element.group}/${element.source}/${element.kind}` as DrawnKey];
}

function sourceOf(
  element: DeclaredElement,
): Pick<WeatherElement, "sourceSpec" | "sourceLayer" | "placeholderTiles" | "placeholderData"> {
  switch (element.kind) {
    case "rasterTile":
      return {
        sourceSpec: {
          type: "raster",
          tileSize: 256,
          minzoom: element.tile.minZoom,
          maxzoom: element.tile.maxZoom,
        },
        placeholderTiles: [jmaPlaceholderTileUrl(element)],
      };
    case "vectorTile":
      return {
        sourceSpec: { type: "vector", minzoom: element.tile.minZoom, maxzoom: element.tile.maxZoom },
        sourceLayer: element.tile.vectorLayer,
        placeholderTiles: [jmaPlaceholderTileUrl(element)],
      };
    case "gridFill":
    case "gridMark":
    case "outline":
      return { sourceSpec: { type: "geojson" }, placeholderData: EMPTY_FEATURE_COLLECTION };
  }
}

/** 並びは源泉の宣言のまま。同じ段（`LAYER_OF_KIND`）の中ではこの並びが重なり順になる。 */
const WEATHER_ELEMENTS: readonly WeatherElement[] = mapDisplay.weatherElements.map((element) => ({
  group: element.group,
  source: element.source,
  kind: element.kind,
  drawing: drawingOf(element),
  ...sourceOf(element),
}));

export type WeatherState = {
  /** 表示ON/OFFと中身。鍵は`weatherElementKey`が作る。 */
  readonly shown: ReadonlyMap<string, { readonly visible: boolean; readonly payload?: WeatherPayload }>;
};

export function weatherElementKey(element: Pick<WeatherElement, "group" | "source">): string {
  return `${element.group}/${element.source}`;
}

/** 登録が要るアイコン。**出す前に登録しないと記号が描かれない。** */
export const WEATHER_ICONS: readonly { id: string; create: () => ImageData }[] = WEATHER_ELEMENTS.flatMap((element) =>
  element.drawing.icon === undefined ? [] : [element.drawing.icon],
);

/** 要素が持つソースの名前。**チップidは源泉の語をそのまま使う**——ここで別の呼び名を
 * 付け直すと、源泉が知っているものに画面だけの語彙が重なる。1要素＝1ソース（要素ごとに
 * 配信先が違うため相乗りできない）。
 * **描き方も名前に含める**——同じ名前付きソースを描き方違いで2要素が名乗る（降水の`main`は
 * 配信元のラスタと自前の格子の面）。描き方を落とすとソースが1本へ畳まれ、後から名乗った側の
 * レイヤーが種類の合わないソースを指して、そのレイヤーだけが黙って描かれない。 */
function weatherSourceId(element: Pick<WeatherElement, "group" | "source" | "kind">): SceneSourceId {
  return sceneSourceId(`${element.group}-${element.source}-${element.kind}`);
}

export const weatherGroup = declareGroup<WeatherState>((state) => {
  const sources: SceneSourceEntry[] = [];
  const layers: SceneLayerEntry[] = [];

  for (const element of WEATHER_ELEMENTS) {
    const shown = state.shown.get(weatherElementKey(element));
    const payload = shown?.payload;
    const matches = payload !== undefined && payload.kind === element.kind;
    const id = weatherSourceId(element);
    const { drawing } = element;

    const sourceLayer = element.sourceLayer === undefined ? {} : { sourceLayer: element.sourceLayer };
    const tiles = matches && "tiles" in payload ? payload.tiles : element.placeholderTiles;
    const data = matches && "data" in payload ? payload.data : element.placeholderData;
    sources.push({
      id,
      spec: element.sourceSpec,
      ...sourceLayer,
      ...(tiles === undefined ? {} : { tiles }),
      ...(data === undefined ? {} : { data }),
    });

    const visible = (shown?.visible ?? false) && matches;
    const layerOf = (role: string, paint: SceneLayerEntry["paint"]): SceneLayerEntry => ({
      role,
      ...LAYER_OF_KIND[element.kind],
      source: id,
      ...sourceLayer,
      paint,
      ...(drawing.layout === undefined ? {} : { layout: drawing.layout }),
      visible,
      ...(drawing.filter === undefined ? {} : { filter: drawing.filter }),
    });
    // 縁取りは同じ段の中で主の線より先に積み、下に置く。
    if (drawing.casing !== undefined) layers.push(layerOf(`${element.kind}-casing`, drawing.casing.paint));
    layers.push(layerOf(element.kind, drawing.paint));
  }

  return { sources, layers };
});
