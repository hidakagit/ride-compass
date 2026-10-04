/**
 * 地図の代役（`recordingMap.ts`）と本物の `maplibre-gl` の `Map` へ同じ順に流す呼び出しと、そのあと地図に載っている
 * べきもの。代役は vitest（`recordingMap.test.ts`）で、本物は実ブラウザ（`e2e/recording-map.spec.ts`）で流す——本物は
 * WebGL を要し、テスト環境（happy-dom）では作れない。
 *
 * 呼び出しは scene が地図に使う口（`features/map/scene/applyMapScene.ts: MapSceneTarget`）に限る。e2e も読むので、
 * vitest を読み込まない。
 */

/** 地図の口を1つ呼ぶ。`source` があれば、そのソース（`getSource` の戻り値）の口を呼ぶ。 */
export type MapStep = { readonly call: string; readonly args: readonly unknown[]; readonly source?: string };

/** 載っているレイヤー1枚（背面から前面の順）。`paint` は名指しした項目だけを読む。 */
export type MapLayerReading = {
  readonly id: string;
  readonly visibility: string;
  readonly paint: Readonly<Record<string, unknown>>;
  readonly filter: unknown;
};

export type MapReading = {
  readonly layers: readonly MapLayerReading[];
  /** 名指しした地物の状態（消えていれば空）。 */
  readonly featureStates: readonly {
    readonly source: string;
    readonly id: number;
    readonly state: Record<string, unknown>;
  }[];
  /** 名指ししたソースへ最後に流し込んだ GeoJSON。 */
  readonly sourceData: readonly { readonly source: string; readonly data: unknown }[];
};

export type MapContractCase = {
  readonly name: string;
  readonly steps: readonly MapStep[];
  readonly expected: MapReading;
};

const EMPTY = { type: "FeatureCollection", features: [] } as const;

function point(id: number) {
  return { type: "Feature", id, geometry: { type: "Point", coordinates: [139.7, 35.7] }, properties: {} } as const;
}

function circle(id: string, layout: Record<string, unknown> = {}) {
  return { id, type: "circle", source: "points", layout };
}

const ADD_POINTS: MapStep = { call: "addSource", args: ["points", { type: "geojson", data: EMPTY }] };

export const MAP_CONTRACT: readonly MapContractCase[] = [
  {
    name: "レイヤーは前に置く相手の直下へ入り、相手を名指ししなければ最前面に載り、名指しした相手が無ければ載らず、外したものは消える",
    steps: [
      ADD_POINTS,
      { call: "addLayer", args: [circle("a")] },
      { call: "addLayer", args: [circle("b")] },
      { call: "addLayer", args: [circle("c"), "a"] },
      { call: "addLayer", args: [circle("d")] },
      { call: "addLayer", args: [circle("e"), "missing"] },
      { call: "removeLayer", args: ["b"] },
    ],
    expected: {
      layers: [
        { id: "c", visibility: "visible", paint: {}, filter: undefined },
        { id: "a", visibility: "visible", paint: {}, filter: undefined },
        { id: "d", visibility: "visible", paint: {}, filter: undefined },
      ],
      featureStates: [],
      sourceData: [],
    },
  },
  {
    name: "作るときの見え方の宣言が残り、あとから見え方・塗り・絞り込みを変えられる",
    steps: [
      ADD_POINTS,
      { call: "addLayer", args: [circle("hidden", { visibility: "none" })] },
      { call: "addLayer", args: [circle("shown")] },
      { call: "setLayoutProperty", args: ["shown", "visibility", "none"] },
      { call: "setLayoutProperty", args: ["hidden", "visibility", "visible"] },
      { call: "setPaintProperty", args: ["hidden", "circle-radius", 4] },
      { call: "setFilter", args: ["hidden", ["==", ["get", "kind"], "a"]] },
    ],
    expected: {
      layers: [
        { id: "hidden", visibility: "visible", paint: { "circle-radius": 4 }, filter: ["==", ["get", "kind"], "a"] },
        { id: "shown", visibility: "none", paint: {}, filter: undefined },
      ],
      featureStates: [],
      sourceData: [],
    },
  },
  {
    name: "地物の状態は鍵ごとに重ね、鍵を名指しして消すとその鍵だけが消える",
    steps: [
      { call: "addSource", args: ["points", { type: "geojson", data: { ...EMPTY, features: [point(1), point(2)] } }] },
      { call: "setFeatureState", args: [{ source: "points", id: 1 }, { hover: true }] },
      { call: "setFeatureState", args: [{ source: "points", id: 1 }, { selected: true }] },
      { call: "setFeatureState", args: [{ source: "points", id: 2 }, { hover: true }] },
      { call: "removeFeatureState", args: [{ source: "points", id: 1 }, "hover"] },
    ],
    expected: {
      layers: [],
      featureStates: [
        { source: "points", id: 1, state: { selected: true } },
        { source: "points", id: 2, state: { hover: true } },
      ],
      sourceData: [],
    },
  },
  {
    name: "地物を名指しせずに消すと、そのソースの地物の状態だけが全部消える",
    steps: [
      { call: "addSource", args: ["points", { type: "geojson", data: { ...EMPTY, features: [point(1)] } }] },
      { call: "addSource", args: ["others", { type: "geojson", data: { ...EMPTY, features: [point(1)] } }] },
      { call: "setFeatureState", args: [{ source: "points", id: 1 }, { hover: true }] },
      { call: "setFeatureState", args: [{ source: "others", id: 1 }, { hover: true }] },
      { call: "removeFeatureState", args: [{ source: "points" }] },
    ],
    expected: {
      layers: [],
      featureStates: [
        { source: "points", id: 1, state: {} },
        { source: "others", id: 1, state: { hover: true } },
      ],
      sourceData: [],
    },
  },
  {
    name: "ソースへ流し込んだ GeoJSON が、最後に流し込んだものになる",
    steps: [
      ADD_POINTS,
      { call: "setData", source: "points", args: [{ ...EMPTY, features: [point(1)] }] },
      { call: "setData", source: "points", args: [{ ...EMPTY, features: [point(2)] }] },
    ],
    expected: {
      layers: [],
      featureStates: [],
      sourceData: [{ source: "points", data: { ...EMPTY, features: [point(2)] } }],
    },
  },
];
