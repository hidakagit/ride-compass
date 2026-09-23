import type { FilterSpecification, LayerSpecification, SourceSpecification } from "maplibre-gl";

/**
 * 重なりの段。背面から前面の順に並べ、地図上の重なりはこの宣言だけが決める
 * （scene を組み立てる側が配列へ挿す位置では決まらない）。
 * 並びは「後から前面へ積まれる側が、先に積まれた側を塗り潰さない」ように決める。
 * 面の塗りは下にあるものを隠すため、基礎地図の道路網より下へ潜らせる。
 */
const MAP_SCENE_TIERS = [
  { id: "area", underBasemapRoads: true },
  { id: "estimatedLine", underBasemapRoads: false },
  { id: "observedLine", underBasemapRoads: false },
  { id: "lensLine", underBasemapRoads: false },
  { id: "point", underBasemapRoads: false },
  { id: "route", underBasemapRoads: false },
] as const;

export type MapSceneTier = (typeof MAP_SCENE_TIERS)[number]["id"];

export function isTierUnderBasemapRoads(tier: MapSceneTier): boolean {
  return MAP_SCENE_TIERS.some((entry) => entry.id === tier && entry.underBasemapRoads);
}

/** feature-state へ載せられる値。 */
export type MapSceneFeatureStateValue = string | number | boolean | null;

/**
 * feature-state。外側のキーが state のキー、内側のキーが feature の id。
 * feature の id は文字列のまま保つ——配信側の id の体系は数値とは限らず、
 * 数値へ変換すると黙って NaN へ潰れて色が付かなくなる。
 */
export type MapSceneFeatureStates = ReadonlyMap<string, ReadonlyMap<string, MapSceneFeatureStateValue>>;

type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

/**
 * ソースを作るときの宣言。作り直さずには変えられないものだけを持つ。
 * 実行時に入れ替わる中身は型の上でここへ書けない——両方が持てると、入れ替えで済むものまで
 * 作り直して取得済みのタイルを捨てることになる。
 */
type MapSceneSourceSpec = DistributiveOmit<SourceSpecification, "tiles" | "data">;

/**
 * あとから入れ替わるソースの中身。どう入れ替えるかは種類ごとに違うため、
 * 当てる側ではなく宣言する側が持つ。
 */
export type MapSceneSourceContent = {
  /** 作成時の宣言へ混ぜる部分。ここが変わったときだけ `replace` が呼ばれる。 */
  readonly spec: Readonly<Record<string, unknown>>;
  /** ソースを作り直さずに中身を当て直す。引数は地図が持つソース。 */
  readonly replace: (source: unknown) => void;
};

export type MapSceneSource = {
  readonly id: string;
  readonly spec: MapSceneSourceSpec;
  readonly content?: MapSceneSourceContent;
  /** feature-state を当てる source-layer。ベクタタイルでは必須。 */
  readonly sourceLayer?: string;
  readonly featureStates?: MapSceneFeatureStates;
};

export type MapSceneLayer = {
  /**
   * MapLibre のレイヤー宣言。id はこの中の `id` が唯一の出どころ。
   * `type`・`source`・`source-layer` は作った後に変えられないため、別のものを描くなら
   * 別の id にする。`layout.visibility` と `filter` はここへ書いても読まれない
   * ——下の `visible`・`filter` が唯一の持ち主で、両方が持てる形にすると
   * 「今は条件なし」と「外側が管理しているので触るな」が区別できなくなる。
   */
  readonly spec: LayerSpecification;
  /** 宣言したときの役割。**idの綴りを知らなくても引ける**ようにここへ残す
   * （idはソース名＋役割で、ソース名は宣言側が決める）。 */
  readonly role: string;
  /** 同じ id で段を変えない（重なりは足された時点の段で決まる）。 */
  readonly tier: MapSceneTier;
  readonly visible: boolean;
  /**
   * 押したときに拾う対象としての名前。空なら押せない。
   * 既定値を持たず1枚ごとに宣言する——既定があると、新しいレイヤーが黙ってどちらかへ入り、
   * 「カーソルは変わるのに何も起きない」という形で後から出る。
   */
  readonly hitTargets: readonly string[];
  /** 省略は「絞り込み無し」。前回あった絞り込みは解除される。 */
  readonly filter?: FilterSpecification;
};

/**
 * 地図に載っているべきものの宣言。ソース・レイヤーの id はそれぞれ一意。
 * 表示 ON/OFF・絞り込み・feature-state もここが持つ——スタイルを差し替えると
 * これらは地図から消えるため、宣言から辿れない位置に置いたものは作り直されない。
 */
export type MapScene = {
  readonly sources: readonly MapSceneSource[];
  readonly layers: readonly MapSceneLayer[];
};

/** スタイルを差し替えた直後に「前回」として渡すと、scene 全体が作り直される。 */
export const EMPTY_MAP_SCENE: MapScene = { sources: [], layers: [] };

/** 段の順に並べ替えたレイヤー。同じ段の中は scene が並べた順を保つ。 */
export function orderedSceneLayers(scene: MapScene): readonly MapSceneLayer[] {
  return scene.layers
    .map((layer, index) => ({ layer, index }))
    .sort((a, b) => tierIndex(a.layer.tier) - tierIndex(b.layer.tier) || a.index - b.index)
    .map((entry) => entry.layer);
}

/** 押せるレイヤーの id。MapLibre へ渡すのは呼び出し側で、ここは宣言から導くだけ。 */
export function interactiveSceneLayerIds(scene: MapScene): readonly string[] {
  return sceneLayerIdsWhere(scene, (layer) => layer.hitTargets.length > 0);
}

/** ある対象を拾うレイヤーの id。対象を増やしてもこの関数は変わらない。 */
export function sceneLayerIdsForHitTarget(scene: MapScene, target: string): readonly string[] {
  return sceneLayerIdsWhere(scene, (layer) => layer.hitTargets.includes(target));
}

function tierIndex(tier: MapSceneTier): number {
  return MAP_SCENE_TIERS.findIndex((entry) => entry.id === tier);
}

function sceneLayerIdsWhere(scene: MapScene, keep: (layer: MapSceneLayer) => boolean): readonly string[] {
  return orderedSceneLayers(scene)
    .filter(keep)
    .map((layer) => layer.spec.id);
}
