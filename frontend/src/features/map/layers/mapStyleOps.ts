/** MapLibreの地図インスタンスに対する、どのレイヤーからも使う低水準の操作。
 *
 * ここに置くのは「特定のレイヤー種を知らない」ものだけ。レイヤー固有の描画は
 * それぞれの担当ファイル（`features/map/scene/groups/*.ts`）が持つ。
 */
import type { ExpressionSpecification, Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
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

/** 基礎地図に出さない店・施設の種類（OpenMapTilesのスキーマの`poi`の値）。このアプリの点の層が同じ種類をOSMでない
 * 出どころから出すもの——同じ種類を基礎地図（OSM）と混ぜて出すと、ODbLの共有の義務がかかる。`class`はスキーマが束ねた
 * 種類（束ねる先の無い値は`subclass`と同じ値）で、`class`が粗すぎる種類だけ`subclass`で名指す（コンビニは店全体の`shop`に入る）。
 * 病院・銀行・郵便局・学校と駅・バス・空港（`poi_transit`）は出したまま残す。 */
const BASEMAP_POIS_SHOWN_ELSEWHERE: { readonly class: readonly string[]; readonly subclass: readonly string[] } = {
  class: [
    // 立ち寄り先の飲食店
    "restaurant",
    "fast_food",
    "cafe",
    "bar",
    "beer",
    "ice_cream",
    // 立ち寄り先の自転車（店・貸し自転車）
    "bicycle",
    "bicycle_rental",
    // 立ち寄り先の景色・名所（公園・庭園・城・博物館・観光地と展望地）
    "park",
    "garden",
    "castle",
    "museum",
    "attraction",
    // 立ち寄り先の宿（ホテル・旅館の類とキャンプ場）
    "lodging",
    "campsite",
    // 立ち寄り先の寺社は文化財の一覧から出す
    "place_of_worship",
  ],
  // 補給の点のコンビニはOverture Mapsの地点から出す
  subclass: ["convenience"],
};

/** 基礎地図の店・施設を描く全部のレイヤーの絞りに「`BASEMAP_POIS_SHOWN_ELSEWHERE`の種類でない」を足す。
 * 基礎地図の絞りは式の形（libertyはそう書いている）を前提にする——旧い形の絞りと式は1つの`all`に混ぜられない。 */
function hideBasemapPoisShownElsewhere(map: MapLibreMap, layers: StyleSpecification["layers"]): void {
  const notShownElsewhere: ExpressionSpecification = [
    "!",
    [
      "any",
      ["in", ["get", "class"], ["literal", BASEMAP_POIS_SHOWN_ELSEWHERE.class]],
      ["in", ["get", "subclass"], ["literal", BASEMAP_POIS_SHOWN_ELSEWHERE.subclass]],
    ],
  ];
  const hidden: string[] = [];
  for (const layer of layers) {
    if (!("source-layer" in layer) || layer["source-layer"] !== POI_SOURCE_LAYER) continue;
    map.setFilter(
      layer.id,
      layer.filter === undefined
        ? notShownElsewhere
        : ["all", layer.filter as ExpressionSpecification, notShownElsewhere],
    );
    hidden.push(layer.id);
  }
  debugLog("map:lifecycle", "基礎地図の店・施設から隠す種類", { layers: hidden, ...BASEMAP_POIS_SHOWN_ELSEWHERE });
}

interface StyleReadyTag {
  __rcStyleReady?: boolean;
  __rcBasemapPrepared?: boolean;
  __rcAreaLayerAnchorId?: string;
}

/** 基礎地図をこのアプリの層を重ねられる形にする。同じスタイルに対しては1度しか実行しない。
 * - 店・施設のうち、このアプリの点の層が別の出どころから出す種類を隠す（`hideBasemapPoisShownElsewhere`）
 * - 面レイヤーの差し込み位置を求めて記録し、基礎地図が道路より後ろに置いている面をその手前へ動かす
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
  // `setStyle()`から新しいスタイルの`style.load`までは`getStyle()`がundefinedを返す。その間は
  // 解決済みにせず、読めるようになった後の呼び出しへ回す。
  const style: StyleSpecification | undefined = map.getStyle();
  if (style === undefined) return;
  tagged.__rcBasemapPrepared = true;

  const { layers } = style;
  hideBasemapPoisShownElsewhere(map, layers);
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
export function areaLayerAnchor(map: MapLibreMap): string | undefined {
  const anchorId = (map as unknown as StyleReadyTag).__rcAreaLayerAnchorId;
  return anchorId !== undefined && map.getLayer(anchorId) ? anchorId : undefined;
}

/** スタイルが差し替わった（`map.setStyle()`）ときに呼ぶ。次の`prepareBasemap`が
 * 新しいスタイルに対して改めて走るようにする。 */
export function resetBasemapPreparation(map: MapLibreMap): void {
  (map as unknown as StyleReadyTag).__rcBasemapPrepared = false;
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
