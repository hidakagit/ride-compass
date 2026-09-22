/** 地図に載るものを、1つの形で宣言する。
 *
 * 種類（面・道路の線・点・評価軸・ルート・気象）で書き方を変えない——**どれも
 * 「いまの状態から、載っているべきレイヤーの並びを返す」1つの形**で表す。役割が固定の
 * ものは固定の並びを返し、実行時に増減するものは状態から導いた並びを返す。
 *
 * 見た目の値はこのファイルが持つ（呼び出し側は埋めない）。外から来る値——実行時に
 * 増減する軸・タイルの配信先と世代・取得した中身——だけを状態として受け取る。
 */
import type { FilterSpecification, LayerSpecification } from "maplibre-gl";

import type { LegendEntry } from "@/components/Map/legendFilter";

import { orderedSceneLayers } from "./mapScene";
import type { MapScene, MapSceneFeatureStates, MapSceneLayer, MapSceneSource, MapSceneTier } from "./mapScene";
import { geojsonContent, layerSpec, sceneLayerId, type SceneSourceId, tilesContent } from "./sceneBuilders";

/** 凡例の1行。**地図と凡例が同じ1つの形を共有する**——別々に持つと色が静かに食い違う。
 * `values` は「この行に属するタイルの値」で、地図の絞り込みと色分けの両方がこれを使う。 */
export type LegendRow = Pick<LegendEntry, "key" | "label" | "color"> & {
  readonly values: readonly (string | boolean)[];
};

/** レイヤー1枚ぶんの宣言。id は役割から決まる。
 *
 * **宣言を1件足すと、地図のレイヤーが1枚増える。** 段・表示・押せるかの付け方を家族ごとに
 * 書かないための形で、どの家族でも同じ——足す場所が1つだから、増やしたときに
 * 「差し込み位置を書き忘れて最前面へ出る」類の食い違いが起きない。 */
export type SceneLayerEntry = {
  /** 役割。id の綴りはここから機械的に決まる。 */
  readonly role: string;
  readonly tier: MapSceneTier;
  readonly source: SceneSourceId;
  readonly sourceLayer?: string;
  readonly type: LayerSpecification["type"];
  readonly paint?: Readonly<Record<string, unknown>>;
  readonly layout?: Readonly<Record<string, unknown>>;
  readonly visible: boolean;
  /** 押したときに拾う対象。空なら押せない。 */
  readonly hitTargets?: readonly string[];
  readonly filter?: FilterSpecification;
};

/** ソース1本ぶんの宣言。同じ id を複数のグループが名乗ってもよい——束ねる側が1本へ畳む。 */
export type SceneSourceEntry = {
  readonly id: SceneSourceId;
  readonly spec: MapSceneSource["spec"];
  readonly sourceLayer?: string;
  /** 実行時に入れ替わるタイルのURL。 */
  readonly tiles?: readonly string[];
  /** 実行時に入れ替わる GeoJSON。 */
  readonly data?: unknown;
  /** feature-state。同じソースへ複数のグループが載せたものは、束ねる側が1つへ畳む。 */
  readonly featureStates?: MapSceneFeatureStates;
};

/** 地図に載るもののひとまとまり。状態から、ソースとレイヤーの並びを返す。 */
export type SceneGroup<State> = {
  /** ソース名の接頭辞。**レイヤーidには入らない**（レイヤーidはソース名＋役割）。 */
  readonly idPrefix: string;
  readonly build: (state: State) => {
    readonly sources: readonly SceneSourceEntry[];
    readonly layers: readonly SceneLayerEntry[];
  };
};

export function declareGroup<State>(idPrefix: string, build: SceneGroup<State>["build"]): SceneGroup<State> {
  return { idPrefix, build };
}

/**
 * グループの並びを scene へ畳む。
 *
 * **重なりは段（tier）だけが決める**ので、グループをどの順で並べても結果は変わらない
 * （同じ段の中だけは、宣言の順を保つ）。同じソースを複数のグループが名乗ったときは
 * 1本へ畳み、feature-state は合わせる——ソースは地図に1本しか作れないため。
 */
export function composeScene<State>(groups: readonly SceneGroup<State>[], state: State): MapScene {
  const sources = new Map<string, MapSceneSource>();
  const layers: MapSceneLayer[] = [];

  for (const group of groups) {
    const built = group.build(state);
    for (const entry of built.sources) mergeSource(sources, entry);
    for (const entry of built.layers) layers.push(toSceneLayer(group.idPrefix, entry));
  }

  // 段で並べ直してから返す——ここで正規化しておけば、下流はグループの並べ方を知らずに済む。
  return { sources: [...sources.values()], layers: [...orderedSceneLayers({ sources: [], layers })] };
}

function toSceneLayer(idPrefix: string, entry: SceneLayerEntry): MapSceneLayer {
  return {
    role: entry.role,
    spec: layerSpec({
      id: sceneLayerId(entry.source, entry.role),
      type: entry.type,
      source: entry.source,
      ...(entry.sourceLayer === undefined ? {} : { sourceLayer: entry.sourceLayer }),
      ...(entry.paint === undefined ? {} : { paint: entry.paint }),
      ...(entry.layout === undefined ? {} : { layout: entry.layout }),
    }),
    tier: entry.tier,
    visible: entry.visible,
    hitTargets: entry.hitTargets ?? [],
    ...(entry.filter === undefined ? {} : { filter: entry.filter }),
  };
}

function mergeSource(into: Map<string, MapSceneSource>, entry: SceneSourceEntry): void {
  const content = entry.tiles !== undefined ? tilesContent(entry.tiles) : entry.data !== undefined ? geojsonContent(entry.data) : undefined;
  const existing = into.get(entry.id);
  if (existing === undefined) {
    into.set(entry.id, {
      id: entry.id,
      spec: entry.spec,
      ...(entry.sourceLayer === undefined ? {} : { sourceLayer: entry.sourceLayer }),
      ...(content === undefined ? {} : { content }),
      ...(entry.featureStates === undefined ? {} : { featureStates: entry.featureStates }),
    });
    return;
  }
  // 同じソースを2つのグループが名乗った。地図には1本しか作れないので、feature-state だけを
  // 合わせる——宣言（タイルの配信先・source-layer）は先に名乗った側を使う。
  if (entry.featureStates === undefined) return;
  const merged = new Map(existing.featureStates ?? []);
  for (const [key, values] of entry.featureStates) merged.set(key, values);
  into.set(entry.id, { ...existing, featureStates: merged });
}
