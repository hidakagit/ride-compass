/** 地図への呼び出しを順番に記録する代役。
 *
 * 新旧どちらの実装へも同じ筋書きを通し、出てくる呼び出し列を突き合わせるために使う。
 * 記録するのは**地図の中身を変える呼び出しと、その判断に使う問い合わせ**だけで、
 * 描画そのものは行わない。`maplibre-gl` の代役（`testing/maplibre.ts`）も、地図の中身の記録にこれを使う。
 */
interface TraceEntry {
  readonly call: string;
  readonly args: readonly unknown[];
}

interface FakeLayer {
  id: string;
  type: string;
  source?: string;
  visibility: string;
  filter?: unknown;
  paint: Record<string, unknown>;
  layout: Record<string, unknown>;
}

interface RecordingMap {
  /** 出た呼び出しの列（順序を持つ）。 */
  readonly trace: readonly TraceEntry[];
  /** いま載っているレイヤーのid（背面から前面の順）。 */
  layerOrder(): string[];
  layer(id: string): FakeLayer | undefined;
  sources(): string[];
  /** `addSource` に渡された宣言。 */
  sourceSpec(sourceId: string): unknown;
  featureState(sourceId: string, featureId: string): Record<string, unknown> | undefined;
  /** ソースへ最後に流し込まれた中身（`setData`・`setTiles`）。 */
  sourceContent(sourceId: string): { data?: unknown; tiles?: readonly string[] } | undefined;
  /** スタイルを差し替えたときの状態（このアプリが足したものが消える）。 */
  dropEverything(): void;
}

/**
 * `map`として実装へ渡す値と、記録を読む側のハンドルを返す。
 * `basemapLayerIds` は、スタイルが最初から持つ下地のレイヤー（背面から前面の順）。
 */
