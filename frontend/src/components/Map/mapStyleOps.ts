/** MapLibreの地図インスタンスに対する、どのレイヤーからも使う低水準の操作。
 *
 * ここに置くのは「特定のレイヤー種を知らない」ものだけ。レイヤー固有の描画は
 * それぞれの担当ファイル（`MapView.routes.ts`・`axisLayers.ts`等）が持つ。
 */
import type * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import { debugLog } from "@/lib/debugLog";

export function setLayerVisibility(map: MapLibreMap, layerId: string, visible: boolean) {
  if (!map.getLayer(layerId)) return;
  map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
}

/** 「面で塗る」レイヤー種。地図の一区画を色で覆い、下にあるものを隠す描き方をまとめて指す
 * （残りのline/symbol/circle/heatmapは線・記号として、面の上に乗って読まれる側）。 */
const AREA_LAYER_TYPES: ReadonlySet<string> = new Set(["background", "raster", "fill", "fill-extrusion", "hillshade"]);

export function isAreaLayerType(type: string): boolean {
  return AREA_LAYER_TYPES.has(type);
}

/** 面で塗るレイヤーを差し込む位置（このidのレイヤーの直前＝下へ入る）を、スタイルの並びから
 * 導く。基礎地図が最後に面を描いたレイヤーの次、つまり道路・境界の線と地名の記号が始まる
 * 位置を指す。基礎地図のレイヤーidを名指しせず並びから導くのは、配信元がidを変えても
 * 「面の上・線と記号の下」という関係だけは変わらないため。面しか持たないスタイルでは
 * undefined（差し込み先が無い＝最前面）になる。 */
export function areaLayerAnchorId(layers: readonly { id: string; type: string }[]): string | undefined {
  let lastAreaIndex = -1;
  layers.forEach((layer, index) => {
    if (isAreaLayerType(layer.type)) lastAreaIndex = index;
  });
  return layers[lastAreaIndex + 1]?.id;
}

interface StyleReadyTag {
  __rcStyleReady?: boolean;
  __rcAreaLayerAnchorResolved?: boolean;
  __rcAreaLayerAnchorId?: string;
}

/** 差し込み位置をスタイルの並びから求めてmapへ記録する。**このアプリのレイヤーを1枚も
 * 足していない時点で一度だけ**求めるため、`load`の購読者が複数いても最初の1人だけが実際に
 * 走る。位置が求まらないスタイル（面しか無い等）では面が最前面へ戻り、面の濃さだけで
 * 下の情報の読みやすさが決まる状態に落ちるため、黙って続けずログへ残す。 */
function resolveAreaLayerAnchor(map: MapLibreMap) {
  const tagged = map as unknown as StyleReadyTag;
  if (tagged.__rcAreaLayerAnchorResolved) return;
  tagged.__rcAreaLayerAnchorResolved = true;
  tagged.__rcAreaLayerAnchorId = areaLayerAnchorId(map.getStyle().layers ?? []);
  const anchorId = tagged.__rcAreaLayerAnchorId;
  debugLog(
    "map:lifecycle",
    anchorId === undefined ? "面レイヤーの差し込み位置が求まらず、面を最前面へ積む" : "面レイヤーの差し込み位置",
    { anchorId: anchorId ?? null },
    anchorId === undefined ? "warn" : "info",
  );
}

/** `areaLayerAnchorId`が返した位置。**スタイル読み込み直後（このアプリのレイヤーを1枚も
 * 足していない時点）に記録した値**を返す——差し込むたびに探し直すと、自分が足した線
 * レイヤーが先に見つかって面が一段ずつ下がっていく。記録した位置が今のスタイルに無いときは
 * undefined（差し込まず最前面へ）。 */
export function areaLayerAnchor(map: MapLibreMap): string | undefined {
  const anchorId = (map as unknown as StyleReadyTag).__rcAreaLayerAnchorId;
  return anchorId !== undefined && map.getLayer(anchorId) ? anchorId : undefined;
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
    resolveAreaLayerAnchor(map);
    fn();
  });
}

// ズームに応じた追加の拡大率。symbolレイヤーのicon-sizeは既定で画面上の
// 固定ピクセルサイズのため、拡大するほど周囲の道路・建物がどんどん大きく描かれる一方で
// 矢印だけ同じ大きさのまま相対的に小さく・目立たなくなる。初期表示ズーム（13、page.tsx:
// map.zoom初期値）を基準（倍率1）に据え、それより拡大するほど大きく・縮小するほど小さく
// 描画することで、ズームレベルが変わってもアイコンの「目立ち具合」が視覚的に保たれるようにする。
// gridMark全般（DynamicWeatherMarkSpec）向けの汎用式のため、風以外の要素を追加する場合も
// 同じ式を共有できる。
export const ICON_ZOOM_SCALE_STOPS: readonly { zoom: number; multiplier: number }[] = [
  { zoom: 10, multiplier: 0.75 },
  { zoom: 13, multiplier: 1 },
  { zoom: 16, multiplier: 1.5 },
  { zoom: 19, multiplier: 2 },
];

/** ズーム×格子点プロパティの「zoom-and-property」式（MapLibre/Mapboxスタイル仕様の標準
 * パターン）。外側のinterpolateがzoomの各段でscaleMultiplier×そのズーム段の倍率を適用した
 * 内側のinterpolate（プロパティ値→サイズ、0〜maxValueForFullScaleの範囲でmin〜maxScaleへ
 * 線形補間）を返す。gridMark表現を使うすべての動的気象要素（現状は風の矢印のみ、プロパティ
 * "speed"・0〜15m/s）がこの関数を共有する（DynamicWeatherMarkSpec参照）。 */
export function zoomAndPropertyIconSizeExpression(
  propertyName: string,
  minScale: number,
  maxScale: number,
  maxValueForFullScale: number,
  scaleMultiplier: number,
) {
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    ...ICON_ZOOM_SCALE_STOPS.flatMap((stop) => [
      stop.zoom,
      [
        "interpolate",
        ["linear"],
        ["to-number", ["get", propertyName]],
        0,
        minScale * scaleMultiplier * stop.multiplier,
        maxValueForFullScale,
        maxScale * scaleMultiplier * stop.multiplier,
      ],
    ]),
  ] as unknown as maplibregl.ExpressionSpecification;
}

/** ズームのみに依存するicon-size式（zoomAndPropertyIconSizeExpressionのプロパティ非依存版）。
 * ルート矢印のように「全シンボル共通の基準サイズをズームでスケールするだけ」で
 * 足りるケース向け。ICON_ZOOM_SCALE_STOPSを共有し、風の矢印と同じズーム曲線に揃える
 * （片側importで2箇所のズーム曲線が食い違わないようにする）。 */
export function zoomIconSizeExpression(baseScale: number) {
  return [
    "interpolate",
    ["linear"],
    ["zoom"],
    ...ICON_ZOOM_SCALE_STOPS.flatMap((stop) => [stop.zoom, baseScale * stop.multiplier]),
  ] as unknown as maplibregl.ExpressionSpecification;
}
