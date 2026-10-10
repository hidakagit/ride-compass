// 点（事故・POI・立ち寄り先）を押したときのポップアップの本文。
// 値はOSMタグ由来で第三者が編集できるため、HTML文字列を経由せずテキストノードで組む
// （`Popup.setHTML()`はサニタイズしない）。
import type { PointAxis } from "@/features/map/scene/groups/points";

// 行間はサイドバーの他のカードに近い密度に合わせる。
const POPUP_BODY_STYLE = "font-size:var(--font-size-md); line-height:1.4;";

function popupBody(lines: readonly string[]): HTMLDivElement {
  const body = document.createElement("div");
  body.style.cssText = POPUP_BODY_STYLE;
  lines.forEach((line, i) => {
    if (i > 0) body.appendChild(document.createElement("br"));
    body.appendChild(document.createTextNode(line));
  });
  return body;
}

/** 名前と位置で地点を探す外の地図（Google マップの検索。公式の文書「Maps URLs」の`search`）。位置を添えるのは、
 * 名前だけでは見ている人の今いる所の近くで探すため。 */
function externalMapSearchUrl(name: string, lngLat: { lng: number; lat: number }): string {
  const query = `${name} ${lngLat.lat.toFixed(6)},${lngLat.lng.toFixed(6)}`;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
}

/** 点の名前（`point_name_property`の値）。名前を宣言しない点・値の無い点はnull。 */
export function pointPlaceName(
  layer: { point_name_property: string | null },
  properties: Record<string, unknown>,
): string | null {
  const name = layer.point_name_property === null ? undefined : properties[layer.point_name_property];
  return typeof name === "string" && name !== "" ? name : null;
}

/** 名前のある点（`point_name_property`の値がある）は、1行目に名前を出し、最後に名前と位置で外の地図を開く導線を添える
 * ——閉店にデータが追いついていないことがあるので、営業を外で確かめられるようにする。続く行は「<点の名前>: <区分の名前>」
 * （区分の軸が複数なら「・」で並べる）。区分の名前は凡例と同じ宣言から引き、引けない値は「不明」にする（値は分類器が付ける
 * 内部名で、そのまま画面へ出さない）。続けて、宣言が点に添える事実を「<名前>: <値>」で1行ずつ出す（値の無い事実は出さない）。 */
export function buildPointPopupContent(
  layer: {
    label: string;
    display_axes: readonly PointAxis[];
    point_facts: readonly { property: string; label: string }[];
    point_name_property: string | null;
  },
  properties: Record<string, unknown>,
  lngLat: { lng: number; lat: number },
): HTMLDivElement {
  const names = layer.display_axes.map((axis) => {
    const value = String(properties[axis.property]);
    return axis.categories.find((category) => category.values.some((v) => String(v) === value))?.label ?? "不明";
  });
  const placeName = pointPlaceName(layer, properties);
  const lines = [...(placeName !== null ? [placeName] : []), `${layer.label}: ${names.join(" ・ ")}`];
  for (const fact of layer.point_facts) {
    const value = properties[fact.property];
    if (value != null) lines.push(`${fact.label}: ${String(value)}`);
  }
  const body = popupBody(lines);
  if (placeName !== null) {
    const link = document.createElement("a");
    link.href = externalMapSearchUrl(placeName, lngLat);
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = "Googleマップで営業を確かめる";
    body.appendChild(document.createElement("br"));
    body.appendChild(link);
  }
  return body;
}
