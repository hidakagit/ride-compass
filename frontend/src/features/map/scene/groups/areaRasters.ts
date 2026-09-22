/** 地域に固定され、時間で変わらない面（色別標高図・土地被覆・起伏の陰影）。
 *
 * どれも基礎地図の道路網より下へ入り、**明示的にONにしたものだけ**が出る。
 */
import { primaryAttributes } from "@/types/generated/primaryAttributes";
import regionTileConfig from "@/types/generated/region-tile-config.json";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";

/** 面の濃さ。**動かす前に`docs/modules/frontend/static-map-layers.md`「面の濃さ」を読む**
 * ——下限・上限の両方に根拠がある。 */
export const AREA_OPACITY = 0.55;

/** 土地被覆タイルが実データを持つ範囲（正本は配信側。生成物から受け取る）。 */
const LANDCOVER_ZOOM = { min: regionTileConfig.landcover.min_zoom, max: regionTileConfig.landcover.max_zoom };

/** 国土地理院タイル（配信元が実データを持つ上限・要求するURL・出典表記）。
 * **正本はbackend**（`domain/gsi_tiles.py`）。ここは受け取るだけで写しを持たない。 */
const GSI = regionTileConfig.gsi;

/** 標高(m) = 原点 + (R*65536 + G*256 + B) * 刻み。**係数は詰め方から決まる**ので、
 * backendが配る刻みと原点だけから組み立てる（係数を直に持つと詰め方の変更で黙ってずれる）。 */
const TERRAIN_RGB = {
  red: 256 * 256 * GSI.terrain.rgb_unit_m,
  green: 256 * GSI.terrain.rgb_unit_m,
  blue: GSI.terrain.rgb_unit_m,
  baseShift: -GSI.terrain.rgb_base_m,
} as const;
/** 上げるほど緩い斜面が読めるが、上げすぎると急斜面との差が潰れる。 */
const TERRAIN_EXAGGERATION = 5;

/** 陰影の濃さは影・光の色のalphaで渡す（hillshadeは不透明度のプロパティを持たない）。
 * 傾きが0の画素は影も光も出ないため、上げても平地は濁らない。 */
const HILLSHADE_SHADOW_COLOR = `rgba(60, 50, 40, ${AREA_OPACITY})`;
const HILLSHADE_HIGHLIGHT_COLOR = `rgba(255, 252, 245, ${AREA_OPACITY})`;
/** 北西からの斜め光（真上からだと起伏が出ない）。 */
const HILLSHADE_ILLUMINATION_DIRECTION = 315;
/** 既定の`standard`は傾きのsinに比例して塗るため、関東平野の傾き（数度）では実効の濃さが
 * 0.03を下回り、出ていても気づけない。`igor`は傾きのarctanに比例する。
 * **`basic`・`multidirectional`は使えない**——平坦な画素にも光を塗るため。 */
const HILLSHADE_METHOD = "igor";

/** 面で塗るもの。源泉が「面の幾何を持つ」と言った属性（標高・土地被覆）に、
 * `hillshade`を足す——**陰影は属性ではなく標高の別の描き方**で、同じ標高タイルを
 * 違う読み方（`raster-dem`）で描いたもの。源泉に属性として現れないのが正しい。 */
export type AreaRasterRole =
  | Extract<(typeof primaryAttributes)[number], { geometry: "area" }>["attr_id"]
  | "hillshade";

export type AreaRasterState = {
  /** 表示ON/OFF。指定が無い役割は出さない。 */
  readonly visible: Readonly<Partial<Record<AreaRasterRole, boolean>>>;
  /** タイルを取りに行くオリジン（環境で変わる）。 */
  readonly tileOrigin: string;
  /** 土地被覆タイルのURL（世代込みで配信側が組み立てたもの）。 */
  readonly landcoverTileUrl: string;
};

export const AREA_SOURCE_ID: Record<AreaRasterRole, string> = {
  elevation: "area-elevation",
  landcover: "area-landcover",
  hillshade: "area-hillshade",
};

function sourcesFor(state: AreaRasterState): readonly SceneSourceEntry[] {
  return [
    {
      id: AREA_SOURCE_ID.elevation,
      spec: { type: "raster", tileSize: 256, maxzoom: GSI.relief.max_zoom, attribution: GSI.relief.attribution },
      tiles: [`${state.tileOrigin}${GSI.relief.tile_url}`],
    },
    {
      id: AREA_SOURCE_ID.landcover,
      spec: { type: "raster", tileSize: 256, minzoom: LANDCOVER_ZOOM.min, maxzoom: LANDCOVER_ZOOM.max },
      tiles: [state.landcoverTileUrl],
    },
    {
      id: AREA_SOURCE_ID.hillshade,
      spec: {
        type: "raster-dem",
        tileSize: 256,
        maxzoom: GSI.terrain.max_zoom,
        // backendが配信元の独自エンコードをTerrain-RGBへ移して返す。係数へ強調倍率を
        // 掛けるためcustomにする。
        encoding: "custom",
        redFactor: TERRAIN_RGB.red * TERRAIN_EXAGGERATION,
        greenFactor: TERRAIN_RGB.green * TERRAIN_EXAGGERATION,
        blueFactor: TERRAIN_RGB.blue * TERRAIN_EXAGGERATION,
        baseShift: TERRAIN_RGB.baseShift * TERRAIN_EXAGGERATION,
      },
      tiles: [`${state.tileOrigin}${GSI.terrain.tile_url}`],
    },
  ];
}

function layersFor(state: AreaRasterState): readonly SceneLayerEntry[] {
  const visible = (role: AreaRasterRole) => state.visible[role] === true;
  return [
    {
      role: "elevation",
      tier: "area",
      source: AREA_SOURCE_ID.elevation,
      type: "raster",
      paint: { "raster-opacity": AREA_OPACITY },
      visible: visible("elevation"),
    },
    {
      role: "landcover",
      tier: "area",
      source: AREA_SOURCE_ID.landcover,
      type: "raster",
      paint: { "raster-opacity": AREA_OPACITY },
      visible: visible("landcover"),
    },
    {
      role: "hillshade",
      tier: "area",
      source: AREA_SOURCE_ID.hillshade,
      type: "hillshade",
      paint: {
        "hillshade-method": HILLSHADE_METHOD,
        // igorは傾きの大きさを`exaggeration * 2`倍してから角度へ直す。上限の1にする。
        "hillshade-exaggeration": 1,
        "hillshade-shadow-color": HILLSHADE_SHADOW_COLOR,
        "hillshade-highlight-color": HILLSHADE_HIGHLIGHT_COLOR,
        "hillshade-illumination-direction": HILLSHADE_ILLUMINATION_DIRECTION,
        "hillshade-illumination-anchor": "map",
      },
      visible: visible("hillshade"),
    },
  ];
}

export const areaRasterGroup = declareGroup<AreaRasterState>("area", (state) => ({
  sources: sourcesFor(state),
  layers: layersFor(state),
}));
