/**
 * `maplibre-gl` の代役。地図の部品を本物で描くテストが、描画の手前（WebGL を要する所）で差し替えるのに使う
 * （docs/conventions/testing.md「確かめる高さ」の境界の表の「テスト環境に無いブラウザの機能」）。
 *
 * 代役は MapLibre の振る舞いを真似ず、受けたものを記録して返すだけにする:
 * - ソース・レイヤー・地物の状態は `mapTrace/recordingMap.ts` へ記録し、`MapOnScreen` から読む。
 * - 印（`Marker`）とポップアップ（`Popup`）は、渡された要素を地図の器へ置く（画面の問い合わせで引ける）。
 * - カメラの操作（`fitBounds`）とスタイルの取り直し（`setStyle`）は、引数を残す。
 * - 出来事（"load"・"click" 等）は自分では起こさず、テストが `MapOnScreen` で起こす。押した所に描かれている地物も、
 *   テストが渡したものを返す。
 *
 * `vi.mock` は import より先へ巻き上げられるため、`vi.mock("maplibre-gl", () => import("@/testing/maplibre"))` の形で置く。
 */
import type { Coordinates } from "@/types/route";

import { createRecordingMap } from "./mapTrace/recordingMap";

type Handler = (event: Record<string, unknown>) => void;
type Listener = { readonly type: string; readonly layerId?: string; readonly handler: Handler; readonly once: boolean };
type LngLat = { lng: number; lat: number };

/** 押した所に描かれている地物。`layer` は描いているレイヤーの id。 */
export interface PointedFeature {
  readonly layer: string;
  readonly properties: Record<string, unknown>;
  readonly geometry?: GeoJSON.Geometry;
}

function toLngLat(value: readonly [number, number] | LngLat): LngLat {
  return "lng" in value ? { lng: value.lng, lat: value.lat } : { lng: value[0], lat: value[1] };
}

class Evented {
  private listeners: Listener[] = [];

  on(type: string, layerIdOrHandler: string | Handler, handler?: Handler) {
    this.listeners.push(
      typeof layerIdOrHandler === "string"
        ? { type, layerId: layerIdOrHandler, handler: handler!, once: false }
        : { type, handler: layerIdOrHandler, once: false },
    );
    return this;
  }

  once(type: string, handler: Handler) {
    this.listeners.push({ type, handler, once: true });
    return this;
  }

  off(type: string, layerIdOrHandler: string | Handler, handler?: Handler) {
    const [layerId, target] =
      typeof layerIdOrHandler === "string" ? [layerIdOrHandler, handler] : [undefined, layerIdOrHandler];
    this.listeners = this.listeners.filter(
      (listener) => !(listener.type === type && listener.layerId === layerId && listener.handler === target),
    );
    return this;
  }

  /** 登録の順に呼ぶ。レイヤーを指した購読へは、そのレイヤーの地物が `features` にあるときだけ、その地物を渡す。 */
  protected fire(type: string, event: Record<string, unknown> = {}, features: readonly PointedFeature[] = []) {
    for (const listener of [...this.listeners]) {
      if (listener.type !== type) continue;
      if (listener.once) this.listeners = this.listeners.filter((entry) => entry !== listener);
      if (listener.layerId === undefined) {
        listener.handler(event);
        continue;
      }
      const onLayer = features.filter((feature) => feature.layer === listener.layerId).map(asRendered);
      if (onLayer.length > 0) listener.handler({ ...event, features: onLayer });
    }
  }
}

function asRendered(feature: PointedFeature) {
  return { layer: { id: feature.layer }, properties: feature.properties, geometry: feature.geometry };
}

export class LngLatBounds {
  readonly points: LngLat[] = [];

  extend(point: readonly [number, number]) {
    this.points.push(toLngLat(point));
    return this;
  }
}

export class NavigationControl {}

export class Marker extends Evented {
  readonly element: HTMLElement;
  draggable: boolean;
  private lngLat: LngLat = { lng: 0, lat: 0 };
  private map: StandInMap | null = null;

  constructor(options: { element?: HTMLElement; draggable?: boolean } = {}) {
    super();
    this.element = options.element ?? document.createElement("div");
    this.draggable = options.draggable ?? false;
  }

  setLngLat(lngLat: readonly [number, number] | LngLat) {
    this.lngLat = toLngLat(lngLat);
    return this;
  }

  getLngLat() {
    return this.lngLat;
  }

  setDraggable(draggable: boolean) {
    this.draggable = draggable;
    return this;
  }

  addTo(map: StandInMap) {
    this.map = map;
    map.markers.add(this);
    map.getContainer().append(this.element);
    return this;
  }

  remove() {
    this.map?.markers.delete(this);
    this.element.remove();
    return this;
  }
}

export class Popup extends Evented {
  private lngLat: LngLat = { lng: 0, lat: 0 };
  private content: Node | null = null;

  setLngLat(lngLat: readonly [number, number] | LngLat) {
    this.lngLat = toLngLat(lngLat);
    return this;
  }

  getLngLat() {
    return this.lngLat;
  }

  setDOMContent(content: Node) {
    this.content = content;
    return this;
  }

  addTo(map: StandInMap) {
    if (this.content !== null) map.getContainer().append(this.content);
    return this;
  }

  remove() {
    if (this.content !== null) this.content.parentNode?.removeChild(this.content);
    return this;
  }
}

