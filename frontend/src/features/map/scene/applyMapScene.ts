import type { FeatureIdentifier, FilterSpecification, LayerSpecification, SourceSpecification } from "maplibre-gl";

import {
  isTierUnderBasemapRoads,
  orderedSceneLayers,
  type MapScene,
  type MapSceneFeatureStateValue,
  type MapSceneFeatureStates,
  type MapSceneLayer,
  type MapSceneSource,
} from "./mapScene";

/** 地図のうち scene が使う口だけを表した形。MapLibre の `Map` はそのまま渡せる。 */
export type MapSceneTarget = {
  getSource(id: string): unknown;
  addSource(id: string, source: SourceSpecification): unknown;
  removeSource(id: string): unknown;
  addLayer(layer: LayerSpecification, beforeId?: string): unknown;
  removeLayer(id: string): unknown;
  setFilter(layerId: string, filter?: FilterSpecification | null): unknown;
  setPaintProperty(layerId: string, name: string, value: unknown): unknown;
  setLayoutProperty(layerId: string, name: string, value: unknown): unknown;
  setFeatureState(target: FeatureIdentifier, state: Record<string, MapSceneFeatureStateValue>): unknown;
  removeFeatureState(target: FeatureIdentifier, key?: string): unknown;
};

type ApplyMapSceneOptions = {
  /** いま載っているべき宣言。 */
  readonly scene: MapScene;
  /**
   * 前回この関数が当てた宣言。**この関数は地図を読み返さず、これを地図の状態そのものとして
   * 扱う**。スタイルを差し替えたら `EMPTY_MAP_SCENE` を渡す。
   */
  readonly previous: MapScene;
  /**
   * 面の段をこのレイヤーの直下へ差し込む。基礎地図のどこから道路網が始まるかは
   * 呼び出し側が決め、この関数は地図を調べない。省略すると面も他の段と同じく
   * 基礎地図の上へ載る（段どうしの前後だけは保たれる）。
   */
  readonly areaLayerBeforeId?: string;
};

const NO_FEATURE_STATES: MapSceneFeatureStates = new Map();

/**
 * scene を地図へ当てる唯一の関数。前回との差分だけを触り、scene が名指ししていない
 * レイヤー・ソース（基礎地図など）には触れない。
 */
export function applyMapScene(map: MapSceneTarget, options: ApplyMapSceneOptions): void {
  const { scene, previous, areaLayerBeforeId } = options;

  const previousSources = new Map(previous.sources.map((s) => [s.id, s]));
  const nextSourceIds = new Set(scene.sources.map((s) => s.id));
  const previousLayers = new Map(previous.layers.map((l) => [l.spec.id, l]));

  // ソースを作り直すのは、作った後に変えられない宣言が変わったときだけ。
  const recreated = new Set(
    scene.sources
      .filter((source) => {
        const before = previousSources.get(source.id);
        return before !== undefined && !isSameValue(before.spec, source.spec);
      })
      .map((source) => source.id),
  );

  const ordered = orderedSceneLayers(scene);
  const keptIds = new Set(ordered.map((layer) => layer.spec.id));
  const present = new Set<string>();
  for (const [id, layer] of previousLayers) {
    const sourceId = sourceIdOf(layer.spec);
    const staysOnMap = keptIds.has(id) && !(sourceId !== undefined && recreated.has(sourceId));
    if (staysOnMap) present.add(id);
    else map.removeLayer(id);
  }

  for (const id of previousSources.keys()) {
    if (nextSourceIds.has(id) && !recreated.has(id)) continue;
    map.removeSource(id);
  }

  for (const source of scene.sources) {
    const before = recreated.has(source.id) ? undefined : previousSources.get(source.id);
    if (before === undefined) {
      map.addSource(source.id, sourceSpecFor(source));
    } else if (!isSameValue(before.content?.spec, source.content?.spec)) {
      source.content?.replace(map.getSource(source.id));
    }
  }

  ordered.forEach((layer, index) => {
    const id = layer.spec.id;
    const before = previousLayers.get(id);
    if (before !== undefined && present.has(id)) {
      updateLayer(map, layer, before);
      return;
    }
    map.addLayer(layerSpecFor(layer), anchorFor(layer, ordered.slice(index + 1), present, areaLayerBeforeId));
    present.add(id);
  });

  for (const source of scene.sources) {
    // 作り直したソースは feature-state ごと消えているため、前回は無かったものとして当て直す。
    const applied = recreated.has(source.id) ? undefined : previousSources.get(source.id)?.featureStates;
    applyFeatureStates(map, source, applied, source.featureStates);
  }
}

/**
 * 1枚足すときの差し込み位置。段の順で自分より前面にあり、かつ既に地図へ載っている
 * 最初のレイヤーの直下へ入れる——これで、足す順に関わらず段の順が保たれる。
 */
