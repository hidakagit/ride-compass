/** MapLibreの地図インスタンスに対する、どのレイヤーからも使う低水準の操作。
 *
 * ここに置くのは「特定のレイヤー種を知らない」ものだけ。レイヤー固有の描画は
 * それぞれの担当ファイル（`features/map/scene/groups/*.ts`）が持つ。
 */
import type { Map as MapLibreMap } from "maplibre-gl";
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
 * レイヤーの次」を採ると位置が道路の後ろまで下がり、面が道路を覆ったまま残る（実機で
 * `boundary_3`が返った）。道路網より後ろの面は`basemapAreaLayersAfter`が前へ動かす。
 *
 * 道路網を持たないスタイルではundefined（差し込み先が無く最前面になる）。 */
function areaLayerAnchorId(layers: readonly { id: string; "source-layer"?: string }[]): string | undefined {
  return layers.find((layer) => layer["source-layer"] === ROAD_NETWORK_SOURCE_LAYER)?.id;
}

/** `anchorId`より後ろにある面レイヤーのid（追加順のまま）。基礎地図が道路より後ろに置いて
 * いる面（建物）を指す。 */
function basemapAreaLayersAfter(layers: readonly { id: string; type: string }[], anchorId: string): string[] {
  const anchorIndex = layers.findIndex((layer) => layer.id === anchorId);
  if (anchorIndex < 0) return [];
  return layers
    .slice(anchorIndex + 1)
    .filter((layer) => isAreaLayerType(layer.type))
    .map((layer) => layer.id);
}

interface StyleReadyTag {
  __rcStyleReady?: boolean;
  __rcAreaLayerAnchorResolved?: boolean;
  __rcAreaLayerAnchorId?: string;
}

/** 差し込み位置を求めて記録し、基礎地図が道路より後ろに置いている面をその手前へ動かす。
 *
 * **このアプリのレイヤーを1枚も足していない時点で呼ぶこと**（`style.load`）。後から呼ぶと、
 * 自分で足した線レイヤーが最長の連なりを伸ばし、差し込み位置が地名側へずれる。同じスタイルに
 * 対しては1度しか実行しない。
 *
 * 建物を道路より前へ動かすと、基礎地図そのものの見た目も「建物の上に道路」へ変わる。
 * この地図はpitchを持たない（建物は平面の足元だけが描かれる）ため影響は小さく、面レイヤーが
 * 建物に穴を開けられない利点が上回る。
 *
 * 位置が求まらないスタイルでは面が最前面へ戻る＝面の濃さだけで下の情報の読みやすさが
 * 決まる状態に落ちるため、黙って続けずログへ残す。 */
export function prepareBasemapForAreaLayers(map: MapLibreMap): void {
  const tagged = map as unknown as StyleReadyTag;
  if (tagged.__rcAreaLayerAnchorResolved) return;
  tagged.__rcAreaLayerAnchorResolved = true;

  const layers = map.getStyle().layers ?? [];
  const anchorId = areaLayerAnchorId(layers);
  tagged.__rcAreaLayerAnchorId = anchorId;
  if (anchorId === undefined) {
    debugLog("map:lifecycle", "面レイヤーの差し込み位置が求まらず、面を最前面へ積む", { anchorId: null }, "warn");
    return;
  }
  const lowered = basemapAreaLayersAfter(layers, anchorId);
  for (const layerId of lowered) map.moveLayer(layerId, anchorId);
  debugLog("map:lifecycle", "面レイヤーの差し込み位置", { anchorId, lowered });
}

/** `prepareBasemapForAreaLayers`が記録した位置。記録が無い・今のスタイルに無いときは
 * undefined（差し込まず最前面へ）——**今のスタイルに無いidを`addLayer`へ渡すと例外になる**。 */
export function areaLayerAnchor(map: MapLibreMap): string | undefined {
  const anchorId = (map as unknown as StyleReadyTag).__rcAreaLayerAnchorId;
  return anchorId !== undefined && map.getLayer(anchorId) ? anchorId : undefined;
}

/** スタイルが差し替わった（`map.setStyle()`）ときに呼ぶ。次の`prepareBasemapForAreaLayers`が
 * 新しいスタイルに対して改めて走るようにする。 */
export function resetBasemapAreaLayerPreparation(map: MapLibreMap): void {
  (map as unknown as StyleReadyTag).__rcAreaLayerAnchorResolved = false;
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
    // style.loadが来ない経路でも面の差し込み位置が未解決のまま残らないようにする
    // （解決済みなら何もしない）。
    prepareBasemapForAreaLayers(map);
    fn();
  });
}
