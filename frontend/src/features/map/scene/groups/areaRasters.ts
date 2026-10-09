/** 地域に固定され、時間で変わらない面（起伏の陰影）。
 *
 * 基礎地図の道路網より下へ入り、**明示的にONにしたときだけ**出る。
 */
import { sceneSourceId, type SceneSourceId } from "@/features/map/scene/sceneBuilders";
import { mapDisplay } from "@/types/generated/mapDisplay";
import regionTileConfig from "@/types/generated/region-tile-config.json";

import { declareGroup, type SceneLayerEntry, type SceneSourceEntry } from "@/features/map/scene/mapSceneGroups";

/** 面の濃さ。**動かす前に`docs/modules/frontend/static-map-layers.md`「面の濃さ」を読む**
 * ——下限・上限の両方に根拠がある。 */
const AREA = mapDisplay.area;
export const AREA_OPACITY = AREA.opacity;

/** 国土地理院の標高タイル（実データを持つ上限・要求するURL）。 */
const GSI = regionTileConfig.gsi;

/** 標高(m) = 原点 + (R*65536 + G*256 + B) * 刻み。**係数は詰め方から決まる**ので、
 * backendが配る刻みと原点だけから組み立てる。 */
const TERRAIN_RGB = {
  red: 256 * 256 * GSI.terrain.rgb_unit_m,
  green: 256 * GSI.terrain.rgb_unit_m,
  blue: GSI.terrain.rgb_unit_m,
  baseShift: -GSI.terrain.rgb_base_m,
} as const;

type AreaRasterRole = "hillshade";

export type AreaRasterState = {
  /** 表示ON/OFF。指定が無い役割は出さない。 */
  readonly visible: Readonly<Partial<Record<AreaRasterRole, boolean>>>;
  /** タイルを取りに行くオリジン（環境で変わる）。 */
  readonly tileOrigin: string;
};

export const AREA_SOURCE_ID: Record<AreaRasterRole, SceneSourceId> = {
  hillshade: sceneSourceId("area-hillshade"),
};

function sourcesFor(state: AreaRasterState): readonly SceneSourceEntry[] {
  return [
    {
      id: AREA_SOURCE_ID.hillshade,
      spec: {
        type: "raster-dem",
        tileSize: 256,
        maxzoom: GSI.terrain.max_zoom,
        // backendが配信元の独自エンコードをTerrain-RGBへ移して返す。係数へ強調倍率を
        // 掛けるためcustomにする。
        encoding: "custom",
        redFactor: TERRAIN_RGB.red * AREA.terrainExaggeration,
        greenFactor: TERRAIN_RGB.green * AREA.terrainExaggeration,
        blueFactor: TERRAIN_RGB.blue * AREA.terrainExaggeration,
        baseShift: TERRAIN_RGB.baseShift * AREA.terrainExaggeration,
      },
      tiles: [`${state.tileOrigin}${GSI.terrain.tile_url}`],
    },
  ];
}

function layersFor(state: AreaRasterState): readonly SceneLayerEntry[] {
  const visible = (role: AreaRasterRole) => state.visible[role] === true;
  return [
    {
      role: "hillshade",
      tier: "area",
      source: AREA_SOURCE_ID.hillshade,
      type: "hillshade",
      paint: {
        "hillshade-method": AREA.hillshadeMethod,
        "hillshade-exaggeration": AREA.hillshadeExaggeration,
        "hillshade-shadow-color": AREA.hillshadeShadowColor,
        "hillshade-highlight-color": AREA.hillshadeHighlightColor,
        "hillshade-illumination-direction": AREA.hillshadeIlluminationDeg,
        "hillshade-illumination-anchor": "map",
      },
      visible: visible("hillshade"),
    },
  ];
}

export const areaRasterGroup = declareGroup<AreaRasterState>((state) => ({
  sources: sourcesFor(state),
  layers: layersFor(state),
}));