function anchorFor(
  layer: MapSceneLayer,
  laterLayers: readonly MapSceneLayer[],
  present: ReadonlySet<string>,
  areaLayerBeforeId: string | undefined,
): string | undefined {
  const goesUnder = (candidate: MapSceneLayer): boolean =>
    areaLayerBeforeId !== undefined && isTierUnderBasemapRoads(candidate.tier);
  const under = goesUnder(layer);
  for (const later of laterLayers) {
    if (goesUnder(later) !== under) continue;
    if (present.has(later.spec.id)) return later.spec.id;
  }
  return under ? areaLayerBeforeId : undefined;
}

function sourceSpecFor(source: MapSceneSource): SourceSpecification {
  return {
    ...source.spec,
    ...(source.content?.spec ?? {}),
  } as unknown as SourceSpecification;
}

function updateLayer(map: MapSceneTarget, layer: MapSceneLayer, before: MapSceneLayer): void {
  const id = layer.spec.id;

  applyRecordDiff(paintOf(before.spec), paintOf(layer.spec), (name, value) => {
    map.setPaintProperty(id, name, value);
  });
  applyRecordDiff(layoutWithoutVisibility(before.spec), layoutWithoutVisibility(layer.spec), (name, value) => {
    map.setLayoutProperty(id, name, value);
  });

  if (before.visible !== layer.visible) {
    map.setLayoutProperty(id, "visibility", visibilityOf(layer));
  }
  if (!isSameValue(before.filter, layer.filter)) {
    map.setFilter(id, layer.filter ?? null);
  }
}

/**
 * ソース単位の一括クリアは、そのソースの feature-state が1つも残らないときだけ使う
 * ——`removeFeatureState` は source/sourceLayer 単位で全キーをまとめて消すため、
 * まだ値を持っている別のキーまで巻き添えにする。
 */
function applyFeatureStates(
  map: MapSceneTarget,
  source: MapSceneSource,
  before: MapSceneFeatureStates | undefined,
  after: MapSceneFeatureStates | undefined,
): void {
  const previousStates = before ?? NO_FEATURE_STATES;
  const nextStates = after ?? NO_FEATURE_STATES;
  const sourceTarget: FeatureIdentifier = {
    source: source.id,
    sourceLayer: source.sourceLayer,
  };

  if (nextStates.size === 0) {
    if (previousStates.size > 0) map.removeFeatureState(sourceTarget);
    return;
  }

  for (const [key, previousValues] of previousStates) {
    const nextValues = nextStates.get(key);
    for (const featureId of previousValues.keys()) {
      if (nextValues?.has(featureId) === true) continue;
      map.removeFeatureState({ ...sourceTarget, id: featureId }, key);
    }
  }

  const pending = new Map<string, Record<string, MapSceneFeatureStateValue>>();
  for (const [key, nextValues] of nextStates) {
    const previousValues = previousStates.get(key);
    for (const [featureId, value] of nextValues) {
      if (isSameValue(previousValues?.get(featureId), value)) continue;
      const state = pending.get(featureId) ?? {};
      state[key] = value;
      pending.set(featureId, state);
    }
  }
  for (const [featureId, state] of pending) {
    map.setFeatureState({ ...sourceTarget, id: featureId }, state);
  }
}

function visibilityOf(layer: MapSceneLayer): "visible" | "none" {
  return layer.visible ? "visible" : "none";
}

/**
 * `LayerSpecification` は `type` ごとの合併型のため、layout を差し替えた形を
 * 合併型として組み立て直せない。
 */
function layerSpecFor(layer: MapSceneLayer): LayerSpecification {
  const spec: Record<string, unknown> = {
    ...(layer.spec as unknown as Record<string, unknown>),
    layout: {
      ...layoutWithoutVisibility(layer.spec),
      visibility: visibilityOf(layer),
    },
  };
  delete spec.filter;
  if (layer.filter !== undefined) spec.filter = layer.filter;
  return spec as unknown as LayerSpecification;
}

function sourceIdOf(spec: LayerSpecification): string | undefined {
  return (spec as { source?: string }).source;
}

function paintOf(spec: LayerSpecification): Record<string, unknown> {
  return (spec as { paint?: Record<string, unknown> }).paint ?? {};
}

function layoutWithoutVisibility(spec: LayerSpecification): Record<string, unknown> {
  const layout = { ...((spec as { layout?: Record<string, unknown> }).layout ?? {}) };
  delete layout.visibility;
  return layout;
}

/** 消えたプロパティは `null` で既定へ戻す（MapLibre の指定の外し方）。 */
function applyRecordDiff(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
  set: (name: string, value: unknown) => void,
): void {
  for (const [name, value] of Object.entries(after)) {
    if (isSameValue(before[name], value)) continue;
    set(name, value);
  }
  for (const name of Object.keys(before)) {
    if (name in after) continue;
    set(name, null);
  }
}

function isSameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((item, i) => isSameValue(item, b[i]));
  }
  if (isPlainObject(a) && isPlainObject(b)) {
    const keys = Object.keys(a);
    return keys.length === Object.keys(b).length && keys.every((key) => key in b && isSameValue(a[key], b[key]));
  }
  return false;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
