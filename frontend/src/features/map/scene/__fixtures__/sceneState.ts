// sceneの入口（`sceneInputsFrom`）へ渡す状態。既定は「何も出していない」空だけで、見たい性質は
// 各テストが上書きで書く。
import type { MapLayerVisibility } from "@/features/map/layers/mapLayers";
import type { sceneInputsFrom } from "@/features/map/scene/applyToMap";

export type SceneState = Parameters<typeof sceneInputsFrom>[0];
type Look = SceneState["look"];

export type SceneStateOverrides = Omit<Partial<SceneState>, "look" | "catalog"> & {
  look?: Omit<Partial<Look>, "layerVisibility"> & { layerVisibility?: Record<string, boolean> };
  catalog?: Partial<SceneState["catalog"]>;
};

export function sceneState(overrides: SceneStateOverrides = {}): SceneState {
  const { look = {}, catalog = {}, ...rest } = overrides;
  return {
    routes: [],
    selectedRouteId: null,
    spliceStretches: [],
    splicedRoute: null,
    experimentSlots: [],
    tileVersionsReady: true,
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
