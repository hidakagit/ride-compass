/** MapLibreの地図インスタンスに対する、どのレイヤーからも使う低水準の操作。
 *
 * ここに置くのは「特定のレイヤー種を知らない」ものだけ。レイヤー固有の描画は
 * それぞれの担当ファイル（`features/map/scene/groups/*.ts`）が持つ。
 */
import type { ExpressionSpecification, FilterSpecification, Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import { debugLog } from "@/lib/debugLog";

/** 「面で塗る」レイヤー種。地図の一区画を色で覆い、下にあるものを隠す描き方をまとめて指す
 * （残りのline/symbol/circle/heatmapは線・記号として、面の上に乗って読まれる側）。 */
const AREA_LAYER_TYPES: ReadonlySet<string> = new Set(["background", "raster", "fill", "fill-extrusion", "hillshade"]);

function isAreaLayerType(type: string): boolean {
  return AREA_LAYER_TYPES.has(type);
}

/** 基礎地図のベクタタイルが道路網を収めているレイヤー名（OpenMapTilesスキーマ。
 * 基礎地図はこのスキーマのタイルを配る）。スタイルの並び順やレイヤーidと違い、
 * これはスキーマが公開している語彙で、配色や見せ方を変えても名前は変わらない。 */
const ROAD_NETWORK_SOURCE_LAYER = "transportation";

/** 面で塗るレイヤーを差し込む位置（このidのレイヤーの直前＝下へ入る）。基礎地図が道路網
 * （`source-layer`が`transportation`）を描き始める最初のレイヤーを返す。面はその下、つまり
 * 土地の塗り（公園・土地利用・水面・建物）の上・道路と地名の下に入る。
 *
 * **並び順から導いてはいけない**。基礎地図は面と線を交互に描き、道路網より後ろにも面を置く
 * （libertyでは建物のfill/fill-extrusionが道路・橋の41枚より後ろ）。「最後に面を描いた
 * レイヤーの次」を採ると位置が道路の後ろまで下がり、面が道路を覆ったまま残る。道路網より後ろの面は
 * `basemapAreaLayersAfter`が前へ動かす。
 *
 * 道路網を持たないスタイルでは-1（差し込み先が無く最前面になる）。 */
function areaLayerAnchorIndex(layers: readonly { id: string; "source-layer"?: string }[]): number {
  return layers.findIndex((layer) => layer["source-layer"] === ROAD_NETWORK_SOURCE_LAYER);
}

/** 文字に場所を譲る点を差し込む位置（このidのレイヤーの直前＝下へ入る）。基礎地図が最後まで続けて描く記号の並びの
 * 頭を返す。基礎地図は文字（地名・通りの名前・店や駅の印）を最後にまとめて描くが、その前にも記号を挟む（libertyでは道路網の
 * 途中に一方通行の矢印があり、その後ろに橋の線・建物・境界を描く）。最初の記号の層の下に入れると、その後ろの線と面が
 * 点の絵の上に描かれる。
 *
 * 求めるのはこのアプリのレイヤーが載る前（スタイルを読んだ直後）に限る——このアプリの線が最前面にあると、並びの頭が求まらない。 */
function labelLayerAnchorIndex(layers: readonly { type: string }[]): number {
  return layers.findLastIndex((layer) => layer.type !== "symbol") + 1;
}

/** 差し込み位置より後ろにある面レイヤーのid（追加順のまま）。基礎地図が道路より後ろに置いて
 * いる面（建物）を指す。 */
function basemapAreaLayersAfter(layers: readonly { id: string; type: string }[], anchorIndex: number): string[] {
  return layers
    .slice(anchorIndex + 1)
    .filter((layer) => isAreaLayerType(layer.type))
    .map((layer) => layer.id);
}

/** 基礎地図のベクタタイルが店・施設の点を収めているレイヤー名（OpenMapTilesスキーマ）。 */
const POI_SOURCE_LAYER = "poi";

/** 基礎地図の店・施設の種類（OpenMapTilesのスキーマの`poi`の値）。`class`はスキーマが束ねた種類（束ねる先の無い値は
 * `subclass`と同じ値）で、`class`が粗すぎる種類だけ`subclass`（元のOSMのタグの値）で名指す。 */
export type BasemapPoiKinds = { readonly class: readonly string[]; readonly subclass: readonly string[] };

export const NO_BASEMAP_POI_KINDS: BasemapPoiKinds = { class: [], subclass: [] };

/** 基礎地図の店・施設を描くレイヤーのうち、`kinds`の種類だけを描かないようにする。種類が空なら配信元の絞りへ戻す。
 * 何を隠すかは呼ぶ側が決める（このアプリの点の層が、同じ種類を出している間だけ隠す）。`prepareBasemap`が記録した
 * 配信元の絞りへ足すので、何度当てても絞りを重ねない。基礎地図の絞りは式の形（libertyはそう書いている）を前提にする
 * ——旧い形の絞りと式は1つの`all`に混ぜられない。 */
export function hideBasemapPois(map: MapLibreMap, kinds: BasemapPoiKinds): void {
  const tagged = map as unknown as StyleReadyTag;
  const original = tagged.__rcBasemapPoiFilters;
  if (original === undefined) return;
  const notHidden: ExpressionSpecification | null =
    kinds.class.length === 0 && kinds.subclass.length === 0
      ? null
      : [
          "!",
          [
            "any",
            ["in", ["get", "class"], ["literal", kinds.class]],
            ["in", ["get", "subclass"], ["literal", kinds.subclass]],
          ],
        ];
  for (const [layerId, filter] of original) {
    if (notHidden === null) map.setFilter(layerId, filter ?? null);
    else
      map.setFilter(layerId, filter === undefined ? notHidden : ["all", filter as ExpressionSpecification, notHidden]);
  }
  debugLog("map:lifecycle", "基礎地図の店・施設から隠す種類", { layers: [...original.keys()], ...kinds });
}

interface StyleReadyTag {
  __rcStyleReady?: boolean;
  __rcBasemapPrepared?: boolean;
  __rcAreaLayerAnchorId?: string;
  __rcLabelLayerAnchorId?: string;
  /** 基礎地図の店・施設を描くレイヤーの配信元の絞り（id → 絞り）。 */
  __rcBasemapPoiFilters?: ReadonlyMap<string, FilterSpecification | undefined>;
}

/** 基礎地図をこのアプリの層を重ねられる形にする。同じスタイルに対しては1度しか実行しない。
 * - 店・施設を描くレイヤーの配信元の絞りを記録する（隠すのは`hideBasemapPois`）
 * - 面レイヤーの差し込み位置を求めて記録し、基礎地図が道路より後ろに置いている面をその手前へ動かす
 * - 文字に場所を譲る点の差し込み位置を求めて記録する
 *
 * 建物を道路より前へ動かすと、基礎地図そのものの見た目も「建物の上に道路」へ変わる。
 * この地図はpitchを持たない（建物は平面の足元だけが描かれる）ため影響は小さく、面レイヤーが
 * 建物に穴を開けられない利点が上回る。
 *
 * 位置が求まらないスタイルでは面が最前面へ戻る＝面の濃さだけで下の情報の読みやすさが
 * 決まる状態に落ちるため、黙って続けずログへ残す。 */
export function prepareBasemap(map: MapLibreMap): void {
  const tagged = map as unknown as StyleReadyTag;
  if (tagged.__rcBasemapPrepared) return;
  // `getStyle()`がundefinedを返すのは、スタイルが読み込まれる前（最初の読み込みと、差分にできず作り直す
  // `setStyle()`から新しいスタイルの`style.load`まで）だけ。差分で当てる間は今のスタイルを返す（`reloadStyle`）。
  // undefinedの間は解決済みにせず、読めるようになった後の呼び出しへ回す。
  const style: StyleSpecification | undefined = map.getStyle();
  if (style === undefined) return;
  tagged.__rcBasemapPrepared = true;

  const { layers } = style;
  tagged.__rcBasemapPoiFilters = new Map(
    layers.flatMap((layer) =>
      "source-layer" in layer && layer["source-layer"] === POI_SOURCE_LAYER ? [[layer.id, layer.filter] as const] : [],
    ),
  );
  tagged.__rcLabelLayerAnchorId = layers[labelLayerAnchorIndex(layers)]?.id;
  debugLog("map:lifecycle", "文字に場所を譲る点の差し込み位置", { anchorId: tagged.__rcLabelLayerAnchorId ?? null });
  const anchorIndex = areaLayerAnchorIndex(layers);
  const anchorId = anchorIndex < 0 ? undefined : layers[anchorIndex].id;
  tagged.__rcAreaLayerAnchorId = anchorId;
  if (anchorId === undefined) {
    debugLog("map:lifecycle", "面レイヤーの差し込み位置が求まらず、面を最前面へ積む", { anchorId: null }, "warn");
    return;
  }
  const lowered = basemapAreaLayersAfter(layers, anchorIndex);
  for (const layerId of lowered) map.moveLayer(layerId, anchorId);
  debugLog("map:lifecycle", "面レイヤーの差し込み位置", { anchorId, lowered });
}

/** `prepareBasemap`が記録した位置。記録が無い・今のスタイルに無いときは
 * undefined（差し込まず最前面へ）——**今のスタイルに無いidを`addLayer`へ渡すと例外になる**。 */
function recordedAnchor(map: MapLibreMap, anchorId: string | undefined): string | undefined {
  return anchorId !== undefined && map.getLayer(anchorId) ? anchorId : undefined;
}

/** 面レイヤーの差し込み位置（`recordedAnchor`）。 */
export function areaLayerAnchor(map: MapLibreMap): string | undefined {
  return recordedAnchor(map, (map as unknown as StyleReadyTag).__rcAreaLayerAnchorId);
}

/** 文字に場所を譲る点の差し込み位置（`recordedAnchor`）。 */
export function labelLayerAnchor(map: MapLibreMap): string | undefined {
  return recordedAnchor(map, (map as unknown as StyleReadyTag).__rcLabelLayerAnchorId);
}

/** スタイルを`url`から取り直し、新しいスタイルが読み込まれたら（`style.load`）、次の`prepareBasemap`が新しいスタイルに
 * 対して改めて走るようにしてから`onLoaded`を呼ぶ。準備を解くのは読み込まれたあと——MapLibreの`setStyle`は既定で今の
 * スタイルとの差分を当て、差分が届くまで`getStyle()`は今の（このアプリの層を足し、店・施設を隠した）スタイルを返すので、
 * その間に準備し直すと、隠した後の絞りを配信元の絞りとして記録する。 */
export function reloadStyle(map: MapLibreMap, url: string, onLoaded: () => void): void {
  map.once("style.load", () => {
    (map as unknown as StyleReadyTag).__rcBasemapPrepared = false;
    onLoaded();
  });
  map.setStyle(url);
}

/** スタイルが一度でも読み込まれたか（`runWhenStyleReady`が記録する印）。 */
export function isStyleReady(map: MapLibreMap): boolean {
  return (map as unknown as StyleReadyTag).__rcStyleReady === true;
}

// map.isStyleLoaded()はタイル読み込み中も一時的にfalseを返すため、
// それをガードに使うと「loadイベントは一度しか発火しない」性質と組み合わさって
// 二度目以降の描画が永久にスキップされることがある。スタイル自体が一度でも
// 読み込まれたかどうかだけをmapインスタンスに記録し、それを判定に使う。
export function runWhenStyleReady(map: MapLibreMap, fn: () => void) {
  const tagged = map as unknown as StyleReadyTag;
  if (tagged.__rcStyleReady) {
    fn();
    return;
  }
  map.once("load", () => {
    tagged.__rcStyleReady = true;
    fn();
  });
}
