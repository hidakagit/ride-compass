/** 地図キャンバスの上に重なるUIで覆われている辺ごとの高さ(px)。 */
export interface RouteFitObscuredPx {
  top?: number;
  bottom?: number;
  left?: number;
  right?: number;
}

type Edge = keyof RouteFitObscuredPx;

export const MAP_OVERLAY_EDGE_ATTRIBUTE = "data-map-overlay-edge";

/** 地図の上に重ねる部品へ付ける印。ルートを地図へ収めるとき、この部品が`edge`の辺から覆う幅を余白へ足す。 */
export function mapOverlayEdge(edge: Edge): { [MAP_OVERLAY_EDGE_ATTRIBUTE]: Edge } {
  return { [MAP_OVERLAY_EDGE_ATTRIBUTE]: edge };
}

/** 印の付いた部品が、地図の各辺から内側へどこまで覆っているか(px)。大きさの無い（隠れている）部品は数えない。 */
export function measureMapOverlayEdges(canvas: DOMRect, root: ParentNode = document): RouteFitObscuredPx {
  const obscured: RouteFitObscuredPx = {};
  for (const element of root.querySelectorAll(`[${MAP_OVERLAY_EDGE_ATTRIBUTE}]`)) {
    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) continue;
    const depth: Record<Edge, number> = {
      left: rect.right - canvas.left,
      right: canvas.right - rect.left,
      top: rect.bottom - canvas.top,
      bottom: canvas.bottom - rect.top,
    };
    const edge = element.getAttribute(MAP_OVERLAY_EDGE_ATTRIBUTE);
    if (edge !== "left" && edge !== "right" && edge !== "top" && edge !== "bottom") continue;
    obscured[edge] = Math.max(obscured[edge] ?? 0, depth[edge]);
  }
  return obscured;
}
