// sceneの入口（`sceneInputsFrom`）へ渡す状態。既定は「何も出していない」空とタイルの世代が揃った状態だけで、
// 見たい性質は各テストが上書きで書く。
import type { MapLayerVisibility } from "@/features/map/layers/mapLayers";
import { completeTileVersions } from "@/features/map/regionApi";
import type { sceneInputsFrom } from "@/features/map/scene/applyToMap";
import regionTileConfig from "@/types/generated/region-tile-config.json";

export type SceneState = Parameters<typeof sceneInputsFrom>[0];
type Look = SceneState["look"];

export type SceneStateOverrides = Omit<Partial<SceneState>, "look" | "catalog"> & {
  look?: Omit<Partial<Look>, "layerVisibility"> & { layerVisibility?: Record<string, boolean> };
  catalog?: Partial<SceneState["catalog"]>;
};

const READY_TILE_VERSIONS = completeTileVersions(
  Object.fromEntries(regionTileConfig.tile_version_kinds.map((kind) => [kind, "1-test"])),
);

export function sceneState(overrides: SceneStateOverrides = {}): SceneState {
  const { look = {}, catalog = {}, ...rest } = overrides;
  return {
    routes: [],
    selectedRouteId: null,
    spliceStretches: [],
    splicedRoute: null,
    experimentSlots: [],
    tileVersions: READY_TILE_VERSIONS,
    inspectedWayId: null,
    ...rest,
    look: {
      dynamicWeather: {},
      lens: "none",
      paintedAxisId: null,
      dedicatedWayValues: new Map(),
      hiddenLegendKeys: {},
      ...look,
      layerVisibility: (look.layerVisibility ?? {}) as MapLayerVisibility,
    },
    catalog: { rampAxes: [], dedicatedAxes: [], routeStyleModes: [], secondaryAxes: [], ...catalog },
  };
}
