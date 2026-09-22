/** 地域に固定され、時間で変わらない面（色別標高図・土地被覆・起伏の陰影）。
 *
 * どれも基礎地図の道路網より下へ入り、**明示的にONにしたものだけ**が出る。
 */
import regionTileConfig from "@/types/generated/region-tile-config.json";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "../mapSceneGroups";

/** 面の濃さ。
 *
 * 下げると薄い階級が背景と区別できなくなり、上げると面の下にある基礎地図の土地の塗りが
 * 潰れる。上下から挟まれているため、片側だけを見て動かさない。 */
const AREA_OPACITY = 0.55;

/** 土地被覆タイルが実データを持つ範囲（正本は配信側。生成物から受け取る）。 */
const LANDCOVER_ZOOM = { min: regionTileConfig.landcover.min_zoom, max: regionTileConfig.landcover.max_zoom };

const RELIEF_TILE_PATH = "/api/gsi-relief-tile/xyz/relief/{z}/{x}/{y}.png";
const RELIEF_MAX_ZOOM = 15;
const RELIEF_ATTRIBUTION =
  '<a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank" rel="noreferrer">地理院タイル(色別標高図)</a>';

const TERRAIN_TILE_PATH = "/api/gsi-terrain-tile/{z}/{x}/{y}.png";
/** 配信元が実データを持つ上限。これより上はMapLibreが拡大して見せる
 * （正本はbackendの`services/terrain_tile_service.py`）。 */
const TERRAIN_MAX_ZOOM = 14;
/** 標高の復元式の係数（正本はbackendの`domain/terrain_rgb.py`）。
 * **タイルの値は実際の標高のまま**で、読み方だけを強調する。 */
const TERRAIN_RGB = { red: 6553.6, green: 25.6, blue: 0.1, baseShift: 10000 } as const;
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

export type AreaRasterRole = "elevation" | "landcover" | "hillshade";

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
      spec: { type: "raster", tileSize: 256, maxzoom: RELIEF_MAX_ZOOM, attribution: RELIEF_ATTRIBUTION },
      tiles: [`${state.tileOrigin}${RELIEF_TILE_PATH}`],
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
        maxzoom: TERRAIN_MAX_ZOOM,
        // backendが配信元の独自エンコードをTerrain-RGBへ移して返す。係数へ強調倍率を
        // 掛けるためcustomにする。
        encoding: "custom",
        redFactor: TERRAIN_RGB.red * TERRAIN_EXAGGERATION,
        greenFactor: TERRAIN_RGB.green * TERRAIN_EXAGGERATION,
        blueFactor: TERRAIN_RGB.blue * TERRAIN_EXAGGERATION,
        baseShift: TERRAIN_RGB.baseShift * TERRAIN_EXAGGERATION,
      },
      tiles: [`${state.tileOrigin}${TERRAIN_TILE_PATH}`],
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
