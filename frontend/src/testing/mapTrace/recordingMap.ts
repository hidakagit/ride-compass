/** 地図への呼び出しを順番に記録する代役。
 *
 * 新旧どちらの実装へも同じ筋書きを通し、出てくる呼び出し列を突き合わせるために使う。
 * 記録するのは**地図の中身を変える呼び出しと、その判断に使う問い合わせ**だけで、
 * 描画そのものは行わない。
 */
export interface TraceEntry {
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

export interface RecordingMap {
  /** 出た呼び出しの列（順序を持つ）。 */
  readonly trace: readonly TraceEntry[];
  /** いま載っているレイヤーのid（背面から前面の順）。 */
  layerOrder(): string[];
  layer(id: string): FakeLayer | undefined;
  sources(): string[];
  featureState(sourceId: string, featureId: string): Record<string, unknown> | undefined;
  /** ソースへ最後に流し込まれた中身（`setData`・`setTiles`）。 */
  sourceContent(sourceId: string): { data?: unknown; tiles?: readonly string[] } | undefined;
  /** スタイルを差し替えたときの状態（このアプリが足したものが消える）。 */
  dropEverything(): void;
  reset(): void;
}

/** `map`として実装へ渡す値と、記録を読む側のハンドルを返す。 */
export function createRecordingMap(options: { styleReady?: boolean; imagesRegistered?: boolean } = {}) {
  const trace: TraceEntry[] = [];
  let layers: FakeLayer[] = [];
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
    // アイコンの生成はブラウザのcanvasを要るため、既定では「登録済み」を返して作らせない
    // （比べたいのはレイヤーの構成で、画像の中身ではない）。
    hasImage: (id: string) => (options.imagesRegistered ?? true) || sources.has(`image:${id}`),

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
    addImage: (id: string, ...rest: unknown[]) => {
      record("addImage", id, ...rest);
      sources.set(`image:${id}`, true);
    },
    addLayer: (
      spec: { id: string; type: string; source?: string; paint?: unknown; layout?: unknown },
      beforeId?: string,
    ) => {
      record("addLayer", spec.id, beforeId ?? null, spec);
      insert(
        {
          id: spec.id,
          type: spec.type,
          source: spec.source,
          visibility: "visible",
          paint: { ...((spec.paint as Record<string, unknown>) ?? {}) },
          layout: { ...((spec.layout as Record<string, unknown>) ?? {}) },
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
      if (layer) layer.paint[name] = value;
    },
    setLayoutProperty: (id: string, name: string, value: unknown) => {
      record("setLayoutProperty", id, name, value);
      const layer = layers[indexOf(id)];
      if (!layer) return;
      if (name === "visibility") layer.visibility = String(value);
      else layer.layout[name] = value;
    },
    setFilter: (id: string, filter: unknown) => {
      record("setFilter", id, filter);
      const layer = layers[indexOf(id)];
      if (layer) layer.filter = filter;
    },
    setFeatureState: (target: { source: string; sourceLayer?: string; id: string }, state: Record<string, unknown>) => {
      record("setFeatureState", target.source, target.id, state);
      const key = `${target.source}:${target.id}`;
      featureStates.set(key, { ...(featureStates.get(key) ?? {}), ...state });
    },
    removeFeatureState: (target: { source: string; sourceLayer?: string; id?: string }, key?: string) => {
      record("removeFeatureState", target.source, target.id ?? null, key ?? null);
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
    reset: () => {
      layers = [];
      sources = new Map();
      sourceHandles = new Map();
      content.clear();
      featureStates = new Map();
      trace.length = 0;
    },
  };

  return { map, handle };
}