/** 地図の中身（ソース・レイヤー・地物の状態）を記録する操作。ここから先は `recordingMap` へそのまま渡す。 */
const STYLE_OPERATIONS = [
  "getStyle",
  "getLayer",
  "getSource",
  "hasImage",
  "addSource",
  "removeSource",
  "addLayer",
  "removeLayer",
  "moveLayer",
  "setPaintProperty",
  "setLayoutProperty",
  "setFilter",
  "setFeatureState",
  "removeFeatureState",
] as const;

const drawn: StandInMap[] = [];

class StandInMap extends Evented {
  readonly markers = new Set<Marker>();
  readonly fits: { bounds: LngLatBounds; options: unknown }[] = [];
  readonly styles: string[];
  readonly content: ReturnType<typeof createRecordingMap>["handle"];
  private readonly container: HTMLElement;
  private readonly canvas: HTMLCanvasElement;
  private readonly zoom: number;
  private pointed: readonly PointedFeature[] = [];

  constructor(options: { container: HTMLElement; style: string; zoom: number }) {
    super();
    const { map, handle } = createRecordingMap({ styleReady: false });
    Object.assign(this, Object.fromEntries(STYLE_OPERATIONS.map((name) => [name, map[name]])));
    this.content = handle;
    this.container = options.container;
    this.styles = [options.style];
    this.zoom = options.zoom;
    // 描画面は窓いっぱいとして大きさを返す（テスト環境はレイアウトの実寸を0で返す）。
    this.canvas = document.createElement("canvas");
    Object.defineProperties(this.canvas, {
      clientWidth: { value: window.innerWidth },
      clientHeight: { value: window.innerHeight },
    });
    this.container.append(this.canvas);
    drawn.push(this);
  }

  getContainer() {
    return this.container;
  }

  getCanvas() {
    return this.canvas;
  }

  getZoom() {
    return this.zoom;
  }

  getBounds() {
    return null;
  }

  addControl() {
    return this;
  }

  resize() {
    return this;
  }

  flyTo() {
    return this;
  }

  fitBounds(bounds: LngLatBounds, options: unknown) {
    this.fits.push({ bounds, options });
    return this;
  }

  setStyle(style: string) {
    this.styles.push(style);
    this.content.dropEverything();
    return this;
  }

  isSourceLoaded() {
    return false;
  }

  querySourceFeatures() {
    return [];
  }

  queryRenderedFeatures(_point: unknown, options: { layers?: readonly string[] } = {}) {
    return this.pointed
      .filter((feature) => options.layers === undefined || options.layers.includes(feature.layer))
      .map(asRendered);
  }

  remove() {
    drawn.splice(drawn.indexOf(this), 1);
  }

  /** テストが起こす出来事。 */
  emit(type: string) {
    this.fire(type);
  }

  /** `lngLat` を押す。`features` はそこに描かれている地物。 */
  click(lngLat: Coordinates, features: readonly PointedFeature[]) {
    this.pointed = features;
    try {
      this.fire("click", { lngLat: { lng: lngLat.longitude, lat: lngLat.latitude }, point: { x: 0, y: 0 } }, features);
    } finally {
      this.pointed = [];
    }
  }
}

export { StandInMap as Map };

export function addProtocol() {}

export function setWorkerUrl() {}

/** いま描かれている地図。 */
export interface MapOnScreen {
  /** 出来事を起こす（"load"・"style.load" 等）。 */
  emit(type: string): void;
  /** `lngLat` を押す。`features` はそこに描かれている地物。 */
  click(lngLat: Coordinates, features?: readonly PointedFeature[]): void;
  /** いま表示しているレイヤーの id。 */
  visibleLayerIds(): string[];
  /** GeoJSON のソースへ最後に渡された地物。ソースが無ければ空。 */
  sourceFeatures(sourceId: string): GeoJSON.Feature[];
  /** 地図に置いた印。 */
  markers(): { coordinates: Coordinates; draggable: boolean; element: HTMLElement }[];
  /** 収めた範囲の指定（古い順）。 */
  readonly fits: readonly { bounds: LngLatBounds; options: unknown }[];
  /** 求めたスタイル（最初の1つと、取り直しの分）。 */
  readonly styles: readonly string[];
}

/** ソースへ最後に渡された中身（作ったときの宣言の `data` か、そのあとの `setData`）。消えていれば undefined。 */
function lastData(trace: StandInMap["content"]["trace"], sourceId: string): unknown {
  for (const { call, args } of [...trace].reverse()) {
    if (call === "__styleReplaced") return undefined;
    if (args[0] !== sourceId) continue;
    if (call === "setData") return args[1];
    if (call === "addSource") return (args[1] as { data?: unknown }).data;
    if (call === "removeSource") return undefined;
  }
  return undefined;
}

export function mapOnScreen(): MapOnScreen {
  const map = drawn.at(-1);
  if (map === undefined) throw new Error("地図が描かれていない");
  return {
    emit: (type) => map.emit(type),
    click: (lngLat, features = []) => map.click(lngLat, features),
    visibleLayerIds: () => map.content.layerOrder().filter((id) => map.content.layer(id)?.visibility !== "none"),
    sourceFeatures: (sourceId) =>
      (lastData(map.content.trace, sourceId) as GeoJSON.FeatureCollection | undefined)?.features ?? [],
    markers: () =>
      [...map.markers].map((marker) => ({
        coordinates: { latitude: marker.getLngLat().lat, longitude: marker.getLngLat().lng },
        draggable: marker.draggable,
        element: marker.element,
      })),
    fits: map.fits,
    styles: map.styles,
  };
}