export function createRecordingMap(options: { styleReady?: boolean; basemapLayerIds?: readonly string[] } = {}) {
  const trace: TraceEntry[] = [];
  let layers: FakeLayer[] = (options.basemapLayerIds ?? []).map((id) => ({
    id,
    type: "background",
    visibility: "visible",
    paint: {},
    layout: {},
  }));
  let sources = new Map<string, unknown>();
  // **ソースの実体は id ごとに1つに保つ。** 実装側は「同じ中身なら流し込まない」の判定に
  // ソースのインスタンスを鍵として使うため、呼ぶたびに別物を返すと毎回作り直しになる。
  let sourceHandles = new Map<string, { setData: (data: unknown) => void; setTiles: (tiles: string[]) => void }>();
  const content = new Map<string, { data?: unknown; tiles?: readonly string[] }>();
  let featureStates = new Map<string, Record<string, unknown>>();

  const record = (call: string, ...args: unknown[]) => {
    trace.push({ call, args });
  };
  const indexOf = (id: string) => layers.findIndex((layer) => layer.id === id);
  // MapLibreは、ベクタのソースの地物の状態を source-layer の名指し無しでは扱わず、エラーの出来事にする。
  const refusesFeatureState = (target: { source: string; sourceLayer?: string }) =>
    (sources.get(target.source) as { type?: unknown } | undefined)?.type === "vector" && !target.sourceLayer;
  // MapLibreは、塗り・配置・絞り込みに null を渡すと、その指定を外して既定へ戻す（読み返すと undefined）。
  const assignOrDelete = (record: Record<string, unknown>, name: string, value: unknown) => {
    if (value === null || value === undefined) delete record[name];
    else record[name] = value;
  };
  const insert = (layer: FakeLayer, beforeId?: string) => {
    const at = beforeId ? indexOf(beforeId) : -1;
    if (at < 0) layers.push(layer);
    else layers.splice(at, 0, layer);
  };

  const map = {
    // スタイルの準備を待つ仕組み（`mapStyleOps.ts: runWhenStyleReady`）が読む印。
    __rcStyleReady: options.styleReady ?? true,

    getStyle: () => ({ layers: layers.map((layer) => ({ id: layer.id, type: layer.type })) }),
    getLayer: (id: string) => layers[indexOf(id)],
    getSource: (id: string) => sourceHandles.get(id),
    // 記号の絵はブラウザのcanvasが要るため、「登録済み」を返して作らせない
    // （比べたいのはレイヤーの構成で、絵の中身ではない）。
    hasImage: () => true,

    addSource: (id: string, spec: unknown) => {
      record("addSource", id, spec);
      sources.set(id, spec);
      sourceHandles.set(id, {
        setData: (data: unknown) => {
          record("setData", id, data);
          content.set(id, { ...content.get(id), data });
        },
        setTiles: (tiles: string[]) => {
          record("setTiles", id, tiles);
          content.set(id, { ...content.get(id), tiles });
        },
      });
    },
    removeSource: (id: string) => {
      record("removeSource", id);
      sources.delete(id);
      sourceHandles.delete(id);
      content.delete(id);
    },
    addLayer: (
      spec: { id: string; type: string; source?: string; paint?: unknown; layout?: unknown; filter?: unknown },
      beforeId?: string,
    ) => {
      record("addLayer", spec.id, beforeId ?? null, spec);
      // MapLibreは、前に置く相手が無いレイヤーをエラーの出来事にして載せない。
      if (beforeId !== undefined && indexOf(beforeId) < 0) return;
      const { visibility, ...layout } = (spec.layout as Record<string, unknown>) ?? {};
      insert(
        {
          id: spec.id,
          type: spec.type,
          source: spec.source,
          // 作るときの宣言をそのまま持つ——既定で見えることにすると、
          // 「隠したまま作る」を実装が守っているかを見られない。
          visibility: typeof visibility === "string" ? visibility : "visible",
          ...(spec.filter === undefined ? {} : { filter: spec.filter }),
          paint: { ...((spec.paint as Record<string, unknown>) ?? {}) },
          layout,
        },
        beforeId,
      );
    },
    removeLayer: (id: string) => {
      record("removeLayer", id);
      const at = indexOf(id);
      if (at >= 0) layers.splice(at, 1);
    },
    moveLayer: (id: string, beforeId?: string) => {
      record("moveLayer", id, beforeId ?? null);
      const at = indexOf(id);
      if (at < 0) return;
      const [layer] = layers.splice(at, 1);
      insert(layer, beforeId);
    },
    setPaintProperty: (id: string, name: string, value: unknown) => {
      record("setPaintProperty", id, name, value);
      const layer = layers[indexOf(id)];
      if (layer) assignOrDelete(layer.paint, name, value);
    },
    setLayoutProperty: (id: string, name: string, value: unknown) => {
      record("setLayoutProperty", id, name, value);
      const layer = layers[indexOf(id)];
      if (!layer) return;
      if (name === "visibility") layer.visibility = String(value);
      else assignOrDelete(layer.layout, name, value);
    },
    setFilter: (id: string, filter: unknown) => {
      record("setFilter", id, filter);
      const layer = layers[indexOf(id)];
      if (!layer) return;
      if (filter === null || filter === undefined) delete layer.filter;
      else layer.filter = filter;
    },
    setFeatureState: (target: { source: string; sourceLayer?: string; id: string }, state: Record<string, unknown>) => {
      record("setFeatureState", target.source, target.id, state);
      if (refusesFeatureState(target)) return;
      const key = `${target.source}:${target.id}`;
      featureStates.set(key, { ...(featureStates.get(key) ?? {}), ...state });
    },
    removeFeatureState: (target: { source: string; sourceLayer?: string; id?: string }, key?: string) => {
      record("removeFeatureState", target.source, target.id ?? null, key ?? null);
      if (refusesFeatureState(target)) return;
      if (target.id === undefined) {
        // ソース単位のクリア（MapLibreは全キー・全地物を落とす）。
        for (const stateKey of [...featureStates.keys()]) {
          if (stateKey.startsWith(`${target.source}:`)) featureStates.delete(stateKey);
        }
        return;
      }
      const entry = featureStates.get(`${target.source}:${target.id}`);
      if (entry && key) delete entry[key];
    },

    // 地図の生成・カメラ・購読は記録だけして何もしない。
    addControl: (...args: unknown[]) => record("addControl", ...args),
    on: (...args: unknown[]) => record("on", args[0]),
    once: (event: string, handler: () => void) => {
      record("once", event);
      if (event === "style.load" || event === "load") handler();
    },
    off: () => {},
    flyTo: (...args: unknown[]) => record("flyTo", ...args),
    fitBounds: (...args: unknown[]) => record("fitBounds", ...args),
    getZoom: () => 14,
    getBounds: () => ({ getWest: () => 139, getSouth: () => 35, getEast: () => 140, getNorth: () => 36 }),
    getCanvas: () => ({ clientWidth: 390, clientHeight: 812, style: {} }),
    isStyleLoaded: () => true,
    queryRenderedFeatures: () => [],
  };

  const handle: RecordingMap = {
    trace,
    layerOrder: () => layers.map((layer) => layer.id),
    layer: (id: string) => layers[indexOf(id)],
    sources: () => [...sources.keys()],
    sourceSpec: (sourceId) => sources.get(sourceId),
    featureState: (sourceId, featureId) => featureStates.get(`${sourceId}:${featureId}`),
    sourceContent: (sourceId) => content.get(sourceId),
    dropEverything: () => {
      layers = [];
      sources = new Map();
      sourceHandles = new Map();
      content.clear();
      featureStates = new Map();
      trace.push({ call: "__styleReplaced", args: [] });
    },
  };

  return { map, handle };
}
