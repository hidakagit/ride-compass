/** scene を組み立てる道具。
 *
 * 型の契約は`mapScene.ts`が持ち、ここはそれを作るときに**どの家族でも同じ形になるもの**
 * だけを置く。家族に固有のもの（どんな色で塗るか・何を宣言するか）はここへ入れない。
 */
import type { LayerSpecification } from "maplibre-gl";

import type { MapSceneLayer, MapSceneSource, MapSceneSourceContent, MapSceneTier } from "./mapScene";

/** レイヤー・ソースの id は役割から機械的に決める（役割を1つ足せば id も増える）。 */
export function sceneLayerId(prefix: string, role: string): string {
  return `${prefix}-${role}`;
}

/**
 * MapLibre のレイヤー宣言。`LayerSpecification` は `type` ごとの合併型のため、
 * paint/layout を外から受け取る形では合併型として組み立て直せない。
 * **この取り替えはここ1箇所だけに置く**。
 */
export function layerSpec(spec: {
  readonly id: string;
  readonly type: LayerSpecification["type"];
  readonly source: string;
  readonly sourceLayer?: string;
  readonly paint?: Readonly<Record<string, unknown>>;
  readonly layout?: Readonly<Record<string, unknown>>;
}): LayerSpecification {
  const { sourceLayer, ...rest } = spec;
  return {
    ...rest,
    ...(sourceLayer === undefined ? {} : { "source-layer": sourceLayer }),
  } as unknown as LayerSpecification;
}

/** 記号を拡大する曲線（ズーム→倍率）。**記号はどれも同じ曲線で拡大する**——家族ごとに
 * 別の曲線を使うと、同じ地図の中で拡大の速さが食い違う。
 *
 * 曲線が要るのは、`icon-size`が既定で画面上の固定ピクセルだからである。拡大するほど周囲の
 * 道路・建物は大きく描かれるのに記号だけ同じ大きさで残り、相対的に小さく・目立たなくなる。
 * 初期表示のズーム（13）を倍率1の基準に置く。 */
const ICON_ZOOM_SCALE: readonly (readonly [number, number])[] = [
  [10, 0.75],
  [13, 1],
  [16, 1.5],
  [19, 2],
];

/** 大きさを、ズームで決まる倍率で伸縮させる式。`base`は定数でも値から決まる式でもよい。 */
export function zoomScaleExpression(
  base: unknown,
  stops: readonly (readonly [number, number])[] = ICON_ZOOM_SCALE,
): unknown {
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    ...stops.flatMap(([zoom, factor]) => [zoom, typeof base === "number" ? base * factor : ["*", base, factor]]),
  ];
}

/** 実行時に入れ替わる GeoJSON の中身。ソースを作り直さずに当て直す。
 *
 * タイルと同じく**中身が変わっていないときは当て直さない**（呼び出し側が前回の宣言と
 * 比べる）——`setData`はネットワークへ出ないが、渡したデータをワーカーへ送り直して
 * インデックスを作り直させる。 */
export function geojsonContent(data: unknown): MapSceneSourceContent {
  return {
    spec: { data },
    replace: (source) => {
      (source as { setData: (data: unknown) => void }).setData(data);
    },
  };
}

/** 実行時に入れ替わるタイルのURL。ソースを作り直さずに当て直す
 * （作り直すと、取得済みのタイルを捨てることになる）。**URLが変わっていないときは当て直さない**
 * ——同じURLで`setTiles`を呼んでも、タイルの再取得とPNGデコード・GPUへの転送をやり直す。 */
export function tilesContent(tiles: readonly string[]): MapSceneSourceContent {
  return {
    spec: { tiles: [...tiles] },
    replace: (source) => {
      (source as { setTiles: (tiles: string[]) => void }).setTiles([...tiles]);
    },
  };
}

type SceneLayerDeclaration<Role extends string, State> = {
  readonly role: Role;
  /** 役割から決まった id を受け取り、そのレイヤーの宣言を返す。 */
  readonly build: (state: State, id: string) => {
    readonly spec: LayerSpecification;
    readonly hitTargets?: readonly string[];
    readonly filter?: MapSceneLayer["filter"];
    readonly visible?: boolean;
  };
};
