// 点（事故・POI）を押したときのポップアップの本文。
// 値はOSMタグ由来で第三者が編集できるため、HTML文字列を経由せずテキストノードで組む
// （`Popup.setHTML()`はサニタイズしない。docs/modules/frontend/static-map-layers.md参照）。
import type { PointAxis } from "@/features/map/scene/groups/points";

// line-height 1.4はサイドバーの他カード（components/ui/Card等）に近い密度に合わせている。
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

/** 1行目は「<点の名前>: <区分の名前>」（区分の軸が複数なら「・」で並べる）。区分の名前は凡例と同じ宣言から引き、
 * 引けない値は「不明」にする（値は分類器が付ける内部名で、そのまま画面へ出さない）。 */
export function buildPointPopupContent(
  layer: { label: string; display_axes: readonly PointAxis[] },
  properties: Record<string, unknown>,
): HTMLDivElement {
  const names = layer.display_axes.map((axis) => {
    const value = String(properties[axis.property]);
    return axis.categories.find((category) => category.values.some((v) => String(v) === value))?.label ?? "不明";
  });
  const lines = [`${layer.label}: ${names.join(" ・ ")}`];
  // 発生年は区分ではなく、事故の点だけが持つ事実。
  if (typeof properties.occurred_year === "number") lines.push(`発生年: ${properties.occurred_year}`);
  return popupBody(lines);
}
